"""U145: the native Odysseus tab can use protected credentials without revealing them."""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from starlette.requests import Request

from bridge.routers import ody


ROOT = Path(__file__).resolve().parents[2]


def request(*, cookie: str = "", fetch_site: str = "none") -> Request:
    headers = [(b"sec-fetch-site", fetch_site.encode())]
    if cookie:
        headers.append((b"cookie", f"odysseus_session={cookie}".encode()))
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/odysseus",
        "raw_path": b"/odysseus",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8700),
    })


def response(status: int, body: dict, *, cookie: str = "") -> httpx.Response:
    headers = {}
    if cookie:
        headers["set-cookie"] = (
            f"odysseus_session={cookie}; HttpOnly; Max-Age=604800; Path=/; SameSite=lax")
    return httpx.Response(status, json=body, headers=headers,
                          request=httpx.Request("POST", "http://127.0.0.1:7860/api/auth/login"))


class Client:
    def __init__(self, *, status=None, login=None):
        self.status = status
        self.login = login
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, path, **kwargs):
        self.calls.append(("GET", path, kwargs))
        return self.status

    async def post(self, path, **kwargs):
        self.calls.append(("POST", path, kwargs))
        return self.login


def configure(monkeypatch, client: Client, *, user="admin", password="protected-password"):
    monkeypatch.setattr(ody, "cfg", lambda: {"components": {"odysseus": {
        "admin_user": user, "admin_password": password}}})
    monkeypatch.setattr(ody.httpx, "AsyncClient", lambda **_kwargs: client)


def test_tab_enters_through_bridge_not_a_direct_password_form():
    swift = (ROOT / "app" / "main.swift").read_text()
    row = next(line for line in swift.splitlines()
               if 'MOTDeckTab(id: "odysseus"' in line)
    assert "127.0.0.1:8700/odysseus" in row
    assert "7860" not in row


def test_valid_existing_browser_session_is_reused_without_new_login(monkeypatch):
    client = Client(status=response(200, {"authenticated": True}),
                    login=response(500, {}))
    configure(monkeypatch, client)
    result = asyncio.run(ody.ody_managed_workspace(request(cookie="existing")))
    assert result.status_code == 303
    assert result.headers["location"] == "http://127.0.0.1:7860/"
    assert "set-cookie" not in result.headers
    assert [call[0] for call in client.calls] == ["GET"]
    assert client.calls[0][2]["cookies"] == {"odysseus_session": "existing"}


def test_protected_login_transfers_only_http_only_session_cookie(monkeypatch):
    client = Client(login=response(200, {"ok": True}, cookie="new-session"))
    configure(monkeypatch, client)
    result = asyncio.run(ody.ody_managed_workspace(request()))
    assert result.status_code == 303
    assert result.headers["location"] == "http://127.0.0.1:7860/"
    cookie = result.headers["set-cookie"]
    assert "odysseus_session=new-session" in cookie
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert client.calls == [("POST", "/api/auth/login", {"json": {
        "username": "admin", "password": "protected-password", "remember": True,
        "totp_code": None}})]
    assert b"protected-password" not in result.body


def test_cross_site_navigation_is_rejected_before_credentials_or_network(monkeypatch):
    monkeypatch.setattr(ody, "cfg", lambda: (_ for _ in ()).throw(
        AssertionError("credentials must not be read")))
    monkeypatch.setattr(ody.httpx, "AsyncClient", lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("network must not be reached")))
    result = asyncio.run(ody.ody_managed_workspace(request(fetch_site="cross-site")))
    assert result.status_code == 403
    assert b"cross-site" in result.body


def test_missing_or_rejected_credentials_fail_closed_without_reflection(monkeypatch):
    configure(monkeypatch, Client(), user="", password="")
    missing = asyncio.run(ody.ody_managed_workspace(request()))
    assert missing.status_code == 503

    client = Client(login=response(401, {"detail": "protected-password"}))
    configure(monkeypatch, client)
    rejected = asyncio.run(ody.ody_managed_workspace(request()))
    assert rejected.status_code == 502
    assert b"protected-password" not in rejected.body
    assert b"rejected" in rejected.body


def test_2fa_and_missing_cookie_are_named_refusals_not_false_success(monkeypatch):
    client = Client(login=response(200, {"ok": False, "requires_totp": True}))
    configure(monkeypatch, client)
    two_factor = asyncio.run(ody.ody_managed_workspace(request()))
    assert two_factor.status_code == 409
    assert b"2FA" in two_factor.body

    client = Client(login=response(200, {"ok": True}))
    configure(monkeypatch, client)
    no_cookie = asyncio.run(ody.ody_managed_workspace(request()))
    assert no_cookie.status_code == 502
    assert b"no session cookie" in no_cookie.body
