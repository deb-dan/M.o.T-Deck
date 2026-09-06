#!/usr/bin/env python3
"""Explicit, resumable migration from live YAML credentials to data/.env.local.

This command never prints a credential and never restarts a process implicitly.  Its
redacted plan is safe to inspect first; ``apply`` refuses before writing when an
installed Odysseus cannot authenticate with either side of the intended cutover.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

try:
    import httpx
    import yaml
except ModuleNotFoundError:
    # The operator-facing executable must work on a stock macOS shell. Re-enter with
    # this exact root's bridge interpreter rather than requiring a global dependency
    # or accidentally borrowing another MOT Deck copy's environment.
    _root = Path(__file__).resolve().parents[1]
    _python = _root / "data" / "bridge-venv" / "bin" / "python"
    if _python.is_file() and os.access(_python, os.X_OK) \
            and Path(sys.executable).resolve() != _python.resolve():
        os.execv(str(_python), [str(_python), str(Path(__file__).resolve()), *sys.argv[1:]])
    raise SystemExit(
        "ERROR: httpx is unavailable and this root has no runnable bridge Python; "
        "bootstrap data/bridge-venv before migrating secrets")


# These services read runner.api_key into their launch environment or seed an endpoint
# carrying it.  The two interactive CLI lanes read the bridge's overlay only when they
# are launched, so they have no daemon to restart here.
RUNNER_CONSUMERS = (
    "odysseus", "voicestudio", "deepseek", "opencode", "hermes",
)


def _load(root: Path) -> dict:
    value = yaml.safe_load((root / "motdeck.yaml").read_text()) or {}
    if not isinstance(value, dict):
        raise ValueError("motdeck.yaml root must be a mapping")
    return value


def _installed_odysseus(data: dict) -> bool:
    row = (data.get("components") or {}).get("odysseus") or {}
    return row.get("installed") is True


def _ody_port(data: dict) -> int:
    row = (data.get("components") or {}).get("odysseus") or {}
    port = row.get("port", 7860)
    return port if isinstance(port, int) and not isinstance(port, bool) else 7860


def restart_components(data: dict, *, runner_key_changed: bool) -> list[str]:
    """Return only managed installed services needing a post-cutover relaunch.

    ``aux`` is deliberately absent.  It is an optional model process, not a component
    managed by ``start_component.sh``; more importantly its credential is commonly
    copied by the user into Odysseus's Background Tasks endpoint.  Treating it as a
    normal component would either start a deliberately stopped model or rotate a
    credential we cannot transactionally update in Odysseus.  See ``apply_migration``.
    """
    if not runner_key_changed:
        return []
    components = data.get("components") or {}
    result: list[str] = ["runner"]
    for name in RUNNER_CONSUMERS:
        row = components.get(name) or {}
        if row.get("installed") is True:
            result.append(name)
    return result


def _login(client: httpx.Client, user: str, password: str) -> bool:
    response = client.post("/api/auth/login", json={
        "username": user, "password": password, "remember": True,
        "totp_code": None,
    })
    if response.status_code == 200:
        body = response.json()
        if body.get("requires_totp"):
            raise RuntimeError("Odysseus has 2FA enabled; rotate its password manually, then rerun")
        return body.get("ok") is True
    if response.status_code == 401:
        return False
    raise RuntimeError(f"Odysseus login preflight returned HTTP {response.status_code}")


def plan(root: Path, *, rotate: bool,
         rotate_active_managed: bool = False) -> dict:
    from bridge.core import localsecrets

    data = _load(root)
    manifest_values = localsecrets.manifest_secret_values(root)
    stored = localsecrets.read(root)
    if rotate_active_managed and not stored:
        raise ValueError("--rotate-active-managed requires an existing protected store")
    # An existing protected store is already the effective source read by the bridge
    # and launchers; the scrubbed YAML being blank is not a credential change. On an
    # initial provision, rotation always changes the runner key, while preservation
    # changes it only when no manifest key existed and a new one must be generated.
    runner_key_changed = bool(rotate_active_managed or (not stored and (
        rotate or not manifest_values["MOT_DECK_RUNNER_API_KEY"])))
    aux_existing = bool(manifest_values["MOT_DECK_AUX_API_KEY"] or
                        (stored or {}).get("MOT_DECK_AUX_API_KEY"))
    return {
        "store": "already-provisioned" if stored else "will-create",
        "yaml": "will-scrub" if any(manifest_values.values()) else "already-scrubbed",
        "rotate": bool(rotate_active_managed or (rotate and not stored)),
        "aux_key": ("preserve-active: external Background Tasks consumers are not "
                    "transactionally managed" if rotate_active_managed else
                    "already-provisioned" if stored else
                    "preserve-existing: external Background Tasks consumers are not "
                    "transactionally managed" if rotate and not stored and aux_existing
                    else "generate-on-first-provision"),
        "odysseus_auth_preflight": _installed_odysseus(data),
        "restart_required": restart_components(data, runner_key_changed=runner_key_changed),
    }


def apply_migration(root: Path, *, rotate: bool,
                    rotate_active_managed: bool = False,
                    client_factory=httpx.Client) -> dict:
    from bridge.core import localsecrets

    root = root.resolve()
    data = _load(root)
    before = localsecrets.manifest_secret_values(root)
    existing = localsecrets.read(root)
    if rotate_active_managed and not existing:
        raise ValueError("--rotate-active-managed requires an existing protected store")
    if existing and rotate_active_managed:
        desired = localsecrets.generate()
        # Rotating active managed credentials must not silently change account
        # identity or the externally consumed auxiliary key.
        desired["MOT_DECK_ODYSSEUS_ADMIN_USER"] = existing["MOT_DECK_ODYSSEUS_ADMIN_USER"]
        desired["MOT_DECK_AUX_API_KEY"] = existing["MOT_DECK_AUX_API_KEY"]
    elif existing:
        desired = existing
    elif rotate:
        desired = localsecrets.generate()
        # Username migration is a separate account-identity operation. Preserve the
        # current account while rotating its password and every local API key.
        if before["MOT_DECK_ODYSSEUS_ADMIN_USER"]:
            desired["MOT_DECK_ODYSSEUS_ADMIN_USER"] = before["MOT_DECK_ODYSSEUS_ADMIN_USER"]
        # The optional aux server is launched by the Models pane, while its key may
        # have been copied into Odysseus's user-owned Background Tasks endpoint.  M.O.T
        # has no authoritative, transactional API for that endpoint configuration.
        # Preserve a live legacy aux key as we migrate it into the protected store;
        # rotating it here would knowingly strand that endpoint (and any running aux
        # server) on the old value.  A future managed endpoint adapter can perform an
        # explicit coordinated auxiliary-key rotation with independent verification.
        if before["MOT_DECK_AUX_API_KEY"]:
            desired["MOT_DECK_AUX_API_KEY"] = before["MOT_DECK_AUX_API_KEY"]
    else:
        desired = localsecrets.generate()
        for key, value in before.items():
            if value:
                desired[key] = value

    client = None
    authenticated = "not-installed"
    effective_before = existing or before
    old_password = effective_before["MOT_DECK_ODYSSEUS_ADMIN_PASSWORD"]
    new_password = desired["MOT_DECK_ODYSSEUS_ADMIN_PASSWORD"]
    user = desired["MOT_DECK_ODYSSEUS_ADMIN_USER"]
    password_needs_change = False
    if _installed_odysseus(data):
        client = client_factory(base_url=f"http://127.0.0.1:{_ody_port(data)}",
                                timeout=10.0)
        try:
            if old_password and _login(client, user, old_password):
                authenticated = "old"
                password_needs_change = old_password != new_password
            elif _login(client, user, new_password):
                authenticated = "new"
            else:
                raise RuntimeError("Odysseus rejected both the current and staged credentials")
        except (httpx.HTTPError, OSError) as exc:
            client.close()
            raise RuntimeError("Odysseus is installed but unavailable; start it before migration") from exc

    created_store = not bool(existing)
    replaced_store = bool(existing and rotate_active_managed)
    password_changed = False
    try:
        if created_store or replaced_store:
            localsecrets.write(root, desired)
        if client is not None and password_needs_change:
            response = client.post("/api/auth/change-password", json={
                "current_password": old_password, "new_password": new_password,
            })
            if response.status_code != 200 or response.json().get("ok") is not True:
                raise RuntimeError(f"Odysseus password cutover returned HTTP {response.status_code}")
            password_changed = True
            # Verify independently before removing the only previous credential copy.
            verifier = client_factory(base_url=f"http://127.0.0.1:{_ody_port(data)}",
                                      timeout=10.0)
            try:
                if not _login(verifier, user, new_password):
                    raise RuntimeError("Odysseus rejected the new password after cutover")
            finally:
                verifier.close()
        localsecrets.scrub_manifest(root)
        if localsecrets.read(root) != desired:
            raise RuntimeError("local secret store did not verify after migration")
    except Exception:
        # Before a successful password cutover, removing only the file created by this
        # invocation restores the original YAML-owned state. After a cutover, keep the
        # verified new store: deleting it would deliberately lock the bridge out.
        if (created_store or replaced_store) and not password_changed:
            if replaced_store:
                localsecrets.write(root, existing)
            else:
                (root / "data" / ".env.local").unlink(missing_ok=True)
        raise
    finally:
        if client is not None:
            client.close()

    # ``before`` is the YAML staging source only on the first migration. Once the
    # protected store exists it is already the effective credential, even though YAML
    # is intentionally blank. Comparing that store back to blank YAML would create a
    # false rotation and an unnecessary restart loop on every idempotent rerun.
    runner_key_changed = bool(desired["MOT_DECK_RUNNER_API_KEY"] !=
                              effective_before["MOT_DECK_RUNNER_API_KEY"])
    aux_preserved = bool(effective_before["MOT_DECK_AUX_API_KEY"] and
                         desired["MOT_DECK_AUX_API_KEY"] ==
                         effective_before["MOT_DECK_AUX_API_KEY"])
    return {
        "ok": True,
        "credentials": ("rotated-managed-secrets; aux-preserved"
                        if (rotate and created_store or rotate_active_managed) and aux_preserved
                        else "rotated" if rotate and created_store else "preserved"),
        "aux_key": ("preserved: Background Tasks endpoint remains valid"
                    if rotate_active_managed and aux_preserved else
                    "already-provisioned" if existing else
                    "preserved: Background Tasks endpoint remains valid" if aux_preserved
                    else "new: no legacy auxiliary credential existed"),
        "odysseus": authenticated,
        "restart_required": restart_components(data, runner_key_changed=runner_key_changed),
    }


def _print_redacted(result: dict) -> None:
    for key, value in result.items():
        if isinstance(value, list):
            print(f"{key}: {','.join(value)}")
        else:
            print(f"{key}: {str(value).lower() if isinstance(value, bool) else value}")
    print("values: redacted")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("plan", "apply"))
    parser.add_argument("root", type=Path)
    parser.add_argument("--rotate", action="store_true",
                        help="generate new API keys/password on the initial migration")
    parser.add_argument("--rotate-active-managed", action="store_true",
                        help="rotate the active runner key and Odysseus password; preserve aux/user")
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0, str(root))
    try:
        if args.rotate and args.rotate_active_managed:
            parser.error("choose either --rotate or --rotate-active-managed")
        result = plan(root, rotate=args.rotate,
                      rotate_active_managed=args.rotate_active_managed) \
            if args.command == "plan" else apply_migration(
                root, rotate=args.rotate,
                rotate_active_managed=args.rotate_active_managed)
        _print_redacted(result)
        if args.command == "apply":
            names = ",".join(result["restart_required"])
            if names:
                print(f"NEXT: from the canonical repo run ./scripts/ship.sh --restart={names}")
            else:
                print("NEXT: no managed running-secret consumer is implied by this migration")
        return 0
    except Exception as exc:  # never interpolate a credential
        print(f"ERROR: local-secret migration stopped safely: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
