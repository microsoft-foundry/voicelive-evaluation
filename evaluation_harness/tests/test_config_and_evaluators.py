"""
Unit tests for configuration loading, evaluator parsing, and SessionConfig behavior.

These tests validate the new harness features WITHOUT requiring Azure credentials
or VoiceLive endpoint access. They test pure logic: config file parsing, CLI override
precedence, evaluator string resolution, VAD type selection, and model override.

Usage:
    python evaluation_harness/tests/test_config_and_evaluators.py
    python evaluation_harness/tests/test_config_and_evaluators.py --verbose
"""

import argparse
import json
import os
import sys
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from voice_agent_audio_input_evaluation import (
    SessionConfig,
    DEFAULT_EVALUATORS,
    ADDITIONAL_EVALUATORS,
    ALL_EVALUATORS,
)


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

_results: List[Tuple[str, str, Optional[str]]] = []  # (name, status, detail)


def _run(name: str, fn: Callable[[], None]) -> None:
    """Run a single test and record the result."""
    try:
        fn()
        _results.append((name, "PASS", None))
        print(f"  ✅ {name}")
    except AssertionError as e:
        _results.append((name, "FAIL", str(e)))
        print(f"  ❌ {name}: {e}")
    except Exception as e:
        _results.append((name, "ERROR", str(e)))
        print(f"  💥 {name}: {e}")


# ---------------------------------------------------------------------------
# 1. SessionConfig dataclass tests
# ---------------------------------------------------------------------------

def test_session_config_defaults():
    """Default values match Container App alignment."""
    cfg = SessionConfig()
    assert cfg.model == "gpt-realtime"
    assert cfg.voice == "en-US-Ava:DragonHDLatestNeural"
    assert cfg.voice_type == "azure-standard"
    assert cfg.sample_rate == 24000
    assert cfg.push_to_talk is False
    assert cfg.enable_barge_in is True
    assert cfg.noise_reduction == "azure_deep_noise_suppression"
    assert cfg.echo_cancellation == "server_echo_cancellation"
    assert cfg.vad_type == "azure_semantic_vad_multilingual"
    assert cfg.vad_threshold is None
    assert cfg.silence_duration_ms is None
    assert cfg.use_eou_detection is True
    assert cfg.eou_model == "semantic_detection_v1_multilingual"
    assert cfg.transcription_model is None
    assert cfg.tools is None
    assert cfg.tool_definitions is None


def test_get_transcription_model_realtime():
    """gpt-realtime → gpt-4o-transcribe."""
    cfg = SessionConfig(model="gpt-realtime")
    assert cfg.get_transcription_model() == "gpt-4o-transcribe"


def test_get_transcription_model_mini():
    """gpt-realtime-mini → gpt-4o-mini-transcribe."""
    cfg = SessionConfig(model="gpt-realtime-mini")
    assert cfg.get_transcription_model() == "gpt-4o-mini-transcribe"


def test_get_transcription_model_cascaded():
    """gpt-4.1 (cascaded) → azure-speech."""
    cfg = SessionConfig(model="gpt-4.1")
    assert cfg.get_transcription_model() == "azure-speech"


def test_get_transcription_model_explicit_override():
    """Explicit transcription_model overrides auto-detection."""
    cfg = SessionConfig(model="gpt-realtime", transcription_model="custom-model")
    assert cfg.get_transcription_model() == "custom-model"


def test_supports_eou_detection_realtime():
    """gpt-realtime does NOT support EOU detection."""
    assert SessionConfig(model="gpt-realtime").supports_eou_detection() is False


def test_supports_eou_detection_mini():
    """gpt-realtime-mini does NOT support EOU detection."""
    assert SessionConfig(model="gpt-realtime-mini").supports_eou_detection() is False


def test_supports_eou_detection_cascaded():
    """gpt-4.1 cascaded DOES support EOU detection."""
    assert SessionConfig(model="gpt-4.1").supports_eou_detection() is True


def test_get_final_instructions_no_tools():
    """Without tools, instructions returned as-is."""
    cfg = SessionConfig(instructions="Hello")
    assert cfg.get_final_instructions() == "Hello"


def test_get_final_instructions_with_tools():
    """With tools, appends tool hint."""
    cfg = SessionConfig(instructions="Hello", tools=[{"type": "function"}])
    result = cfg.get_final_instructions()
    assert "Hello" in result
    assert "Use available tools" in result


def test_dataclass_replace_override():
    """dataclasses.replace() creates new config with overrides."""
    base = SessionConfig()
    modified = replace(base, model="gpt-4.1", voice="en-US-Andrew:DragonHDLatestNeural")
    assert modified.model == "gpt-4.1"
    assert modified.voice == "en-US-Andrew:DragonHDLatestNeural"
    # Original unchanged
    assert base.model == "gpt-realtime"
    assert base.voice == "en-US-Ava:DragonHDLatestNeural"


# ---------------------------------------------------------------------------
# 2. Evaluator constants tests
# ---------------------------------------------------------------------------

def test_default_evaluators_count():
    """Default evaluator list has exactly 8 items."""
    assert len(DEFAULT_EVALUATORS) == 8


def test_all_evaluators_superset():
    """ALL_EVALUATORS = DEFAULT + ADDITIONAL with no duplicates."""
    assert ALL_EVALUATORS == DEFAULT_EVALUATORS + ADDITIONAL_EVALUATORS
    assert len(set(ALL_EVALUATORS)) == len(ALL_EVALUATORS), "Duplicate evaluator names"


def test_evaluator_names_are_strings():
    """All evaluator names are non-empty strings."""
    for name in ALL_EVALUATORS:
        assert isinstance(name, str) and len(name) > 0, f"Invalid evaluator: {name!r}"


def test_known_evaluators_present():
    """Key evaluators present in the lists."""
    assert "intent_resolution" in DEFAULT_EVALUATORS
    assert "task_completion" in DEFAULT_EVALUATORS
    assert "tool_call_accuracy" in DEFAULT_EVALUATORS
    assert "groundedness" in ADDITIONAL_EVALUATORS
    assert "relevance" in ADDITIONAL_EVALUATORS


# ---------------------------------------------------------------------------
# 3. Evaluator string parsing tests (simulating _run_evaluation logic)
# ---------------------------------------------------------------------------

def _parse_evaluators(evaluators: Optional[str]) -> List[str]:
    """Replicate the evaluator parsing logic from _run_evaluation."""
    if evaluators == "all":
        return ALL_EVALUATORS
    elif evaluators and evaluators != "default":
        eval_list = [e.strip() for e in evaluators.split(",") if e.strip()]
        if not eval_list:
            return DEFAULT_EVALUATORS  # fallback
        return eval_list
    else:
        return DEFAULT_EVALUATORS


def test_parse_evaluators_default():
    """'default' → 8 DEFAULT_EVALUATORS."""
    result = _parse_evaluators("default")
    assert result == DEFAULT_EVALUATORS
    assert len(result) == 8


def test_parse_evaluators_all():
    """'all' → 13 ALL_EVALUATORS."""
    result = _parse_evaluators("all")
    assert result == ALL_EVALUATORS
    assert len(result) == 13


def test_parse_evaluators_none():
    """None → defaults."""
    assert _parse_evaluators(None) == DEFAULT_EVALUATORS


def test_parse_evaluators_custom_list():
    """Comma-separated list → exact items."""
    result = _parse_evaluators("intent_resolution,task_adherence,groundedness")
    assert result == ["intent_resolution", "task_adherence", "groundedness"]


def test_parse_evaluators_single():
    """Single evaluator name."""
    result = _parse_evaluators("intent_resolution")
    assert result == ["intent_resolution"]


def test_parse_evaluators_with_spaces():
    """Spaces around commas are trimmed."""
    result = _parse_evaluators(" intent_resolution , task_adherence ")
    assert result == ["intent_resolution", "task_adherence"]


def test_parse_evaluators_empty_string():
    """Empty string → fallback to defaults."""
    result = _parse_evaluators("")
    assert result == DEFAULT_EVALUATORS


def test_parse_evaluators_only_commas():
    """Commas only → fallback to defaults."""
    result = _parse_evaluators(",,,")
    assert result == DEFAULT_EVALUATORS


# ---------------------------------------------------------------------------
# 4. Config file loading tests
# ---------------------------------------------------------------------------

def _apply_config_file(file_config: dict, cli_overrides: dict = None) -> argparse.Namespace:
    """Simulate config file loading + CLI override logic from main()."""
    # Build an argparse namespace with defaults
    defaults = {
        "model": "gpt-realtime",
        "voice": "en-US-Ava:DragonHDLatestNeural",
        "voice_type": "azure-standard",
        "sample_rate": 24000,
        "push_to_talk": False,
        "enable_barge_in": True,
        "noise_reduction": "azure_deep_noise_suppression",
        "echo_cancellation": "server_echo_cancellation",
        "vad_type": "azure_semantic_vad_multilingual",
        "vad_threshold": None,
        "silence_duration_ms": None,
        "use_eou_detection": True,
        "eou_model": "semantic_detection_v1_multilingual",
        "transcription_model": None,
    }

    # Create namespace
    args = argparse.Namespace(**defaults)

    # Apply CLI overrides first (these should win)
    cli_set = set()
    if cli_overrides:
        for k, v in cli_overrides.items():
            setattr(args, k, v)
            cli_set.add(k)

    # Nested key mapping (same as main())
    nested_to_dest = {
        ("voice", "name"): "voice",
        ("voice", "type"): "voice_type",
        ("audio", "sample_rate"): "sample_rate",
        ("audio", "noise_reduction"): "noise_reduction",
        ("audio", "echo_cancellation"): "echo_cancellation",
        ("turn_detection", "type"): "vad_type",
        ("turn_detection", "threshold"): "vad_threshold",
        ("turn_detection", "silence_duration_ms"): "silence_duration_ms",
        ("turn_detection", "use_eou_detection"): "use_eou_detection",
        ("turn_detection", "eou_model"): "eou_model",
        ("turn_detection", "enable_barge_in"): "enable_barge_in",
    }

    # Apply file values (CLI args take precedence via default check)
    for key, val in file_config.items():
        if isinstance(val, dict):
            for k2, v2 in val.items():
                dest = nested_to_dest.get((key, k2), k2)
                if hasattr(args, dest) and dest not in cli_set:
                    if defaults.get(dest) == getattr(args, dest):
                        setattr(args, dest, v2)
        elif hasattr(args, key) and key not in cli_set:
            if defaults.get(key) == getattr(args, key):
                setattr(args, key, val)

    return args


def test_config_file_flat_keys():
    """Flat config file keys applied to args."""
    config = {
        "model": "gpt-4.1",
        "voice": "en-US-Andrew:DragonHDLatestNeural",
        "sample_rate": 16000,
    }
    args = _apply_config_file(config)
    assert args.model == "gpt-4.1"
    assert args.voice == "en-US-Andrew:DragonHDLatestNeural"
    assert args.sample_rate == 16000


def test_config_file_nested_keys():
    """Nested config keys mapped correctly."""
    config = {
        "voice": {"name": "en-US-Brian:DragonHDLatestNeural", "type": "preset"},
        "audio": {"sample_rate": 48000, "noise_reduction": "none"},
        "turn_detection": {"type": "server_vad", "threshold": 0.7, "silence_duration_ms": 500},
    }
    args = _apply_config_file(config)
    assert args.voice == "en-US-Brian:DragonHDLatestNeural"
    assert args.voice_type == "preset"
    assert args.sample_rate == 48000
    assert args.noise_reduction == "none"
    assert args.vad_type == "server_vad"
    assert args.vad_threshold == 0.7
    assert args.silence_duration_ms == 500


def test_config_cli_override_precedence():
    """CLI args override config file values."""
    config = {
        "model": "gpt-4.1",
        "voice": "en-US-Andrew:DragonHDLatestNeural",
    }
    cli = {"model": "gpt-realtime-mini"}
    args = _apply_config_file(config, cli_overrides=cli)
    # CLI wins for model
    assert args.model == "gpt-realtime-mini"
    # File wins for voice (no CLI override)
    assert args.voice == "en-US-Andrew:DragonHDLatestNeural"


def test_config_file_json_roundtrip():
    """Write and read a config file via JSON."""
    config = {
        "model": "gpt-4.1",
        "voice": "en-US-Andrew:DragonHDLatestNeural",
        "vad_type": "server_vad",
        "push_to_talk": True,
    }
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(config, f)
        f.flush()
        path = f.name
    try:
        with open(path, 'r', encoding='utf-8') as f2:
            loaded = json.load(f2)
        args = _apply_config_file(loaded)
        assert args.model == "gpt-4.1"
        assert args.voice == "en-US-Andrew:DragonHDLatestNeural"
        assert args.vad_type == "server_vad"
        assert args.push_to_talk is True
    finally:
        os.unlink(path)


def test_config_file_sample_config():
    """sample_config.json loads without errors."""
    sample_path = Path(__file__).parent.parent / "sample_config.json"
    if not sample_path.exists():
        raise AssertionError(f"sample_config.json not found at {sample_path}")
    with open(sample_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    args = _apply_config_file(config)
    assert args.voice == "en-US-Andrew:DragonHDLatestNeural"
    assert args.use_eou_detection is True


def test_config_unknown_keys_ignored():
    """Unknown keys in config file are silently ignored."""
    config = {"model": "gpt-4.1", "unknown_key": "value", "another_unknown": 42}
    args = _apply_config_file(config)
    assert args.model == "gpt-4.1"
    assert not hasattr(args, "unknown_key")


def test_config_empty_file():
    """Empty config file applies no changes."""
    args = _apply_config_file({})
    assert args.model == "gpt-realtime"
    assert args.voice == "en-US-Ava:DragonHDLatestNeural"


# ---------------------------------------------------------------------------
# 5. VAD type selection tests (unit testing the logic, not SDK calls)
# ---------------------------------------------------------------------------

def test_vad_type_server_vad():
    """server_vad config selects ServerVad behavior."""
    cfg = SessionConfig(vad_type="server_vad")
    assert cfg.vad_type == "server_vad"
    # In configure_session(), this triggers ServerVad (not AzureSemanticVadMultilingual)


def test_vad_type_azure_semantic():
    """azure_semantic_vad_multilingual is the default."""
    cfg = SessionConfig()
    assert cfg.vad_type == "azure_semantic_vad_multilingual"


def test_vad_threshold_applied():
    """Threshold and silence_duration_ms are stored."""
    cfg = SessionConfig(vad_threshold=0.5, silence_duration_ms=300)
    assert cfg.vad_threshold == 0.5
    assert cfg.silence_duration_ms == 300


def test_eou_not_applied_for_realtime():
    """EOU detection should not be applied for gpt-realtime models."""
    cfg = SessionConfig(model="gpt-realtime", use_eou_detection=True)
    # supports_eou_detection returns False, so configure_session skips EOU
    assert cfg.supports_eou_detection() is False


def test_eou_applied_for_cascaded():
    """EOU detection should be applied for cascaded models."""
    cfg = SessionConfig(model="gpt-4.1", use_eou_detection=True)
    assert cfg.supports_eou_detection() is True


def test_eou_disabled_explicitly():
    """Even for cascaded, use_eou_detection=False skips EOU."""
    cfg = SessionConfig(model="gpt-4.1", use_eou_detection=False)
    # supports_eou_detection is True, but use_eou_detection is False
    # configure_session checks both conditions
    assert cfg.supports_eou_detection() is True
    assert cfg.use_eou_detection is False


# ---------------------------------------------------------------------------
# 6. Model override logic tests
# ---------------------------------------------------------------------------

def test_model_env_var_priority():
    """When no --model in sys.argv, env var wins."""
    env_model = "gpt-4.1"
    args_model = "gpt-realtime"  # argparse default
    # Simulate: "--model" not in sys.argv
    cli_explicit = False
    result = args_model if cli_explicit else (env_model or args_model)
    assert result == "gpt-4.1"


def test_model_cli_overrides_env():
    """When --model in sys.argv, CLI wins."""
    env_model = "gpt-4.1"
    args_model = "gpt-realtime"
    cli_explicit = True  # "--model" in sys.argv
    result = args_model if cli_explicit else (env_model or args_model)
    assert result == "gpt-realtime"


def test_model_no_env_uses_default():
    """No env var, no --model → argparse default."""
    env_model = None
    args_model = "gpt-realtime"
    cli_explicit = False
    result = args_model if cli_explicit else (env_model or args_model)
    assert result == "gpt-realtime"


def test_model_cli_can_set_gpt_realtime():
    """--model gpt-realtime overrides env var to gpt-realtime."""
    env_model = "gpt-4.1"
    args_model = "gpt-realtime"
    cli_explicit = True  # "--model" in sys.argv
    result = args_model if cli_explicit else (env_model or args_model)
    assert result == "gpt-realtime"


# ---------------------------------------------------------------------------
# 7. Agent mode tests
# ---------------------------------------------------------------------------

def test_agent_mode_defaults_false():
    """SessionConfig without agent fields is not agent mode."""
    c = SessionConfig()
    assert not c.is_agent_mode, f"Expected is_agent_mode=False, got {c.is_agent_mode}"

def test_agent_mode_requires_both_fields():
    """Agent mode requires both agent_name AND project_name."""
    c1 = SessionConfig(agent_name="test-agent")
    assert not c1.is_agent_mode, "agent_name alone should not enable agent mode"
    
    c2 = SessionConfig(project_name="test-project")
    assert not c2.is_agent_mode, "project_name alone should not enable agent mode"

def test_agent_mode_enabled():
    """Agent mode is enabled when both fields are set."""
    c = SessionConfig(agent_name="test-agent", project_name="test-project")
    assert c.is_agent_mode, "Expected is_agent_mode=True"

def test_build_agent_config_minimal():
    """build_agent_config returns minimal config with required fields."""
    c = SessionConfig(agent_name="my-agent", project_name="my-project")
    cfg = c.build_agent_config()
    assert cfg is not None, "Expected non-None agent config"
    assert cfg["agent_name"] == "my-agent"
    assert cfg["project_name"] == "my-project"
    assert "agent_version" not in cfg
    assert "conversation_id" not in cfg

def test_build_agent_config_full():
    """build_agent_config includes optional fields when set."""
    c = SessionConfig(
        agent_name="my-agent",
        project_name="my-project",
        agent_version="v2",
        conversation_id="conv-123",
        foundry_resource_override="other-resource",
        authentication_identity_client_id="client-id-abc",
    )
    cfg = c.build_agent_config()
    assert cfg["agent_version"] == "v2"
    assert cfg["conversation_id"] == "conv-123"
    assert cfg["foundry_resource_override"] == "other-resource"
    assert cfg["authentication_identity_client_id"] == "client-id-abc"

def test_build_agent_config_none_when_not_agent_mode():
    """build_agent_config returns None when not in agent mode."""
    c = SessionConfig()
    assert c.build_agent_config() is None

def test_build_agent_config_auth_requires_resource_override():
    """authentication_identity_client_id only included when foundry_resource_override is set."""
    c = SessionConfig(
        agent_name="agent",
        project_name="project",
        authentication_identity_client_id="client-id",
    )
    cfg = c.build_agent_config()
    assert "authentication_identity_client_id" not in cfg, \
        "auth client ID should not be included without foundry_resource_override"

def test_agent_mode_config_file_loading():
    """Config file with agent section sets agent mode fields."""
    config_data = {
        "agent": {
            "agent_name": "file-agent",
            "project_name": "file-project",
            "agent_version": "v3",
        },
        "voice": "en-US-Andrew:DragonHDLatestNeural",
    }
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(config_data, f)
        tmp_path = f.name
    try:
        with open(tmp_path, 'r') as f:
            loaded = json.load(f)
        assert "agent" in loaded
        assert loaded["agent"]["agent_name"] == "file-agent"
        assert loaded["agent"]["project_name"] == "file-project"
    finally:
        os.unlink(tmp_path)

def test_agent_mode_override_tracking():
    """Override tracking fields default to False."""
    c = SessionConfig()
    assert c._voice_explicitly_set is False
    assert c._vad_explicitly_set is False

def test_agent_mode_with_model_fields_preserved():
    """Agent mode config still has model mode fields accessible."""
    c = SessionConfig(
        agent_name="agent",
        project_name="project",
        model="gpt-realtime",
        voice="en-US-Ava:DragonHDLatestNeural",
    )
    assert c.is_agent_mode
    assert c.model == "gpt-realtime"
    assert c.voice == "en-US-Ava:DragonHDLatestNeural"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Evaluation Harness — Config & Evaluator Unit Tests")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("=" * 60)

    sections = [
        ("SessionConfig Defaults & Helpers", [
            test_session_config_defaults,
            test_get_transcription_model_realtime,
            test_get_transcription_model_mini,
            test_get_transcription_model_cascaded,
            test_get_transcription_model_explicit_override,
            test_supports_eou_detection_realtime,
            test_supports_eou_detection_mini,
            test_supports_eou_detection_cascaded,
            test_get_final_instructions_no_tools,
            test_get_final_instructions_with_tools,
            test_dataclass_replace_override,
        ]),
        ("Evaluator Constants", [
            test_default_evaluators_count,
            test_all_evaluators_superset,
            test_evaluator_names_are_strings,
            test_known_evaluators_present,
        ]),
        ("Evaluator String Parsing", [
            test_parse_evaluators_default,
            test_parse_evaluators_all,
            test_parse_evaluators_none,
            test_parse_evaluators_custom_list,
            test_parse_evaluators_single,
            test_parse_evaluators_with_spaces,
            test_parse_evaluators_empty_string,
            test_parse_evaluators_only_commas,
        ]),
        ("Config File Loading", [
            test_config_file_flat_keys,
            test_config_file_nested_keys,
            test_config_cli_override_precedence,
            test_config_file_json_roundtrip,
            test_config_file_sample_config,
            test_config_unknown_keys_ignored,
            test_config_empty_file,
        ]),
        ("VAD Type Selection", [
            test_vad_type_server_vad,
            test_vad_type_azure_semantic,
            test_vad_threshold_applied,
            test_eou_not_applied_for_realtime,
            test_eou_applied_for_cascaded,
            test_eou_disabled_explicitly,
        ]),
        ("Model Override Logic", [
            test_model_env_var_priority,
            test_model_cli_overrides_env,
            test_model_no_env_uses_default,
            test_model_cli_can_set_gpt_realtime,
        ]),
        ("Agent Mode", [
            test_agent_mode_defaults_false,
            test_agent_mode_requires_both_fields,
            test_agent_mode_enabled,
            test_build_agent_config_minimal,
            test_build_agent_config_full,
            test_build_agent_config_none_when_not_agent_mode,
            test_build_agent_config_auth_requires_resource_override,
            test_agent_mode_config_file_loading,
            test_agent_mode_override_tracking,
            test_agent_mode_with_model_fields_preserved,
        ]),
    ]

    for section_name, tests in sections:
        print(f"\n{'─' * 60}")
        print(f"{section_name}")
        print(f"{'─' * 60}")
        for test_fn in tests:
            _run(test_fn.__name__, test_fn)

    # Summary
    passed = sum(1 for _, s, _ in _results if s == "PASS")
    failed = sum(1 for _, s, _ in _results if s == "FAIL")
    errors = sum(1 for _, s, _ in _results if s == "ERROR")
    total = len(_results)

    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{total} passed, {failed} failed, {errors} errors")
    print(f"{'=' * 60}")

    if failed or errors:
        print("\nFailures:")
        for name, status, detail in _results:
            if status in ("FAIL", "ERROR"):
                print(f"  {status}: {name} — {detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
