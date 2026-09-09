"""Unit tests for the Phase-3 voice-MCP registration helpers (bridge/app.py).

Two pure-ish seams, both exercised without a live Odysseus or a real ~/.hermes:

  voice_mcp_spec(name, port) → the wire payloads for BOTH hosts (Odysseus's
      form-encoded POST /api/mcp/servers, Hermes's url-only mcp_servers entry).
  _hermes_write_mcp / _hermes_get_mcp → the yaml round-trip over a TEMP
      HERMES_HOME: add, idempotent re-add, no-op removal, real removal, and the
      critical property that writing ONE server never disturbs the others (the
      Browse toggle's browsermcp entry, or any server the user added by hand).

Run: python3 bridge/tests/test_voice_mcp.py  (from repo root).
"""
import os
import sys
import tempfile
from pathlib import Path

# Sandbox hygiene: importing bridge.app builds an httpx client at import time.
for _k in [k for k in os.environ if k.lower().endswith("_proxy")]:
    os.environ.pop(_k, None)

_TMP = tempfile.mkdtemp(prefix="motdeck-hermes-home-")
os.environ["HERMES_HOME"] = _TMP          # read at call time by _hermes_config_path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import yaml  # noqa: E402
from bridge.app import (  # noqa: E402
    VOICE_MCP, voice_mcp_spec, _hermes_write_mcp, _hermes_get_mcp, _hermes_has_mcp,
    _hermes_set_mcp, _hermes_config_path,
)

FAILS = []
CFG = Path(_TMP) / "config.yaml"


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name)


def cfg_dict():
    if not CFG.exists():
        return {}
    return yaml.safe_load(CFG.read_text()) or {}


# ── voice_mcp_spec: the wire shapes ──────────────────────────────────────────
vs = voice_mcp_spec("voicestudio", 3900)
vb = voice_mcp_spec("voicebox", 17493)

check("both voice components are known", set(VOICE_MCP) == {"voicestudio", "voicebox"})
check("voicestudio url is loopback + /mcp", vs["url"] == "http://127.0.0.1:3900/mcp")
check("voicebox url is loopback + /mcp", vb["url"] == "http://127.0.0.1:17493/mcp")
check("never binds a non-loopback host",
      all(s["url"].startswith("http://127.0.0.1:") for s in (vs, vb)))

check("odysseus form is the http transport with a url",
      vs["odysseus_form"] == {"name": "voicestudio", "transport": "http",
                              "url": "http://127.0.0.1:3900/mcp",
                              "args": "[]", "env": "{}"})
check("odysseus form carries NO command (http transport)",
      "command" not in vs["odysseus_form"] and "command" not in vb["odysseus_form"])
check("odysseus form args/env are JSON STRINGS (form-encoded endpoint)",
      isinstance(vs["odysseus_form"]["args"], str)
      and isinstance(vs["odysseus_form"]["env"], str))
check("hermes entry is url-only (= streamable http)",
      vs["hermes_entry"] == {"url": "http://127.0.0.1:3900/mcp"}
      and vb["hermes_entry"] == {"url": "http://127.0.0.1:17493/mcp"})
check("registration name matches the component name",
      vs["name"] == "voicestudio" and vs["odysseus_form"]["name"] == "voicestudio")
check("spec is pure — same input, equal output",
      voice_mcp_spec("voicestudio", 3900) == vs)
check("port is honoured (a motdeck.yaml port change moves the url)",
      voice_mcp_spec("voicebox", 4242)["url"] == "http://127.0.0.1:4242/mcp")
check("tools list is non-empty for both", bool(vs["tools"]) and bool(vb["tools"]))

# rejections
check("unknown component → None", voice_mcp_spec("nope", 3900) is None)
check("missing port → None", voice_mcp_spec("voicebox", None) is None)
check("empty-string port → None", voice_mcp_spec("voicebox", "") is None)
check("non-numeric port → None", voice_mcp_spec("voicebox", "abc") is None)
check("zero/negative port → None",
      voice_mcp_spec("voicebox", 0) is None and voice_mcp_spec("voicebox", -1) is None)
check("out-of-range port → None", voice_mcp_spec("voicebox", 70000) is None)
check("numeric-string port accepted (yaml can hand us a str)",
      voice_mcp_spec("voicebox", "17493")["url"] == "http://127.0.0.1:17493/mcp")

# ── _hermes_write_mcp: the yaml round-trip ───────────────────────────────────
check("absent config + removal → False, and no file is created",
      _hermes_write_mcp("voicestudio", None) is False and not CFG.exists())

check("add creates the config and returns True",
      _hermes_write_mcp("voicestudio", vs["hermes_entry"]) is True)
check("entry landed under mcp_servers with exactly our url",
      cfg_dict().get("mcp_servers", {}).get("voicestudio") == {"url": vs["url"]})
check("_hermes_get_mcp reads it back", _hermes_get_mcp("voicestudio") == {"url": vs["url"]})
check("_hermes_has_mcp(name) is True", _hermes_has_mcp("voicestudio") is True)
check("_hermes_has_mcp defaults to browsermcp (browse toggle unchanged)",
      _hermes_has_mcp() is False)

# idempotence: re-adding the identical entry must not rewrite the file
_mtime = CFG.stat().st_mtime_ns
_before = CFG.read_text()
check("re-add of an identical entry returns True",
      _hermes_write_mcp("voicestudio", vs["hermes_entry"]) is True)
check("re-add of an identical entry does NOT rewrite the file",
      CFG.stat().st_mtime_ns == _mtime and CFG.read_text() == _before)

# unrelated keys + other servers survive a write
data = cfg_dict()
data["model"] = {"default": "some-model", "provider": "custom"}
data["mcp_servers"]["browsermcp"] = {"command": "npx", "args": ["@browsermcp/mcp"]}
CFG.write_text(yaml.safe_dump(data, sort_keys=False))
check("adding voicebox leaves voicestudio + browsermcp + model:* intact",
      _hermes_write_mcp("voicebox", vb["hermes_entry"]) is True
      and set(cfg_dict()["mcp_servers"]) == {"voicestudio", "browsermcp", "voicebox"}
      and cfg_dict()["model"]["default"] == "some-model")

# a stale url (port changed in motdeck.yaml) must be overwritten, not duplicated
check("changed url overwrites in place",
      _hermes_write_mcp("voicebox", {"url": "http://127.0.0.1:4242/mcp"}) is True
      and cfg_dict()["mcp_servers"]["voicebox"] == {"url": "http://127.0.0.1:4242/mcp"}
      and len(cfg_dict()["mcp_servers"]) == 3)

# removal
check("remove returns False and drops only that key",
      _hermes_write_mcp("voicebox", None) is False
      and set(cfg_dict()["mcp_servers"]) == {"voicestudio", "browsermcp"})
_before = CFG.read_text()
check("removing an absent server is a no-op (file untouched)",
      _hermes_write_mcp("voicebox", None) is False and CFG.read_text() == _before)

# the browse toggle still works through the shared writer
check("_hermes_set_mcp(False) removes browsermcp only",
      _hermes_set_mcp(False) is False
      and set(cfg_dict()["mcp_servers"]) == {"voicestudio"})
check("_hermes_set_mcp(True) restores the stdio browsermcp entry",
      _hermes_set_mcp(True) is True
      and cfg_dict()["mcp_servers"]["browsermcp"] == {"command": "npx",
                                                      "args": ["@browsermcp/mcp"]})

# a malformed config must not crash the reader
CFG.write_text("mcp_servers: not-a-mapping\n")
check("non-mapping mcp_servers → get returns None, has returns False",
      _hermes_get_mcp("voicestudio") is None and _hermes_has_mcp("voicestudio") is False)
CFG.write_text(": : not yaml : :\n")
check("unparseable config → get returns None instead of raising",
      _hermes_get_mcp("voicestudio") is None)

check("config path honours HERMES_HOME",
      _hermes_config_path() == str(CFG))

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1)
print("all voice-mcp tests passed")
