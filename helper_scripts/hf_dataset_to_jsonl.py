"""
HuggingFace Dataset → Evaluation JSONL Converter

Downloads a HuggingFace audio dataset and produces a JSONL file in the format
required by the VoiceLive evaluation pipeline:

  {"WavPath": "...", "Question": "...", "Answer": "...", "conversationID": "...", "system_prompt": "...", "tool_definitions": null}

Usage:
  python hf_dataset_to_jsonl.py TwinkStart/llama-questions
  python hf_dataset_to_jsonl.py TwinkStart/llama-questions --split test --limit 50 --output-dir ./local_datasets
  python hf_dataset_to_jsonl.py TwinkStart/speech-web-questions --system-prompt "You are a helpful assistant."
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from datasets import Audio, Dataset, load_dataset
from huggingface_hub import HfApi, login

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Known HF dataset column mappings → our JSONL schema
# ---------------------------------------------------------------------------
DEFAULT_DATASETS = [
    "TwinkStart/llama-questions",
    "TwinkStart/speech-web-questions",
    "TwinkStart/speech-triavia-qa",
]

COLUMN_MAPS: Dict[str, Dict[str, str]] = {
    "TwinkStart/llama-questions": {"question": "Questions", "answer": "Answer"},
    "TwinkStart/speech-web-questions": {"question": "question", "answer": "answers"},
    "TwinkStart/speech-triavia-qa": {"question": "question", "answer": "answer"},
}


class HuggingFaceAudioLoader:
    """Load HuggingFace audio datasets with authentication handling."""

    def __init__(self, cache_dir: str = "./hf_data_cache") -> None:
        self.cache_dir = cache_dir
        self.token: Optional[str] = None
        self.dataset: Optional[Dataset] = None
        self._setup_authentication()

    # -- auth ---------------------------------------------------------------
    def _setup_authentication(self) -> None:
        hf_token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN")
        if hf_token:
            try:
                login(token=hf_token)
                logger.info("Using HF token from environment variable")
                self.token = hf_token
            except Exception as exc:
                logger.warning("HF token login failed: %s", exc)
        else:
            logger.info("No HF token found — continuing without auth (public datasets only)")
        api = HfApi()
        if not self.token:
            self.token = getattr(api, "token", None)

    # -- loading ------------------------------------------------------------
    def load_dataset(
        self,
        name: str,
        split: str = "test",
        limit: Optional[int] = None,
        decode_audio: bool = False,
    ) -> Dataset:
        split_str = split
        if limit:
            split_str = f"{split}[:{limit}]"

        logger.info("Loading dataset %s split=%s", name, split_str)
        self.dataset = load_dataset(
            name, cache_dir=self.cache_dir, split=split_str, token=self.token
        )
        if not decode_audio and "audio" in self.dataset.features:
            self.dataset = self.dataset.cast_column("audio", Audio(decode=False))
        logger.info("Loaded %d samples, columns: %s", len(self.dataset), self.dataset.column_names)
        return self.dataset

    # -- iteration ----------------------------------------------------------
    def iterate_items(self) -> Iterator[Dict[str, Any]]:
        if not self.dataset:
            raise ValueError("No dataset loaded")
        for idx in range(len(self.dataset)):
            item = self.dataset[idx]
            audio_bytes: Optional[bytes] = None
            if "audio" in item:
                info = item["audio"]
                if isinstance(info, dict):
                    if info.get("bytes"):
                        audio_bytes = info["bytes"]
                    elif info.get("path"):
                        try:
                            audio_bytes = Path(info["path"]).read_bytes()
                        except OSError:
                            pass
            yield {
                "index": idx,
                "audio_data": audio_bytes,
                "metadata": {k: v for k, v in item.items() if k != "audio"},
            }


# ---------------------------------------------------------------------------
# JSONL generation
# ---------------------------------------------------------------------------
def _resolve_column(metadata: Dict[str, Any], candidates: list[str]) -> str:
    """Try multiple column names; return first match or empty string."""
    for key in candidates:
        if key in metadata and metadata[key]:
            val = metadata[key]
            return ", ".join(val) if isinstance(val, list) else str(val)
    return ""


def generate_jsonl(
    dataset_name: str,
    split: str = "test",
    limit: Optional[int] = None,
    output_dir: str = "./local_datasets",
    system_prompt: str = "",
    cache_dir: str = "./hf_data_cache",
) -> Path:
    """Download HF dataset, save WAVs, and write pipeline-ready JSONL."""

    loader = HuggingFaceAudioLoader(cache_dir=cache_dir)
    loader.load_dataset(dataset_name, split=split, limit=limit)

    # Resolve column mapping
    col_map = COLUMN_MAPS.get(dataset_name)
    if not col_map:
        # Auto-detect: look for common column names
        cols = set(loader.dataset.column_names)
        q_col = next((c for c in ["Questions", "question", "Question", "query", "prompt"] if c in cols), None)
        a_col = next((c for c in ["Answer", "answer", "answers", "response", "ground_truth"] if c in cols), None)
        if not q_col:
            print(f"WARNING: Could not auto-detect question column from {cols}")
        col_map = {"question": q_col or "", "answer": a_col or ""}

    # Prepare output paths
    safe_name = dataset_name.replace("/", "-")
    wav_dir = Path(output_dir) / safe_name / "wav"
    wav_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    skipped = 0

    for item in loader.iterate_items():
        idx = item["index"]
        meta = item["metadata"]

        # Save WAV
        if not item["audio_data"]:
            skipped += 1
            continue
        wav_path = wav_dir / f"{idx}.wav"
        wav_path.write_bytes(item["audio_data"])

        # Build JSONL record
        question = _resolve_column(meta, [col_map["question"]])
        answer = _resolve_column(meta, [col_map["answer"]])

        record = {
            "WavPath": str(wav_path.resolve()),
            "Question": question,
            "Answer": answer,
            "conversationID": f"{safe_name}-{idx}",
            "system_prompt": system_prompt or None,
            "tool_definitions": None,
        }
        records.append(record)

    # Write JSONL
    jsonl_path = Path(output_dir) / safe_name / f"{safe_name}.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\n✅ Created {len(records)} records → {jsonl_path}")
    if skipped:
        print(f"⚠️  Skipped {skipped} items with no audio data")
    print(f"📁 WAV files saved to {wav_dir}")
    return jsonl_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download HuggingFace audio dataset and create evaluation-ready JSONL"
    )
    parser.add_argument(
        "dataset",
        nargs="*",
        default=DEFAULT_DATASETS,
        help=f"HuggingFace dataset name(s). Default: all 3 TwinkStart datasets",
    )
    parser.add_argument("--split", default="test", help="Dataset split (default: test)")
    parser.add_argument("--limit", type=int, default=None, help="Max number of samples")
    parser.add_argument("--output-dir", default="./local_datasets", help="Output directory (default: ./local_datasets)")
    parser.add_argument("--system-prompt", default="", help="System prompt to include in every JSONL row")
    parser.add_argument("--token", default=None, help="HuggingFace token for gated datasets (or set HF_TOKEN env var)")
    parser.add_argument("--cache-dir", default="./hf_data_cache", help="HuggingFace cache directory")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    # CLI --token takes precedence over env var
    if args.token:
        os.environ["HF_TOKEN"] = args.token

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    for ds_name in args.dataset:
        print(f"\n{'='*60}")
        print(f"Processing: {ds_name}")
        print(f"{'='*60}")
        generate_jsonl(
            dataset_name=ds_name,
            split=args.split,
            limit=args.limit,
            output_dir=args.output_dir,
            system_prompt=args.system_prompt,
            cache_dir=args.cache_dir,
        )


if __name__ == "__main__":
    main()
