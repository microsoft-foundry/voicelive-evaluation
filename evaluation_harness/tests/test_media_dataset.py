"""
Unit tests for media dataset format support (input_audio via base64 / URL).

Validates read_dataset(), _extract_media_ref(), _resolve_audio_from_media(),
and backward compatibility with legacy WavPath format.

Usage:
    python evaluation_harness/tests/test_media_dataset.py
    python evaluation_harness/tests/test_media_dataset.py --verbose
"""

import base64
import json
import os
import struct
import sys
import tempfile
from typing import Callable, List, Optional, Tuple

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from voice_agent_audio_input_evaluation import (
    DatasetEntry,
    read_dataset,
    _extract_media_ref,
    _resolve_audio_from_media,
    _extract_text_from_messages,
    _extract_system_prompt_from_messages,
)


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

_results: List[Tuple[str, str, Optional[str]]] = []


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


def _make_wav_bytes(duration_s: float = 0.1, sample_rate: int = 16000) -> bytes:
    """Generate a minimal valid WAV file (PCM16 mono silence)."""
    n_samples = int(sample_rate * duration_s)
    data_size = n_samples * 2
    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF', 36 + data_size, b'WAVE',
        b'fmt ', 16, 1, 1, sample_rate, sample_rate * 2, 2, 16,
        b'data', data_size,
    )
    return header + b'\x00' * data_size


# ---------------------------------------------------------------------------
# 1. _extract_media_ref tests
# ---------------------------------------------------------------------------

def test_extract_media_ref_from_messages():
    """Extracts input_audio from Foundry messages array."""
    record = {
        "messages": [
            {"role": "system", "content": "You are a helper."},
            {"role": "user", "content": [
                {"type": "text", "text": "Hello"},
                {"type": "input_audio", "input_audio": {"data": "data:audio/wav;base64,AAAA", "format": "wav"}}
            ]}
        ]
    }
    ref = _extract_media_ref(record)
    assert ref is not None, "Should find input_audio in messages"
    assert ref["data"].startswith("data:audio/wav"), f"Expected data URI, got: {ref['data'][:30]}"
    assert ref["format"] == "wav"


def test_extract_media_ref_top_level():
    """Extracts input_audio from top-level audio field."""
    record = {
        "audio": {
            "type": "input_audio",
            "input_audio": {"data": "https://example.com/audio.wav", "format": "wav"}
        }
    }
    ref = _extract_media_ref(record)
    assert ref is not None, "Should find input_audio at top level"
    assert ref["data"] == "https://example.com/audio.wav"


def test_extract_media_ref_legacy_returns_none():
    """Legacy WavPath records return None (no media ref)."""
    record = {"WavPath": "test.wav", "Question": "Hello"}
    ref = _extract_media_ref(record)
    assert ref is None, "Legacy records should not have a media ref"


def test_extract_media_ref_empty_data_returns_none():
    """input_audio with empty data is rejected."""
    record = {
        "messages": [
            {"role": "user", "content": [
                {"type": "input_audio", "input_audio": {"data": "", "format": "wav"}}
            ]}
        ]
    }
    ref = _extract_media_ref(record)
    assert ref is None, "Empty data should be rejected"


# ---------------------------------------------------------------------------
# 2. _extract_text_from_messages tests
# ---------------------------------------------------------------------------

def test_extract_text_from_messages():
    """Extracts user text from content array."""
    record = {
        "messages": [
            {"role": "user", "content": [
                {"type": "text", "text": "What time is it?"},
                {"type": "input_audio", "input_audio": {"data": "xxx", "format": "wav"}}
            ]}
        ]
    }
    text = _extract_text_from_messages(record)
    assert text == "What time is it?"


def test_extract_text_string_content():
    """Extracts text when content is a plain string."""
    record = {"messages": [{"role": "user", "content": "Just text"}]}
    text = _extract_text_from_messages(record)
    assert text == "Just text"


def test_extract_system_prompt():
    """Extracts system prompt from messages."""
    record = {"messages": [
        {"role": "system", "content": "You are Tobi the agent."},
        {"role": "user", "content": "Hi"},
    ]}
    prompt = _extract_system_prompt_from_messages(record)
    assert prompt == "You are Tobi the agent."


# ---------------------------------------------------------------------------
# 3. _resolve_audio_from_media tests
# ---------------------------------------------------------------------------

def test_resolve_base64_data_uri():
    """Resolves base64 data URI to a local file."""
    wav_bytes = _make_wav_bytes()
    b64 = "data:audio/wav;base64," + base64.b64encode(wav_bytes).decode()
    ref = {"data": b64, "format": "wav"}

    with tempfile.TemporaryDirectory() as td:
        result = _resolve_audio_from_media(ref, cache_dir=td)
        assert result is not None, "Should resolve base64 data URI"
        assert os.path.exists(result), f"File should exist: {result}"
        with open(result, 'rb') as f:
            content = f.read()
        assert content == wav_bytes, "Decoded content should match original"


def test_resolve_url_returns_none_for_unreachable():
    """URL that fails to download returns None."""
    ref = {"data": "https://nonexistent.example.com/audio.wav", "format": "wav"}
    result = _resolve_audio_from_media(ref)
    assert result is None, "Unreachable URL should return None"


def test_resolve_raw_base64_rejected():
    """Raw base64 (no data: prefix) is no longer supported."""
    wav_bytes = _make_wav_bytes()
    b64 = base64.b64encode(wav_bytes).decode()
    ref = {"data": b64, "format": "wav"}

    with tempfile.TemporaryDirectory() as td:
        result = _resolve_audio_from_media(ref, cache_dir=td)
        assert result is None, "Raw base64 without data: prefix should be rejected"


def test_resolve_empty_ref_returns_none():
    """Empty or None ref returns None."""
    assert _resolve_audio_from_media(None) is None
    assert _resolve_audio_from_media({}) is None
    assert _resolve_audio_from_media({"data": "", "format": "wav"}) is None


def test_resolve_invalid_base64_returns_none():
    """Invalid base64 returns None."""
    ref = {"data": "data:audio/wav;base64,NOT_VALID_BASE64!!!", "format": "wav"}
    result = _resolve_audio_from_media(ref)
    assert result is None, "Invalid base64 should return None"


# ---------------------------------------------------------------------------
# 4. read_dataset integration tests
# ---------------------------------------------------------------------------

def test_read_dataset_legacy_format():
    """read_dataset correctly parses legacy WavPath entries."""
    wav_bytes = _make_wav_bytes()

    with tempfile.TemporaryDirectory() as td:
        # Create a WAV file
        wav_file = os.path.join(td, "test.wav")
        with open(wav_file, 'wb') as f:
            f.write(wav_bytes)

        # Create JSONL
        jsonl_file = os.path.join(td, "test.jsonl")
        record = {"WavPath": "test.wav", "Question": "Hello", "Answer": "Hi there"}
        with open(jsonl_file, 'w') as f:
            f.write(json.dumps(record) + "\n")

        entries = read_dataset(jsonl_file)
        assert len(entries) == 1, f"Expected 1 entry, got {len(entries)}"
        assert entries[0].audio_path is not None
        assert entries[0].audio_media_ref is None
        assert entries[0].question == "Hello"
        assert entries[0].ground_truth == "Hi there"


def test_read_dataset_media_base64_format():
    """read_dataset correctly parses Foundry media format with base64."""
    wav_bytes = _make_wav_bytes()
    b64 = "data:audio/wav;base64," + base64.b64encode(wav_bytes).decode()

    with tempfile.TemporaryDirectory() as td:
        jsonl_file = os.path.join(td, "media_test.jsonl")
        record = {
            "messages": [
                {"role": "system", "content": "You are a helper."},
                {"role": "user", "content": [
                    {"type": "text", "text": "What time?"},
                    {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}}
                ]}
            ],
            "expected_output": "It is noon.",
            "conversationID": "test_conv_1",
        }
        with open(jsonl_file, 'w') as f:
            f.write(json.dumps(record) + "\n")

        entries = read_dataset(jsonl_file)
        assert len(entries) == 1, f"Expected 1 entry, got {len(entries)}"
        assert entries[0].audio_path is None, "Media entries should not have audio_path"
        assert entries[0].audio_media_ref is not None, "Should have audio_media_ref"
        assert entries[0].audio_media_ref["format"] == "wav"
        assert entries[0].question == "What time?"
        assert entries[0].ground_truth == "It is noon."
        assert entries[0].system_prompt == "You are a helper."
        assert entries[0].conversation_id == "test_conv_1"


def test_read_dataset_media_url_format():
    """read_dataset correctly parses Foundry media format with URL."""
    with tempfile.TemporaryDirectory() as td:
        jsonl_file = os.path.join(td, "url_test.jsonl")
        record = {
            "messages": [
                {"role": "user", "content": [
                    {"type": "text", "text": "Describe"},
                    {"type": "input_audio", "input_audio": {
                        "data": "https://example.com/audio.wav",
                        "format": "wav"
                    }}
                ]}
            ],
            "expected_output": "Audio description",
        }
        with open(jsonl_file, 'w') as f:
            f.write(json.dumps(record) + "\n")

        entries = read_dataset(jsonl_file)
        assert len(entries) == 1
        assert entries[0].audio_media_ref is not None
        assert entries[0].audio_media_ref["data"] == "https://example.com/audio.wav"
        assert entries[0].question == "Describe"


def test_read_dataset_mixed_formats():
    """read_dataset handles mixed legacy + media entries in one file."""
    wav_bytes = _make_wav_bytes()
    b64 = "data:audio/wav;base64," + base64.b64encode(wav_bytes).decode()

    with tempfile.TemporaryDirectory() as td:
        wav_file = os.path.join(td, "turn1.wav")
        with open(wav_file, 'wb') as f:
            f.write(wav_bytes)

        jsonl_file = os.path.join(td, "mixed.jsonl")
        lines = [
            json.dumps({"WavPath": "turn1.wav", "Question": "Q1", "Answer": "A1"}),
            json.dumps({
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": "Q2"},
                    {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}}
                ]}],
                "expected_output": "A2",
            }),
        ]
        with open(jsonl_file, 'w') as f:
            f.write("\n".join(lines) + "\n")

        entries = read_dataset(jsonl_file)
        assert len(entries) == 2, f"Expected 2 entries, got {len(entries)}"
        assert entries[0].audio_path is not None and entries[0].audio_media_ref is None
        assert entries[1].audio_path is None and entries[1].audio_media_ref is not None


def test_read_dataset_actual_base64_file():
    """read_dataset parses the generated base64 test dataset."""
    path = os.path.join(
        os.path.dirname(__file__), "..",
        "sample_evaluation_input",
        "Eiffel_Tower_Visit_1_media_base64",
        "Eiffel_Tower_Visit_1_media_base64.jsonl",
    )
    if not os.path.exists(path):
        print("    (skipped — test file not found)")
        return
    entries = read_dataset(path)
    assert len(entries) == 6, f"Expected 6 entries, got {len(entries)}"
    for e in entries:
        assert e.audio_media_ref is not None, "Should be media ref"
        assert e.audio_media_ref["data"].startswith("data:audio/wav;base64,")
        assert e.question is not None
        assert e.ground_truth is not None
        assert e.system_prompt is not None
        assert e.conversation_id == "Eiffel_Tower_Visit_1"


def test_read_dataset_actual_legacy_file():
    """read_dataset still parses the original Eiffel Tower dataset (backward compat)."""
    path = os.path.join(
        os.path.dirname(__file__), "..",
        "sample_evaluation_input",
        "Eiffel_Tower_Visit_1",
        "Eiffel_Tower_Visit_1.jsonl",
    )
    if not os.path.exists(path):
        print("    (skipped — test file not found)")
        return
    entries = read_dataset(path)
    assert len(entries) == 6, f"Expected 6 entries, got {len(entries)}"
    for e in entries:
        assert e.audio_path is not None, "Legacy entries must have audio_path"
        assert e.audio_media_ref is None, "Legacy entries must NOT have media ref"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    print("\n🧪 Media Dataset Format Tests\n")

    print("  _extract_media_ref:")
    _run("extract_from_messages", test_extract_media_ref_from_messages)
    _run("extract_top_level", test_extract_media_ref_top_level)
    _run("extract_legacy_none", test_extract_media_ref_legacy_returns_none)
    _run("extract_empty_data_none", test_extract_media_ref_empty_data_returns_none)

    print("\n  _extract_text / _extract_system_prompt:")
    _run("extract_text_from_messages", test_extract_text_from_messages)
    _run("extract_text_string_content", test_extract_text_string_content)
    _run("extract_system_prompt", test_extract_system_prompt)

    print("\n  _resolve_audio_from_media:")
    _run("resolve_base64_data_uri", test_resolve_base64_data_uri)
    _run("resolve_url_unreachable_none", test_resolve_url_returns_none_for_unreachable)
    _run("resolve_raw_base64_rejected", test_resolve_raw_base64_rejected)
    _run("resolve_empty_none", test_resolve_empty_ref_returns_none)
    _run("resolve_invalid_base64_none", test_resolve_invalid_base64_returns_none)

    print("\n  read_dataset integration:")
    _run("legacy_format", test_read_dataset_legacy_format)
    _run("media_base64_format", test_read_dataset_media_base64_format)
    _run("media_url_format", test_read_dataset_media_url_format)
    _run("mixed_formats", test_read_dataset_mixed_formats)
    _run("actual_base64_file", test_read_dataset_actual_base64_file)
    _run("actual_legacy_file", test_read_dataset_actual_legacy_file)

    # Summary
    passed = sum(1 for _, s, _ in _results if s == "PASS")
    failed = sum(1 for _, s, _ in _results if s == "FAIL")
    errors = sum(1 for _, s, _ in _results if s == "ERROR")
    total = len(_results)

    print(f"\n{'='*60}")
    print(f"  Results: {passed}/{total} passed", end="")
    if failed:
        print(f", {failed} failed", end="")
    if errors:
        print(f", {errors} errors", end="")
    print()

    if verbose and (failed or errors):
        print("\n  Failures/Errors:")
        for name, status, detail in _results:
            if status in ("FAIL", "ERROR"):
                print(f"    {status} {name}: {detail}")

    sys.exit(1 if (failed + errors) > 0 else 0)


if __name__ == "__main__":
    main()
