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
            "source": "jan-import",
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


def merge(existing, jan_entries):
    """Keep every existing entry whose source != 'jan-import'; replace the
    jan-import set with the fresh scan."""
    kept = [m for m in existing if m.get("source") != "jan-import"]
    return kept + jan_entries


def write(path, models):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump({"models": models}, fh, indent=2)
        fh.write("\n")


def main():
    jan_entries = scan_jan(JAN_MODELS_DIR)
    existing = load_existing(REGISTRY_PATH)
    merged = merge(existing, jan_entries)
    write(REGISTRY_PATH, merged)
    print(f"seeded {len(merged)} models ({len(jan_entries)} jan-imports)")


if __name__ == "__main__":
    main()
