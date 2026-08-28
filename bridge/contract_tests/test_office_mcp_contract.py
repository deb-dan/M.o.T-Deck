"""LOffice MCP toolset contract — the pin-bump gate for the AGENT lane.

⚠️ DELIBERATELY REWRITTEN AT loffice-2026-08-28b, AND THE REASON IS THE WHOLE POINT OF
THE SLICE. This file used to guard four MCP tools that WROTE Debi's spreadsheets, by
pinning the two upstream-internal facts that put them behind an approval card. Those four
tools are GONE (docs/FABLE-AGENT-CHANGESET-SPEC.md §1, ruled after the 2026-08-27 consent
incident): the catalog is now four READ tools, every one annotated `readOnlyHint: true`,
and the consent for a change lives on a card in the LOffice panel with an Apply button
that only a person can press.

So what this file guards has INVERTED, and the new negative is the stronger one:

  BEFORE: "readOnlyHint must be absent from the four write tools, or their card
           disappears silently."
  NOW:    "no tool on this server may write at all, and nothing may reach a workbook
           except the human-only apply route."

The upstream facts are still pinned — `trust`, `readOnlyHint is True`,
`_trust_gate_check`, gate-before-transport — because they are the fence for the day a
tool here ever DOES need to write again, and because /api/office/mcp still reports that
mechanism to Debi and that sentence must not become a lie. But they are no longer what
stands between a model and her files. THAT is now:

  1. bridge/office_mcp.py serves exactly four tools and every one of them is read-only.
  2. Apply is `POST /api/office/changeset/{id}/apply` — a bridge route, reachable from
     the panel, with no MCP method that can call it.
  3. Staging never touches a workbook (asserted by mtime and by bytes in
     bridge/tests/test_office_mcp.py group 4c-1), which is what makes the annotation on
     office_stage_changes honest rather than convenient.

⚠️ IF ONE OF THESE FAILS, DO NOT RELAX THE ASSERTION. Re-read the new upstream code (or
the new tool), decide what the consent story IS, then say so in bridge/office_mcp.py's
docstring and in bridge/app.py's /api/office/mcp `approval`/`consent` block — the panel
tells Debi which mechanism is protecting her, and it must keep being true.
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
    # ⚠️ WIDENED AT THE mcp 1.28.1 → 2.0.0 JUMP (2026-08-28, Hermes v0.20.6).
    # 2.0.0 inlined the `JSON` constant: `content_type.startswith(JSON)` became
    # `content_type.startswith("application/json")` (streamable_http.py:382). Same
    # branch, same first-class status — a literal rename, not a behaviour change.
    # Both spellings are accepted so this passes on mcp 1.x AND 2.x; what it must
    # never tolerate is the branch disappearing.
    assert ('content_type.startswith(JSON)' in src
            or 'content_type.startswith("application/json")' in src), (
        "the MCP client no longer accepts an application/json reply to a request — "
        "bridge/office_mcp.py never opens an SSE stream, so this is load-bearing")
    assert "status_code == 405" in src, (
        "the MCP client no longer tolerates a 405 on the GET stream — "
        "bridge/office_mcp.py 405s it because it never initiates anything")


def test_hermes_stays_on_the_handshake_era_so_our_hand_written_server_is_reachable():
    """THE mcp 2.x QUESTION, ANSWERED AND PINNED (2026-08-28, v0.20.6 bump).

    mcp 2.0.0 implements MCP revision **2026-07-28**, which replaces the
    `initialize` handshake with a stateless per-request envelope and discovers the
    peer with a `server/discover` probe. bridge/office_mcp.py speaks the HANDSHAKE
    era and nothing else: five methods, `initialize` among them.

    That is safe because the SDK keeps BOTH eras and Hermes deliberately stays on
    the old one:
      · `mcp_types.version` splits HANDSHAKE_PROTOCOL_VERSIONS (up to 2025-11-25)
        from MODERN_PROTOCOL_VERSIONS (2026-07-28);
      · Hermes's HTTP transport connects with `ClientSession.initialize()` and
        seeds the `mcp-protocol-version` header from LATEST_HANDSHAKE_VERSION —
        with a comment saying that advertising 2026-07-28 would route the request
        onto the envelope ladder, which then rejects a legacy body;
      · Hermes never calls `mcp.client._probe.negotiate_auto`, so `server/discover`
        is never sent to us at all. (Even if it were, our -32601 "method not found"
        is on that module's fallback DENYLIST — anything that is not positive
        modern evidence falls back to `initialize`.)

    IF THIS TEST FAILS, our server is being spoken to in an era it does not
    implement. The fix is NOT to relax it: either add the per-request envelope to
    bridge/office_mcp.py, or answer `server/discover` advertising handshake
    versions only (which the SDK treats as an explicit legacy advertisement).

    ⚠️ THE UPSTREAM HALF IS DORMANT AT THE PIN WE SHIP (v2026.8.13, mcp 1.28.1 —
    one era, no split) AND ARMS BY ITSELF the moment the vendored Hermes moves to
    mcp 2.x. The OUR-SIDE half below runs at every pin, because
    `office_mcp.negotiate()` must never claim the modern revision regardless of what
    any client asks for. The v0.20.6 bump this was written against was rolled back —
    see docs/handoff/HERMES-v0.20.6-BLOCKED-2026-08-28.md — but the answer it
    records ("our hand-written server needs no change for mcp 2.0.0") is measured
    and still stands.
    """
    src = _read("tools/mcp_tool.py")
    if "LATEST_HANDSHAKE_VERSION" not in src:
        # mcp 1.x era: there is no handshake/modern split to get wrong upstream.
        # Fall through to our own invariants only.
        _assert_our_negotiate_never_claims_the_modern_revision()
        return
    assert 'headers["mcp-protocol-version"] = LATEST_HANDSHAKE_VERSION' in src, (
        "the MCP-Protocol-Version header is no longer seeded from the HANDSHAKE "
        "version — see bridge/office_mcp.py KNOWN_PROTOCOLS/negotiate()")
    assert "session.initialize()" in src, (
        "Hermes's MCP transport no longer connects via ClientSession.initialize() "
        "— bridge/office_mcp.py implements `initialize` and no envelope")
    assert "negotiate_auto" not in src, (
        "Hermes now uses the SDK's mode='auto' era negotiation, so our server WILL "
        "be probed with `server/discover`. Our -32601 should still fall back to the "
        "handshake (mcp/client/_probe.py is a denylist), but that is now a live "
        "path and must be walked, not assumed — see office_mcp.handle()")
    _assert_our_negotiate_never_claims_the_modern_revision()


def _assert_our_negotiate_never_claims_the_modern_revision() -> None:
    """Our half of the era contract — true at EVERY pin, so it is checked at every
    pin, whichever SDK generation the vendored Hermes happens to carry."""
    import sys
    sys.path.insert(0, str(ROOT))
    from bridge import office_mcp                                # noqa: E402
    assert "2025-11-25" in office_mcp.KNOWN_PROTOCOLS, (
        "office_mcp.KNOWN_PROTOCOLS no longer contains the newest handshake "
        "revision — we would answer initialize with our own default instead of "
        "echoing the client's offer")
    assert office_mcp.negotiate("2026-07-28") == office_mcp.DEFAULT_PROTOCOL, (
        "office_mcp.negotiate() now ECHOES the modern revision back. It must not: "
        "echoing 2026-07-28 claims a per-request envelope this server does not "
        "implement")


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
def test_the_bridge_writes_the_trust_key_and_every_tool_claims_read_only():
    """Our side of the same contract — and the assertion that replaced the old one.

    The trust key is still written (it costs nothing and it arms the gate for the day a
    tool here needs to write). What actually protects the files now is the line below it:
    EVERY tool is read-only, so write_tool_names() is empty.
    """
    start = (ROOT / "scripts" / "start_component.sh").read_text(encoding="utf-8")
    assert '"trust": "untrusted"' in start, (
        "the config-gen step stopped writing trust: untrusted — harmless while nothing "
        "on this server writes, but it is the armed fence for the day one does")
    src = (BRIDGE / "office_mcp.py").read_text(encoding="utf-8")
    assert '"trust": "untrusted"' in src, "hermes_entry() stopped writing the trust key"
    import sys
    sys.path.insert(0, str(ROOT))
    from bridge import office_mcp                                # noqa: E402
    assert office_mcp.read_tool_names() == [
        "office_list", "office_read", "office_sheet_stats",
        "office_stage_changes"], (
        "the catalog changed. It must be exactly these four, all read-only: three reads "
        "and one that records a PROPOSAL the bridge holds")
    assert office_mcp.write_tool_names() == [], (
        "A WRITE-CAPABLE TOOL APPEARED ON THE LOFFICE MCP SERVER. That is the one change "
        "docs/FABLE-AGENT-CHANGESET-SPEC.md forbids: a document edit is one intention "
        "and its consent belongs on the panel's changeset card, not on a per-call "
        "approval that cannot show what is being written. Apply is "
        "POST /api/office/changeset/{id}/apply and it must stay human-only")
    payload = office_mcp.tool_list_payload()
    for tool in payload:
        assert tool["annotations"].get("readOnlyHint") is True, (
            f"{tool['name']} must claim readOnlyHint exactly True (Hermes tests "
            "`hint is True`) — and must therefore actually be read-only")
    # Containment by construction: no tool may take a path-shaped argument at all.
    for tool in payload:
        props = set((tool["inputSchema"].get("properties") or {}).keys())
        assert not props & {"path", "filepath", "file", "dir", "directory", "folder"}, (
            f"{tool['name']} grew a path-shaped argument — the whole containment "
            "argument for this toolset is that a tool which takes no path cannot "
            "escape one")


def test_apply_is_reachable_from_the_panel_and_from_no_tool():
    """THE NEGATIVE THIS SLICE LIVES BY, and it is a two-sided one.

    A workbook is written in exactly one place (office_ops.apply_changeset /
    restore_checkpoint), and the only door to it is an HTTP route the panel POSTs to. If
    the MCP dispatcher ever gains a branch that reaches an apply, the whole consent model
    is gone and nothing else in the suite would notice.
    """
    mcp = (BRIDGE / "office_mcp.py").read_text(encoding="utf-8")
    dispatch = mcp[mcp.index("def call_tool("):mcp.index("def _ok(")]
    for forbidden in ("apply_changeset", "restore_checkpoint", "undo_changeset",
                      "_apply(", "save_doc", "write_snapshot"):
        assert forbidden not in dispatch, (
            f"the MCP tool dispatcher can now reach {forbidden} — an MCP tool call must "
            "never be able to write a workbook. Apply is a human gesture: "
            "POST /api/office/changeset/{id}/apply")
    app = (BRIDGE / "app.py").read_text(encoding="utf-8")
    assert '@app.post("/api/office/changeset/{cid}/apply")' in app, (
        "the apply route moved or vanished — the panel's Apply button has nowhere to go")
    ops = (BRIDGE / "office_ops.py").read_text(encoding="utf-8")
    # office.save_doc is the ONE writer this module may call, and only from the apply
    # path. Counting call sites is crude and that is why it works: a second one has to
    # be argued for here before it can ship.
    assert ops.count("office.save_doc(") == 1, (
        "office_ops grew a second workbook writer. There is one apply path, and every "
        "guarantee this lane makes (checkpoint first, atomic single save, receipt by "
        "re-read) is a property of that one path")


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
