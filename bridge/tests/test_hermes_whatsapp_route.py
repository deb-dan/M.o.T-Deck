"""Driven contracts for M.O.T's non-destructive WhatsApp disable control."""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from bridge import app as A
from bridge.routers import hermeschannels as H


client = TestClient(A.app)


def test_status_route_is_mounted_and_read_only(monkeypatch):
    calls = []
    monkeypatch.setattr(H, "_whatsapp_helper",
                        lambda *args: calls.append(args) or {
                            "ok": True, "config_enabled": False,
                            "env_enabled": False, "aligned": True,
                            "recovery_pending": False,
                        })
    response = client.get("/api/hermes/channels/whatsapp")
    assert response.status_code == 200
    assert response.json()["aligned"] is True
    assert calls == [("--status",)]


def test_disable_without_owned_hermes_changes_state_but_does_not_start_it(monkeypatch):
    scripts = []
    monkeypatch.setattr(H, "_hermes_launch_state", lambda: "stopped")
    monkeypatch.setattr(H, "_port_alive_sync", lambda port: False)
    monkeypatch.setattr(H, "_whatsapp_helper",
                        lambda *args: {"ok": True, "changed": True, "enabled": False})
    monkeypatch.setattr(H, "_script",
                        lambda *args, **kwargs: scripts.append((args, kwargs)))
    response = client.post("/api/hermes/channels/whatsapp/disable")
    assert response.status_code == 200
    assert response.json() == {
        "ok": True, "changed": True, "enabled": False,
        "restarted": False, "credentials_preserved": True,
    }
    assert scripts == []


def test_disable_restarts_only_an_exactly_owned_running_hermes(monkeypatch):
    scripts = []
    monkeypatch.setattr(H, "_hermes_launch_state", lambda: "owned-running")
    monkeypatch.setattr(H, "_port_alive_sync", lambda port: True)
    monkeypatch.setattr(H, "_whatsapp_helper",
                        lambda *args: {"ok": True, "changed": True, "enabled": False})

    def script(*args, **kwargs):
        scripts.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(H, "_script", script)
    response = client.post("/api/hermes/channels/whatsapp/disable")
    assert response.status_code == 200
    assert response.json()["restarted"] is True
    assert scripts == [
        (("stop.sh", "hermes"), {"timeout": 60}),
        (("start_component.sh", "hermes"), {"timeout": 180}),
    ]


def test_stop_failure_is_truthful_and_never_attempts_restart(monkeypatch):
    scripts = []
    helpers = []
    monkeypatch.setattr(H, "_hermes_launch_state", lambda: "owned-running")
    monkeypatch.setattr(H, "_port_alive_sync", lambda port: True)
    monkeypatch.setattr(H, "_whatsapp_helper", lambda *args: helpers.append(args))

    def script(*args, **kwargs):
        scripts.append(args)
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(H, "_script", script)
    response = client.post("/api/hermes/channels/whatsapp/disable")
    assert response.status_code == 500
    assert "was not changed" in response.json()["detail"]
    assert "no output" in response.json()["detail"]
    assert scripts == [("stop.sh", "hermes")]
    assert helpers == []


def test_state_failure_after_stop_restarts_the_prior_state(monkeypatch):
    scripts = []
    monkeypatch.setattr(H, "_hermes_launch_state", lambda: "owned-running")
    monkeypatch.setattr(H, "_port_alive_sync", lambda port: True)
    monkeypatch.setattr(H, "_whatsapp_helper",
                        lambda *args: (_ for _ in ()).throw(RuntimeError("injected write failure")))

    def script(*args, **kwargs):
        scripts.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(H, "_script", script)
    response = client.post("/api/hermes/channels/whatsapp/disable")
    assert response.status_code == 500
    assert "prior on-disk state" in response.json()["detail"]
    assert scripts == [
        (("stop.sh", "hermes"), {"timeout": 60}),
        (("start_component.sh", "hermes"), {"timeout": 180}),
    ]


def test_unowned_live_hermes_is_never_edited_or_restarted(monkeypatch):
    helper_calls = []
    monkeypatch.setattr(H, "_hermes_launch_state", lambda: "stopped")
    monkeypatch.setattr(H, "_port_alive_sync", lambda port: True)
    monkeypatch.setattr(H, "_whatsapp_helper",
                        lambda *args: helper_calls.append(args))
    response = client.post("/api/hermes/channels/whatsapp/disable")
    assert response.status_code == 409
    assert "lacks an exact M.O.T launch claim" in response.json()["detail"]
    assert helper_calls == []


def test_exact_owner_without_reporting_pid_still_quiesces_before_edit(monkeypatch):
    """The `.owner` record—not a possibly missing `.pid` report—controls the route."""
    monkeypatch.setattr(H, "_read_ownership", lambda name: (8123, "birth-1"))
    monkeypatch.setattr(H, "_ownership_path",
                        lambda name: SimpleNamespace(exists=lambda: True))
    monkeypatch.setattr(H, "_ownership_matches",
                        lambda pid, name: (pid, name) == (8123, "hermes"))
    assert H._hermes_launch_state() == "owned-running"


def test_live_legacy_pid_without_owner_is_ambiguous(monkeypatch, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "hermes.pid").write_text("8123\n")
    monkeypatch.setattr(H, "ROOT", tmp_path)
    monkeypatch.setattr(H, "_read_ownership", lambda name: None)
    monkeypatch.setattr(H, "_ownership_path", lambda name: data / "hermes.owner")
    monkeypatch.setattr(H.os, "kill", lambda pid, sig: None)
    assert H._hermes_launch_state() == "ambiguous"


def test_unverifiable_legacy_pid_fails_closed(monkeypatch, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "hermes.pid").write_text("8123\n")
    monkeypatch.setattr(H, "ROOT", tmp_path)
    monkeypatch.setattr(H, "_read_ownership", lambda name: None)
    monkeypatch.setattr(H, "_ownership_path", lambda name: data / "hermes.owner")

    def denied(pid, sig):
        raise PermissionError("injected probe denial")

    monkeypatch.setattr(H.os, "kill", denied)
    assert H._hermes_launch_state() == "ambiguous"


def test_ambiguous_launch_state_never_touches_whatsapp_files(monkeypatch):
    helpers = []
    scripts = []
    monkeypatch.setattr(H, "_hermes_launch_state", lambda: "ambiguous")
    monkeypatch.setattr(H, "_whatsapp_helper", lambda *args: helpers.append(args))
    monkeypatch.setattr(H, "_script",
                        lambda *args, **kwargs: scripts.append((args, kwargs)))
    response = client.post("/api/hermes/channels/whatsapp/disable")
    assert response.status_code == 409
    assert helpers == []
    assert scripts == []


def test_mot_exposes_no_credential_deletion_route():
    hermes_paths = {route.path for route in A.app.routes
                    if getattr(route, "path", "").startswith(
                        "/api/hermes/channels/whatsapp")}
    assert hermes_paths == {
        "/api/hermes/channels/whatsapp",
        "/api/hermes/channels/whatsapp/disable",
    }
