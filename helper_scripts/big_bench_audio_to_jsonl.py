"""
Big Bench Audio → VoiceLive Evaluation JSONL Converter
======================================================

Downloads the ArtificialAnalysis/big_bench_audio dataset from HuggingFace
and produces a JSONL file ready for the VoiceLive evaluation harness.

The dataset contains 1000 spoken reasoning questions (MP3) across 4 categories:
  - formal_fallacies  (250)  — logical deduction from syllogisms
  - navigate           (250)  — spatial reasoning from nav instructions
  - object_counting    (250)  — counting objects from descriptions
  - web_of_lies        (250)  — boolean truth-value evaluation

Each question has a known `official_answer` for exact-match evaluation.

Pipeline:
  1. Download metadata.jsonl + MP3 files via huggingface_hub (no torch needed)
  2. Convert MP3 → 24kHz mono 16-bit WAV via ffmpeg
  3. Write VoiceLive-compatible JSONL

Usage:
  # Full dataset (1000 questions)
  python big_bench_audio_to_jsonl.py --output ./local_datasets/big_bench_audio

  # Subset by category
  python big_bench_audio_to_jsonl.py --output ./local_datasets/bba_navigate --category navigate

  # Limit sample count (for quick testing)
  python big_bench_audio_to_jsonl.py --output ./local_datasets/bba_test --limit 10

  # Then run evaluation with VoiceLive (realtime model, NOT cascade):
  python evaluation_harness/voice_agent_audio_input_evaluation.py \\
      -f local_datasets/big_bench_audio/big_bench_audio.jsonl \\
      -o output/big_bench_audio \\
      --model gpt-realtime \\
      --session-mode per-file
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from huggingface_hub import hf_hub_download

logger = logging.getLogger("big_bench_audio")

REPO_ID = "ArtificialAnalysis/big_bench_audio"
TARGET_SAMPLE_RATE = 24000

# System prompt tailored for reasoning benchmarks:
# Must force exact-answer format — the model otherwise responds conversationally.
# Casing matches the official_answer values in the dataset metadata.
DEFAULT_SYSTEM_PROMPT = (
    "You are taking a reasoning test. "
    "Listen to the audio question carefully and respond with ONLY the final answer. "
    "For logic questions, answer ONLY 'valid' or 'invalid'. "
    "For navigation questions, answer ONLY 'Yes' or 'No'. "
    "For counting questions, answer ONLY the number. "
    "For truth-telling questions, answer ONLY 'yes' or 'no'. "
    "Do NOT explain your reasoning. Just give the answer."
)

CATEGORIES = ["formal_fallacies", "navigate", "object_counting", "web_of_lies"]


def _convert_mp3_to_wav(mp3_path: Path, wav_path: Path) -> bool:
    """Convert MP3 to 24kHz mono 16-bit WAV using ffmpeg."""
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", str(mp3_path),
                "-ar", str(TARGET_SAMPLE_RATE),
                "-ac", "1",
                "-sample_fmt", "s16",
                str(wav_path),
            ],
            capture_output=True,
            check=True,
        )
        return True
    except FileNotFoundError:
        logger.error(
            "ffmpeg not found. Install it: winget install ffmpeg  "
            "or download from https://ffmpeg.org/download.html"
        )
        return False
    except subprocess.CalledProcessError as exc:
        logger.error(f"ffmpeg failed for {mp3_path.name}: {exc.stderr.decode()[:200]}")
        return False


def download_and_convert(
    output_dir: Path,
    category: Optional[str] = None,
    limit: Optional[int] = None,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    cache_dir: Optional[str] = None,
) -> Path:
    """Download Big Bench Audio, convert to WAV, and write harness JSONL."""

    output_dir.mkdir(parents=True, exist_ok=True)
    wav_dir = output_dir / "wav"
    wav_dir.mkdir(exist_ok=True)

    # Step 1: Download metadata
    logger.info("Downloading metadata.jsonl from HuggingFace...")
    kwargs = {"repo_id": REPO_ID, "repo_type": "dataset"}
    if cache_dir:
        kwargs["cache_dir"] = cache_dir
    meta_path = hf_hub_download(filename="metadata.jsonl", **kwargs)

    with open(meta_path, encoding="utf-8") as f:
        all_records = [json.loads(line) for line in f if line.strip()]

    logger.info(f"Loaded {len(all_records)} records from metadata")

    # Filter by category
    if category:
        if category not in CATEGORIES:
            raise ValueError(f"Unknown category '{category}'. Choose from: {CATEGORIES}")
        all_records = [r for r in all_records if r["category"] == category]
        logger.info(f"Filtered to {len(all_records)} records for category '{category}'")

    # Limit
    if limit and limit < len(all_records):
        all_records = all_records[:limit]
        logger.info(f"Limited to {limit} records")

    # Step 2: Download MP3s and convert to WAV
    records_out = []
    skipped = 0

    for i, rec in enumerate(all_records):
        file_name = rec["file_name"]  # e.g. "data/question_0.mp3"
        sample_id = rec["id"]
        cat = rec["category"]
        answer = rec["official_answer"]

        # Download MP3
        try:
            mp3_local = Path(hf_hub_download(filename=file_name, **kwargs))
        except Exception as exc:
            logger.warning(f"Failed to download {file_name}: {exc}")
            skipped += 1
            continue

        # Convert to WAV (atomic: write to temp, rename on success)
        wav_path = wav_dir / f"{cat}_{sample_id}.wav"
        if wav_path.exists():
            logger.debug(f"WAV already exists: {wav_path.name}")
        else:
            wav_tmp = wav_dir / f".{cat}_{sample_id}.converting.wav"
            if not _convert_mp3_to_wav(mp3_local, wav_tmp):
                wav_tmp.unlink(missing_ok=True)
                skipped += 1
                continue
            wav_tmp.rename(wav_path)

        # Build JSONL record
        conv_id = f"bba-{cat}-{sample_id}"
        record = {
            "WavPath": str(wav_path.resolve()),
            "Question": f"[audio question: {cat}, id={sample_id}]",
            "Answer": answer,
            "conversationID": conv_id,
            "system_prompt": system_prompt,
            "tool_definitions": None,
            "_category": cat,
        }
        records_out.append(record)

        if (i + 1) % 100 == 0:
            logger.info(f"  Processed {i + 1}/{len(all_records)}...")

    # Step 3: Write JSONL
    suffix = f"_{category}" if category else ""
    jsonl_path = output_dir / f"big_bench_audio{suffix}.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for rec in records_out:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Summary
    print(f"\n{'='*60}")
    print(f"Big Bench Audio -> VoiceLive JSONL")
    print(f"{'='*60}")
    print(f"  Records:    {len(records_out)}")
    if skipped:
        print(f"  Skipped:    {skipped}")
    print(f"  Answers:    {sorted(set(r['Answer'] for r in records_out))[:10]}...")
    print(f"  WAV dir:    {wav_dir}")
    print(f"  JSONL:      {jsonl_path}")

    # Category breakdown (use the _category metadata field, not conversationID parsing)
    from collections import Counter
    cat_counts = Counter(r.get("_category", "unknown") for r in records_out)
    print(f"\n  Category breakdown:")
    for cat_name, count in sorted(cat_counts.items()):
        print(f"    {cat_name}: {count}")

    print(f"\n  Next step — run evaluation:")
    print(f"    python evaluation_harness/voice_agent_audio_input_evaluation.py \\")
    print(f"        -f \"{jsonl_path}\" \\")
    print(f"        -o output/big_bench_audio \\")
    print(f"        --model gpt-realtime \\")
    print(f"        --session-mode per-file")
    print()

    return jsonl_path


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Download Big Bench Audio and convert to VoiceLive evaluation JSONL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--output", "-o", default="./local_datasets/big_bench_audio",
        help="Output directory (default: ./local_datasets/big_bench_audio)",
    )
    parser.add_argument(
        "--category", "-c", choices=CATEGORIES,
        help="Filter to a single category (default: all categories)",
    )
    parser.add_argument(
        "--limit", "-n", type=int,
        help="Limit number of samples (useful for quick testing)",
    )
    parser.add_argument(
        "--system-prompt", default=DEFAULT_SYSTEM_PROMPT,
        help="System prompt for VoiceLive sessions",
    )
    parser.add_argument(
        "--cache-dir", default=None,
        help="HuggingFace cache directory",
    )

    args = parser.parse_args()
    download_and_convert(
        output_dir=Path(args.output),
        category=args.category,
        limit=args.limit,
        system_prompt=args.system_prompt,
        cache_dir=args.cache_dir,
    )


if __name__ == "__main__":
    main()
