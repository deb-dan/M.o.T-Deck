"""CORE — THE MODEL REGISTRY'S ONE DEFINITION OF "REAL" (ledger S29).

Every list of models this app offers a human — our own composer picker, the Models
view, Odysseus's `pinned_models`, goose's provider file, Hermes's custom provider,
OpenCode's provider catalog — must be built from the SAME sentence:

    a CHAT model, not hidden, not flagged absent, whose file is not provably gone.

Before this module that sentence existed in five near-copies (gooseprov.model_entries,
seed_odysseus_jan.registry_wire_models, seed_hermes_provider._models,
start_component.sh's opencode heredoc, and the panel). They agreed on the audio/hidden
half and NONE of them knew about the file half — which is how Debi, days after deleting
the muse/glimmer family and gemma-4 in LM Studio, was still offered those models by
OpenCode's picker. Picking one is not an error: llama.cpp ignores the request's `model`
field, so the turn WORKS and answers under the dead model's name. That is the LIE class,
which the doctrine ranks above crashes.

⚠️ STDLIB ONLY, AND NO INTRA-PACKAGE IMPORTS. Three of the five consumers are standalone
scripts run by `python3` from the repo root (scripts/seed_registry.py,
scripts/seed_odysseus_jan.py, scripts/seed_opencode_config.py) and one runs under
Odysseus's own venv. They load this file BY PATH (`load_by_path()` below), the way
seed_registry already loads bridge/modeltools.py. Adding an import from bridge.core.*
here breaks all of them at once, silently, at seed time.

⚠️ ABSENCE IS NOT INFORMATION. `path_present` is three-valued on purpose: a stat that
fails for a reason that is not absence (EACCES, a sleeping network mount, ETIMEDOUT)
answers None, and None NEVER excludes a model from a list and never sets the absent
flag. A detached volume must not make us tell the user their models are gone — the same
rule core/health.py's two-strike debounce enforces one layer up, for the same incident.
"""
from __future__ import annotations

import json
import os
import re
import stat as _stat

# The persisted flag. `absent: true` on a registry row means: the two-strike file check
# said this row's artifact is not on disk. The row KEEPS ITS IDENTITY (its id, its ctx,
# its pinned voice, its per-model sampling) because the file may be on a volume that is
# merely unplugged — we never silently delete a row over a stat. Removal happens in
# exactly one place, and only on an explicit human action: the Models view's RESCAN.
ABSENT_KEY = "absent"

# Registry formats whose artifact is a DIRECTORY rather than a single file. Byte for
# byte the rule scripts/start_component.sh resolves with, widened to the audio kinds
# (checkpoint directories). Anything unrecognised is treated as a file, which is what
# `gguf` — the overwhelming majority — is.
_DIR_FORMATS_PREFIX = ("stt-", "tts-")
_GGUF_SHARD_RE = re.compile(r"^(.*)-(\d{5})-of-(\d{5})\.gguf$", re.I)
_MLX_SHARD_RE = re.compile(r"^(.*)-(\d{5})-of-(\d{5})\.safetensors$", re.I)


def wants_dir(fmt: "str | None") -> bool:
    f = str(fmt or "gguf").lower()
    return f == "mlx" or f.startswith(_DIR_FORMATS_PREFIX)


def _verdict(state, reason, detail, evidence=None):
    return {"state": state, "reason": reason, "detail": detail,
            "evidence": evidence or {}}


def _stat_required(path, label, *, missing_reason, invalid_reason):
    """A cheap regular/non-empty direct-file check for the shared probe."""
    try:
        st = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None, _verdict("incomplete", missing_reason, f"{label} is missing")
    except OSError:
        return None, _verdict("unknown", "unreadable", f"could not read {label}")
    except Exception:                                            # noqa: BLE001
        return None, _verdict("unknown", "unreadable", f"could not read {label}")
    if not _stat.S_ISREG(st.st_mode) or st.st_size <= 0:
        return None, _verdict("incomplete", invalid_reason, f"{label} is empty or not a file")
    return st, None


def split_gguf_group(name: str):
    """(prefix, total) for a numbered GGUF member, else None (shared with discovery)."""
    m = _GGUF_SHARD_RE.match(str(name or ""))
    if not m:
        return None
    ordinal, total = int(m.group(2)), int(m.group(3))
    return (m.group(1), total) if 1 <= ordinal <= total else None


def _shard_names(prefix, total, suffix):
    return [f"{prefix}-{n:05d}-of-{total:05d}{suffix}" for n in range(1, total + 1)]


def _audio_type_present(path, fmt):
    """The pre-U75 audio compatibility rule; audio owns separate validators."""
    if not path or not isinstance(path, str):
        return None
    try:
        st = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError:
        return None
    except Exception:                                            # noqa: BLE001
        return None
    return bool(_stat.S_ISDIR(st.st_mode) if wants_dir(fmt) else _stat.S_ISREG(st.st_mode))


def artifact_probe(entry: dict) -> dict:
    """Cheap, read-only integrity verdict for one chat GGUF or MLX artifact.

    The probe intentionally reads only direct metadata: one directory listing, tiny JSON
    manifests and direct stats. It never hashes or recursively sizes model weights.
    """
    if not isinstance(entry, dict):
        return _verdict("unknown", "invalid-entry", "model entry is not readable")
    fmt = str(entry.get("format") or "gguf").strip().lower()
    path = entry.get("path")
    if not isinstance(path, str) or not path:
        return _verdict("unknown", "no-path", "model path is not recorded")
    if is_audio(entry):
        present = _audio_type_present(path, fmt)
        state = "ready" if present is True else ("missing" if present is False else "unknown")
        return _verdict(state, "audio-type" if present is not None else "unreadable",
                        "audio artifact is available" if present else "could not read audio artifact")
    try:
        root = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return _verdict("missing", "path-missing", "model artifact is missing")
    except OSError:
        return _verdict("unknown", "unreadable", "could not read model artifact")
    except Exception:                                            # noqa: BLE001
        return _verdict("unknown", "unreadable", "could not read model artifact")
    if fmt == "mlx":
        if not _stat.S_ISDIR(root.st_mode):
            return _verdict("incomplete", "wrong-kind", "MLX model path is not a directory")
        try:
            names = os.listdir(path)
        except OSError:
            return _verdict("unknown", "unreadable", "could not read MLX model directory")
        config = os.path.join(path, "config.json")
        _, bad = _stat_required(config, "config.json", missing_reason="missing-config",
                                invalid_reason="invalid-config")
        if bad:
            return bad
        try:
            with open(config, encoding="utf-8") as fh:
                cfg = json.load(fh)
        except OSError:
            return _verdict("unknown", "unreadable", "could not read config.json")
        except (ValueError, TypeError):
            return _verdict("incomplete", "invalid-config", "config.json is not valid JSON")
        if not isinstance(cfg, dict):
            return _verdict("incomplete", "invalid-config", "config.json is not a JSON object")
        names = sorted(names)
        weights = [n for n in names if n.endswith(".safetensors")]
        if not weights:
            return _verdict("incomplete", "missing-weight", "MLX model has no weight file")
        required = {"config.json"}
        indexes = [n for n in names if n.endswith(".safetensors.index.json")]
        if indexes:
            valid_weight = False
            for n in weights:
                st, _ = _stat_required(os.path.join(path, n), n, missing_reason="missing-weight",
                                       invalid_reason="invalid-weight")
                valid_weight = valid_weight or st is not None
            if not valid_weight:
                return _verdict("incomplete", "invalid-weight", "MLX model has no usable weight file")
            for n in indexes:
                required.add(n)
                _, bad = _stat_required(os.path.join(path, n), n, missing_reason="missing-index",
                                        invalid_reason="invalid-index")
                if bad:
                    return bad
                try:
                    with open(os.path.join(path, n), encoding="utf-8") as fh:
                        idx = json.load(fh)
                    weight_map = idx.get("weight_map") if isinstance(idx, dict) else None
                except OSError:
                    return _verdict("unknown", "unreadable", f"could not read {n}")
                except (ValueError, TypeError):
                    return _verdict("incomplete", "invalid-index", f"{n} is not valid JSON")
                if not isinstance(weight_map, dict) or not weight_map:
                    return _verdict("incomplete", "invalid-weight-map", f"{n} has no weight map")
                targets = []
                for target in weight_map.values():
                    if (not isinstance(target, str) or not target.endswith(".safetensors")
                            or target in (".", "..") or "/" in target or "\\" in target
                            or os.path.basename(target) != target):
                        return _verdict("incomplete", "invalid-index-target",
                                        f"{n} names an invalid weight path")
                    targets.append(target)
                for target in sorted(set(targets)):
                    _, bad = _stat_required(os.path.join(path, target), target,
                                            missing_reason="missing-indexed-shard",
                                            invalid_reason="invalid-indexed-shard")
                    if bad:
                        return bad
                    required.add(target)
        else:
            groups = {}
            for n in weights:
                m = _MLX_SHARD_RE.match(n)
                if m:
                    ordinal, total = int(m.group(2)), int(m.group(3))
                    if not 1 <= ordinal <= total:
                        return _verdict("incomplete", "invalid-shard-name",
                                        f"{n} has invalid shard numbering")
                    groups[(m.group(1), total)] = True
            grouped = {n for prefix, total in groups for n in _shard_names(prefix, total, ".safetensors")}
            for n in weights:
                if n in grouped:
                    continue
                _, bad = _stat_required(os.path.join(path, n), n, missing_reason="missing-weight",
                                        invalid_reason="invalid-weight")
                if bad:
                    return bad
                required.add(n)
            for (prefix, total) in groups:
                for shard in _shard_names(prefix, total, ".safetensors"):
                    _, bad = _stat_required(os.path.join(path, shard), shard,
                                            missing_reason="missing-shard", invalid_reason="invalid-shard")
                    if bad:
                        return bad
                    required.add(shard)
        return _verdict("ready", "ready", "model artifact is ready", {
            "v": 1, "real_path": os.path.realpath(path), "device": root.st_dev,
            "manifest": {"kind": "mlx", "files": sorted(required)}})
    if not _stat.S_ISREG(root.st_mode):
        return _verdict("incomplete", "wrong-kind", "GGUF model path is not a file")
    name = os.path.basename(path)
    group = split_gguf_group(name)
    if _GGUF_SHARD_RE.match(name) and group is None:
        return _verdict("incomplete", "invalid-shard-name",
                        f"{name} has invalid shard numbering")
    required = [name]
    if group:
        required = _shard_names(group[0], group[1], ".gguf")
        parent = os.path.dirname(path)
        for shard in required:
            _, bad = _stat_required(os.path.join(parent, shard), shard,
                                    missing_reason="missing-shard", invalid_reason="invalid-shard")
            if bad:
                return bad
    elif root.st_size <= 0:
        return _verdict("incomplete", "empty-file", "GGUF model file is empty")
    mmproj = entry.get("mmproj")
    if mmproj not in (None, "") and not isinstance(mmproj, str):
        return _verdict("incomplete", "invalid-mmproj", "projection file path is invalid")
    if isinstance(mmproj, str) and mmproj:
        _, bad = _stat_required(mmproj, "projection file", missing_reason="missing-mmproj",
                                invalid_reason="invalid-mmproj")
        if bad:
            return bad
        required.append(os.path.basename(mmproj))
    return _verdict("ready", "ready", "model artifact is ready", {
        "v": 1, "real_path": os.path.realpath(path), "device": root.st_dev,
        "manifest": {"kind": "gguf", "files": required}})


def path_present(path: "str | None", fmt: str = "gguf") -> "bool | None":
    """Three-valued compatibility mapping of the structured artifact probe."""
    f = str(fmt or "gguf").lower()
    if f.startswith(_DIR_FORMATS_PREFIX):
        return _audio_type_present(path, f)
    state = artifact_probe({"path": path, "format": f}).get("state")
    return True if state == "ready" else (False if state in ("missing", "incomplete") else None)


def entry_present(m: dict) -> "bool | None":
    """path_present for a whole registry row (three-valued, same contract)."""
    if not isinstance(m, dict):
        return None
    if is_audio(m):
        return _audio_type_present(str(m.get("path") or ""), str(m.get("format") or "gguf"))
    state = artifact_probe(m).get("state")
    return True if state == "ready" else (False if state in ("missing", "incomplete") else None)


def is_absent(m: dict) -> bool:
    """Does this row carry the persisted absent flag? (Strict: only a real True.)"""
    return isinstance(m, dict) and m.get(ABSENT_KEY) is True


def is_audio(m: dict) -> bool:
    """Audio (voice) rows are not chat models. Two spellings exist in the registry —
    `kind: "audio"` (what seed_registry writes) and a tts-/stt- `format` (what a
    download registrar can leave) — and the seeders disagreed about which to check:
    the hermes seed tested both, the others only `kind`. Both, here, once."""
    if not isinstance(m, dict):
        return False
    if m.get("kind") == "audio":
        return True
    return str(m.get("format") or "").strip().lower().startswith(_DIR_FORMATS_PREFIX)


def wire_id(m: dict) -> str:
    """The identifier a client must SEND for this row — the two-identifier rule.

    llama.cpp is launched with `--alias <registry id>`, so its wire name IS the id; the
    MLX servers treat the request's `model` field as a model to LOAD and need the
    registry PATH (an id would be resolved on HuggingFace → 404 → runner 400).

    ★ THIS IS THE ONLY COPY OF THAT RULE (S33/F5, 2026-08-29). It lives HERE rather
    than in core/modelid.py because three of the five consumers are standalone
    scripts that load this file BY PATH and cannot import bridge.core.*;
    modelid.wire_model_id (the id → row lookup) now calls into this function instead
    of restating the branch, and bridge/contract_tests/test_wire_id_contract.py
    fails the gate if the two ever disagree again.
    """
    if not isinstance(m, dict):
        return ""
    mid = str(m.get("id") or "").strip()
    if str(m.get("format") or "gguf").strip().lower() == "mlx":
        return str(m.get("path") or "").strip() or mid
    return mid


def offerable(registry, require_file: bool = True) -> list:
    """★ THE ONE RULE (S29). Every row this app may put in front of a human.

    Keeps: a dict with a non-empty id · not audio · not hidden · not flagged absent ·
    (when require_file) whose file is not PROVABLY gone.

    `require_file=False` exists for the one legitimate caller shape — a consumer that
    already holds a fresher verdict (the bridge's debounced tracker) and only wants the
    flag/hidden/audio half. It does NOT exist as a convenience for skipping the stat.
    """
    out, missing, eligible = [], [], 0
    for m in (registry or []):
        if not isinstance(m, dict):
            continue
        if not str(m.get("id") or "").strip():
            continue
        if is_audio(m) or m.get("hidden") or is_absent(m):
            continue
        eligible += 1
        if require_file:
            state = artifact_probe(m).get("state")
            if state == "incomplete":
                continue
            if state == "missing":
                missing.append(m)
                continue
        out.append(m)
    # ★ THE UNPLUGGED-DISK GUARD (adversarial pass, this slice). Debi keeps models on an
    # external volume and in LM Studio's library; pull the cable and EVERY path answers
    # ENOENT at once. Without this, one enumeration would empty Hermes's row, collapse
    # OpenCode's catalog to its placeholder, and strip Odysseus's pins — over a cable,
    # and the next seed with the disk back would not undo the confusion it caused.
    # "Every single model in the registry vanished simultaneously" is not a user
    # deleting models; it is us losing sight of the disk, and the standing rule is that
    # what we cannot see we do not claim. So the FILE clause abstains entirely in that
    # case (audio/hidden/absent still apply — those are recorded facts, not stats).
    # A registry that is genuinely empty stays empty: the guard needs candidates to fire.
    if missing and not out and len(missing) == eligible:
        return list(missing)
    return out


def offerable_wire_ids(registry, active: str = "", require_file: bool = True) -> list:
    """offerable() as the wire identifiers, de-duplicated, first-seen order, with
    `active` hoisted to the front so a fresh default lands on the loaded model."""
    out: list = []
    for m in offerable(registry, require_file=require_file):
        w = wire_id(m)
        if w and w not in out:
            out.append(w)
    a = str(active or "").strip()
    if a:
        if a in out:
            out.remove(a)
        out.insert(0, a)
    return out


# ── registry + pin readers (no yaml dependency — the seeders have none) ───────
def registry_path(root: str = ".") -> str:
    return os.path.join(root or ".", "data", "models.json")


def load_registry(root: str = ".") -> list:
    """The registry's model list, or [] when absent/unreadable.

    ⚠️ [] IS NOT A DECISION. Every consumer must treat an empty list as "we learned
    nothing this run" and leave whatever it already advertised alone — an unreadable
    registry for one Start must never empty a working picker (the rule seed_odysseus_jan
    already spells out at its `w_models` guard)."""
    try:
        with open(registry_path(root), encoding="utf-8") as fh:
            data = json.load(fh)
        models = data.get("models", []) if isinstance(data, dict) else []
        return models if isinstance(models, list) else []
    except Exception:                                            # noqa: BLE001
        return []


_PIN_RE = re.compile(r"^\s{2}model:\s*(.+?)\s*$")


def pinned_model_id(root: str = ".") -> str:
    """harness.yaml's `runner.model` — the PIN, read without pyyaml.

    An INTENT record, never evidence that a model exists (U18): it is read here only so
    the rescan knows which row it must flag-rather-than-remove."""
    try:
        with open(os.path.join(root or ".", "harness.yaml"), encoding="utf-8") as fh:
            in_runner = False
            for line in fh:
                if line and not line[:1].isspace():
                    in_runner = line.rstrip().startswith("runner:")
                    continue
                if not in_runner:
                    continue
                m = _PIN_RE.match(line.rstrip("\n"))
                if m:
                    v = m.group(1).split("#", 1)[0].strip().strip('"').strip("'")
                    return v
    except Exception:                                            # noqa: BLE001
        pass
    return ""


def protected_ids(root: str = ".", extra=()) -> set:
    """Ids a rescan must FLAG rather than REMOVE: the pin, plus whatever the caller
    knows is live. Also honours HARNESS_PROTECT_MODELS (newline- or comma-separated),
    which is how the bridge's rescan route hands the live model to the seed subprocess.
    """
    out = {str(x).strip() for x in (extra or []) if str(x or "").strip()}
    pin = pinned_model_id(root)
    if pin:
        out.add(pin)
    raw = os.environ.get("HARNESS_PROTECT_MODELS") or ""
    for part in raw.replace(",", "\n").splitlines():
        if part.strip():
            out.add(part.strip())
    return out


# ── loading this module from a standalone script ─────────────────────────────
def load_by_path(from_file: str):
    """Import THIS module from a script that is not part of the bridge package.

    `from_file` is the calling script's __file__; the module is resolved relative to it
    (never the cwd), so it works from the repo and from the provisioned snapshot alike.
    Returns None if it cannot be loaded — and every caller must then fall back to its
    own inline rule rather than enumerating nothing, because a helper that fails to
    import must not empty a user's model picker.
    """
    import importlib.util
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(from_file)),
                         os.pardir, "bridge", "core", "modelreg.py")
        spec = importlib.util.spec_from_file_location("harness_modelreg", p)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:                                            # noqa: BLE001
        return None


# ── the shell-consumable form (scripts/start_component.sh) ───────────────────
def main(argv=None) -> int:
    """`python3 bridge/core/modelreg.py [--root DIR] [--wire-ids|--ids|--json]`

    The SAME rule, for the shell arms that cannot import Python. Default output is one
    wire id per line — safe to read with `while IFS= read -r`, and deliberately NOT
    space-separated, because MLX wire ids are filesystem paths.
    """
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    root, mode = ".", "--wire-ids"
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--root" and i + 1 < len(argv):
            root = argv[i + 1]
            i += 2
            continue
        if a in ("--wire-ids", "--ids", "--json", "--count"):
            mode = a
        i += 1
    reg = load_registry(root)
    keep = offerable(reg)
    if mode == "--json":
        print(json.dumps(keep, indent=2))
    elif mode == "--count":
        print(len(keep))
    elif mode == "--ids":
        for m in keep:
            print(m.get("id"))
    else:
        for w in offerable_wire_ids(reg):
            print(w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
