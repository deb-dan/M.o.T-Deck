"""Persistent MLX TTS worker — one process, one loaded model, many renders.

WHY THIS EXISTS
    Every ▶ speak used to spawn `python -m mlx_audio.tts.generate`, which loads the
    whole 3.6GB checkpoint before it says a word. A re-listen therefore cost exactly
    as much as the first listen. This script is the same engine call with the load
    hoisted out of the loop: the bridge spawns it once, sends `load`, and then every
    render is just `model.generate(...)`.

PROTOCOL — JSON lines over stdin/stdout. No port, no auth surface, no framing
    beyond '\\n'. One request per line, one response per line, ids echoed back:

        → {"id":1,"cmd":"ping"}
        ← {"id":1,"ok":true,"loaded":false}
        → {"id":2,"cmd":"load","model":"/path/to/model-dir"}
        ← {"id":2,"ok":true,"model":"/path/to/model-dir","secs":31.4}
        → {"id":3,"cmd":"tts","text":"hello","voice":"serena","out":"/tmp/x/out.wav",
           "ref_audio":"/…/data/voices/sample.wav","ref_text":"…"}   (both optional)
        ← {"id":3,"ok":true,"out":"/tmp/x/out.wav","bytes":88244,"secs":1.9}
        ← {"id":n,"ok":false,"error":"…"}                        (any failure)

    The worker NEVER dies on a bad request: an unknown command, a malformed line, a
    failed render and an engine exception all come back as ok:false and the loop
    keeps reading. Only EOF on stdin ends it — which is exactly what happens when
    the bridge closes the pipe or exits.

TWO INVARIANTS CARRIED OVER FROM bridge/voice.py

  1. **The engine exits 0 on failure.** `mlx_audio.tts.generate.generate_audio`
     wraps its whole body in `except Exception: traceback.print_exc()` and returns
     normally. So a render is successful ONLY when the wav exists and is non-empty
     (`_render_ok`) — a returned-without-raising call proves nothing.
  2. **stdout is protocol-only.** The engine prints banners, progress and its own
     tracebacks with plain `print()`, and any one of those lines would corrupt the
     stream. `main()` therefore dup2's fd 1 onto fd 2 (catching C-level writes too)
     and keeps a private duplicate of the original fd 1 for responses. Everything
     the engine says lands in the bridge's worker log, where it belongs.

SANDBOX NOTE: mlx is Apple-Silicon only, so this file can never RUN in the Linux
    dev sandbox. Every mlx import is therefore inside a function — the module
    imports cleanly anywhere, and the protocol helpers below are unit-tested by
    bridge/tests/test_voice_worker.py without mlx present.
"""
from __future__ import annotations

import json
import os
import sys
import time

PROTOCOL_VERSION = 1
COMMANDS = ("ping", "load", "tts")

# The exact kwargs `python -m mlx_audio.tts.generate` passes for a plain
# `--model X --text Y [--voice V] --join_audio --output_path D --file_prefix P`
# invocation, read out of mlx-audio 0.4.7's parse_args() defaults.
#
# This is NOT decoration. generate_audio()'s own signature defaults differ from the
# CLI's in ways that change the audio: `max_tokens` defaults to 1200 in the signature
# but None on the CLI (1200 would truncate a long reply), and argparse's extra
# knobs (top_p/top_k/repetition_penalty/exaggeration/gender/pitch) flow into the
# model through **kwargs. Reproducing the CLI's dict exactly is what makes a worker
# render byte-comparable to the one-shot render it replaces — a worker that quietly
# sounded different would be a worse bug than a slow one.
CLI_PARITY_KWARGS = {
    "max_tokens": None,
    "prompt": None,
    "instruct": None,
    "exaggeration": 0.5,
    "cfg_scale": None,
    "ddpm_steps": None,
    "speed": 1.0,
    "gen_duration": None,
    "duration_multiplier": None,
    "steps": None,
    "stg_scale": None,
    "stg_block": None,
    "rescale_scale": None,
    "gender": "male",
    "pitch": 1.0,
    "lang_code": "en",
    "audio_format": "wav",
    "ref_audio": None,
    "ref_text": None,
    "stt_model": "mlx-community/whisper-large-v3-turbo-asr-fp16",
    "temperature": 0.7,
    "sigma": None,
    "use_zero_spk_emb": None,
    "top_p": 0.9,
    "top_k": 50,
    "min_p": None,
    "repetition_penalty": 1.1,
    "stream": None,
    "streaming_interval": 2.0,
    "save": None,
    "play": None,
    "verbose": None,
}


# ── protocol helpers (PURE — no mlx, no filesystem) ─────────────────────────────
def encode_response(obj: dict) -> str:
    """One response, one line. ensure_ascii so a non-ASCII error can never widen a
    line into something the reader splits differently."""
    return json.dumps(obj, ensure_ascii=True) + "\n"


def make_response(rid, ok: bool, error: str = "", **extra) -> dict:
    """Every response carries the request's id (0 when it could not be read) and a
    boolean `ok`. Errors are strings the bridge can show a human verbatim."""
    out = {"id": rid if isinstance(rid, int) else 0, "ok": bool(ok)}
    if not ok:
        out["error"] = str(error or "unknown error")[:500]
    out.update(extra)
    return out


def decode_request(line: object) -> tuple:
    """(request, error). A malformed line is an ERROR REPLY, never a crash — the
    bridge and the worker must never wedge each other over one bad byte."""
    if not isinstance(line, str) or not line.strip():
        return None, "empty request"
    try:
        req = json.loads(line)
    except ValueError as e:
        return None, f"malformed json ({str(e)[:120]})"
    if not isinstance(req, dict):
        return None, "request must be a json object"
    return req, ""


def validate_request(req: object) -> str:
    """'' when the request is servable, else a short reason. PURE."""
    if not isinstance(req, dict):
        return "request must be a json object"
    cmd = str(req.get("cmd") or "").strip().lower()
    if not cmd:
        return "no cmd"
    if cmd not in COMMANDS:
        return f"unknown cmd {cmd!r} (expected one of {', '.join(COMMANDS)})"
    if cmd == "load" and not str(req.get("model") or "").strip():
        return "load needs a model path"
    if cmd == "tts":
        if not str(req.get("text") or "").strip():
            return "tts needs text"
        if not str(req.get("out") or "").strip():
            return "tts needs an out path"
    return ""


def render_kwargs(text: str, voice: object, out_path: str,
                  ref_audio: object = None, ref_text: object = None) -> dict:
    """The full generate_audio kwargs for one render, minus the model object. PURE,
    so the CLI-parity contract above is asserted by a test rather than by hope.

    `voice` is normalised to None when empty: the CLI passes None (argparse default)
    and generate_audio's own signature default is "af_heart", so passing '' or
    omitting it would silently impose a Kokoro voice name on every model.

    `ref_audio`/`ref_text` follow the same rule and for the same reason: argparse
    defaults both to None, and generate_audio branches on `ref_audio` being falsy —
    an empty STRING would take the cloning path with a path of '' and raise
    "Reference audio file not found: ". They are per-REQUEST, never per-worker: the
    voice a zero-shot model speaks in is an argument, not part of the loaded model.
    """
    out_dir = os.path.dirname(str(out_path)) or "."
    stem = os.path.splitext(os.path.basename(str(out_path)))[0]
    kw = dict(CLI_PARITY_KWARGS)
    kw.update({
        "text": str(text),
        "voice": (str(voice).strip() or None) if voice else None,
        "ref_audio": (str(ref_audio).strip() or None) if ref_audio else None,
        "ref_text": (str(ref_text).strip() or None) if ref_text else None,
        "output_path": out_dir,
        "file_prefix": stem,
        "join_audio": True,      # without it the engine writes <stem>_000.wav parts
    })
    return kw


def _render_ok(path: str) -> bool:
    """The ONLY definition of a successful render (see invariant 1)."""
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


# ── the worker ──────────────────────────────────────────────────────────────────
class TtsWorker:
    """Holds the loaded model. `handle()` is total: it returns a response dict for
    every input and raises nothing."""

    def __init__(self):
        self.model = None
        self.model_path = ""

    # mlx imports live HERE, not at module scope: the file must import on Linux.
    def _load(self, path: str):
        from mlx_audio.tts.utils import load_model
        return load_model(model_path=path)

    def _generate(self, kwargs: dict):
        from mlx_audio.tts.generate import generate_audio
        generate_audio(model=self.model, **kwargs)

    def handle(self, req: dict) -> dict:
        rid = req.get("id")
        err = validate_request(req)
        if err:
            return make_response(rid, False, err)
        cmd = str(req.get("cmd")).strip().lower()
        if cmd == "ping":
            return make_response(rid, True, loaded=bool(self.model),
                                 model=self.model_path or None,
                                 protocol=PROTOCOL_VERSION, pid=os.getpid())
        if cmd == "load":
            path = str(req["model"]).strip()
            if self.model is not None and path == self.model_path:
                return make_response(rid, True, model=path, secs=0.0, cached=True)
            t0 = time.time()
            try:
                self.model = self._load(path)
            except Exception as e:                                  # noqa: BLE001
                self.model, self.model_path = None, ""
                return make_response(rid, False, f"could not load {path}: {str(e)[:300]}")
            self.model_path = path
            return make_response(rid, True, model=path,
                                 secs=round(time.time() - t0, 2), cached=False)
        # cmd == "tts"
        if self.model is None:
            return make_response(rid, False, "no model loaded — send load first")
        out = str(req["out"]).strip()
        kw = render_kwargs(req.get("text") or "", req.get("voice"), out,
                           req.get("ref_audio"), req.get("ref_text"))
        t0 = time.time()
        try:
            os.makedirs(kw["output_path"], exist_ok=True)
            self._generate(kw)
        except Exception as e:                                      # noqa: BLE001
            # generate_audio swallows almost everything itself; this catches the rest
            # (a bad out dir, an OOM) so one failed render never kills the worker.
            return make_response(rid, False, f"render failed: {str(e)[:300]}")
        if not _render_ok(out):
            return make_response(
                rid, False,
                "the engine produced no audio (it exits 0 on failure — see the "
                "worker log for its traceback)")
        return make_response(rid, True, out=out, bytes=os.path.getsize(out),
                             secs=round(time.time() - t0, 2))


def serve(stdin, out) -> int:
    """Read requests until EOF. Total: never raises, never exits early on bad input."""
    worker = TtsWorker()
    for line in stdin:
        req, err = decode_request(line)
        resp = make_response(0, False, err) if err else worker.handle(req)
        try:
            out.write(encode_response(resp))
            out.flush()
        except (OSError, ValueError):
            return 1          # the bridge closed the pipe mid-reply
    return 0


def main() -> int:
    # Invariant 2: hand fd 1 over to stderr so NOTHING the engine prints (python-level
    # or C-level) can reach the protocol stream, and keep a private dup for responses.
    proto_fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    out = os.fdopen(proto_fd, "w", encoding="utf-8")
    try:
        return serve(sys.stdin, out)
    finally:
        try:
            out.close()
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
