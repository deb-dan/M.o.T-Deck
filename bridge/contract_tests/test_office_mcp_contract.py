"""LOffice MCP toolset contract — the pin-bump gate for the AGENT lane's approval.

Slice S1 of docs/FABLE-LOFFICE-HERMES-TOOLS-SPEC.md hands Hermes four tools that WRITE
Debi's spreadsheets. What stands between those four and an unattended write is not code
we own — it is two upstream-internal facts inside `vendor/hermes`:

  1. `mcp_servers.<name>.trust: untrusted` ARMS the gate. Absent (or `full`), Hermes runs
     every MCP tool with no approval at all.
  2. A tool is WRITE-CAPABLE, and therefore gated, unless its discovery-time
     `annotations.readOnlyHint` is **exactly `True`**.

Both are read out of the pin rather than remembered, and BOTH ARE SILENT WHEN THEY MOVE:
a Hermes release that renames the `trust` key, or that starts treating a truthy
`readOnlyHint` as read-only, or that stops routing the gate through the approval surface,
would leave `office_write_cells` firing with no card and NOTHING ELSE WOULD FAIL. There
is no runtime symptom to notice — the tool just works, which is the problem.

So this is a purely STATIC check of the vendored source, in the shape of
test_hermes_toolsets_contract.py: no network, no build, no running Hermes. It also pins
the ONE fact our own transport leans on — that the MCP client this Hermes ships accepts
an `application/json` reply to a request and a bare 202 to a notification, which is why
bridge/office_mcp.py needs no MCP SDK.

⚠️ IF ONE OF THESE FAILS, DO NOT RELAX THE ASSERTION. Re-read the new upstream code and
decide what the approval story IS at the new pin, then say so in bridge/office_mcp.py's
docstring and in bridge/app.py's /api/office/mcp `approval.mechanism` string — the panel
tells Debi which mechanism is protecting her, and that sentence must not become a lie.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
HERMES = ROOT / "vendor" / "hermes"
BRIDGE = ROOT / "bridge"


def _read(rel: str) -> str:
    p = HERMES / rel
    assert p.exists(), f"vendored file missing: {rel}"
    return p.read_text(encoding="utf-8", errors="replace")


# ── 1. the transport shape our server is written against ────────────────────
def test_mcp_servers_is_still_the_config_key_and_a_url_still_means_http():
    src = _read("tools/mcp_tool.py")
    assert 'config.get("mcp_servers")' in src, (
        "the mcp_servers config key moved — scripts/start_component.sh's config-gen "
        "step and bridge/app.py's _hermes_write_mcp both write it")
    assert 'return "url" in self._config' in src, (
        "_is_http no longer decides transport by the presence of `url` — "
        "bridge/office_mcp.hermes_entry() writes a url-only entry precisely because "
        "that is what selects Streamable HTTP")
    # `transport: sse` is the OTHER branch. We must NOT be on it: our server answers a
    # POST with one JSON body and 405s the GET, which is Streamable HTTP, not SSE.
    assert 'config.get("transport") == "sse"' in src, (
        "the SSE opt-in moved; check that a url-only entry still means Streamable HTTP")


def test_the_client_hermes_ships_accepts_a_json_reply_and_a_bare_202():
    """The two rules bridge/office_mcp.py implements by hand instead of via an SDK.

    Read out of the MCP client in Hermes's OWN venv when it is provisioned; skipped
    (not failed) when it is not, because a contract test may not require an optional
    component to be installed.
    """
    import glob
    hits = glob.glob(str(ROOT / "data" / "hermes-venv" / "lib" / "python3.*" /
                         "site-packages" / "mcp" / "client" / "streamable_http.py"))
    if not hits:
        import pytest
        pytest.skip("hermes venv not provisioned — nothing to read the client out of")
    src = Path(hits[0]).read_text(encoding="utf-8", errors="replace")
    assert "if response.status_code == 202:" in src, (
        "the MCP client no longer treats 202 as the answer to a notification — "
        "bridge/office_mcp.py answers every notification 202-with-no-body")
    assert "content_type.startswith(JSON)" in src, (
        "the MCP client no longer accepts an application/json reply to a request — "
        "bridge/office_mcp.py never opens an SSE stream, so this is load-bearing")
    assert "status_code == 405" in src, (
        "the MCP client no longer tolerates a 405 on the GET stream — "
        "bridge/office_mcp.py 405s it because it never initiates anything")


# ── 2. THE APPROVAL STORY. This is the group that matters. ───────────────────
def test_per_server_trust_is_still_the_switch_that_arms_the_gate():
    src = _read("tools/mcp_tool.py")
    assert '_TRUST_UNTRUSTED = "untrusted"' in src and '_TRUST_FULL = "full"' in src, (
        "the trust tier VALUES moved — scripts/start_component.sh writes "
        "`trust: untrusted` verbatim into mcp_servers.loffice")
    assert '(config or {}).get("trust")' in src, (
        "the per-server trust key is no longer read from the mcp_servers entry — the "
        "LOffice write tools may now be running with NO approval card")
    # Default-full is why the key must be written EXPLICITLY. If upstream ever flips the
    # default to untrusted this assertion trips and the key becomes redundant, not wrong.
    assert "if value is None:\n        return _TRUST_FULL" in src, (
        "the default trust level changed; re-read _normalize_server_trust and confirm "
        "what an entry WITHOUT a trust key now means")


def test_read_only_is_still_exactly_true_and_missing_annotations_fail_closed():
    src = _read("tools/mcp_tool.py")
    assert "def _annotation_read_only_hint(" in src
    assert "return hint is True" in src, (
        "readOnlyHint is no longer tested with `is True`. bridge/office_mcp.py's whole "
        "per-tool approval split rests on this: a truthy-but-not-True hint must NOT "
        "disarm the gate, and a write tool with no hint at all must stay gated")
    assert 'annotations.get("readOnlyHint")' in src
    assert "def _trust_gate_check(" in src, (
        "the trust gate is gone — find what replaced it before shipping write tools")
    assert "request_elicitation_consent" in src, (
        "the trust gate no longer routes through the approval surface, so the LOffice "
        "write tools may no longer produce a card Debi can see")


def test_the_gate_runs_before_any_transport_work():
    """A denied call must never reach this bridge — including via a lazy first-use
    spawn. Pinned because "approval happened" and "approval happened FIRST" are
    different guarantees, and only the second one means an unapproved write cannot
    touch a file."""
    src = _read("tools/mcp_tool.py")
    assert "gate_error = _trust_gate_check(server_name, tool_name)" in src
    assert "if gate_error is not None:\n            return gate_error" in src


def test_there_is_still_no_per_tool_approval_field_to_use_instead():
    """The honest negative. If a future pin ADDS a per-tool approval knob to an
    mcp_servers entry, this trips — and the right response is to move to it, because a
    config field the operator controls beats a hint the server declares about itself.

    `tools.include` / `tools.exclude` exist but only gate REGISTRATION, not approval.
    """
    src = _read("tools/mcp_tool.py")
    assert "# Selective tool loading: honour include/exclude lists from config." in src
    for knob in ('config.get("approval")', 'config.get("approvals")',
                 'config.get("require_approval")', 'config.get("tool_approval")'):
        assert knob not in src, (
            f"vendor/hermes now reads {knob} from an mcp_servers entry — that is a "
            "per-tool/per-server approval field the operator controls, which is "
            "STRICTLY better than a server-declared readOnlyHint. Move the LOffice "
            "write tools onto it and update bridge/office_mcp.py's docstring plus "
            "/api/office/mcp's approval.mechanism string.")


# ── 3. our own side of the same contract ────────────────────────────────────
def test_the_bridge_writes_the_trust_key_and_only_the_read_tools_claim_read_only():
    """Both halves of the two-factor gate, asserted on OUR side, in the same test as
    the upstream half — so a reader sees the whole mechanism in one place."""
    start = (ROOT / "scripts" / "start_component.sh").read_text(encoding="utf-8")
    assert '"trust": "untrusted"' in start, (
        "the config-gen step stopped writing trust: untrusted — every LOffice write "
        "tool would run with no approval card")
    src = (BRIDGE / "office_mcp.py").read_text(encoding="utf-8")
    assert '"trust": "untrusted"' in src, "hermes_entry() stopped writing the trust key"
    # The split itself, read out of the module rather than restated here.
    import sys
    sys.path.insert(0, str(ROOT))
    from bridge import office_mcp                                # noqa: E402
    assert office_mcp.read_tool_names() == [
        "office_list", "office_read", "office_sheet_stats"], (
        "a tool changed sides in the read-only split. `readOnlyHint: true` DISARMS "
        "Hermes's approval card — putting it on a tool that writes removes the card "
        "silently")
    assert office_mcp.write_tool_names() == [
        "office_write_cells", "office_sort", "office_insert_delete", "office_create"], (
        "a write tool left the gated set — see above, and note that Hermes cannot "
        "gate it for us if we do not declare it")
    payload = office_mcp.tool_list_payload()
    for tool in payload:
        hint = tool["annotations"].get("readOnlyHint")
        if tool["name"] in office_mcp.write_tool_names():
            assert hint is None, f"{tool['name']} writes and must claim nothing"
        else:
            assert hint is True, f"{tool['name']} must claim readOnlyHint exactly True"
    # Containment by construction: no tool may take a path-shaped argument at all.
    for tool in payload:
        props = set((tool["inputSchema"].get("properties") or {}).keys())
        assert not props & {"path", "filepath", "file", "dir", "directory", "folder"}, (
            f"{tool['name']} grew a path-shaped argument — the whole containment "
            "argument for this toolset is that a tool which takes no path cannot "
            "escape one")


def test_the_toolset_needs_no_manifest_entry_and_no_port():
    """The 'not a component' discipline, same as the Office lane itself."""
    c = yaml.safe_load((ROOT / "harness.yaml").read_text())
    assert "loffice" not in c["components"] and "office" not in c["components"], (
        "the office toolset must never become a manifest component — it is mounted on "
        "the existing bridge app")
    import sys
    sys.path.insert(0, str(ROOT))
    from bridge import office_mcp                                # noqa: E402
    assert office_mcp.hermes_entry(c["bridge"]["port"])["url"] == (
        f"http://127.0.0.1:{c['bridge']['port']}/mcp/office"), (
        "the MCP url must be the EXISTING bridge port — no new listener")
