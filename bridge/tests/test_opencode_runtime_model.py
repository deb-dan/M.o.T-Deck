"""U13/U20: OpenCode model truth comes from the exact running child, not disk."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

from bridge.routers import components


class _ConfigHandler(BaseHTTPRequestHandler):
    payload = {"model": "llama.cpp/requested-model"}

    def do_GET(self):  # noqa: N802 - stdlib handler API
        if self.path != "/config":
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(type(self).payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        pass


def _server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ConfigHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_runtime_default_is_bound_to_the_same_owned_process(monkeypatch):
    server, thread = _server()
    owner = (4242, "kernel-birth")
    monkeypatch.setattr(components, "_read_ownership", lambda name: owner)
    monkeypatch.setattr(
        components, "_ownership_matches",
        lambda pid, name: pid == 4242 and name == "opencode",
    )
    try:
        assert components._opencode_runtime_model(server.server_port) == "requested-model"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_foreign_provider_and_process_replacement_make_no_claim(monkeypatch):
    server, thread = _server()
    owner = (4242, "kernel-birth")
    monkeypatch.setattr(components, "_ownership_matches", lambda _pid, _name: True)
    try:
        _ConfigHandler.payload = {"model": "anthropic/claude"}
        monkeypatch.setattr(components, "_read_ownership", lambda _name: owner)
        assert components._opencode_runtime_model(server.server_port) == ""

        _ConfigHandler.payload = {"model": "llama.cpp/requested-model"}
        seen = iter((owner, (4242, "replacement-birth")))
        monkeypatch.setattr(components, "_read_ownership", lambda _name: next(seen))
        assert components._opencode_runtime_model(server.server_port) == ""
    finally:
        _ConfigHandler.payload = {"model": "llama.cpp/requested-model"}
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
