"""Single local secret store for launch configuration that must not live in YAML."""
from __future__ import annotations

import os
import base64
from pathlib import Path
import secrets
import stat
import tempfile
from typing import Mapping

import yaml

from ..yamlfile import transform_file


SECRET_PATHS = {
    "runner.api_key": "MOT_RUNNER_API_KEY",
    "aux.api_key": "MOT_AUX_API_KEY",
    "components.odysseus.admin_user": "MOT_ODYSSEUS_ADMIN_USER",
    "components.odysseus.admin_password": "MOT_ODYSSEUS_ADMIN_PASSWORD",
}
WEAK_DEFAULTS = {
    "MOT_RUNNER_API_KEY": "harness-local",
    "MOT_AUX_API_KEY": "harness-aux",
    "MOT_ODYSSEUS_ADMIN_USER": "admin",
    "MOT_ODYSSEUS_ADMIN_PASSWORD": "admin123",
}
MAX_BYTES = 16 * 1024


def _path(root: Path) -> Path:
    return Path(root) / "data" / ".env.local"


def _read_regular(path: Path) -> str:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("local secret store is not a regular file")
        if info.st_mode & 0o077:
            raise PermissionError("data/.env.local must be mode 0600")
        if info.st_size > MAX_BYTES:
            raise ValueError("local secret store is unexpectedly large")
        with os.fdopen(fd, encoding="utf-8") as handle:
            fd = -1
            return handle.read()
    finally:
        if fd >= 0:
            os.close(fd)


def read(root: Path) -> dict[str, str]:
    path = _path(root)
    try:
        text = _read_regular(path)
    except FileNotFoundError:
        return {}
    values: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid data/.env.local line {number}")
        stored_key, encoded = line.split("=", 1)
        stored_key, encoded = stored_key.strip(), encoded.strip()
        if not stored_key.endswith("_B64"):
            raise ValueError(f"invalid data/.env.local entry on line {number}")
        key = stored_key[:-4]
        if key not in SECRET_PATHS.values() or not encoded:
            raise ValueError(f"invalid data/.env.local entry on line {number}")
        try:
            padded = encoded + "=" * (-len(encoded) % 4)
            value = base64.b64decode(padded, altchars=b"-_", validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError(f"invalid data/.env.local encoding on line {number}") from exc
        if not value or "\x00" in value or "\n" in value or "\r" in value:
            raise ValueError(f"invalid data/.env.local value on line {number}")
        if key in values:
            raise ValueError(f"duplicate data/.env.local entry on line {number}")
        values[key] = value
    if values and set(values) != set(SECRET_PATHS.values()):
        raise ValueError("data/.env.local is incomplete")
    return values


def _yaml_value(data: Mapping, dotted: str) -> str:
    value: object = data
    for part in dotted.split("."):
        if not isinstance(value, Mapping):
            return ""
        value = value.get(part)
    return value.strip() if isinstance(value, str) else ""


def generate() -> dict[str, str]:
    return {
        "MOT_RUNNER_API_KEY": secrets.token_urlsafe(32),
        "MOT_AUX_API_KEY": secrets.token_urlsafe(32),
        "MOT_ODYSSEUS_ADMIN_USER": "mot-admin-" + secrets.token_hex(4),
        "MOT_ODYSSEUS_ADMIN_PASSWORD": secrets.token_urlsafe(32),
    }


def write(root: Path, values: Mapping[str, str]) -> None:
    missing = set(SECRET_PATHS.values()) - set(values)
    if missing:
        raise ValueError("local secret set is incomplete")
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded: dict[str, str] = {}
    for key in SECRET_PATHS.values():
        value = values[key]
        if not isinstance(value, str) or not value or "\x00" in value or "\n" in value or "\r" in value:
            raise ValueError(f"invalid local secret value for {key}")
        encoded[key] = base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")
    payload = "# M.O.T local launch secrets — base64 encoded; do not commit or share.\n" + "".join(
        f"{key}_B64={encoded[key]}\n" for key in SECRET_PATHS.values())
    fd, raw = tempfile.mkstemp(prefix=".env-local-", suffix=".tmp", dir=path.parent)
    temporary: Path | None = Path(raw)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            mode = path.lstat().st_mode
            if not stat.S_ISREG(mode):
                raise ValueError("refusing to replace a non-regular local secret store")
        except FileNotFoundError:
            pass
        os.replace(temporary, path)
        temporary = None
        os.chmod(path, 0o600)
        try:
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            pass
    finally:
        if fd >= 0:
            os.close(fd)
        if temporary is not None and temporary.exists():
            temporary.unlink()


def ensure(root: Path, *, fresh: bool = False) -> dict[str, str]:
    existing = read(root)
    if existing:
        missing = set(SECRET_PATHS.values()) - set(existing)
        if not missing:
            return existing
        raise ValueError("data/.env.local exists but is incomplete")
    manifest = yaml.safe_load((Path(root) / "harness.yaml").read_text()) or {}
    generated = generate()
    values = {}
    for dotted, key in SECRET_PATHS.items():
        old = _yaml_value(manifest, dotted)
        # Fresh provisioning must never inherit repository-era weak defaults. An
        # explicit migration may preserve a custom operator value until its live
        # consumer has been changed transactionally.
        values[key] = generated[key] if not old or (fresh and old == WEAK_DEFAULTS[key]) else old
    write(root, values)
    return values


def overlay_config(data: dict, root: Path) -> dict:
    values = read(root)
    for dotted, key in SECRET_PATHS.items():
        if key not in values:
            continue
        cursor = data
        parts = dotted.split(".")
        for part in parts[:-1]:
            child = cursor.get(part)
            if not isinstance(child, dict):
                child = {}
                cursor[part] = child
            cursor = child
        cursor[parts[-1]] = values[key]
    return data


def manifest_secret_values(root: Path) -> dict[str, str]:
    data = yaml.safe_load((Path(root) / "harness.yaml").read_text()) or {}
    if not isinstance(data, Mapping):
        raise ValueError("harness.yaml root must be a mapping")
    return {key: _yaml_value(data, dotted) for dotted, key in SECRET_PATHS.items()}


def scrub_manifest(root: Path) -> None:
    """Blank only the four secret scalars while preserving all unrelated bytes."""
    path = Path(root) / "harness.yaml"
    targets = {tuple(dotted.split(".")) for dotted in SECRET_PATHS}

    def edit(text: str) -> str:
        document = yaml.compose(text)
        if document is None:
            raise ValueError("harness.yaml is empty")
        replacements: list[tuple[int, int]] = []

        def walk(node, prefix: tuple[str, ...] = ()) -> None:
            if not isinstance(node, yaml.MappingNode):
                return
            for key_node, value_node in node.value:
                if not isinstance(key_node, yaml.ScalarNode):
                    continue
                current = prefix + (str(key_node.value),)
                if current in targets:
                    if not isinstance(value_node, yaml.ScalarNode):
                        raise ValueError("a manifest secret must be a scalar")
                    replacements.append((value_node.start_mark.index,
                                         value_node.end_mark.index))
                else:
                    walk(value_node, current)

        walk(document)
        if len(replacements) != len(targets):
            raise ValueError("harness.yaml does not contain every secret field")
        result = text
        for start, end in sorted(replacements, reverse=True):
            result = result[:start] + result[end:]
        parsed = yaml.safe_load(result) or {}
        if any(_yaml_value(parsed, dotted) for dotted in SECRET_PATHS):
            raise ValueError("harness.yaml secret scrub did not verify")
        return result

    transform_file(path, edit)
