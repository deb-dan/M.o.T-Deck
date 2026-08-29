"""UPSTREAM's side of the Hermes NAMED CUSTOM PROVIDER seam (isolation mode).

scripts/seed_hermes_provider.py writes ONE entry into `custom_providers:` in
~/.hermes/config.yaml and start_component.sh points `model.provider` at its slug.
Every mechanic that makes that work lives in vendored Hermes source and upstream
promises none of it — so a pin bump must re-prove each one here, statically.

THE GOOSE LESSON (v1.5.40: three guessed on-disk provider layouts, all "Unknown
provider"): nothing in this file is a guessed format. Each assertion names the file
and the behaviour it pins, and each one was READ at v2026.8.13 (hermes_cli
__version__ 0.20.1) before the seeding was written.

Run: pytest bridge/contract_tests/test_hermes_provider_contract.py -q
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERMES = ROOT / "vendor" / "hermes"


def _src(*parts: str) -> str:
    return (HERMES.joinpath(*parts)).read_text(errors="replace")


def _skip() -> bool:
    return not HERMES.exists()


# ── 1. the slug: what our model.provider value has to be ─────────────────────
def test_custom_provider_slug_is_name_lowercased_with_dashes():
    """providers.py::custom_provider_slug — the identity our seed reproduces.

    If this ever stops being `custom:<name.lower().replace(' ','-')>`, the
    `model.provider` value start_component.sh writes stops resolving and every
    Hermes turn falls through to the global default provider."""
    if _skip():
        return
    s = _src("hermes_cli", "providers.py")
    assert "def custom_provider_slug(" in s
    assert 'normalized = identity.lower().replace(" ", "-")' in s, (
        "custom_provider_slug no longer normalises name -> slug that way; "
        "scripts/seed_hermes_provider.py::custom_provider_slug must be re-derived")
    assert 'return normalized if normalized.startswith("custom:") else f"custom:{normalized}"' in s
    assert "def custom_provider_aliases(" in s, (
        "the alias set is what makes a RENAMED entry still resolve — our seed "
        "mirrors it to decide whether model.provider is dangling")


# ── 2. the entry's accepted keys: no 'unknown config keys' warning ───────────
def test_entry_keys_we_write_are_all_known():
    """config.py::_normalize_custom_provider_entry._KNOWN_KEYS — every key our seed
    writes must be in it, or Hermes logs `unknown config keys ignored` on every load
    (and, worse, the key is dropped from the runtime view)."""
    if _skip():
        return
    s = _src("hermes_cli", "config.py")
    i = s.index("_KNOWN_KEYS = {")
    block = s[i:s.index("}", i)]
    for key in ("name", "base_url", "api_key", "key_env", "models",
                "context_length", "discover_models"):
        assert '"%s"' % key in block, (
            "custom-provider key %r is no longer accepted by "
            "_normalize_custom_provider_entry — seed_hermes_provider.py writes it" % key)
    # base_url must still be the field the normalizer reads FIRST: it is our
    # identity (we match our own entry by URL, never by name).
    assert 'for url_key in ("base_url", "url", "api"):' in s


# ── 3. dict-shaped `models` is METADATA, not an allowlist ────────────────────
def test_dict_models_is_metadata_not_an_allowlist():
    """model_switch.py::_models_config_is_allowlist — our catalog is a DICT keyed by
    wire id with per-model context_length, exactly the shape Hermes's own writer
    (main.py::_save_custom_provider) produces."""
    if _skip():
        return
    s = _src("hermes_cli", "model_switch.py")
    i = s.index("def _models_config_is_allowlist(")
    body = s[i:i + 1400]
    assert "if isinstance(value, dict):\n        return False" in body, (
        "a dict-shaped models: map is no longer read as per-model metadata")
    assert "def _declared_model_ids(" in s, (
        "the reader that turns our models map into the picker's model list is gone")


# ── 4. discover_models: false PINS the catalog (the runner-down property) ────
def test_discover_models_false_suppresses_the_live_probe():
    """model_switch.py section 4 — with `discover_models: false` no /models probe
    runs, so the row keeps OUR registry list whether the runner is up or down. This
    is the whole reason the picker stays populated (and the reason it does not
    collapse to the single model llama-server currently serves)."""
    if _skip():
        return
    s = _src("hermes_cli", "model_switch.py")
    assert '_discovery_allowed = bool(api_url) and grp.get("discover_models", True)' in s, (
        "the discover_models gate moved — the seeded catalog may be replaced by a "
        "live probe again")
    assert "if _discovery_allowed:" in s
    # and the writer that would overwrite our map only runs after a real probe
    assert "def _save_discovered_models_to_config(" in s
    i = s.index("def _save_discovered_models_to_config(")
    body = s[i:i + 2600]
    assert "if isinstance(existing, dict):\n                continue" in body, (
        "upstream would now overwrite a dict-shaped (curated) models map with a "
        "probe result — our per-model context_length metadata is no longer safe")


# ── 5. one endpoint, one row: the bare `custom` row is suppressed ────────────
def test_bare_custom_row_is_suppressed_when_our_entry_exists():
    """model_switch.py section 3b — the anonymous 'Custom endpoint' row is emitted
    ONLY when no custom_providers entry shares model.base_url. That condition is what
    guarantees the migration cannot leave two rows for our one runner."""
    if _skip():
        return
    s = _src("hermes_cli", "model_switch.py")
    i = s.index("# --- 3b. Active bare custom endpoint from model config ---")
    block = s[i:s.index("# --- 4. Saved custom providers from config ---", i)]
    assert '_current_provider_norm == "custom"' in block
    assert "and not any(" in block and "for _cp in (custom_providers or [])" in block, (
        "section 3b no longer skips itself when a custom_providers entry carries the "
        "same base_url — a double picker row is now possible")
    assert '"name": "Custom endpoint"' in block


# ── 6. runtime: a named provider resolves base_url + inline api_key ──────────
def test_named_provider_resolves_url_and_inline_key_at_runtime():
    """runtime_provider.py::_get_named_custom_provider + _resolve_named_custom_runtime
    — after the migration, model.provider carries only the slug; the endpoint and the
    key come from the entry. An inline `api_key` must still be honoured (we write one
    unless the user declared key_env)."""
    if _skip():
        return
    s = _src("hermes_cli", "runtime_provider.py")
    assert "def _get_named_custom_provider(" in s
    i = s.index("    # Fall back to custom_providers: list (legacy format)")
    block = s[i:i + 3000]
    assert 'custom_providers = get_compatible_custom_providers(config)' in block
    assert 'if requested_norm not in custom_provider_aliases(name, provider_key):' in block
    assert '"api_key": str(entry.get("api_key", "") or "").strip(),' in block, (
        "an inline api_key on a custom_providers entry is no longer read")
    # and the key precedence that makes key_env-vs-api_key a real user choice
    j = s.index("def _resolve_named_custom_runtime(")
    rb = s[j:j + 6000]
    assert 'str(custom_provider.get("api_key", "") or "").strip(),' in rb
    assert '_getenv(str(custom_provider.get("key_env", "") or "").strip(), "").strip(),' in rb


# ── 7. the picker payload the dashboard renders ─────────────────────────────
def test_models_page_reads_the_payload_we_verify_after_start():
    """web_server.py + inventory.py — start_component.sh's provider self-check curls
    GET /api/model/options?include_unconfigured=1, which is exactly what the Models
    page / SET MAIN MODEL modal fetches. If the route or the row shape moves, the
    check would print a false negative."""
    if _skip():
        return
    ws = _src("hermes_cli", "web_server.py")
    assert '@app.get("/api/model/options")' in ws
    assert "build_model_options_payload" in ws
    inv = _src("hermes_cli", "inventory.py")
    assert "def build_model_options_payload(" in inv
    assert "probe_custom_providers=refresh," in inv
    assert '"providers": rows,' in inv
    api = _src("web", "src", "lib", "api.ts")
    assert "/api/model/options" in api and 'qs.set("include_unconfigured", "1")' in api


# ── 8. applying a pick from OUR row must not be rewritten to openrouter ──────
def test_picking_a_model_under_a_named_custom_row_keeps_the_slug():
    """web_server.py::_normalize_main_model_assignment — our model ids are local
    names (and, for MLX, absolute paths). The vendor-prefix fallback must keep
    excluding `custom:*` slugs, or selecting one of our models in Hermes's own picker
    silently reassigns the main slot to OpenRouter."""
    if _skip():
        return
    s = _src("hermes_cli", "web_server.py")
    i = s.index("def _normalize_main_model_assignment(")
    body = s[i:i + 5200]
    assert 'is_custom_provider_slug = canonical == "custom" or canonical.startswith("custom:")' in body
    assert "and not is_custom_provider_slug" in body
    assert "custom_provider = resolve_custom_provider(" in body


# ── 9. Hermes's own auto-registration dedupes by base_url ────────────────────
def test_hermes_own_writer_dedupes_by_base_url():
    """main.py::_save_custom_provider — POST /api/model/set calls this whenever the
    main slot is set to a bare `custom` endpoint (web_server.py). It matches on
    base_url, so it UPDATES our entry instead of adding a second row for the same
    runner. Our seed adopts its auto-generated name (main.py::_auto_provider_name)
    for the same reason."""
    if _skip():
        return
    m = _src("hermes_cli", "main.py")
    i = m.index("def _save_custom_provider(")
    body = m[i:i + 3000]
    assert 'entry.get("base_url", "").rstrip(\n            "/"\n        ) == base_url.rstrip("/")' in body \
        or 'entry.get("base_url", "").rstrip("/") == base_url.rstrip("/")' in body, (
        "_save_custom_provider no longer dedupes by base_url — Hermes's own Models "
        "page can now add a SECOND row for the runner our seed already owns")
    assert "def _auto_provider_name(" in m
    ws = _src("hermes_cli", "web_server.py")
    assert 'if provider.strip().lower() in {"custom", "local"} and base_url:' in ws
    assert "_save_custom_provider(" in ws
