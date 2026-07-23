#!/usr/bin/env python3
"""Build data/models.json — the harness's own model registry (llamacpp adapter).

Scans Jan's model folder (imports GGUF models the user already has) and merges the
result into data/models.json, preserving any non-jan-import entries (e.g. future
download-manager additions). stdlib only.

Structured as functions so the scan/merge logic can be unit-tested against a temp
Jan dir without touching the real one. main() uses the real paths.
"""
import os
import json
import configparser

JAN_MODELS_DIR = os.path.expanduser(
    "~/Library/Application Support/Jan/data/llamacpp/models")
JAN_PRESET_INI = os.path.expanduser(
    "~/Library/Application Support/Jan/data/llamacpp/router.preset.ini")
LMSTUDIO_MODELS_DIR = os.path.expanduser("~/.lmstudio/models")
REGISTRY_PATH = os.path.join("data", "models.json")


def _load_preset(preset_path):
    """Parse router.preset.ini → {section_id: ctx_size_int}. Ignores [*] defaults."""
    ctx_by_id = {}
    if not os.path.isfile(preset_path):
        return ctx_by_id
    cfg = configparser.ConfigParser()
    try:
        cfg.read(preset_path)
    except Exception:
        return ctx_by_id
    for section in cfg.sections():
        if section == "*":
            continue
        raw = cfg.get(section, "ctx-size", fallback=None)
        if raw is None:
            continue
        try:
            ctx_by_id[section] = int(str(raw).strip())
        except (ValueError, TypeError):
            ctx_by_id[section] = None
    return ctx_by_id


def scan_jan(jan_dir, preset_path=JAN_PRESET_INI):
    """Return a list of jan-import registry entries for every subfolder of jan_dir
    that contains a model.gguf."""
    entries = []
    if not os.path.isdir(jan_dir):
        return entries
    ctx_by_id = _load_preset(preset_path)
    for name in sorted(os.listdir(jan_dir)):
        folder = os.path.join(jan_dir, name)
        if not os.path.isdir(folder):
            continue
        model_path = os.path.join(folder, "model.gguf")
        if not os.path.isfile(model_path):
            continue
        mmproj_path = os.path.join(folder, "mmproj.gguf")
        mmproj = mmproj_path if os.path.isfile(mmproj_path) else None
        try:
            size_bytes = os.path.getsize(model_path)
        except OSError:
            size_bytes = None
        entries.append({
            "id": name,
            "name": name,
            "format": "gguf",
            "path": os.path.abspath(model_path),
            "mmproj": os.path.abspath(mmproj) if mmproj else None,
            "size_bytes": size_bytes,
            "ctx": ctx_by_id.get(name),
            "vision": bool(mmproj),
            "source": "jan-import",
        })
    return entries


def scan_lmstudio(lms_dir):
    """Return lmstudio-import registry entries by walking exactly two levels:
    <lms_dir>/<publisher>/<model_dir>/. GGUF files → one entry each; an MLX model
    dir (config.json + >=1 *.safetensors) → one entry."""
    entries = []
    if not os.path.isdir(lms_dir):
        return entries
    for publisher in sorted(os.listdir(lms_dir)):
        pub_dir = os.path.join(lms_dir, publisher)
        if not os.path.isdir(pub_dir):
            continue
        for model_dir_name in sorted(os.listdir(pub_dir)):
            model_dir = os.path.join(pub_dir, model_dir_name)
            if not os.path.isdir(model_dir):
                continue
            files = os.listdir(model_dir)
            # GGUF files directly inside the model dir (skip mmproj files).
            ggufs = [f for f in sorted(files)
                     if f.endswith(".gguf") and "mmproj" not in f
                     and os.path.isfile(os.path.join(model_dir, f))]
            mmproj_files = [f for f in files
                            if f.endswith(".gguf") and "mmproj" in f
                            and os.path.isfile(os.path.join(model_dir, f))]
            mmproj = (os.path.abspath(os.path.join(model_dir, mmproj_files[0]))
                      if len(mmproj_files) == 1 else None)
            for fname in ggufs:
                fpath = os.path.join(model_dir, fname)
                stem = os.path.splitext(fname)[0]
                try:
                    size_bytes = os.path.getsize(fpath)
                except OSError:
                    size_bytes = None
                entries.append({
                    "id": stem,
                    "name": stem,
                    "format": "gguf",
                    "path": os.path.abspath(fpath),
                    "mmproj": mmproj,
                    "size_bytes": size_bytes,
                    "ctx": None,
                    "vision": bool(mmproj),
                    "source": "lmstudio-import",
                })
            # MLX model dir (config.json + safetensors).
            config_path = os.path.join(model_dir, "config.json")
            safetensors = [f for f in files if f.endswith(".safetensors")
                           and os.path.isfile(os.path.join(model_dir, f))]
            if os.path.isfile(config_path) and safetensors:
                total = 0
                for f in safetensors:
                    try:
                        total += os.path.getsize(os.path.join(model_dir, f))
                    except OSError:
                        pass
                vision = False
                try:
                    with open(config_path) as fh:
                        cfg = json.load(fh)
                    vision = "vision_config" in cfg
                except Exception:
                    vision = False
                entries.append({
                    "id": model_dir_name,
                    "name": model_dir_name,
                    "format": "mlx",
                    "path": os.path.abspath(model_dir),
                    "mmproj": None,
                    "size_bytes": total,
                    "ctx": None,
                    "vision": vision,
                    "source": "lmstudio-import",
                })
    return entries


def load_existing(path):
    """Return the existing registry's model list (or [] if none/invalid)."""
    if not os.path.isfile(path):
        return []
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data.get("models", []) or []
    except Exception:
        return []


def merge(existing, jan_entries, lmstudio_entries=None):
    """Keep every existing entry whose source is neither 'jan-import' nor
    'lmstudio-import'; replace each of those sets with its fresh scan. On id
    collision, suffix the lmstudio entry's id with '-lms'."""
    lmstudio_entries = lmstudio_entries or []
    kept = [m for m in existing
            if m.get("source") not in ("jan-import", "lmstudio-import")]
    result = kept + list(jan_entries)
    used = {m.get("id") for m in result}
    for m in lmstudio_entries:
        if m.get("id") in used:
            m = dict(m)
            m["id"] = f"{m['id']}-lms"
        used.add(m.get("id"))
        result.append(m)
    return result


def write(path, models):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump({"models": models}, fh, indent=2)
        fh.write("\n")


def main():
    jan_entries = scan_jan(JAN_MODELS_DIR)
    lmstudio_entries = scan_lmstudio(LMSTUDIO_MODELS_DIR)
    existing = load_existing(REGISTRY_PATH)
    merged = merge(existing, jan_entries, lmstudio_entries)
    write(REGISTRY_PATH, merged)
    print(f"seeded {len(merged)} models "
          f"({len(jan_entries)} jan-imports, {len(lmstudio_entries)} lmstudio-imports)")


if __name__ == "__main__":
    main()
