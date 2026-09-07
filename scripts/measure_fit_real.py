#!/usr/bin/env python3
"""Measure one model launch without confusing prediction, allocation and footprint.

This is the repeatable A6 instrument.  It launches exactly the requested model on a
caller-selected unused loopback port, submits one real completion, samples macOS
``phys_footprint`` from the exact child PID, and writes a JSON receipt.  It does not
touch the model registry, MOT Deck configuration, the live runner port or any process
it did not itself spawn.

For GGUF, ``context`` is the server's allocated context.  MLX servers have no context
launch flag; for them ``prompt_words`` is a workload, and the returned API usage is the
only honest prompt-token count.  The two are intentionally distinct in the receipt.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

try:
    from bridge.core import fit, memory, runnermeasure  # noqa: E402
except ModuleNotFoundError as exc:
    # A Finder-minimal shell commonly resolves Apple's stdlib-only Python first. The
    # measurement imports the same fit/memory modules as the bridge, so re-exec through
    # that explicitly owned environment rather than asking users to repair PATH.
    bridge_python = REPO / "data/bridge-venv/bin/python"
    if exc.name in {"httpx", "fastapi", "yaml"} and bridge_python.is_file() \
            and Path(sys.executable).resolve() != bridge_python.resolve():
        os.execv(str(bridge_python), [str(bridge_python), str(Path(__file__).resolve()),
                                     *sys.argv[1:]])
    raise


def _post_json(url: str, payload: dict, key: str, timeout: float) -> dict:
    request = Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                      headers={"Content-Type": "application/json",
                               "Authorization": f"Bearer {key}"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(url: str, key: str, timeout: float = 2.0) -> dict:
    request = Request(url, headers={"Authorization": f"Bearer {key}"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _port_is_free(port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", int(port)))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _stop_exact(process: subprocess.Popen) -> None:
    """Stop only the process group this invocation created."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=15)
    except ProcessLookupError:
        return
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=10)


def _sampler(pid: int, stop: threading.Event, samples: list[dict]) -> None:
    while not stop.wait(0.10):
        row = memory.proc_footprint(pid)
        if row:
            samples.append({"at": time.monotonic(), **row})


def _argv(args: argparse.Namespace, keyfile: Path) -> list[str]:
    if args.engine == "llamacpp":
        command = [args.binary, "--no-context-shift", "--host", "127.0.0.1",
                   "--port", str(args.port), "--alias", args.model_id,
                   "--ctx-size", str(args.context), "--no-cont-batching",
                   "--cache-ram", "-1", "--fit", "off", "--model", args.model,
                   "--parallel", "1", "--verbosity", "4",
                   "--api-key-file", str(keyfile)]
        if args.mmproj:
            command += ["--mmproj", args.mmproj]
        return command
    return [args.python, "-m", "mlx_lm.server", "--model", args.model,
            "--host", "127.0.0.1", "--port", str(args.port)]


def measure(args: argparse.Namespace) -> dict:
    if not _port_is_free(args.port):
        raise RuntimeError(f"loopback port {args.port} is already occupied; nothing was stopped")
    model = Path(args.model).expanduser().resolve()
    if args.engine == "llamacpp" and not model.is_file():
        raise RuntimeError(f"GGUF is not a file: {model}")
    if args.engine == "mlx" and not model.is_dir():
        raise RuntimeError(f"MLX model is not a directory: {model}")
    if args.mmproj and not Path(args.mmproj).expanduser().resolve().is_file():
        raise RuntimeError(f"projector is not a file: {args.mmproj}")

    key = "motdeck-a6-disposable"
    receipt: dict = {"schema": 1, "label": args.label, "engine": args.engine,
                     "model_id": args.model_id, "model": str(model),
                     "context_requested": args.context if args.engine == "llamacpp" else None,
                     "prompt_words_requested": args.prompt_words,
                     "mmproj": str(Path(args.mmproj).expanduser().resolve()) if args.mmproj else None,
                     "port": args.port, "started_at": int(time.time())}
    samples: list[dict] = []
    process = None
    with tempfile.TemporaryDirectory(prefix="motdeck-a6-") as temporary:
        temp = Path(temporary)
        keyfile = temp / "keys"
        keyfile.write_text(key + "\n", encoding="utf-8")
        keyfile.chmod(0o600)
        logfile = temp / "server.log"
        command = _argv(args, keyfile)
        receipt["command_shape"] = ["<binary>" if i == 0 else
                                    "<disposable-key-file>" if i == str(keyfile) else i
                                    for i in command]
        started = time.monotonic()
        with logfile.open("wb") as output:
            process = subprocess.Popen(command, cwd=REPO, stdout=output,
                                       stderr=subprocess.STDOUT, start_new_session=True)
        stop = threading.Event()
        thread = threading.Thread(target=_sampler, args=(process.pid, stop, samples),
                                  name="a6-footprint", daemon=True)
        thread.start()
        try:
            deadline = started + args.ready_timeout
            models = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"server exited during load with rc={process.returncode}")
                try:
                    models = _get_json(f"http://127.0.0.1:{args.port}/v1/models", key)
                    break
                except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
                    time.sleep(0.25)
            if models is None:
                raise RuntimeError(f"server did not become ready within {args.ready_timeout}s")
            receipt["ready_s"] = round(time.monotonic() - started, 3)
            receipt["models_response"] = models
            # Keep the text deterministic while allowing MLX to report the true token
            # count.  This is intentionally ordinary text, not a tokenizer assumption.
            prompt = ("measurement " * max(1, args.prompt_words)).strip()
            before_prompt = time.monotonic()
            # mlx_lm.server treats the request's ``model`` field as a model to load,
            # even when the process was launched with --model.  MOT Deck's production
            # relay therefore sends the local MLX path, while llama.cpp receives the
            # public alias declared at launch.  A single shared ID here makes the MLX
            # server attempt a Hub lookup and return 404—the exact false parity A6 is
            # meant to prevent.
            wire_model = str(model) if args.engine == "mlx" else args.model_id
            receipt["wire_model_shape"] = "local-path" if args.engine == "mlx" else "alias"
            answer = _post_json(f"http://127.0.0.1:{args.port}/v1/chat/completions",
                                {"model": wire_model,
                                 "messages": [{"role": "user", "content": prompt}],
                                 "temperature": 0, "max_tokens": 1},
                                key, args.prompt_timeout)
            receipt["prompt_s"] = round(time.monotonic() - before_prompt, 3)
            receipt["usage"] = answer.get("usage") if isinstance(answer, dict) else None
            receipt["completion_received"] = bool(
                isinstance(answer, dict) and answer.get("choices"))
            time.sleep(0.5)
        finally:
            if process is not None:
                _stop_exact(process)
            stop.set()
            thread.join(timeout=3)
        log_text = logfile.read_text(encoding="utf-8", errors="replace")
        receipt["log_tail"] = log_text[-4000:]

    if samples:
        receipt["footprint"] = {
            "samples": len(samples),
            "peak_phys_footprint_bytes": max(x["footprint"] for x in samples),
            "peak_rusage_bytes": max(x["peak"] for x in samples),
            "peak_rss_bytes": max(x["rss"] for x in samples),
            "metric": "phys_footprint",
        }
    entry = {"id": args.model_id, "name": args.model_id,
             "format": "gguf" if args.engine == "llamacpp" else "mlx",
             "path": str(model), "size_bytes": (model.stat().st_size
                                                   if model.is_file() else 0)}
    if args.mmproj:
        entry["mmproj"] = str(Path(args.mmproj).expanduser().resolve())
    prompt_tokens = int((receipt.get("usage") or {}).get("prompt_tokens") or 0)
    estimate_ctx = args.context if args.engine == "llamacpp" else max(256, prompt_tokens)
    settings = fit.settings_for(entry, {"ctx": estimate_ctx})
    receipt["estimate"] = fit.estimate(entry, settings)
    receipt["estimate_context"] = estimate_ctx
    if args.engine == "llamacpp":
        # Parsing only the diagnostic tail can lose the startup's load marker once a
        # verbose prompt adds enough later lines. The persisted receipt remains small,
        # but the measurement is derived from the complete temporary launch log.
        receipt["runner_allocation"] = runnermeasure.parse_latest(log_text)
    receipt["finished_at"] = int(time.time())
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=("llamacpp", "mlx"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--context", type=int, default=16384)
    parser.add_argument("--prompt-words", type=int, default=32)
    parser.add_argument("--mmproj", default="")
    parser.add_argument("--port", type=int, default=6799)
    parser.add_argument("--binary", default=str(REPO / "data/llamacpp/build/bin/llama-server"))
    parser.add_argument("--python", default=str(Path.home() / "Library/Application Support/MOT Deck/data/mlx-venv/bin/python"))
    parser.add_argument("--ready-timeout", type=float, default=240.0)
    parser.add_argument("--prompt-timeout", type=float, default=240.0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.context < 256 or args.context > 1_048_576:
        parser.error("--context must be between 256 and 1048576")
    if args.prompt_words < 1 or args.prompt_words > 131_072:
        parser.error("--prompt-words must be between 1 and 131072")
    try:
        receipt = measure(args)
    except Exception as exc:  # noqa: BLE001
        print(f"[a6] ERROR: {exc}", file=sys.stderr)
        return 1
    destination = Path(args.out).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name("." + destination.name + ".tmp")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    os.replace(temporary, destination)
    print(json.dumps({"ok": True, "out": str(destination),
                      "ready_s": receipt.get("ready_s"),
                      "prompt_s": receipt.get("prompt_s"),
                      "footprint": receipt.get("footprint"),
                      "usage": receipt.get("usage")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
