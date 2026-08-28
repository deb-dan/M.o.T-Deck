# APP-FACADE MANIFEST — the surface `bridge/app.py` must keep answering for

**Generated, not hand-written** (router/core split, 2026-08-28). It is the answer to
the one question the next refactor of this area will ask: *if I move this, what
breaks?* Regenerate it whenever the split changes shape.

## Why a facade at all

`bridge/app.py` was 10,072 lines. It could not simply be cut into modules, because
the rest of the tree does not treat it as a web app — it treats it as a library:

* 50+ suites and the contract gate import its internals directly
  (`from bridge import app as A; A.caps_map_write(...)`);
* seven of those symbols are **monkeypatched** (`A.ROOT = tmpdir`, `A._script = fake`)
  and the patch has to change what the code under test actually calls;
* ~40 test files, seven of them in the contract gate, assert against app.py's
  **source text** — 78 of those assertions read the literal `@app.get("…")`
  decorator line, and a dozen slice the source *between* two neighbouring routes.

So the split had to preserve three surfaces, not one: the importable symbols, the
mutability of the patched ones, and the source text itself. It does that with
`bridge/app.py`'s module-class proxy (symbols + mutation) and `bridge/appsrc.py`'s
ordered source view (text). Neither is optional; both are commented in place.

## The module map

Order is the order the code sat in the pre-split file, which is also
`bridge/appsrc.py`'s `FILES` and `bridge/app.py`'s `_LANES`.

| # | module | lines | was app.py |
|---:|---|---:|---|
| 1 | `bridge/core/appctx.py` | 180 | 1-155 (+ moved satellite-import depth fix) |
| 2 | `bridge/app.py` | 277 | 156-219 + the facade |
| 3 | `bridge/core/procs.py` | 251 | 220-363, 1047-1140, 2484-2489 |
| 4 | `bridge/routers/panel.py` | 16 | 364-374 |
| 5 | `bridge/core/modelid.py` | 193 | 375-557 |
| 6 | `bridge/core/health.py` | 87 | 558-641 |
| 7 | `bridge/routers/components.py` | 523 | 642-1207 (− port kills) + 338-362 |
| 8 | `bridge/routers/ody.py` | 588 | 1208-1787 |
| 9 | `bridge/core/analytics.py` | 81 | 1788-1862 |
| 10 | `bridge/routers/sidecars.py` | 343 | 1863-2198 |
| 11 | `bridge/routers/version.py` | 87 | 2199-2278 |
| 12 | `bridge/routers/odychat.py` | 45 | 2279-2315 |
| 13 | `bridge/core/yamlset.py` | 64 | 2316-2375 |
| 14 | `bridge/routers/models.py` | 744 | 2376-3110 (− _registry_models) |
| 15 | `bridge/routers/hf.py` | 548 | 3111-3654 (− the two HF clients) |
| 16 | `bridge/core/hfclient.py` | 19 | 3113-3116 |
| 17 | `bridge/routers/downloads.py` | 497 | 3655-4142 |
| 18 | `bridge/routers/sampling.py` | 689 | 4143-4822 |
| 19 | `bridge/routers/chat.py` | 226 | 4823-5035 |
| 20 | `bridge/routers/hermes.py` | 1206 | 5036-6247 (− _hermes_token/_port) |
| 21 | `bridge/routers/misc.py` | 155 | 6248-6394 |
| 22 | `bridge/routers/nav.py` | 67 | 6395-6455 |
| 23 | `bridge/core/hermescfg.py` | 149 | 6456-6563 + 5052-5073 |
| 24 | `bridge/routers/hermestools.py` | 1108 | 6564-7661 |
| 25 | `bridge/routers/voicecomp.py` | 204 | 7662-7855 |
| 26 | `bridge/routers/voice.py` | 1043 | 7856-8881 |
| 27 | `bridge/routers/music.py` | 331 | 8882-9198 |
| 28 | `bridge/routers/aider.py` | 262 | 9199-9447 |
| 29 | `bridge/routers/office.py` | 508 | 9448-9951 (− the logger pair) |
| 30 | `bridge/core/officelog.py` | 25 | 9460-9467 |
| 31 | `bridge/routers/oo.py` | 150 | 9952-10092 |
| | **total** | **10666** | 10,072 |

Largest file: routers/hermes.py at 1206 lines (ceiling was ~1,500). The growth over 10,072 is
module docstrings and generated per-module import blocks; not a line of logic moved,
changed or was retyped — the carve copied line ranges.

## Import direction (enforced by construction, verified after every stage)

```
app.py  ──imports──▶  core/*  and  routers/*        (and nothing imports app.py)
routers/* ──▶ core/*, the satellites, other routers (acyclic — checked)
core/*    ──▶ core/* only                           (never a router)
```

## The re-exported surface

**113 symbols** are named from outside `bridge/app.py` today (mechanically
enumerated across `bridge/tests`, `bridge/contract_tests`, `scripts`, `guards`,
`app`). All resolve through the proxy, and so do the other
372 pre-split top-level names — the proxy is total, not a list, so
this table is documentation rather than the mechanism.

### Mutated from outside — the seven that made a re-export list impossible

| symbol | now lives in | patched by |
|---|---|---|
| `ROOT` | `bridge/core/appctx.py` | `bridge/tests/test_aider_lane.py`, `bridge/tests/test_installed_flip.py`, `bridge/tests/test_nav_model.py`, `bridge/tests/test_office_mcp.py` |
| `_hermes_dash` | `bridge/routers/hermestools.py` | `bridge/tests/test_hermes_skills.py`, `bridge/tests/test_hermes_toolsets.py` |
| `_port_listener_pids` | `bridge/core/procs.py` | `bridge/tests/test_ops_hardening.py` |
| `_proc_cmdline` | `bridge/core/procs.py` | `bridge/tests/test_ops_hardening.py` |
| `_script` | `bridge/core/procs.py` | `bridge/tests/test_aider_lane.py`, `bridge/tests/test_load_switch.py` |
| `_set_runner_model` | `bridge/core/yamlset.py` | `bridge/tests/test_load_switch.py` |
| `aider_spawn_spec` | `bridge/routers/aider.py` | `bridge/tests/test_aider_lane.py` |

A write through the facade reaches **every** module holding that name, not just the
owner — `A.ROOT = tmp` rebinds `core.appctx.ROOT` and the copy in each of the ~25
lanes that imported it. That is what keeps the aider / nav / installed-flip /
office-mcp suites working unchanged.

### Everything else, by owning module

**`bridge/core/appctx.py`** — `_NAV_ERR`, `_PTY_ERR`, `_nav`, `_pty`, `app`

**`bridge/core/procs.py`** — `_kill_port_listener`, `_port_alive`, `_port_alive_sync`, `_port_kill_cmd`, `_port_owner_verdict`

**`bridge/core/modelid.py`** — `_display_model`, `_live_model_id`, `_reconcile_live`, `display_model_id`, `wire_model_id`

**`bridge/core/health.py`** — `HEALTH_MISS_LOST`, `PROBE_TIMEOUT_DEFAULT`, `PROBE_TIMEOUT_S`, `_HEALTH_MISS`, `_health_track`, `_probe_timeout`, `health_verdict`

**`bridge/routers/components.py`** — `_NOTES`, `status`

**`bridge/routers/ody.py`** — `CAPS_SETTING_KEYS`, `caps_map_write`

**`bridge/routers/models.py`** — `OPENCODE_TOOLS_NONE`, `OPENCODE_TOOLS_UNKNOWN`, `_SWITCH`, `_deletable_target`, `_do_switch`, `_model_caps`, `api_models`, `api_switch_model`, `opencode_landing_url`, `opencode_tools_warning`

**`bridge/routers/hf.py`** — `AUDIO_GGUF_DEFAULT_TERM`, `AUDIO_SEARCH_KINDS`, `AUDIO_SEARCH_QUERIES`, `AUDIO_WHISPER_REQUIRED`, `AUDIO_WHISPER_VETO`, `LICENSE_NC_REASON`, `LICENSE_OVERRIDES`, `MINIMAX_MUSIC3_LICENSE_REASON`, `OMNIVOICE_LICENSE_REASON`, `audio_license_badge`, `audio_license_row`, `audio_probe_size`, `audio_probe_verdict`, `audio_probe_voices`, `gguf_tts_pair`, `hf_license`, `is_mlx_whisper_cfg`, `license_override`

**`bridge/routers/misc.py`** — `sanitize_artifact_filename`

**`bridge/core/hermescfg.py`** — `_hermes_cfg_bump`, `_hermes_config_path`, `_hermes_get_mcp`, `_hermes_has_mcp`, `_hermes_set_mcp`, `_hermes_write_mcp`, `hermes_cfg_gen`

**`bridge/routers/hermestools.py`** — `HERMES_CONFIG_ONLY_TOOLSETS`, `HERMES_DEFAULT_OFF_TOOLSETS`, `HERMES_GATEWAY_ALWAYS_TOOLS`, `HERMES_GATEWAY_ALWAYS_TOOLSET`, `HERMES_LEVER_PLATFORM`, `HERMES_MINIMAL_TOOLSETS`, `HERMES_SESSION_SOURCE`, `HERMES_SKILL_DEFAULT_DISABLED`, `HERMES_SKILL_INDEX_TOOLS`, `HERMES_SKILL_TOGGLE_PATH`, `HERMES_TOOLSETS_EMPTY_REASON`, `_hermes_toolset_config`, `hermes_lever_enabled`, `hermes_lever_names`, `hermes_preset_desired`, `hermes_skill_lane_off`, `hermes_skill_names`, `hermes_skill_plan`, `hermes_skill_preset_desired`, `hermes_skill_rows`, `hermes_skill_view`, `hermes_skills_get`, `hermes_skills_on`, `hermes_skills_set`, `hermes_skills_summary`, `hermes_skills_valid`, `hermes_tool_summary`, `hermes_toolset_drift`, `hermes_toolset_is_lever`, `hermes_toolset_names`, `hermes_toolset_plan`, `hermes_toolset_platform`, `hermes_toolset_result`, `hermes_toolset_view`, `hermes_toolsets_enabled`, `hermes_toolsets_get`, `hermes_toolsets_set`, `hermes_toolsets_summary`, `hermes_toolsets_valid`

**`bridge/routers/voicecomp.py`** — `VOICE_MCP`, `voice_mcp_spec`

**`bridge/routers/aider.py`** — `_AIDER_INSTALLING`, `_AIDER_INSTALL_LOCK`

**`bridge/(re-exported / stdlib)`** — `subprocess`

## Regenerating

The carve, the reference scan and this document are scripted; the scripts live with
the session that ran them rather than in the repo, because a one-shot refactor tool
that stays on disk is a tool that rots. What DOES stay is the checkable invariant:

```sh
python -m bridge.appsrc                     # the source view's module boundaries
./scripts/verify.sh                         # the contract gate (142 + 4 skipped)
for f in bridge/tests/test_*.py; do python "$f"; done   # 44 suites
for f in bridge/tests/test_*.js; do node   "$f"; done   # 24 suites
```
