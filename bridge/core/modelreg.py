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
import struct
import tempfile
import threading
from contextlib import contextmanager
import fcntl

# The persisted flag. `absent: true` on a registry row means: the two-strike file check
# said this row's artifact is not on disk. The row KEEPS ITS IDENTITY (its id, its ctx,
# its pinned voice, its per-model sampling) because the file may be on a volume that is
# merely unplugged — we never silently delete a row over a stat. Removal happens in
# exactly one place, and only on an explicit human action: the Models view's RESCAN.
ABSENT_KEY = "absent"
EVIDENCE_KEY = "artifact_evidence"
_REGISTRY_LOCKS, _REGISTRY_LOCKS_GUARD, _REGISTRY_LOCK_STATE = {}, threading.Lock(), threading.local()


def _require_regular(path, *, absent_ok=False):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        if absent_ok:
            return None
        raise
    if not _stat.S_ISREG(info.st_mode):
        raise ValueError(f"refusing non-regular model registry state file: {path}")
    return info


def _read_registry_text(path):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        if not _stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError(f"refusing non-regular model registry state file: {path}")
        with os.fdopen(fd, "r", encoding="utf-8") as fh:
            fd = -1
            return fh.read()
    finally:
        if fd >= 0:
            os.close(fd)


@contextmanager
def registry_lock(path: str | None = None):
    """Cross-process, re-entrant exclusion for one registry read-modify-replace."""
    registry = os.path.abspath(path or os.path.join("data", "models.json"))
    with _REGISTRY_LOCKS_GUARD:
        mutex = _REGISTRY_LOCKS.setdefault(registry, threading.RLock())
    with mutex:
        held = getattr(_REGISTRY_LOCK_STATE, "held", {})
        if held.get(registry):
            held[registry] += 1
            try:
                yield
            finally:
                held[registry] -= 1
            return
        os.makedirs(os.path.dirname(registry) or ".", exist_ok=True)
        lock_path = registry + ".lock"
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR
                     | getattr(os, "O_NOFOLLOW", 0), 0o600)
        held[registry] = 1
        _REGISTRY_LOCK_STATE.held = held
        try:
            if not _stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError(f"refusing non-regular model registry lock: {lock_path}")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            held.pop(registry, None)
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def write_registry(path: str, data: dict) -> bool:
    """One deterministic, crash-resistant writer for ``models.json``.

    Callers normally hold :func:`registry_lock` across their read/modify/write; this
    helper takes it re-entrantly as a guard against future direct callers. Returns
    False for a byte-identical no-op and True after replacement.
    """
    registry = os.path.abspath(path)
    payload = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with registry_lock(registry):
        try:
            if _read_registry_text(registry) == payload:
                return False
        except FileNotFoundError:
            pass
        except UnicodeError:
            # A corrupt regular registry is recoverable from a validated fresh scan.
            pass
        directory = os.path.dirname(registry) or "."
        os.makedirs(directory, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".models-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            _require_regular(registry, absent_ok=True)
            os.replace(temporary, registry)
            temporary = ""
            try:
                dir_fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
        finally:
            if temporary:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
        return True


def opencode_model_key(model_id) -> str:
    """The current OpenCode address key for one M.O.T registry id.

    Kept here so the seeder and the running-process drift probe cannot silently use
    different normalizations. Collision-free escaping is a separate migration: the
    legacy slash-to-underscore contract is preserved until existing saved defaults
    and live catalogs can be migrated coherently.
    """
    return str(model_id or "").replace("/", "_")

# Registry formats whose artifact is a DIRECTORY rather than a single file. Byte for
# byte the rule scripts/start_component.sh resolves with, widened to the audio kinds
# (checkpoint directories). Anything unrecognised is treated as a file, which is what
# `gguf` — the overwhelming majority — is.
_DIR_FORMATS_PREFIX = ("stt-", "tts-")
_GGUF_SHARD_RE = re.compile(r"^(.*)-(\d{5})-of-(\d{5})\.gguf$", re.I)
_MLX_SHARD_RE = re.compile(r"^(.*)-(\d{5})-of-(\d{5})\.safetensors$", re.I)
# Exact ``enum ggml_type`` values in the pinned llama.cpp b10662 reader. Removed
# historical slots are intentionally absent. A future type must first arrive through
# a pin update plus its own fixture; an invented numeric ceiling is not format proof.
_PINNED_GGML_TYPES = frozenset(
    (0, 1, 2, 3, *range(6, 31), 34, 35, 39, 40, 41, 42)
)


def wants_dir(fmt: "str | None") -> bool:
    f = str(fmt or "gguf").lower()
    return f == "mlx" or f.startswith(_DIR_FORMATS_PREFIX)


def _verdict(state, reason, detail, evidence=None):
    return {"state": state, "reason": reason, "detail": detail,
            "evidence": evidence or {}}


def _stat_required(path, label, *, missing_reason, invalid_reason):
    """A regular/non-empty direct-file check used before format validation."""
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


def _gguf_header(path, label, *, invalid_reason):
    """Validate the bounded GGUF metadata and tensor-info structure.

    Tensor payload bytes are never read and semantic/runnable validity remains the
    serving engine's job. Unlike the rejected prefix-only draft, however, nonzero
    inventory counters are not trusted until every declared metadata value and tensor
    descriptor can be walked within the real file bounds.
    """
    try:
        with open(path, "rb") as fh:
            size = os.fstat(fh.fileno()).st_size
            structure_limit = min(size, 256 * 1024 * 1024)

            def take(n):
                n = int(n)
                if n < 0 or n > structure_limit - fh.tell():
                    raise ValueError("truncated structure")
                value = fh.read(n)
                if len(value) != n:
                    raise ValueError("truncated structure")
                return value

            def skip(n):
                n = int(n)
                if n < 0 or n > structure_limit - fh.tell():
                    raise ValueError("structure exceeds bounded header budget")
                fh.seek(n, os.SEEK_CUR)

            def u32():
                return struct.unpack("<I", take(4))[0]

            def u64():
                return struct.unpack("<Q", take(8))[0]

            def text(*, maximum=8 * 1024 * 1024):
                length = u64()
                if length > maximum:
                    raise ValueError("implausible string length")
                return take(length).decode("utf-8")

            fixed = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4,
                     6: 4, 7: 1, 10: 8, 11: 8, 12: 8}

            def value(vtype, *, keep_u32=False):
                if vtype in fixed:
                    raw = take(fixed[vtype])
                    return struct.unpack("<I", raw)[0] if keep_u32 and vtype == 4 else None
                if vtype == 8:                       # GGUF string
                    text()
                    return None
                if vtype != 9:                       # GGUF array
                    raise ValueError("unknown metadata type")
                element_type, count = u32(), u64()
                if element_type == 9:
                    raise ValueError("nested metadata array")
                if element_type in fixed:
                    skip(fixed[element_type] * count)
                    return None
                if element_type == 8:
                    # Each string needs at least its uint64 length prefix. This bound
                    # prevents an attacker declaring billions of empty strings and
                    # turning Rescan into an unbounded loop.
                    if count > (structure_limit - fh.tell()) // 8:
                        raise ValueError("implausible string array length")
                    for _ in range(count):
                        text()
                    return None
                raise ValueError("unknown array element type")

            if take(4) != b"GGUF":
                raise ValueError("wrong magic")
            version = u32()
            if version == 1:
                tensor_count, metadata_count = u32(), u32()
            elif version in (2, 3):
                tensor_count, metadata_count = u64(), u64()
            else:
                raise ValueError("unsupported version")
            if tensor_count < 1 or tensor_count > 10_000_000:
                raise ValueError("empty or implausible tensor inventory")
            if metadata_count < 1 or metadata_count > 100_000:
                raise ValueError("empty or implausible metadata inventory")

            alignment = 32
            metadata_keys = set()
            for _ in range(metadata_count):
                key = text()
                if not key or key in metadata_keys:
                    raise ValueError("empty or duplicate metadata key")
                metadata_keys.add(key)
                vtype = u32()
                kept = value(vtype, keep_u32=(key == "general.alignment"))
                if key == "general.alignment":
                    if kept is None or kept < 1 or kept > 4096 or kept & (kept - 1):
                        raise ValueError("invalid tensor alignment")
                    alignment = kept

            tensor_names, offsets = set(), []
            for _ in range(tensor_count):
                name = text(maximum=64)
                if not name or name in tensor_names:
                    raise ValueError("empty or duplicate tensor name")
                tensor_names.add(name)
                dimensions = u32()
                if dimensions < 1 or dimensions > 4:
                    raise ValueError("invalid tensor rank")
                if any(u64() < 1 for _ in range(dimensions)):
                    raise ValueError("empty tensor dimension")
                tensor_type = u32()
                if tensor_type not in _PINNED_GGML_TYPES:
                    raise ValueError("tensor type is not supported by the pinned reader")
                offset = u64()
                if offset % alignment:
                    raise ValueError("misaligned tensor offset")
                offsets.append(offset)

            data_start = fh.tell() + ((-fh.tell()) % alignment)
            if data_start >= size or len(set(offsets)) != len(offsets):
                raise ValueError("missing tensor data or duplicate offsets")
            if any(offset > size - data_start - 1 for offset in offsets):
                raise ValueError("tensor offset is outside the data buffer")
    except OSError:
        return _verdict("unknown", "unreadable", f"could not read {label}")
    except (UnicodeError, ValueError, TypeError, struct.error, OverflowError):
        return _verdict("incomplete", invalid_reason,
                        f"{label} has no valid GGUF structure")
    return None


def _safetensors_header(path, label, *, invalid_reason):
    """Validate a safetensors header and each tensor's declared byte interval."""
    try:
        size = os.stat(path).st_size
        with open(path, "rb") as fh:
            prefix = fh.read(8)
            if len(prefix) != 8:
                raise ValueError("truncated length")
            header_len = struct.unpack("<Q", prefix)[0]
            if header_len < 2 or header_len > 100_000_000 or header_len > size - 8:
                raise ValueError("header length is outside the file")
            raw = fh.read(header_len)
        header = json.loads(raw.decode("utf-8"))
        if not isinstance(header, dict):
            raise ValueError("header is not an object")
        metadata = header.get("__metadata__")
        if metadata is not None and (not isinstance(metadata, dict)
                or any(not isinstance(k, str) or not isinstance(v, str)
                       for k, v in metadata.items())):
            raise ValueError("metadata is malformed")
        tensors = [(name, spec) for name, spec in header.items() if name != "__metadata__"]
        if not tensors:
            raise ValueError("header has no tensors")
        payload = size - 8 - header_len
        # Current safetensors core enum, including packed sub-byte and float8 forms.
        # A guessed regex such as F<number> would accept spellings no reader supports;
        # a stale short allowlist would reject valid MXFP4/FP8 models. Keep this list
        # pinned to the upstream enum and cover every width in fixtures.
        dtype_bits = {
            "BOOL": 8, "F4": 4, "F6_E2M3": 6, "F6_E3M2": 6,
            "U8": 8, "I8": 8, "F8_E4M3": 8, "F8_E5M2": 8,
            "F8_E8M0": 8, "F8_E4M3FNUZ": 8, "F8_E5M2FNUZ": 8,
            "I16": 16, "U16": 16, "F16": 16, "BF16": 16,
            "F32": 32, "I32": 32, "U32": 32,
            "F64": 64, "I64": 64, "U64": 64, "C64": 64,
        }
        intervals = []
        for name, spec in tensors:
            if not isinstance(name, str) or not name or not isinstance(spec, dict):
                raise ValueError("tensor entry is malformed")
            dtype, shape, offsets = spec.get("dtype"), spec.get("shape"), spec.get("data_offsets")
            if not isinstance(dtype, str) or not dtype:
                raise ValueError("tensor dtype is absent")
            if dtype not in dtype_bits:
                raise ValueError("tensor dtype is unsupported")
            if (not isinstance(shape, list)
                    or any(isinstance(n, bool) or not isinstance(n, int) or n < 0 for n in shape)):
                raise ValueError("tensor shape is malformed")
            if (not isinstance(offsets, list) or len(offsets) != 2
                    or any(isinstance(n, bool) or not isinstance(n, int) or n < 0 for n in offsets)
                    or offsets[0] > offsets[1] or offsets[1] > payload):
                raise ValueError("tensor byte interval is malformed")
            elements = 1
            for dimension in shape:
                elements *= dimension
            bits = elements * dtype_bits[dtype]
            if bits % 8 or offsets[1] - offsets[0] != bits // 8:
                raise ValueError("tensor byte interval does not match dtype and shape")
            intervals.append((offsets[0], offsets[1]))
        cursor = 0
        for start, end in sorted(intervals):
            if start != cursor:
                raise ValueError("tensor intervals overlap or leave a hole")
            cursor = end
        if cursor != payload:
            raise ValueError("tensor intervals do not cover the data buffer")
    except OSError:
        return _verdict("unknown", "unreadable", f"could not read {label}")
    except (UnicodeError, ValueError, TypeError, struct.error):
        return _verdict("incomplete", invalid_reason,
                        f"{label} has no valid safetensors header")
    return None


def _mlx_config_has_identity(config):
    """Require an architecture signal, not merely a syntactically valid JSON object."""
    if not isinstance(config, dict) or not config:
        return False
    if isinstance(config.get("model_type"), str) and config["model_type"].strip():
        return True
    architectures = config.get("architectures")
    if (isinstance(architectures, list) and architectures
            and all(isinstance(item, str) and item.strip() for item in architectures)):
        return True
    text = config.get("text_config")
    return isinstance(text, dict) and _mlx_config_has_identity(text)


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
    """Read-only structural verdict for one chat GGUF or MLX artifact.

    This verifies required files plus GGUF/safetensors headers and an MLX architecture
    declaration. It deliberately does not claim semantic correctness or runnability:
    only the serving engine can establish those by loading the full artifact.
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
        if not _mlx_config_has_identity(cfg):
            return _verdict("incomplete", "invalid-config",
                            "config.json has no model architecture identity")
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
                if st is not None and _safetensors_header(
                        os.path.join(path, n), n, invalid_reason="invalid-weight") is None:
                    valid_weight = True
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
                    target_path = os.path.join(path, target)
                    _, bad = _stat_required(target_path, target,
                                            missing_reason="missing-indexed-shard",
                                            invalid_reason="invalid-indexed-shard")
                    if bad:
                        return bad
                    bad = _safetensors_header(target_path, target,
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
                weight_path = os.path.join(path, n)
                _, bad = _stat_required(weight_path, n, missing_reason="missing-weight",
                                        invalid_reason="invalid-weight")
                if bad:
                    return bad
                bad = _safetensors_header(weight_path, n, invalid_reason="invalid-weight")
                if bad:
                    return bad
                required.add(n)
            for (prefix, total) in groups:
                for shard in _shard_names(prefix, total, ".safetensors"):
                    shard_path = os.path.join(path, shard)
                    _, bad = _stat_required(shard_path, shard,
                                            missing_reason="missing-shard", invalid_reason="invalid-shard")
                    if bad:
                        return bad
                    bad = _safetensors_header(shard_path, shard,
                                              invalid_reason="invalid-shard")
                    if bad:
                        return bad
                    required.add(shard)
        return _verdict("ready", "structurally-ready", "model artifact is structurally ready", {
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
            shard_path = os.path.join(parent, shard)
            _, bad = _stat_required(shard_path, shard,
                                    missing_reason="missing-shard", invalid_reason="invalid-shard")
            if bad:
                return bad
            bad = _gguf_header(shard_path, shard, invalid_reason="invalid-shard")
            if bad:
                return bad
    elif root.st_size <= 0:
        return _verdict("incomplete", "empty-file", "GGUF model file is empty")
    else:
        bad = _gguf_header(path, name, invalid_reason="invalid-header")
        if bad:
            return bad
    mmproj = entry.get("mmproj")
    if mmproj not in (None, "") and not isinstance(mmproj, str):
        return _verdict("incomplete", "invalid-mmproj", "projection file path is invalid")
    if isinstance(mmproj, str) and mmproj:
        _, bad = _stat_required(mmproj, "projection file", missing_reason="missing-mmproj",
                                invalid_reason="invalid-mmproj")
        if bad:
            return bad
        bad = _gguf_header(mmproj, "projection file", invalid_reason="invalid-mmproj")
        if bad:
            return bad
        required.append(os.path.basename(mmproj))
    return _verdict("ready", "structurally-ready", "model artifact is structurally ready", {
        "v": 1, "real_path": os.path.realpath(path), "device": root.st_dev,
        "manifest": {"kind": "gguf", "files": required}})


def _mount_root(real_path: str, device: int) -> str | None:
    """Deepest mounted ancestor observed with a ready artifact; never raises."""
    try:
        here = real_path if os.path.isdir(real_path) else os.path.dirname(real_path)
        while True:
            parent = os.path.dirname(here)
            if here == parent or os.path.ismount(here):
                return here
            if os.stat(parent).st_dev != device:
                return here
            here = parent
    except (OSError, TypeError, ValueError):
        return None


def artifact_evidence(entry: dict, probe: dict | None = None) -> dict | None:
    """Names-only v1 identity evidence for an explicit ready Rescan observation."""
    probe = probe or artifact_probe(entry)
    if not isinstance(probe, dict) or probe.get("state") != "ready" or is_audio(entry):
        return None
    evidence = probe.get("evidence") if isinstance(probe.get("evidence"), dict) else {}
    real_path, device, manifest = evidence.get("real_path"), evidence.get("device"), evidence.get("manifest")
    if not isinstance(real_path, str) or not os.path.isabs(real_path) or isinstance(device, bool) or not isinstance(device, int):
        return None
    if not _entry_matches_evidence(entry, real_path, manifest):
        return None
    mount_root = _mount_root(real_path, device)
    return ({"v": 1, "real_path": real_path, "device": device,
             "mount_root": mount_root, "manifest": manifest} if mount_root else None)


def _valid_manifest(manifest) -> bool:
    if not isinstance(manifest, dict) or set(manifest) != {"kind", "files"}:
        return False
    if manifest.get("kind") not in ("gguf", "mlx"):
        return False
    files = manifest.get("files")
    return (isinstance(files, list) and bool(files) and len(files) == len(set(files))
            and all(isinstance(f, str) and f and f not in (".", "..") and not os.path.isabs(f)
                    and os.path.basename(f) == f and os.path.normpath(f) == f for f in files))


def _entry_matches_evidence(entry, real_path, manifest) -> bool:
    """Evidence authorizes only the exact artifact and shape that was observed."""
    if not isinstance(entry, dict) or not _valid_manifest(manifest):
        return False
    path = entry.get("path")
    if not isinstance(path, str) or not path:
        return False
    try:
        if os.path.realpath(path) != real_path:
            return False
    except (OSError, TypeError, ValueError):
        return False
    expected_kind = "mlx" if str(entry.get("format") or "gguf").lower() == "mlx" else "gguf"
    return manifest.get("kind") == expected_kind


def _valid_evidence(evidence) -> bool:
    if (not isinstance(evidence, dict) or set(evidence) != {"v", "real_path", "device", "mount_root", "manifest"}
            or isinstance(evidence.get("v"), bool) or evidence.get("v") != 1):
        return False
    real_path, mount_root, device = evidence.get("real_path"), evidence.get("mount_root"), evidence.get("device")
    if (not isinstance(real_path, str) or not isinstance(mount_root, str)
            or not os.path.isabs(real_path) or not os.path.isabs(mount_root)
            or os.path.normpath(real_path) != real_path or os.path.normpath(mount_root) != mount_root
            or isinstance(device, bool) or not isinstance(device, int) or not _valid_manifest(evidence.get("manifest"))):
        return False
    try:
        return os.path.commonpath((real_path, mount_root)) == mount_root
    except (TypeError, ValueError):
        return False


def source_availability(entry: dict, probe: dict | None = None) -> dict:
    """Classify a missing chat artifact's source without trusting legacy guesses."""
    probe = probe or artifact_probe(entry)
    state = probe.get("state") if isinstance(probe, dict) else "unknown"
    if state in ("ready", "incomplete"):
        return {"state": "available", "reason": state, "detail": "artifact probe is not missing"}
    if state != "missing":
        return {"state": "unknown", "reason": "probe-unknown", "detail": "artifact could not be checked"}
    evidence = entry.get(EVIDENCE_KEY) if isinstance(entry, dict) else None
    if not _valid_evidence(evidence):
        return {"state": "unknown", "reason": "invalid-evidence", "detail": "no valid ready artifact evidence"}
    if not _entry_matches_evidence(entry, evidence["real_path"], evidence["manifest"]):
        return {"state": "unknown", "reason": "identity-mismatch",
                "detail": "current artifact path or format differs from ready evidence"}
    root = evidence["mount_root"]
    try:
        st = os.stat(root)
        mounted = root == os.path.sep or os.path.ismount(root)
    except (FileNotFoundError, NotADirectoryError):
        return {"state": "unavailable", "reason": "mount-missing", "detail": "recorded model source is unavailable"}
    except (OSError, TypeError, ValueError):
        return {"state": "unknown", "reason": "mount-unreadable", "detail": "could not read recorded model source"}
    if not _stat.S_ISDIR(st.st_mode) or not mounted or st.st_dev != evidence["device"]:
        return {"state": "unavailable", "reason": "mount-unavailable", "detail": "recorded model source is unavailable"}
    return {"state": "available", "reason": "mount-present", "detail": "recorded model source is available"}


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


def source_membership(m: dict) -> str:
    """Validated external-manager membership carried by the registry row."""
    value = m.get("source_membership") if isinstance(m, dict) else None
    return value if value in ("listed", "unlisted") else "unknown"


def is_source_unlisted(m: dict) -> bool:
    return source_membership(m) == "unlisted"


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
    out = []
    for m in (registry or []):
        if not isinstance(m, dict):
            continue
        if not str(m.get("id") or "").strip():
            continue
        if is_audio(m) or m.get("hidden") or is_absent(m) or is_source_unlisted(m):
            continue
        if require_file:
            probe = artifact_probe(m)
            state = probe.get("state")
            if state == "incomplete":
                continue
            if state == "missing":
                if source_membership(m) == "listed":
                    continue
                if source_availability(m, probe).get("state") == "available":
                    continue
        out.append(m)
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
