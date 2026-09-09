"""Authoritative U95 manifest for legacy script-style test suites.

These files deliberately execute their assertions at module scope and report one
process exit code.  Importing them into pytest turns a successful ``SystemExit(0)``
into a collection failure; merely adding ``if __name__ == '__main__'`` would collect
zero tests and silently delete their coverage. The collection adapter in ``conftest.py``
instead executes every entry as an isolated subprocess and exposes one honest pytest
item per suite. This is suite-level pytest integration, not a claim that every internal
assertion was rewritten as a native pytest item. The companion completeness test
rejects an unlisted collection failure.
"""

STANDALONE_SUITES = (
    "test_api_keys.py",
    "test_app_facade.py",
    "test_artifact_save.py",
    "test_audio_registry.py",
    "test_audio_search.py",
    "test_bug_echo_ledger.py",
    "test_caps_map.py",
    "test_comfy_lane.py",
    "test_download_verify.py",
    "test_events_hub.py",
    "test_fit_advisor.py",
    "test_hermes_cfg_gen.py",
    "test_hermes_max_turn.py",
    "test_hermes_sessions.py",
    "test_hermes_skills.py",
    "test_hermes_sse_map.py",
    "test_hermes_toolsets.py",
    "test_image_sidecar.py",
    "test_load_switch.py",
    "test_model_delete.py",
    "test_model_load.py",
    "test_model_settings.py",
    "test_msg_actions.py",
    "test_mtp_detect.py",
    "test_music_lane.py",
    "test_ody_vlshim.py",
    "test_office_adversarial.py",
    "test_office_journey.py",
    "test_office_lane.py",
    "test_office_mcp.py",
    "test_office_types.py",
    "test_oo_ai_lane.py",
    "test_oo_lane.py",
    "test_ops_hardening.py",
    "test_parakeet_stt.py",
    "test_path_guard.py",
    "test_port_kill.py",
    "test_script_hygiene.py",
    "test_starter_voices.py",
    "test_thinking_sidecar.py",
    "test_vision_content.py",
    "test_voice_cache.py",
    "test_voice_mcp.py",
    "test_voice_ref.py",
    "test_voice_stt.py",
    "test_voice_tts.py",
    "test_voice_worker.py",
)
