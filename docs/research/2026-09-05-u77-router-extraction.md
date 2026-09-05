# U77 — Cohesive router extraction below the 1,500-line fence

Decision-complete build brief. This is a behavior-preserving architecture repair, not
permission to raise the ceiling or redesign any endpoint.

## Destination

Both oversized app-layer routers must end below 1,500 physical lines with useful
headroom, while preserving route paths/methods/order, response payloads/status codes,
source-view order, facade exports, monkeypatch propagation, and every established
import path used by another router or test. New files must also remain below the same
ceiling. No UI, process, live state, vendor, snapshot, version, or catalog change.

## Exact extractions

### Component lifecycle

Move the contiguous lifecycle block beginning at `_NOTES` through `_provision` from
`bridge/routers/components.py` into new
`bridge/routers/component_lifecycle.py`. The new router owns these decorated routes:

- `GET /api/components/{name}/start-plan`
- `POST /api/components/{name}/start`
- `POST /api/components/{name}/stop`
- `POST /api/components/{name}/restart`
- `POST /api/components/{name}/update`

It also owns `_NOTES`, `_opencode_live_warning`, `_prov_set`, and `_provision`.
Preserve function bodies/comments and route ordering except for import adjustments.
Import core/model/nav/sampling primitives directly into the new lane. Where lifecycle
code needs status/failure symbols that remain in `components.py`
(`clear_start_failure`, `runner_serving`, `runner_model_view`,
`start_failure_reason`, `LAST_START_FAIL`, `_FAIL_OK_STREAK`, `_LANE_RESTART`), use
function-local imports at the narrow call sites so there is no top-level two-way router
cycle.

`routers.quitall` and external callers must keep working through
`bridge.routers.components.stop`. Preserve the old components-module callable surface
with small lazy forwarding functions for `start_plan`, `_opencode_live_warning`,
`start`, `stop`, `restart`, `update`, `_prov_set`, and `_provision`; the forwarding
functions have no route decorators and import their target inside the call. Preserve
`_NOTES` only if a real caller/import is found; otherwise do not invent a mutable proxy
solely for an unused private constant. The facade's public value for moved symbols must
be the owning lifecycle implementation after all lanes load.

### Model visibility

Move the contiguous hidden-model block from `HIDEABLE_SOURCES` through
`api_models_hide` into new `bridge/routers/model_visibility.py`. It imports only the
direct primitives it uses (`app`, `_voice`, `cfg`, `_registry_models`,
`_registry_update`, `Request`, `JSONResponse`) and must never import `routers.models`.

`models.py` re-exports `HIDEABLE_SOURCES`, `_is_hidden`, `_hideable`, `_hidden_view`,
and `api_models_hide` from the new module so `routers.voice` and existing tests retain
their import paths. There must be exactly one decorated `/api/models/hide` route.
Leave the model RAM ledger and all switch/rescan/aux behavior in `models.py`.

## Facade and source view

Register each new module in both ordered manifests at its original source position:

```python
# bridge/app.py _LANES
"core.health",
"routers.components",
"routers.component_lifecycle",
"routers.ody",
...
"core.yamlset",
"routers.model_visibility",
"routers.models",
"routers.aux",
```

```python
# bridge/appsrc.py FILES
"core/health.py",
"routers/components.py",
"routers/component_lifecycle.py",
"routers/ody.py",
...
"core/yamlset.py",
"routers/model_visibility.py",
"routers/models.py",
"routers/aux.py",
```

This is required for route sorting, source-text fences, disk/list parity, facade reads,
and facade monkeypatch writes. Update comments that falsely name the old module owner.
Do not append these lanes at the tail: unlike a new capability, both have an original
pre-split source position.

## Contract updates

- Retarget the Goose restart source assertion in `bridge/tests/test_dep_signal.py` to
  `component_lifecycle.py`.
- Retarget the component stop source assertion in
  `bridge/contract_tests/test_no_name_kills_contract.py` to the owning lifecycle file.
- Keep `bridge/contract_tests/test_quitall_contract.py`'s import through
  `.components.stop`; its compatibility path is intentional.
- Add permanent seam tests proving the old `components.stop` callable delegates to the
  lifecycle owner and `bridge.app.stop` resolves to the lifecycle implementation.
- Add permanent seam tests proving `models._is_hidden` is the exact implementation
  exported by `model_visibility`, and `/api/models/hide` is registered once.
- Update any app facade/source manifest expected sets and line-ceiling expectations by
  adding the real modules, never by excluding a file or increasing 1,500.

## Verification floor

Run the focused set specified in U77's analysis:

```text
bridge/tests/test_app_facade.py
bridge/contract_tests/test_seam.py
bridge/contract_tests/test_no_name_kills_contract.py
bridge/contract_tests/test_quitall_contract.py
bridge/tests/test_dep_signal.py
bridge/tests/test_installed_flip.py
bridge/tests/test_audio_registry.py
bridge/tests/test_voice_cache.py
bridge/tests/test_model_load.py
bridge/tests/test_model_settings.py
bridge/tests/test_registry_hygiene.py
```

Then run `scripts/verify.sh`, all standalone Python suite entry points used by the
repository audit, JavaScript suites, script hygiene, Bash syntax where relevant, and
`git diff --check`. Explicitly report final line counts and endpoint-set/order parity.

The builder must read and follow `CLAUDE.md` and
`docs/DOCTRINE-PROACTIVE-BUILD.md`. It does not ship, edit `VERSION`, commit/push,
touch the installed app/snapshot/live YAML/processes/ports, modify generated `data/`,
touch the archived Claude tree, or touch/stage pre-existing `vendor/hermes` state.
