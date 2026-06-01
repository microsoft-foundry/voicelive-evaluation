#!/usr/bin/env python3
"""
Unit tests for evaluation_agent naming functions.

Tests generate_eval_group_name, generate_run_name, _short_voice_name,
_sanitize_eval_name — mirrors evaluation_harness/tests/test_media_dataset.py
naming tests for cross-solution consistency.

Usage:
    python test_eval_naming.py
    python test_eval_naming.py --verbose
"""

import argparse
import os
import sys
import traceback
import types
from unittest.mock import MagicMock

# ── Mock heavy Azure SDK dependencies before importing function_app ──
# function_app.py imports these at module level; we only need the naming
# functions which have no Azure SDK dependencies.

for mod_name in [
    "azure.functions", "azure.durable_functions",
    "azure.identity", "azure.storage.blob", "azure.data.tables",
    "azure.ai.evaluation", "azure.ai.projects",
    "azure.ai.projects.models",
]:
    parts = mod_name.split(".")
    for i in range(len(parts)):
        partial = ".".join(parts[: i + 1])
        if partial not in sys.modules:
            sys.modules[partial] = MagicMock()

# Provide minimal stubs so module-level code doesn't crash
_func_mock = sys.modules["azure.functions"]
_func_mock.AuthLevel.ANONYMOUS = "anonymous"
_func_mock.AuthLevel.FUNCTION = "function"
_func_mock.FunctionApp.return_value = MagicMock()

# Add function app directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "deploy", "azure-functions"))

from function_app import (
    generate_eval_group_name,
    generate_run_name,
    _short_voice_name,
    _sanitize_eval_name,
    _settings_summary,
    _generate_eval_group_name_by_settings,
)


# ── Test infrastructure ──────────────────────────────────────────────

_results: list = []


def _run(name: str, fn):
    try:
        fn()
        _results.append((name, "PASS", ""))
        print(f"  [OK] {name}")
    except AssertionError as e:
        _results.append((name, "FAIL", str(e)))
        print(f"  [FAIL] {name}: {e}")
    except Exception as e:
        _results.append((name, "ERROR", str(e)))
        print(f"  [ERR] {name}: {e}")
        traceback.print_exc()


# ── _short_voice_name tests ──────────────────────────────────────────

def test_short_voice_simple():
    """Simple voice names pass through unchanged."""
    assert _short_voice_name("alloy") == "alloy"
    assert _short_voice_name("echo") == "echo"
    assert _short_voice_name("shimmer") == "shimmer"


def test_short_voice_azure_format():
    """Azure voice identifiers extract the name portion."""
    assert _short_voice_name("en-US-Ava:DragonHDLatestNeural") == "Ava"
    assert _short_voice_name("en-US-Andrew:DragonHDLatestNeural") == "Andrew"
    assert _short_voice_name("de-DE-Florian:DragonHDLatestNeural") == "Florian"


def test_short_voice_colon_no_locale():
    """Colon-separated but no locale prefix falls back to prefix."""
    assert _short_voice_name("CustomVoice:variant") == "CustomVoice"


def test_short_voice_empty():
    """Empty string returns empty."""
    assert _short_voice_name("") == ""


# ── _sanitize_eval_name tests ────────────────────────────────────────

def test_sanitize_basic():
    """Alphanumeric and underscores pass through."""
    assert _sanitize_eval_name("Eiffel_Tower_Visit_1") == "Eiffel_Tower_Visit_1"


def test_sanitize_special_chars():
    """Special characters replaced with underscores."""
    result = _sanitize_eval_name("test file (v2).jsonl")
    assert "(" not in result
    assert ")" not in result
    assert " " not in result


def test_sanitize_colons():
    """Colons (from Azure voice names) are sanitized."""
    result = _sanitize_eval_name("en-US-Ava:DragonHD")
    assert ":" not in result
    assert "en-US-Ava" in result


def test_sanitize_max_length():
    """Names are truncated to max_length."""
    long_name = "a" * 100
    result = _sanitize_eval_name(long_name, max_length=80)
    assert len(result) <= 80


def test_sanitize_empty():
    """Empty input returns 'unnamed'."""
    assert _sanitize_eval_name("") == "unnamed"


# ── generate_eval_group_name tests ───────────────────────────────────

def test_group_name_dataset_mode():
    """Default (dataset) mode uses dataset filename stem."""
    config = {"model": "gpt-realtime", "voice": "alloy"}
    name = generate_eval_group_name(config, dataset_name="datasets/Eiffel_Tower_Visit_1.jsonl")
    assert name == "Eiffel_Tower_Visit_1", f"Expected dataset stem: {name}"


def test_group_name_dataset_mode_nested_path():
    """Dataset mode works with nested paths."""
    config = {"model": "gpt-realtime", "voice": "alloy"}
    name = generate_eval_group_name(config, dataset_name="some/deep/path/my_dataset.jsonl")
    assert name == "my_dataset", f"Expected 'my_dataset': {name}"


def test_group_name_settings_mode():
    """Settings mode uses model/voice/vad/eod."""
    config = {
        "model": "gpt-realtime",
        "voice": "alloy",
        "vad_threshold": 0.6,
        "silence_duration_ms": 800,
    }
    name = generate_eval_group_name(config, group_by="settings")
    assert "gptrealtime" in name, f"Should contain model: {name}"
    assert "alloy" in name, f"Should contain voice: {name}"
    assert "0.6" in name, f"Should contain vad: {name}"
    assert "800" in name, f"Should contain eod: {name}"


def test_group_name_settings_mode_azure_voice():
    """Settings mode shortens Azure voice names."""
    config = {"model": "gpt-realtime", "voice": "en-US-Ava:DragonHDLatestNeural"}
    name = generate_eval_group_name(config, group_by="settings")
    assert "Ava" in name, f"Should shorten Azure voice: {name}"
    assert "DragonHD" not in name, f"Should not include full suffix: {name}"


def test_group_name_settings_mode_none_defaults():
    """Settings mode shows 'default' for None VAD/silence values."""
    config = {"model": "gpt-realtime", "voice": "alloy"}
    name = generate_eval_group_name(config, group_by="settings")
    assert "default" in name, f"None values should show as 'default': {name}"
    assert "None" not in name, f"Should not contain literal 'None': {name}"


def test_group_name_dataset_fallback():
    """Dataset mode falls back to settings when dataset_name is empty."""
    config = {"model": "gpt-4.1", "voice": "alloy"}
    name = generate_eval_group_name(config, dataset_name="")
    assert "gpt41" in name, f"Should fall back to settings: {name}"


def test_group_name_no_config():
    """No config produces default settings-based name."""
    name = generate_eval_group_name(None, group_by="settings")
    assert "gptrealtime" in name, f"Should use defaults: {name}"


# ── generate_run_name tests ──────────────────────────────────────────

def test_run_name_dataset_mode_shows_settings():
    """In dataset mode, run name highlights settings (not dataset)."""
    config = {"model": "gpt-realtime", "voice": "en-US-Ava:DragonHDLatestNeural"}
    evals = ["intent_resolution", "task_adherence", "task_completion",
             "response_completeness", "tool_call_accuracy", "tool_selection",
             "tool_input_accuracy", "tool_output_utilization"]
    run = generate_run_name("Eiffel_Tower.jsonl", "1", evals, session_config=config, group_by="dataset")
    assert "gptrealtime" in run, f"Should include model: {run}"
    assert "Ava" in run, f"Should include voice: {run}"


def test_run_name_settings_mode_shows_dataset():
    """In settings mode, run name highlights dataset (not settings)."""
    config = {"model": "gpt-realtime", "voice": "alloy"}
    evals = ["intent_resolution", "task_adherence"]
    run = generate_run_name("Eiffel_Tower.jsonl", "1", evals, session_config=config, group_by="settings")
    assert "Eiffel_Tower" in run, f"Should include dataset: {run}"
    assert "gptrealtime" not in run, f"Should NOT include model: {run}"


def test_run_name_eval_summary():
    """Evaluator count maps to correct summary label."""
    config = {"model": "gpt-realtime", "voice": "alloy"}
    # 8 evals = default
    run8 = generate_run_name("ds.jsonl", "1", ["e"] * 8, session_config=config)
    assert "default" in run8, f"8 evals should be 'default': {run8}"
    # 3 evals = subset
    run3 = generate_run_name("ds.jsonl", "1", ["e"] * 3, session_config=config)
    assert "subset" in run3, f"3 evals should be 'subset': {run3}"
    # 12 evals = all
    run12 = generate_run_name("ds.jsonl", "1", ["e"] * 12, session_config=config)
    assert "all" in run12, f"12 evals should be 'all': {run12}"


def test_run_name_no_config_dataset_mode():
    """Dataset mode without config still produces a valid run name."""
    run = generate_run_name("test.jsonl", "1", ["e1"], session_config=None, group_by="dataset")
    assert "test_v1" in run, f"Should fall back to dataset label: {run}"


# ── _settings_summary tests ─────────────────────────────────────────

def test_settings_summary_full():
    """Settings summary includes all present fields."""
    config = {"model": "gpt-realtime", "voice": "alloy", "vad_threshold": 0.5, "silence_duration_ms": 500}
    s = _settings_summary(config)
    assert "gptrealtime" in s
    assert "alloy" in s
    assert "vad0.5" in s
    assert "eod500" in s


def test_settings_summary_minimal():
    """Settings summary omits None vad/eod."""
    config = {"model": "gpt-realtime", "voice": "alloy"}
    s = _settings_summary(config)
    assert "gptrealtime" in s
    assert "alloy" in s
    assert "vad" not in s
    assert "eod" not in s


def test_settings_summary_none_config():
    """None config returns empty string."""
    assert _settings_summary(None) == ""


# ── Cross-solution consistency tests ─────────────────────────────────

def test_consistency_with_harness():
    """Agent naming functions produce structurally similar output to harness.

    The agent uses plain dicts (not SessionConfig dataclass), and does NOT
    add a 'harness_' prefix. Otherwise the naming logic should match.
    """
    config = {
        "model": "gpt-realtime",
        "voice": "en-US-Ava:DragonHDLatestNeural",
        "vad_threshold": 0.6,
        "silence_duration_ms": 800,
    }

    # Dataset mode
    ds_name = generate_eval_group_name(config, dataset_name="Eiffel_Tower_Visit_1.jsonl")
    assert ds_name == "Eiffel_Tower_Visit_1", f"Dataset mode: {ds_name}"

    # Settings mode
    st_name = generate_eval_group_name(config, group_by="settings")
    assert "gptrealtime" in st_name, f"Settings mode model: {st_name}"
    assert "Ava" in st_name, f"Settings mode voice: {st_name}"
    assert "0.6" in st_name, f"Settings mode vad: {st_name}"
    assert "800" in st_name, f"Settings mode eod: {st_name}"
    # Agent does NOT have harness_ prefix
    assert not st_name.startswith("harness_"), f"Agent should not have harness_ prefix: {st_name}"


# ── Main runner ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Unit tests for agent naming functions")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show failure details")
    args = parser.parse_args()

    print("\n== Evaluation Agent - Naming Function Unit Tests ==\n")

    print("  _short_voice_name:")
    _run("short_voice_simple", test_short_voice_simple)
    _run("short_voice_azure", test_short_voice_azure_format)
    _run("short_voice_colon_no_locale", test_short_voice_colon_no_locale)
    _run("short_voice_empty", test_short_voice_empty)

    print("\n  _sanitize_eval_name:")
    _run("sanitize_basic", test_sanitize_basic)
    _run("sanitize_special_chars", test_sanitize_special_chars)
    _run("sanitize_colons", test_sanitize_colons)
    _run("sanitize_max_length", test_sanitize_max_length)
    _run("sanitize_empty", test_sanitize_empty)

    print("\n  generate_eval_group_name:")
    _run("group_dataset_mode", test_group_name_dataset_mode)
    _run("group_dataset_nested", test_group_name_dataset_mode_nested_path)
    _run("group_settings_mode", test_group_name_settings_mode)
    _run("group_settings_azure_voice", test_group_name_settings_mode_azure_voice)
    _run("group_settings_none_defaults", test_group_name_settings_mode_none_defaults)
    _run("group_dataset_fallback", test_group_name_dataset_fallback)
    _run("group_no_config", test_group_name_no_config)

    print("\n  generate_run_name:")
    _run("run_dataset_shows_settings", test_run_name_dataset_mode_shows_settings)
    _run("run_settings_shows_dataset", test_run_name_settings_mode_shows_dataset)
    _run("run_eval_summary", test_run_name_eval_summary)
    _run("run_no_config_dataset", test_run_name_no_config_dataset_mode)

    print("\n  _settings_summary:")
    _run("summary_full", test_settings_summary_full)
    _run("summary_minimal", test_settings_summary_minimal)
    _run("summary_none", test_settings_summary_none_config)

    print("\n  cross-solution consistency:")
    _run("consistency_with_harness", test_consistency_with_harness)

    # Summary
    passed = sum(1 for _, s, _ in _results if s == "PASS")
    failed = sum(1 for _, s, _ in _results if s == "FAIL")
    errors = sum(1 for _, s, _ in _results if s == "ERROR")
    total = len(_results)

    print(f"\n{'=' * 60}")
    print(f"  Results: {passed}/{total} passed", end="")
    if failed:
        print(f", {failed} failed", end="")
    if errors:
        print(f", {errors} errors", end="")
    print()

    if args.verbose and (failed or errors):
        print("\n  Failures/Errors:")
        for name, status, detail in _results:
            if status in ("FAIL", "ERROR"):
                print(f"    {status} {name}: {detail}")

    print()
    sys.exit(0 if (failed + errors) == 0 else 1)


if __name__ == "__main__":
    main()
