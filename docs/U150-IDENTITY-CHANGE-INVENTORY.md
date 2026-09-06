# U150 identity-change inventory

Status: v1.5.84 shipped and done-verified. Update this file whenever an identity-bearing
surface is added, renamed, migrated, retired, or deliberately retained.

This is the exhaustive file-and-state companion to `FABLE-U150-MOT-DECK-IDENTITY-MIGRATION-SPEC.md`. The specification defines behavior; this document answers “where did the name move?” so a future rename or audit does not rely on memory or a blind global replacement.

## Canonical mapping

| Surface | Retired identity | Current identity |
|---|---|---|
| Visible product | Harness / mixed M.O.T labels | MOT Deck |
| Logo artwork | M.O.T | M.O.T (deliberately unchanged) |
| App bundle | Harness.app / M.O.T.app | MOT Deck.app |
| Installer | Harness.dmg | MOT Deck.dmg |
| Mounted volume | Harness | MOT Deck |
| Machine slug | harness | motdeck |
| Bundle identifier | local.harness.app | local.motdeck.app |
| Executable | Harness | MOTDeck |
| Manifest | harness.yaml | motdeck.yaml |
| Environment namespace | HARNESS_* and MOT_* launch-secret keys | MOT_DECK_* |
| Live root | ~/Library/Application Support/Harness | ~/Library/Application Support/MOT Deck |
| Repository folder | .../New Harness/harness | .../New Harness/MOT Deck |
| GitHub repository | Debkbas/new-harness | Debkbas/mot-deck |
| Hermes managed guard | harness-path-guard | motdeck-path-guard |
| First-party browser/native keys | harness.* / harness-* | motdeck.* / motdeck-* |
| First-party WebKit handler/global | harness / harnessShell / harnessNative* | motdeck / motdeckShell / motdeckNative* |

## External and live-state moves

- GitHub was renamed in place to `Debkbas/mot-deck`; `origin` points to that private repository. No token is stored in Git configuration.
- The canonical checkout directory is `/Users/debik/GemiAntigravity/September 3rd new check harness/New Harness/MOT Deck`. Parent folders are outside the approved boundary and remain unchanged.
- Live state moved as one root to `~/Library/Application Support/MOT Deck`. Its manifest and backups moved to `motdeck.yaml*`; protected secret keys changed to `MOT_DECK_*_B64`; explicitly enumerated generated venv/profile paths were retargeted.
- WebKit and HTTP-storage domains moved from `local.harness.app` to `local.motdeck.app` only when the destination did not already exist.
- Shell UserDefaults and first-party localStorage keys migrate once; an already-present new key always wins.
- The installed application is `/Applications/MOT Deck.app`, executable `MOTDeck`, identity `local.motdeck.app`. The exact old app bundle was retained as a temporary rollback artifact through live verification and is retired only after the final clean FAT replacement passes.
- Hermes startup replaces and deduplicates the managed guard ID, then removes only an ownership-verified generated old plug-in directory. User plug-ins and foreign lookalikes are preserved.
- The FAT snapshot synchronizes six explicit repo-owned authoring files and retires only three exact files plus the verified generated old guard directory. It never recursively mirrors app, docs, skills, live YAML, or data.

## Deliberately retained old words

- `DeepSeek Harness` is an upstream product name and remains unchanged.
- “test harness” and similar generic engineering language remain ordinary English.
- The old bundle ID, key prefixes, manifest name, live root, and guard ID remain only inside migration code/tests that must recognize old installations.
- A previously provisioned live root can contain inactive test directories from its older FAT seed. `ship.sh` deliberately does not import, execute, synchronize, or delete those non-runtime trees. Their legacy fixtures may retain old literals; the final v1.5.84 FAT seed contains the current test corpus. Preserving an unproven live directory is safer than assuming every neighbor is disposable.
- Git history, incident records, frozen rollback artifacts, and explicitly historical handoff/research prose may name the identity that existed at that time.
- The visible logo artwork remains `M.O.T`; it is not the app, bundle, executable, installer, or machine slug.

## Exhaustive U150 file inventory

The list below contains all 334 current tracked paths changed by U150 through the
v1.5.84 release candidate, plus the eight retired source paths shown on rename rows.
This count is mechanically checked against the union of the U150 candidate commit and
the release-candidate diff. A path’s presence means its identity-bearing reference,
expectation, fixture, help text, operational instruction, release record, or historical
wording was reviewed; it does not mean product logic was otherwise redesigned.

### Repository root and manifest (5)

- `.gitignore`
- `CLAUDE.md`
- `README.md`
- `VERSION`
- `harness.yaml → motdeck.yaml`

### Native app and icon (4)

- `app/.gitignore`
- `app/Harness.icns → app/MOTDeck.icns`
- `app/main.swift`
- `app/make_icon.swift`

### Bridge runtime (57)

- `bridge/app.py`
- `bridge/core/__init__.py`
- `bridge/core/appctx.py`
- `bridge/core/comfycur.py`
- `bridge/core/events.py`
- `bridge/core/fit.py`
- `bridge/core/health.py`
- `bridge/core/hermescfg.py`
- `bridge/core/localsecrets.py`
- `bridge/core/memory.py`
- `bridge/core/modeldelete.py`
- `bridge/core/modelid.py`
- `bridge/core/modelreg.py`
- `bridge/core/procs.py`
- `bridge/core/singleton.py`
- `bridge/core/yamlset.py`
- `bridge/gooseprov.py`
- `bridge/gooseui.py`
- `bridge/modeltools.py`
- `bridge/music.py`
- `bridge/nav.py`
- `bridge/office.py`
- `bridge/office_mcp.py`
- `bridge/office_ops.py`
- `bridge/oo.py`
- `bridge/ooai.py`
- `bridge/pty_aider.py`
- `bridge/pty_goose.py`
- `bridge/routers/aider.py`
- `bridge/routers/apikeys.py`
- `bridge/routers/aux.py`
- `bridge/routers/chat.py`
- `bridge/routers/comfy.py`
- `bridge/routers/component_lifecycle.py`
- `bridge/routers/components.py`
- `bridge/routers/downloads.py`
- `bridge/routers/goose.py`
- `bridge/routers/gooseui.py`
- `bridge/routers/help.py`
- `bridge/routers/hermes.py`
- `bridge/routers/hermestools.py`
- `bridge/routers/hf.py`
- `bridge/routers/memory.py`
- `bridge/routers/misc.py`
- `bridge/routers/model_rescan.py`
- `bridge/routers/model_visibility.py`
- `bridge/routers/models.py`
- `bridge/routers/odyvision.py`
- `bridge/routers/office.py`
- `bridge/routers/quitall.py`
- `bridge/routers/sampling.py`
- `bridge/routers/sidecars.py`
- `bridge/routers/version.py`
- `bridge/routers/voice.py`
- `bridge/routers/voicecomp.py`
- `bridge/voice.py`
- `bridge/yamlfile.py`

### Bridge contract gates (30)

- `bridge/contract_tests/test_aider_contract.py`
- `bridge/contract_tests/test_app_identity_contract.py`
- `bridge/contract_tests/test_canonical_root_severance.py`
- `bridge/contract_tests/test_detached_spawn_contract.py`
- `bridge/contract_tests/test_goose_contract.py`
- `bridge/contract_tests/test_gooseui_contract.py`
- `bridge/contract_tests/test_hermes_skills_contract.py`
- `bridge/contract_tests/test_hermes_toolsets_contract.py`
- `bridge/contract_tests/test_hermes_ws_contract.py`
- `bridge/contract_tests/test_installers_contract.py`
- `bridge/contract_tests/test_llama_server_contract.py`
- `bridge/contract_tests/test_llama_tts_contract.py`
- `bridge/contract_tests/test_local_secret_migration.py`
- `bridge/contract_tests/test_local_secrets.py`
- `bridge/contract_tests/test_manifest_reader.py`
- `bridge/contract_tests/test_mlx_audio_stt_contract.py`
- `bridge/contract_tests/test_mlx_whisper_contract.py`
- `bridge/contract_tests/test_motdeck_identity_migration.py`
- `bridge/contract_tests/test_motdeck_memory_identity.py`
- `bridge/contract_tests/test_no_name_kills_contract.py`
- `bridge/contract_tests/test_odysseus_managed_handoff.py`
- `bridge/contract_tests/test_office_mcp_contract.py`
- `bridge/contract_tests/test_opencode_contract.py`
- `bridge/contract_tests/test_pidfile_port_contract.py`
- `bridge/contract_tests/test_quitall_contract.py`
- `bridge/contract_tests/test_seam.py`
- `bridge/contract_tests/test_version_truth_contract.py`
- `bridge/contract_tests/test_voicebox_contract.py`
- `bridge/contract_tests/test_voicestudio_contract.py`
- `bridge/contract_tests/test_wire_id_contract.py`

### First-party web surfaces (11)

- `bridge/panel/aider.html`
- `bridge/panel/assets/identity-migration.js`
- `bridge/panel/assets/studio-design.css`
- `bridge/panel/assets/studio-office.css`
- `bridge/panel/assets/turn-stream.js`
- `bridge/panel/comfy.html`
- `bridge/panel/compose.html`
- `bridge/panel/goose.html`
- `bridge/panel/index.html`
- `bridge/panel/office.html`
- `bridge/panel/oo.html`

### Bridge repository and JavaScript gates (78)

- `bridge/tests/test_aider_lane.py`
- `bridge/tests/test_api_keys.py`
- `bridge/tests/test_api_view.js`
- `bridge/tests/test_app_facade.py`
- `bridge/tests/test_audio_drop.js`
- `bridge/tests/test_audio_registry.py`
- `bridge/tests/test_canvas_logic.js`
- `bridge/tests/test_comfy_lane.py`
- `bridge/tests/test_comfy_page.js`
- `bridge/tests/test_compose_page.js`
- `bridge/tests/test_conv_mode.js`
- `bridge/tests/test_deepseek_lane.py`
- `bridge/tests/test_dep_signal.py`
- `bridge/tests/test_download_rows.js`
- `bridge/tests/test_events_hub.py`
- `bridge/tests/test_fit_advisor.py`
- `bridge/tests/test_goose_lane.py`
- `bridge/tests/test_gooseui_lane.py`
- `bridge/tests/test_hermes_cfg_gen.py`
- `bridge/tests/test_hermes_max_turn.py`
- `bridge/tests/test_hermes_provider_seed.py`
- `bridge/tests/test_hermes_sessions.py`
- `bridge/tests/test_hermes_skills.js`
- `bridge/tests/test_hermes_skills.py`
- `bridge/tests/test_hermes_sse_map.py`
- `bridge/tests/test_hermes_toolsets.js`
- `bridge/tests/test_hermes_toolsets.py`
- `bridge/tests/test_identity_migration.js`
- `bridge/tests/test_image_sidecar.py`
- `bridge/tests/test_installed_flip.py`
- `bridge/tests/test_lane_affordances.js`
- `bridge/tests/test_load_switch.py`
- `bridge/tests/test_model_artifact_integrity.py`
- `bridge/tests/test_model_delete.py`
- `bridge/tests/test_model_load.py`
- `bridge/tests/test_model_settings.py`
- `bridge/tests/test_model_settings_ui.js`
- `bridge/tests/test_model_source_adapters.py`
- `bridge/tests/test_model_source_availability.py`
- `bridge/tests/test_music_deck.js`
- `bridge/tests/test_music_lane.py`
- `bridge/tests/test_nav_model.py`
- `bridge/tests/test_nav_panel.js`
- `bridge/tests/test_odysseus_seed.py`
- `bridge/tests/test_office_adversarial.py`
- `bridge/tests/test_office_ai.js`
- `bridge/tests/test_office_grid.js`
- `bridge/tests/test_office_journey.py`
- `bridge/tests/test_office_lane.py`
- `bridge/tests/test_office_mcp.py`
- `bridge/tests/test_oo_ai_lane.py`
- `bridge/tests/test_oo_lane.py`
- `bridge/tests/test_opencode_draft_label.js`
- `bridge/tests/test_opencode_lane.py`
- `bridge/tests/test_ops_hardening.py`
- `bridge/tests/test_optional_components.py`
- `bridge/tests/test_parakeet_stt.py`
- `bridge/tests/test_path_guard.py`
- `bridge/tests/test_process_launch_ownership.py`
- `bridge/tests/test_recovered_turn_abort.js`
- `bridge/tests/test_registry_hygiene.py`
- `bridge/tests/test_registry_writer_durability.py`
- `bridge/tests/test_state_durability.py`
- `bridge/tests/test_studio_chrome.js`
- `bridge/tests/test_studio_design.js`
- `bridge/tests/test_studio_office.js`
- `bridge/tests/test_theme_packs.js`
- `bridge/tests/test_thinking_sidecar.py`
- `bridge/tests/test_turn_lifecycle.js`
- `bridge/tests/test_turn_recovery_marker.js`
- `bridge/tests/test_turn_stream_renderer.js`
- `bridge/tests/test_u74_recovery_hardening.py`
- `bridge/tests/test_vad_segmenter.js`
- `bridge/tests/test_vision_content.py`
- `bridge/tests/test_voice_cache.py`
- `bridge/tests/test_voice_mcp.py`
- `bridge/tests/test_voice_stt.py`
- `bridge/tests/test_voice_tts.py`

### Active specifications, Help, roadmap, and ledgers (17)

- `docs/FABLE-AGENT-CHANGESET-SPEC.md`
- `docs/FABLE-STUDIO-DESIGN-SPEC.md`
- `docs/FABLE-U150-MOT-DECK-IDENTITY-MIGRATION-SPEC.md`
- `docs/FABLE-U24-U25-U66-PROCESS-IDENTITY-SPEC.md`
- `docs/FABLE-U61-U62-STATE-DURABILITY-SPEC.md`
- `docs/FABLE-U71-LOCAL-SECRETS-SPEC.md`
- `docs/FABLE-U72-SHELL-EXECUTION-BOUNDARY-SPEC.md`
- `docs/FABLE-U74-RECOVERY-HARDENING-SPEC.md`
- `docs/FABLE-U78-APP-BUNDLE-DISCOVERY-SPEC.md`
- `docs/HARNESS-INTERNALS.md → docs/MOT-DECK-INTERNALS.md`
- `docs/ROADMAP.md`
- `docs/U150-IDENTITY-CHANGE-INVENTORY.md`
- `docs/UNFORGET.md`
- `docs/USER-EXPLAINERS.md`
- `docs/USER-GUIDE-OPUS5.md`
- `docs/USER-GUIDE.md`
- `docs/harness-architecture.md → docs/mot-deck-architecture.md`

### Historical handoff corpus (33)

- `docs/handoff/00_START_HERE.md`
- `docs/handoff/01_Vision_and_Decision.md`
- `docs/handoff/02_Architecture.md`
- `docs/handoff/03_Licensing.md`
- `docs/handoff/04_Roadmap.md`
- `docs/handoff/05_Reference_and_Learnings.md`
- `docs/handoff/06_Landscape_and_PriorArt.md`
- `docs/handoff/07_Salvage_from_v1.md`
- `docs/handoff/08_Interface_Strategy.md`
- `docs/handoff/09_Ideas_StealList_and_Gaps.md`
- `docs/handoff/10_Modalities_Voice_and_Vision.md`
- `docs/handoff/CLAUDE.md`
- `docs/handoff/DRAFT-CHAT-SPLIT-ISOLATION.md`
- `docs/handoff/FABLE-ARTIFACTS-SPEC.md`
- `docs/handoff/FABLE-FAT-INSTALLER-SPEC.md`
- `docs/handoff/FABLE-HANDOFF-2026-07-23.md`
- `docs/handoff/FABLE-MUSIC-DECK-SPEC.md`
- `docs/handoff/FABLE-MUSIC-LANE-SPEC.md`
- `docs/handoff/FABLE-SPLITSCREEN-SPEC.md`
- `docs/handoff/FABLE-STUDIO-CHROME-SPEC.md`
- `docs/handoff/FABLE-STUDIO-PHASE2-SPEC.md`
- `docs/handoff/FABLE-UI-SPECS.md`
- `docs/handoff/FABLE-VOICE-CAPABILITY-SPEC.md`
- `docs/handoff/FABLE-VOICE-TABS-SPEC.md`
- `docs/handoff/HERMES-v0.20.6-BLOCKED-2026-08-28.md`
- `docs/handoff/LM-Studio-MCP-Setup-Guide.md`
- `docs/handoff/MUSIC-MEASUREMENT-RUNBOOK.md`
- `docs/handoff/ONLYOFFICE-PROBE-RUNBOOK.md`
- `docs/handoff/ROADMAP-2026-08-14.md`
- `docs/handoff/SESSION-NOTE-2026-08-21-opencode-loffice.md`
- `docs/handoff/Top-40-MCP-Servers.md`
- `docs/handoff/UPDATE-RUNBOOK-2026-08-14.md`
- `docs/handoff/archive/CLAUDE-ARCHIVE-2026-07--08.md`

### Preserved interface mockups (10)

- `docs/mockups/2026-08-29/compose-a.html`
- `docs/mockups/2026-08-29/compose-b.html`
- `docs/mockups/2026-08-29/compose-c.html`
- `docs/mockups/2026-08-29/compose-d.html`
- `docs/mockups/2026-08-29/compose-f.html`
- `docs/mockups/2026-08-29/compose-g.html`
- `docs/mockups/2026-08-29/compose-h.html`
- `docs/mockups/2026-08-29/generate-f.html`
- `docs/mockups/2026-08-29/generate-g.html`
- `docs/mockups/2026-08-29/generate-h.html`

### Research corpus (including done files) (39)

- `docs/research/(done) 2026-08-14-omnivoice-provenance.md`
- `docs/research/(done) 2026-08-14-stt-and-starter-voices.md`
- `docs/research/(done) 2026-08-14-update-sweep.md`
- `docs/research/(done) 2026-08-20-model-settings.md`
- `docs/research/(done) 2026-08-20-repos-triage.md`
- `docs/research/2026-08-15-bargein-feasibility.md`
- `docs/research/2026-08-20-aider-recon.md`
- `docs/research/2026-08-20-hermesoffice-recon.md`
- `docs/research/2026-08-20-office-lane-recon.md`
- `docs/research/2026-08-20-unsloth-recon.md`
- `docs/research/2026-08-21-buzz-goose-recon.md`
- `docs/research/2026-08-21-office-alternatives-deep.md`
- `docs/research/2026-08-21-office-ui-reference.md`
- `docs/research/2026-08-21-opencode-omnigent-recon.md`
- `docs/research/2026-08-21-opencode-provider-wiring.md`
- `docs/research/2026-08-21-speech-to-speech.md`
- `docs/research/2026-08-28-adversarial-findings-live.md`
- `docs/research/2026-08-28-adversarial-findings-server.md`
- `docs/research/2026-08-28-bug-echo-sweep.md`
- `docs/research/2026-08-28-fit-math-oss.md`
- `docs/research/2026-08-28-gemini-research-verdict.md`
- `docs/research/2026-08-28-goose-source-verify.md`
- `docs/research/2026-08-28-macos-memory-accounting.md`
- `docs/research/2026-08-28-runner-flags-warmup-measurement.md`
- `docs/research/2026-08-28-s2s-m2-voicechat.md`
- `docs/research/2026-08-28-s2s-measurement.md`
- `docs/research/2026-08-28-update-audit.md`
- `docs/research/2026-08-29-api-adherence-audit.md`
- `docs/research/2026-08-29-comfyui-tab.md`
- `docs/research/2026-08-29-generate-page-redesign.md`
- `docs/research/2026-08-29-goose-desktop-ui.md`
- `docs/research/2026-08-29-isolation-mode.md`
- `docs/research/2026-08-29-opencode-phantom-sessions.md`
- `docs/research/2026-08-29-post-switch-audit.md`
- `docs/research/2026-08-29-surface-audit.md`
- `docs/research/2026-09-02-deepseek-harness.md`
- `docs/research/2026-09-03-flows-page-concept.md`
- `docs/research/2026-09-05-canonical-root-severance.md`
- `docs/research/2026-09-05-u79-aider-contract.md`

### Hermes guard and policy (5)

- `guards/harness-path-guard/README.md → guards/motdeck-path-guard/README.md`
- `guards/harness-path-guard/__init__.py → guards/motdeck-path-guard/__init__.py`
- `guards/harness-path-guard/plugin.yaml → guards/motdeck-path-guard/plugin.yaml`
- `guards/harness-path-guard/policy.yaml → guards/motdeck-path-guard/policy.yaml`
- `policies/routing.yaml`

### Lifecycle, installer, seeder, and migration scripts (44)

- `scripts/app_bundle_identity.sh`
- `scripts/bootstrap.sh`
- `scripts/build_app.sh`
- `scripts/doctor.sh`
- `scripts/ensure_bun.sh`
- `scripts/ensure_ffmpeg.sh`
- `scripts/ensure_node.sh`
- `scripts/fetch_vendor_assets.sh`
- `scripts/firstrun.sh`
- `scripts/firstrun_fat.sh`
- `scripts/flip_installed.py`
- `scripts/install_aider.sh`
- `scripts/install_component.sh`
- `scripts/install_deepseek.sh`
- `scripts/install_goose.sh`
- `scripts/install_goose_ui.sh`
- `scripts/install_llamacpp.sh`
- `scripts/install_mlx.sh`
- `scripts/install_music.sh`
- `scripts/install_onlyoffice.sh`
- `scripts/install_oo_ai_plugin.sh`
- `scripts/install_opencode.sh`
- `scripts/install_searxng.sh`
- `scripts/measure_music.sh`
- `scripts/merge_manifest.py`
- `scripts/migrate_jan_models.sh`
- `scripts/migrate_local_secrets.py`
- `scripts/migrate_motdeck_identity.py`
- `scripts/model_sources.py`
- `scripts/probe_onlyoffice.sh`
- `scripts/read_manifest.py`
- `scripts/repair_deepseek_profiles.py`
- `scripts/seed_deepseek_config.py`
- `scripts/seed_hermes_provider.py`
- `scripts/seed_odysseus_jan.py`
- `scripts/seed_opencode_config.py`
- `scripts/seed_registry.py`
- `scripts/ship.sh`
- `scripts/start.sh`
- `scripts/start_component.sh`
- `scripts/stop.sh`
- `scripts/sync_snapshot_identity.py`
- `scripts/test_hermes.sh`
- `scripts/verify.sh`

### Skills documentation (1)

- `skills/README.md`

## Release closure files

- `VERSION` advanced only after the clean candidate FAT build passed.
- `README.md`, `docs/ROADMAP.md`, `docs/UNFORGET.md`, this inventory, and the U150 spec received final version/verification evidence only after the real-stack release journey passed.

## Verified live closure

- `./scripts/ship.sh --restart hermes` shipped commit `50f28ef` from the canonical
  checkout. The supported gate passed 554 contracts (four explicit checkout-local
  Aider skips), 652 repository Python checks, all 44 JavaScript programs, all shell and
  Swift checks, and the byte/router ceilings.
- Snapshot parity passed for the six allowlisted repo-owned authoring files. The exact
  retired icon, two document filenames, and generated guard directory are absent; no
  recursive app/docs/skills/live-state cleanup occurred.
- Hermes has exactly one enabled `motdeck-path-guard`, no retired guard ID, and no old
  generated plug-in directory. The restarted dashboard and provider check passed.
- All 10 components are healthy. Manifest hash `8ae9d242…`, navigation hash
  `a0838afd…`, 11-model identity hash `a22bf653…`, runner pin/live model, optional Aux
  state, and all four protected-secret encoded fingerprints match the pre-migration
  capture.
- The installed bundle reports `MOT Deck` / `local.motdeck.app` / `MOTDeck`; its deep
  signature verifies. A fresh Direct Chat turn returned
  `MOT-DECK-U150-SHIPPED-OK` and survived Models → Chat, managed Odysseus entry reached
  the authenticated UI without a login form, Help contains no retired product label,
  and the sessions divider still exposes its 8 px `col-resize`/gold-hover affordance.

## Future audit procedure

1. Start from this mapping; never use an unreviewed global replacement.
2. Inventory source, tests, Help, roadmap, done/research files, bundle metadata, scripts, generated snapshot files, live state, preference domains, external managed configuration, and GitHub/repository identity separately.
3. Classify every surviving old literal as migration compatibility, upstream proper name, generic English, or historical evidence.
4. Prove exact live-state conservation before and after migration.
5. Mount the clean FAT DMG and inspect its volume, bundle, plist, executable, icon, seed manifest, and clean-tree stamp.
6. Walk the human entry points whose identity or persistence moved; automated HTTP health is not a substitute.
7. Advance the version and delete rollback artifacts only after all preceding evidence passes.
