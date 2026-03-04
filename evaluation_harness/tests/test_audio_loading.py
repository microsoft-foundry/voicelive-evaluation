"""
Quick smoke tests for the evaluation harness audio loading and dataset parsing.

Usage:
    python evaluation_harness/tests/test_audio_loading.py
"""

import os
import sys
import json

# Add parent to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from voice_agent_audio_input_evaluation import load_audio_file, read_dataset


def test_eiffel_tower_dataset():
    """Test loading Eiffel Tower dataset — PCM16 WAVs with full metadata."""
    dataset_dir = os.path.join(os.path.dirname(__file__), "..", "sample_evaluation_input", "Eiffel_Tower_Visit")
    jsonl = os.path.join(dataset_dir, "Eiffel_Tower_Visit.jsonl")

    if not os.path.exists(jsonl):
        print(f"SKIP: {jsonl} not found")
        return

    entries = read_dataset(jsonl)
    assert len(entries) > 0, "No entries loaded"
    print(f"  Loaded {len(entries)} entries")

    # Verify first entry has expected fields
    e = entries[0]
    assert e.audio_path and os.path.exists(e.audio_path), f"Audio not found: {e.audio_path}"
    assert e.ground_truth, "Missing ground_truth (Answer)"
    assert e.question, "Missing question"
    assert e.conversation_id, "Missing conversation_id"

    # Load audio — should be standard PCM16
    audio_bytes = load_audio_file(e.audio_path)
    assert len(audio_bytes) > 0, "Empty audio data"
    print(f"  Audio loaded: {len(audio_bytes)} bytes PCM16")
    print("  PASS: Eiffel Tower dataset")


def test_speech_trivia_qa_dataset():
    """Test loading speech-trivia-qa dataset — float32 WAVs with OR-joined answers."""
    dataset_dir = os.path.join(os.path.dirname(__file__), "..", "local_datasets", "TwinkStart-speech-triavia-qa")
    jsonl = os.path.join(dataset_dir, "TwinkStart-speech-triavia-qa.jsonl")

    if not os.path.exists(jsonl):
        print(f"SKIP: {jsonl} not found")
        return

    entries = read_dataset(jsonl)
    assert len(entries) > 0, "No entries loaded"
    print(f"  Loaded {len(entries)} entries")

    # Verify first entry
    e = entries[0]
    assert e.audio_path and os.path.exists(e.audio_path), f"Audio not found: {e.audio_path}"
    assert e.ground_truth, "Missing ground_truth (Answer)"
    assert " OR " in e.ground_truth, f"Expected OR-joined answer, got: {e.ground_truth[:50]}"

    # Load audio — float32 WAV (format tag 3), must not crash
    audio_bytes = load_audio_file(e.audio_path)
    assert len(audio_bytes) > 0, "Empty audio data"
    print(f"  Audio loaded: {len(audio_bytes)} bytes PCM16 (converted from float32)")
    print(f"  Answer format: {e.ground_truth[:60]}...")
    print("  PASS: speech-trivia-qa dataset")


if __name__ == "__main__":
    print("=" * 60)
    print("Evaluation Harness - Audio Loading Tests")
    print("=" * 60)

    passed = 0
    failed = 0

    for test in [test_eiffel_tower_dataset, test_speech_trivia_qa_dataset]:
        print(f"\n{test.__name__}:")
        try:
            test()
            passed += 1
        except Exception as ex:
            print(f"  FAIL: {ex}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
