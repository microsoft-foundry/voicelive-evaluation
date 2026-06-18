"""
Full-Duplex-Bench v1 -> VoiceLive Integration Runner
=====================================================

Side-by-side runner that bridges the Full-Duplex-Bench v1.0 turn-taking
benchmark with the VoiceLive evaluation harness.

Unlike Big Bench Audio (which tests reasoning accuracy), FDB v1 evaluates
*conversational dynamics*: does the model respond at the right time?
Does it handle pauses, interruptions, and backchannels naturally?

Requirements:
  - VoiceLive harness venv (pip install -r evaluation_harness/requirements.txt)
  - Full-Duplex-Bench repo cloned locally
  - FDB v1 dataset downloaded from Google Drive (see v1_v1.5/dataset/README.md):
    https://drive.google.com/drive/folders/1DtoxMVO9_Y_nDs2peZtx3pw-U2qYgpd3
  - ffmpeg (for audio resampling)
  - openai-whisper (pip install openai-whisper) for ASR transcription

Pipeline phases (each runnable independently):
  prep     -> Scan FDB v1 dataset folder, generate harness-compatible JSONL
  infer    -> Run VoiceLive harness on the JSONL (captures response audio)
  map      -> Restructure harness output into FDB v1 expected folder layout
  asr      -> Transcribe model outputs (Whisper word-level timestamps)
  eval     -> Run FDB v1 evaluation scripts and aggregate results
  all      -> Full pipeline end-to-end

Usage:
  # Full pipeline (e.g., smooth turn-taking on Candor data)
  python fdb_v1_runner.py all \\
      --fdb-dataset ./fdb_data/v1_0/candor_turn_taking \\
      --fdb-repo ../Full-Duplex-Bench \\
      --task smooth_turn_taking \\
      --output ./fdb_results/smooth_turn_taking

  # Step-by-step
  python fdb_v1_runner.py prep   --fdb-dataset <path> --task <task> --output <dir>
  python fdb_v1_runner.py infer  --output <dir> [--model gpt-realtime]
  python fdb_v1_runner.py map    --output <dir>
  python fdb_v1_runner.py asr    --output <dir>
  python fdb_v1_runner.py eval   --output <dir> --fdb-repo <path> [--task <task>]

Recommended harness flags:
  --model gpt-realtime          (native speech-to-speech, not cascade)
  --silence-duration-ms 2000    (long audio clips need patient VAD)
  --session-mode per-file       (one VoiceLive session per sample)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import wave
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("fdb_v1_runner")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
HARNESS_SCRIPT = "evaluation_harness/voice_agent_audio_input_evaluation.py"
FDB_EVAL_DIR = "v1_v1.5/evaluation"
FDB_TIMING_SCRIPT = "v1_v1.5/evaluation/get_timing.py"

FDB_V1_TASKS = {
    "pause_handling":      {"annotation": "pause.json"},
    "smooth_turn_taking":  {"annotation": "turn_taking.json"},
    "backchannel":         {"annotation": None},
    "user_interruption":   {"annotation": "interrupt.json"},
}

DEFAULT_MODEL = "gpt-realtime"

DEFAULT_SYSTEM_PROMPT = (
    "You are a natural conversational partner. Respond to the user's speech "
    "as you would in a real conversation. Be concise and conversational."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_repo_root() -> Path:
    """Walk up from this script to find the voicelive-evaluation repo root."""
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "evaluation_harness").is_dir() and (p / "helper_scripts").is_dir():
            return p
        p = p.parent
    raise FileNotFoundError("Cannot find voicelive-evaluation repo root")


def _count_samples(dataset_dir: Path) -> List[Path]:
    """Return sorted list of numbered sample folders containing input.wav."""
    folders = []
    for item in sorted(dataset_dir.iterdir()):
        if item.is_dir() and item.name.isdigit():
            if (item / "input.wav").exists():
                folders.append(item)
    return folders


def _wav_info(wav_path: Path) -> dict:
    """Read WAV metadata without loading full audio."""
    with wave.open(str(wav_path), "rb") as wf:
        return {
            "channels": wf.getnchannels(),
            "sample_width": wf.getsampwidth(),
            "frame_rate": wf.getframerate(),
            "duration_s": round(wf.getnframes() / wf.getframerate(), 2),
        }


def _resample_wav(src: Path, dst: Path, target_rate: int = 24000) -> bool:
    """Resample WAV to target rate using ffmpeg (harness expects 24kHz)."""
    try:
        dst_tmp = dst.with_suffix(".converting.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-i", str(src), "-ar", str(target_rate),
             "-ac", "1", "-sample_fmt", "s16", str(dst_tmp)],
            capture_output=True, check=True,
        )
        dst_tmp.rename(dst)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        dst_tmp.unlink(missing_ok=True) if 'dst_tmp' in dir() else None
        logger.error(f"ffmpeg resample failed for {src.name}: {exc}")
        return False


# ---------------------------------------------------------------------------
# Phase 1: PREP
# ---------------------------------------------------------------------------

def phase_prep(
    fdb_dataset: Path,
    output_dir: Path,
    task: str,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> Path:
    """Scan FDB v1 dataset directory and create harness-compatible JSONL."""
    logger.info(f"Phase: PREP -- scanning {fdb_dataset}")

    samples = _count_samples(fdb_dataset)
    if not samples:
        raise FileNotFoundError(
            f"No numbered sample folders with input.wav found in {fdb_dataset}"
        )

    task_info = FDB_V1_TASKS.get(task)
    if not task_info:
        raise ValueError(f"Unknown task '{task}'. Choose from: {list(FDB_V1_TASKS)}")

    output_dir.mkdir(parents=True, exist_ok=True)
    wav_dir = output_dir / "wav_24k"
    wav_dir.mkdir(exist_ok=True)

    records = []
    skipped = 0

    for sample_dir in samples:
        sample_id = sample_dir.name
        input_wav = sample_dir / "input.wav"

        # Validate annotation exists if required
        ann = task_info["annotation"]
        if ann and not (sample_dir / ann).exists():
            logger.warning(f"Sample {sample_id}: missing {ann}, skipping")
            skipped += 1
            continue

        # Resample to 24kHz for VoiceLive (FDB data is typically 16kHz)
        info = _wav_info(input_wav)
        wav_24k = wav_dir / f"{task}_{sample_id}.wav"
        if not wav_24k.exists():
            if info["frame_rate"] != 24000:
                if not _resample_wav(input_wav, wav_24k):
                    skipped += 1
                    continue
            else:
                shutil.copy2(input_wav, wav_24k)

        record = {
            "WavPath": str(wav_24k.resolve()),
            "Question": f"[audio: {task}, sample {sample_id}]",
            "Answer": "",
            "conversationID": f"fdb-{task}-{sample_id}",
            "system_prompt": system_prompt,
            "tool_definitions": None,
        }
        records.append(record)

    jsonl_path = output_dir / "fdb_v1_dataset.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Save manifest for downstream phases
    manifest = {
        "task": task,
        "dataset_dir": str(fdb_dataset.resolve()),
        "jsonl_path": str(jsonl_path.resolve()),
        "sample_count": len(records),
        "samples": [
            {"id": s.name, "source_dir": str(s.resolve())}
            for s in samples if not (task_info["annotation"] and not (s / task_info["annotation"]).exists())
        ],
        "created_at": datetime.now().isoformat(),
    }
    manifest_path = output_dir / "fdb_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    logger.info(f"Created {len(records)} records -> {jsonl_path}")
    if skipped:
        logger.warning(f"Skipped {skipped} samples")
    return jsonl_path


# ---------------------------------------------------------------------------
# Phase 2: INFER
# ---------------------------------------------------------------------------

def phase_infer(
    output_dir: Path,
    model: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
) -> int:
    """Run VoiceLive harness on the generated JSONL."""
    logger.info("Phase: INFER -- running VoiceLive harness")

    jsonl_path = output_dir / "fdb_v1_dataset.jsonl"
    if not jsonl_path.exists():
        raise FileNotFoundError(f"Run 'prep' first -- {jsonl_path} not found")

    repo_root = _find_repo_root()
    harness = repo_root / HARNESS_SCRIPT
    harness_output = output_dir / "harness_output"

    cmd = [
        sys.executable, str(harness),
        "-f", str(jsonl_path),
        "-o", str(harness_output),
        "--session-mode", "per-file",
        "--model", model or DEFAULT_MODEL,
        "--silence-duration-ms", "2000",
        "--evaluators", "none",
    ]
    if extra_args:
        cmd.extend(extra_args)

    logger.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(repo_root))

    if result.returncode != 0:
        logger.error(f"Harness exited with code {result.returncode}")
    else:
        logger.info("Harness completed successfully")
    return result.returncode


# ---------------------------------------------------------------------------
# Phase 3: MAP
# ---------------------------------------------------------------------------

def phase_map(output_dir: Path) -> Path:
    """Restructure harness output into FDB v1 expected folder layout.

    FDB v1 expects per sample:
      {root}/{ID}/input.wav      <- original user audio
      {root}/{ID}/output.wav     <- model response audio
      {root}/{ID}/<task>.json    <- annotation (from original dataset)
      {root}/{ID}/output.json    <- ASR transcript (created in ASR phase)
    """
    logger.info("Phase: MAP -- restructuring output for FDB v1")

    manifest_path = output_dir / "fdb_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Run 'prep' first -- {manifest_path} not found")

    with open(manifest_path) as f:
        manifest = json.load(f)

    task = manifest["task"]
    task_info = FDB_V1_TASKS[task]
    harness_output = output_dir / "harness_output"
    fdb_eval_dir = output_dir / "fdb_eval_data"
    fdb_eval_dir.mkdir(parents=True, exist_ok=True)

    mapped = 0
    missing_audio = 0

    for sample in manifest["samples"]:
        sample_id = sample["id"]
        source_dir = Path(sample["source_dir"])
        conv_id = f"fdb-{task}-{sample_id}"

        # Find harness response audio
        conv_dir = harness_output / conv_id
        response_wavs = sorted(conv_dir.glob("turn_*_response.wav")) if conv_dir.exists() else []
        if not response_wavs:
            logger.warning(f"Sample {sample_id}: no response audio found")
            missing_audio += 1
            continue

        # Create FDB-format sample directory
        dest_dir = fdb_eval_dir / sample_id
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Copy input.wav from original dataset
        dest_input = dest_dir / "input.wav"
        if not dest_input.exists():
            shutil.copy2(source_dir / "input.wav", dest_input)

        # Copy response audio as output.wav
        # If harness output is 24kHz, resample to 16kHz for FDB eval (Silero VAD expects 16kHz)
        response_wav = response_wavs[0]
        dest_output = dest_dir / "output.wav"
        info = _wav_info(response_wav)
        if info["frame_rate"] != 16000:
            _resample_wav(response_wav, dest_output, target_rate=16000)
        else:
            shutil.copy2(response_wav, dest_output)

        # Copy annotations
        if task_info["annotation"]:
            src_ann = source_dir / task_info["annotation"]
            if src_ann.exists():
                shutil.copy2(src_ann, dest_dir / task_info["annotation"])

        # Copy transcription.json if present
        src_trans = source_dir / "transcription.json"
        if src_trans.exists():
            shutil.copy2(src_trans, dest_dir / "transcription.json")

        # For user_interruption: also copy context.wav, interrupt.wav
        if task == "user_interruption":
            for extra in ["context.wav", "interrupt.wav"]:
                src = source_dir / extra
                if src.exists() and not (dest_dir / extra).exists():
                    shutil.copy2(src, dest_dir / extra)

        mapped += 1

    logger.info(f"Mapped {mapped} samples -> {fdb_eval_dir}")
    if missing_audio:
        logger.warning(f"{missing_audio} samples had no response audio")
    return fdb_eval_dir


# ---------------------------------------------------------------------------
# Phase 4: ASR
# ---------------------------------------------------------------------------

def phase_asr(output_dir: Path) -> None:
    """Transcribe model output.wav files using Whisper with word timestamps.

    Produces output.json in FDB v1 format:
      {"text": "full transcript", "chunks": [{"text": "word", "timestamp": [start, end]}, ...]}
    """
    logger.info("Phase: ASR -- transcribing model outputs with Whisper")

    try:
        import whisper
    except ImportError:
        logger.error("whisper not installed. Run: pip install openai-whisper")
        raise

    fdb_eval_dir = output_dir / "fdb_eval_data"
    if not fdb_eval_dir.exists():
        raise FileNotFoundError(f"Run 'map' first -- {fdb_eval_dir} not found")

    logger.info("Loading Whisper model (base.en)...")
    model = whisper.load_model("base.en")

    sample_dirs = _count_samples(fdb_eval_dir)
    transcribed = 0

    for sample_dir in sample_dirs:
        output_wav = sample_dir / "output.wav"
        output_json = sample_dir / "output.json"

        if output_json.exists():
            logger.debug(f"Sample {sample_dir.name}: output.json exists, skipping")
            continue

        if not output_wav.exists():
            logger.warning(f"Sample {sample_dir.name}: no output.wav, skipping")
            continue

        logger.info(f"Transcribing sample {sample_dir.name}...")
        result = model.transcribe(
            str(output_wav),
            word_timestamps=True,
            language="en",
        )

        # Convert to FDB v1 format
        chunks = []
        for segment in result.get("segments", []):
            for word_info in segment.get("words", []):
                chunks.append({
                    "text": word_info["word"].strip(),
                    "timestamp": [
                        round(word_info["start"], 3),
                        round(word_info["end"], 3),
                    ],
                })

        output_dict = {
            "text": result.get("text", "").strip(),
            "chunks": chunks,
        }

        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(output_dict, f, indent=4)

        transcribed += 1
        logger.info(f"  -> {output_json.name} ({len(chunks)} words)")

    logger.info(f"Transcribed {transcribed} samples")


# ---------------------------------------------------------------------------
# Phase 5: EVAL
# ---------------------------------------------------------------------------

def phase_eval(
    output_dir: Path,
    fdb_repo: Path,
    task: Optional[str] = None,
) -> Dict[str, Any]:
    """Run FDB v1 evaluation scripts on the restructured output."""
    logger.info("Phase: EVAL -- running FDB v1 evaluation")

    manifest_path = output_dir / "fdb_manifest.json"
    with open(manifest_path) as f:
        manifest = json.load(f)
    task = task or manifest["task"]

    fdb_repo = fdb_repo.resolve()
    fdb_eval_dir = (output_dir / "fdb_eval_data").resolve()
    eval_script = fdb_repo / FDB_EVAL_DIR / "evaluate.py"
    if not eval_script.exists():
        raise FileNotFoundError(f"FDB eval script not found: {eval_script}")

    # Optional: run get_timing.py first
    timing_script = fdb_repo / FDB_TIMING_SCRIPT
    if timing_script.exists():
        logger.info("Running get_timing.py for VAD latency intervals...")
        result = subprocess.run(
            [sys.executable, str(timing_script), "--root_dir", str(fdb_eval_dir)],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            logger.info("Timing analysis complete")
        else:
            logger.warning(f"get_timing.py failed (non-fatal): {result.stderr[:300]}")

    # Run FDB evaluation
    logger.info(f"Running evaluate.py --task {task}")
    cmd = [
        sys.executable, str(eval_script),
        "--task", task,
        "--root_dir", str(fdb_eval_dir),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=str(fdb_repo / FDB_EVAL_DIR),
    )

    eval_output = {
        "task": task,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
        "timestamp": datetime.now().isoformat(),
        "sample_count": manifest["sample_count"],
    }

    eval_output_path = output_dir / "fdb_eval_results.json"
    with open(eval_output_path, "w", encoding="utf-8") as f:
        json.dump(eval_output, f, indent=2)

    print(f"\n{'='*60}")
    print(f"FDB v1 Evaluation Results -- {task}")
    print(f"{'='*60}")
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        print(f"\nEvaluation exited with code {result.returncode}")
        if result.stderr:
            print(f"stderr:\n{result.stderr[:1000]}")
    print(f"\nResults saved to: {eval_output_path}")

    return eval_output


# ---------------------------------------------------------------------------
# Phase: ALL
# ---------------------------------------------------------------------------

def phase_all(args: argparse.Namespace) -> None:
    """Run all phases sequentially."""
    output_dir = Path(args.output)

    phase_prep(
        fdb_dataset=Path(args.fdb_dataset),
        output_dir=output_dir,
        task=args.task,
        system_prompt=args.system_prompt or DEFAULT_SYSTEM_PROMPT,
    )

    rc = phase_infer(output_dir, model=args.model)
    if rc != 0:
        logger.error("Harness failed -- continuing with map/eval on available output")

    phase_map(output_dir)
    phase_asr(output_dir)
    phase_eval(output_dir, fdb_repo=Path(args.fdb_repo), task=args.task)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Full-Duplex-Bench v1 -> VoiceLive Integration Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="phase", required=True)

    # -- prep
    p = sub.add_parser("prep", help="Generate harness JSONL from FDB v1 dataset")
    p.add_argument("--fdb-dataset", required=True, help="Path to FDB v1 dataset dir")
    p.add_argument("--task", required=True, choices=FDB_V1_TASKS, help="FDB v1 task")
    p.add_argument("--output", required=True, help="Output directory")
    p.add_argument("--system-prompt", default=DEFAULT_SYSTEM_PROMPT)

    # -- infer
    p = sub.add_parser("infer", help="Run VoiceLive harness")
    p.add_argument("--output", required=True, help="Output directory")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--extra-args", nargs="*", help="Extra harness arguments")

    # -- map
    p = sub.add_parser("map", help="Restructure output for FDB v1")
    p.add_argument("--output", required=True)

    # -- asr
    p = sub.add_parser("asr", help="Transcribe model outputs with Whisper")
    p.add_argument("--output", required=True)

    # -- eval
    p = sub.add_parser("eval", help="Run FDB v1 evaluation scripts")
    p.add_argument("--output", required=True)
    p.add_argument("--fdb-repo", required=True, help="Path to Full-Duplex-Bench repo")
    p.add_argument("--task", help="Override task (default: from manifest)")

    # -- all
    p = sub.add_parser("all", help="Full pipeline (prep -> infer -> map -> asr -> eval)")
    p.add_argument("--fdb-dataset", required=True)
    p.add_argument("--fdb-repo", required=True)
    p.add_argument("--task", required=True, choices=FDB_V1_TASKS)
    p.add_argument("--output", required=True)
    p.add_argument("--system-prompt", default=DEFAULT_SYSTEM_PROMPT)
    p.add_argument("--model", default=DEFAULT_MODEL)

    return parser


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = build_parser()
    args = parser.parse_args()

    if args.phase == "prep":
        phase_prep(Path(args.fdb_dataset), Path(args.output), args.task, args.system_prompt)
    elif args.phase == "infer":
        phase_infer(Path(args.output), model=args.model, extra_args=args.extra_args)
    elif args.phase == "map":
        phase_map(Path(args.output))
    elif args.phase == "asr":
        phase_asr(Path(args.output))
    elif args.phase == "eval":
        phase_eval(Path(args.output), Path(args.fdb_repo), args.task)
    elif args.phase == "all":
        phase_all(args)


if __name__ == "__main__":
    main()
