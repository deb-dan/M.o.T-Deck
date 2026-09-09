"""S23 — every optional component may be absent without making MOT Deck lie.

This is a derived matrix, not a hand-picked list: optional means every manifest
component outside the four first-run core services.  A newly added component therefore
enters this fence automatically.
"""
from pathlib import Path
import re

import yaml

from bridge.routers.components import NEEDS_SOFT, needs_derive


ROOT = Path(__file__).resolve().parents[2]
PANEL = (ROOT / "bridge/panel/index.html").read_text(errors="replace")
SWIFT = (ROOT / "app/main.swift").read_text(errors="replace")
MANIFEST = yaml.safe_load((ROOT / "motdeck.yaml").read_text())
COMPONENTS = MANIFEST["components"]
CORE = ("runner", "hermes", "odysseus", "searxng")
OPTIONAL = tuple(sorted(set(COMPONENTS) - set(CORE)))


def _healthy_components():
    rows = {
        name: {"installed": True, "running": True, "port_up": True,
               "health": "ok", "loaded": True}
        for name in COMPONENTS
    }
    rows["runner"] = {"installed": True, "running": True, "port_up": True,
                      "health": "ok", "loaded": True, "pin_intent": "model-a",
                      "live_id": "model-a", "model_file": "ok"}
    return rows


def _hard_deps():
    out = {name: tuple(row.get("depends_on") or ())
           for name, row in COMPONENTS.items()}
    out["runner"] = ()
    return out


def test_matrix_is_derived_and_nonempty():
    assert set(CORE) <= (set(COMPONENTS) | {"runner"})
    assert OPTIONAL, "the optional-install contract has no subjects"


def test_one_absent_optional_component_never_creates_a_dependency_nag():
    hard = _hard_deps()
    for missing in OPTIONAL:
        rows = _healthy_components()
        rows[missing].update({"installed": False, "running": False,
                              "port_up": False, "health": "ok"})
        got = needs_derive(rows, hard, NEEDS_SOFT, {})
        assert missing not in got, (
            f"{missing}: an absent lane already has its own install/placeholder state")
        for owner, detail in got.items():
            deps = {row.get("dep") for row in detail.get("needs", [])}
            assert missing not in deps, (
                f"{missing}: {owner} was made to require an optional component")


def test_first_run_checklist_contains_core_only():
    match = re.search(r"const SETUP_COMPONENTS = \[([^]]+)\]", PANEL)
    assert match, "first-run setup component list moved"
    names = tuple(re.findall(r"'([a-z0-9_-]+)'", match.group(1)))
    assert names == CORE
    assert not set(names) & set(OPTIONAL)


def test_every_optional_native_surface_remains_navigable_when_down():
    begin = SWIFT.index("let tabRegistry:")
    registry = SWIFT[begin:SWIFT.index("\n]", begin) + 2]
    for name in OPTIONAL:
        assert f'id: "{name}"' in registry, f"{name}: optional tab disappeared"
    assert "Not reachable yet" in SWIFT
    assert "re-select this tab" in SWIFT and "&#8984;R" in SWIFT


def test_component_cards_offer_install_without_claiming_failure():
    start = PANEL.index("function cardHTML(")
    end = PANEL.index("\nfunction ", start + 1)
    card = PANEL[start:end]
    assert "c.installed ? 'Stopped' : 'Not installed'" in card
    assert 'planInstall(\'${name}\')">Install</button>' in card
    assert "!c.installed" not in card.split("state =", 1)[0], (
        "absence must not be routed through a failure branch before the honest state")


def test_first_party_help_capabilities_and_models_do_not_depend_on_optional_tabs():
    for view in ("help", "caps", "models"):
        assert f'data-view="{view}"' in PANEL or f"showView('{view}')" in PANEL
    models_start = PANEL.index("function renderModels(")
    models_end = PANEL.index("\nfunction ", models_start + 1)
    models = PANEL[models_start:models_end]
    assert "modelsState" in models or "model" in models.lower()
    assert not any(f"components.{name}" in models for name in OPTIONAL), (
        "the model library must remain registry-driven when an optional app is absent")
