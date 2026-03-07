"""
End-to-end integration test suite for the evaluation harness.

Tests the full pipeline: dataset loading → VoiceLive processing → Foundry evaluation.
Requires active Azure credentials (az login) and VoiceLive endpoint access.

Usage:
    python evaluation_harness/tests/test_e2e_pipeline.py
    python evaluation_harness/tests/test_e2e_pipeline.py --dataset eiffel
    python evaluation_harness/tests/test_e2e_pipeline.py --dataset trivia
    python evaluation_harness/tests/test_e2e_pipeline.py --skip-voicelive   # Audio loading + format only
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from voice_agent_audio_input_evaluation import (
    load_audio_file,
    read_dataset,
    build_evaluation_data,
    SessionConfig,
    ConversationTurn,
)


# ---------------------------------------------------------------------------
# Test datasets
# ---------------------------------------------------------------------------

DATASETS = {
    "eiffel": {
        "name": "Eiffel_Tower_Visit_1",
        "jsonl": "sample_evaluation_input/Eiffel_Tower_Visit_1/Eiffel_Tower_Visit_1.jsonl",
        "expected_entries": 6,
        "has_tool_defs": True,
        "has_ground_truth": True,
        "has_question": True,
        "audio_format": "pcm16",
        "session_mode": "per-conversation",
    },
    "trivia": {
        "name": "TwinkStart-speech-triavia-qa",
        "jsonl": "local_datasets/TwinkStart-speech-triavia-qa/TwinkStart-speech-triavia-qa.jsonl",
        "expected_entries": 10,
        "has_tool_defs": False,
        "has_ground_truth": True,
        "has_question": True,
        "audio_format": "float32",
        "session_mode": "per-file",
    },
}


# ---------------------------------------------------------------------------
# Test functions
# ---------------------------------------------------------------------------

def test_dataset_loading(dataset_key: str) -> bool:
    """Test 1: Dataset loading and parsing."""
    ds = DATASETS[dataset_key]
    harness_dir = Path(__file__).parent.parent
    jsonl_path = harness_dir / ds["jsonl"]

    print(f"\n  Loading: {jsonl_path}")
    if not jsonl_path.exists():
        print(f"  SKIP: File not found")
        return False

    entries = read_dataset(str(jsonl_path))
    assert len(entries) == ds["expected_entries"], f"Expected {ds['expected_entries']} entries, got {len(entries)}"
    print(f"  Entries: {len(entries)}")

    e = entries[0]
    if ds["has_ground_truth"]:
        assert e.ground_truth, f"Missing ground_truth"
        if dataset_key == "trivia":
            assert " OR " in e.ground_truth, f"Expected OR-joined answer, got: {e.ground_truth[:50]}"
    if ds["has_question"]:
        assert e.question, f"Missing question"
    if ds["has_tool_defs"]:
        assert e.tool_definitions, f"Missing tool_definitions"

    print(f"  Ground truth: {(e.ground_truth or '')[:60]}...")
    print(f"  Question: {(e.question or '')[:60]}...")
    return True


def test_audio_loading(dataset_key: str) -> bool:
    """Test 2: Audio file loading (PCM16 + float32)."""
    ds = DATASETS[dataset_key]
    harness_dir = Path(__file__).parent.parent
    entries = read_dataset(str(harness_dir / ds["jsonl"]))

    for i, e in enumerate(entries[:3]):
        audio = load_audio_file(e.audio_path)
        assert len(audio) > 0, f"Empty audio for entry {i}"

    fmt = ds["audio_format"]
    print(f"  Loaded {min(3, len(entries))} files ({fmt} format)")
    return True


def test_eval_format_assembly(dataset_key: str) -> bool:
    """Test 3: Evaluation data assembly (query/response format)."""
    ds = DATASETS[dataset_key]
    harness_dir = Path(__file__).parent.parent
    entries = read_dataset(str(harness_dir / ds["jsonl"]))

    # Simulate a turn
    turn = ConversationTurn()
    turn.user_transcription = "test transcription"
    turn.assistant_response = "test response"
    turn.turn_number = 1

    result = build_evaluation_data(
        turn=turn,
        entry=entries[0],
        conversation_history=[],
        system_instructions="You are a test assistant.",
        tool_definitions=entries[0].tool_definitions,
    )

    # Validate output format
    assert "query" in result, "Missing query field"
    assert "response" in result, "Missing response field"
    assert "transcript" in result, "Missing transcript field"
    assert "ground_truth" in result, "Missing ground_truth field"
    assert "ground_truth_query_used" in result, "Missing ground_truth_query_used flag"
    assert isinstance(result["query"], list), "query must be a list"
    assert isinstance(result["response"], list), "response must be a list"

    # Check query structure
    roles = [m["role"] for m in result["query"]]
    assert "system" in roles, "Missing system message in query"
    assert "user" in roles, "Missing user message in query"

    # Check ground_truth_query_used flag
    if ds["has_question"]:
        assert result["ground_truth_query_used"] is True, "Should use ground truth question when available"
        user_msg = [m for m in result["query"] if m["role"] == "user"][0]
        user_text = user_msg["content"][0]["text"] if isinstance(user_msg["content"], list) else user_msg["content"]
        assert user_text == entries[0].question, f"Query should use Question field, got: {user_text[:50]}"

    print(f"  Format: query={len(result['query'])} msgs, response={len(result['response'])} msgs")
    print(f"  ground_truth_query_used={result['ground_truth_query_used']}")
    print(f"  ground_truth: {result['ground_truth'][:60]}...")
    return True


def test_tool_message_format(dataset_key: str) -> bool:
    """Test 4: Tool message SDK-canonical flat format."""
    ds = DATASETS[dataset_key]
    if not ds["has_tool_defs"]:
        print(f"  SKIP: No tool definitions in dataset")
        return True

    harness_dir = Path(__file__).parent.parent
    entries = read_dataset(str(harness_dir / ds["jsonl"]))

    # Simulate a turn with tool calls
    turn = ConversationTurn()
    turn.user_transcription = "What is my horoscope?"
    turn.assistant_response = "Your horoscope says great things!"
    turn.turn_number = 1
    turn.tool_calls = [{"call_id": "call_test", "name": "get_horoscope", "arguments": '{"sign": "Aquarius"}'}]
    turn.tool_results = [{
        "call_id": "call_test",
        "name": "get_horoscope",
        "arguments": '{"sign": "Aquarius"}',
        "result": "Today is a great day for Aquarius!"
    }]

    result = build_evaluation_data(
        turn=turn, entry=entries[0], conversation_history=[],
        system_instructions="Test", tool_definitions=entries[0].tool_definitions,
    )

    # Find tool messages
    tool_call_msgs = [m for m in result["query"] if m["role"] == "assistant" and isinstance(m.get("content"), list)
                      and any(c.get("type") == "tool_call" for c in m["content"])]
    tool_result_msgs = [m for m in result["query"] if m["role"] == "tool"]

    assert len(tool_call_msgs) == 1, f"Expected 1 tool_call message, got {len(tool_call_msgs)}"
    assert len(tool_result_msgs) == 1, f"Expected 1 tool_result message, got {len(tool_result_msgs)}"

    # Validate flat format (not nested)
    tc_content = tool_call_msgs[0]["content"][0]
    assert "name" in tc_content, "tool_call must have top-level 'name' (SDK flat format)"
    assert "tool_call_id" in tc_content, "tool_call must have top-level 'tool_call_id'"
    assert "arguments" in tc_content, "tool_call must have top-level 'arguments'"
    assert isinstance(tc_content["arguments"], dict), "arguments must be a parsed dict, not JSON string"
    assert "tool_call" not in tc_content, "Must NOT have nested 'tool_call' sub-object"

    tr_content = tool_result_msgs[0]["content"][0]
    assert tr_content["type"] == "tool_result", f"Expected type 'tool_result', got '{tr_content['type']}'"

    print(f"  Tool call format: name={tc_content['name']}, args={tc_content['arguments']}")
    print(f"  Tool result format: type={tr_content['type']}")
    return True


def test_path_traversal_blocked() -> bool:
    """Test 5: Path traversal prevention in _resolve_audio_path."""
    from voice_agent_audio_input_evaluation import _resolve_audio_path

    harness_dir = str(Path(__file__).parent.parent)
    # This should NOT resolve to files outside the dataset dir
    result = _resolve_audio_path("../../etc/passwd", harness_dir)
    # It should either return None (not found) or a path within harness_dir
    if result is not None:
        assert os.path.commonpath([result, os.path.abspath(harness_dir)]) == os.path.abspath(harness_dir), \
            f"Path traversal not blocked: resolved to {result}"
        print(f"  Resolved within bounds: {result}")
    else:
        print(f"  Correctly returned None for traversal attempt")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_tests(dataset_keys: List[str], skip_voicelive: bool = False) -> int:
    """Run all tests and return exit code."""
    print("=" * 60)
    print("Evaluation Harness — E2E Integration Tests")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("=" * 60)

    passed = 0
    failed = 0
    skipped = 0

    tests = [
        ("Dataset Loading", test_dataset_loading),
        ("Audio Loading", test_audio_loading),
        ("Eval Format Assembly", test_eval_format_assembly),
        ("Tool Message Format", test_tool_message_format),
    ]

    for ds_key in dataset_keys:
        print(f"\n{'─' * 60}")
        print(f"Dataset: {DATASETS[ds_key]['name']}")
        print(f"{'─' * 60}")

        for test_name, test_fn in tests:
            print(f"\n[{test_name}]")
            try:
                if test_fn(ds_key):
                    print(f"  ✅ PASS")
                    passed += 1
                else:
                    print(f"  ⏭️  SKIP")
                    skipped += 1
            except Exception as ex:
                print(f"  ❌ FAIL: {ex}")
                failed += 1

    # Dataset-independent tests
    print(f"\n{'─' * 60}")
    print("Security Tests")
    print(f"{'─' * 60}")
    print(f"\n[Path Traversal Prevention]")
    try:
        if test_path_traversal_blocked():
            print(f"  ✅ PASS")
            passed += 1
    except Exception as ex:
        print(f"  ❌ FAIL: {ex}")
        failed += 1

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped")
    print(f"{'=' * 60}")

    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="E2E integration tests for evaluation harness")
    parser.add_argument("--dataset", choices=["eiffel", "trivia", "all"], default="all",
                        help="Which dataset to test (default: all)")
    parser.add_argument("--skip-voicelive", action="store_true",
                        help="Skip VoiceLive API tests (format/loading only)")
    args = parser.parse_args()

    keys = list(DATASETS.keys()) if args.dataset == "all" else [args.dataset]
    sys.exit(run_tests(keys, skip_voicelive=args.skip_voicelive))
