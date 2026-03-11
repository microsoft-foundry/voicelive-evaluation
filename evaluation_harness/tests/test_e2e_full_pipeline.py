"""
End-to-end evaluation pipeline test.

Runs the full harness pipeline (dataset → VoiceLive → Foundry evaluation) with both
realtime and cascaded modes using sample datasets. Validates outputs exist and contain
expected fields.

Requires:
    - Active Azure credentials (az login)
    - VoiceLive endpoint (AZURE_VOICELIVE_ENDPOINT env var)
    - Foundry project endpoint (.env or PROJECT_ENDPOINT env var)
    - Sample dataset: sample_evaluation_input/Eiffel_Tower_Visit_1/

Usage:
    python evaluation_harness/tests/test_e2e_full_pipeline.py
    python evaluation_harness/tests/test_e2e_full_pipeline.py --mode realtime
    python evaluation_harness/tests/test_e2e_full_pipeline.py --mode cascaded
    python evaluation_harness/tests/test_e2e_full_pipeline.py --skip-evaluation
    python evaluation_harness/tests/test_e2e_full_pipeline.py --limit 2
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add harness to path
HARNESS_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(HARNESS_DIR))


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATASET_JSONL = HARNESS_DIR / "sample_evaluation_input" / "Eiffel_Tower_Visit_1" / "Eiffel_Tower_Visit_1.jsonl"

# Models: realtime (gpt-realtime) and cascaded (gpt-4.1)
MODES = {
    "realtime": {"model": "gpt-realtime", "label": "Realtime (gpt-realtime)"},
    "cascaded": {"model": "gpt-4.1", "label": "Cascaded (gpt-4.1)"},
}

# Expected output JSONL fields (harness output format)
REQUIRED_OUTPUT_FIELDS = [
    "query", "response", "ground_truth", "transcript",
    "ground_truth_query_used",
]


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def run_pipeline(
    mode: str,
    output_dir: str,
    evaluators: str = "default",
    skip_evaluation: bool = False,
) -> Tuple[bool, str, Dict]:
    """Run the full harness pipeline for a given mode.
    
    Returns (success, output_jsonl_path, stats_dict).
    """
    model = MODES[mode]["model"]
    label = MODES[mode]["label"]
    print(f"\n{'━' * 60}")
    print(f"  Pipeline: {label}")
    print(f"  Dataset: {DATASET_JSONL.name}")
    print(f"  Evaluators: {evaluators}")
    print(f"  Output: {output_dir}")
    print(f"{'━' * 60}\n")

    # Build CLI args (use actual argparse names from voice_agent_audio_input_evaluation.py)
    cli_args = [
        sys.executable,
        str(HARNESS_DIR / "voice_agent_audio_input_evaluation.py"),
        "--test-files", str(DATASET_JSONL),
        "--evaluation-dir", output_dir,
        "--model", model,
        "--evaluators", evaluators,
        "--session-mode", "per-conversation",
    ]
    if skip_evaluation:
        cli_args.extend(["--skip-evaluation"])

    # Run as subprocess (isolates from test process state, inherits env vars)
    import subprocess
    start = time.time()
    env = os.environ.copy()
    result = subprocess.run(
        cli_args,
        capture_output=True,
        text=True,
        cwd=str(HARNESS_DIR),
        timeout=600,  # 10 min max
        env=env,
    )
    elapsed = time.time() - start

    stats = {
        "mode": mode,
        "model": model,
        "elapsed_seconds": round(elapsed, 1),
        "exit_code": result.returncode,
    }

    if result.returncode != 0:
        print(f"  ❌ Pipeline failed (exit code {result.returncode})")
        print(f"  STDERR: {result.stderr[-500:]}" if result.stderr else "  (no stderr)")
        print(f"  STDOUT tail: {result.stdout[-500:]}" if result.stdout else "  (no stdout)")
        return False, "", stats

    # Find output JSONL
    out_path = Path(output_dir)
    jsonl_files = list(out_path.rglob("*.jsonl"))
    if not jsonl_files:
        print(f"  ❌ No output JSONL files found in {output_dir}")
        return False, "", stats

    # Pick the most recent JSONL
    jsonl_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    output_jsonl = str(jsonl_files[0])
    stats["output_file"] = output_jsonl
    stats["output_files_count"] = len(jsonl_files)

    print(f"  ✅ Pipeline completed in {elapsed:.1f}s")
    print(f"  Output: {output_jsonl}")
    return True, output_jsonl, stats


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

def validate_output(jsonl_path: str, mode: str) -> Tuple[bool, Dict]:
    """Validate the output JSONL structure and content."""
    results = {
        "file": jsonl_path,
        "mode": mode,
        "issues": [],
        "entries": 0,
        "fields_ok": True,
    }

    if not os.path.exists(jsonl_path):
        results["issues"].append(f"File not found: {jsonl_path}")
        return False, results

    entries = []
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                entries.append(entry)
            except json.JSONDecodeError as e:
                results["issues"].append(f"Line {line_num}: invalid JSON — {e}")

    results["entries"] = len(entries)
    if not entries:
        results["issues"].append("No entries in output file")
        return False, results

    print(f"\n  Validating {len(entries)} output entries ({mode})...")

    # Check required fields
    for i, entry in enumerate(entries):
        for field in REQUIRED_OUTPUT_FIELDS:
            if field not in entry:
                results["issues"].append(f"Entry {i}: missing '{field}'")
                results["fields_ok"] = False

        # Validate query structure
        if "query" in entry:
            q = entry["query"]
            if not isinstance(q, list):
                results["issues"].append(f"Entry {i}: 'query' not a list")
            elif q:
                roles = [m.get("role") for m in q if isinstance(m, dict)]
                if "system" not in roles:
                    results["issues"].append(f"Entry {i}: no system message in query")
                if "user" not in roles:
                    results["issues"].append(f"Entry {i}: no user message in query")

        # Validate response structure
        if "response" in entry:
            r = entry["response"]
            if not isinstance(r, list):
                results["issues"].append(f"Entry {i}: 'response' not a list")

        # Validate transcript (empty transcripts are warnings for cascaded mode)
        if "transcript" in entry:
            t = entry["transcript"]
            if not isinstance(t, str):
                results["issues"].append(f"Entry {i}: transcript not a string")
            elif len(t.strip()) == 0:
                # Known: gpt-4.1 cascaded occasionally produces empty transcripts
                # on longer audio files due to VAD behavior — treat as warning
                results.setdefault("warnings", []).append(
                    f"Entry {i}: empty transcript (known for cascaded mode)"
                )

        # Validate ground_truth
        if "ground_truth" in entry:
            gt = entry["ground_truth"]
            if not isinstance(gt, str):
                results["issues"].append(f"Entry {i}: ground_truth not a string")

    # Print sample entry structure
    if entries:
        sample = entries[0]
        print(f"  Sample entry fields: {list(sample.keys())}")
        if "query" in sample:
            roles = [m.get("role", "?") for m in sample["query"] if isinstance(m, dict)]
            print(f"  Query roles: {roles}")
        if "response" in sample:
            print(f"  Response messages: {len(sample['response'])}")
        if "transcript" in sample:
            print(f"  Transcript: {sample['transcript'][:80]}...")
        if "ground_truth" in sample:
            print(f"  Ground truth: {sample['ground_truth'][:80]}...")

    ok = len(results["issues"]) == 0
    warnings = results.get("warnings", [])
    if ok:
        msg = f"  ✅ All {len(entries)} entries valid"
        if warnings:
            msg += f" ({len(warnings)} warnings)"
        print(msg)
        for w in warnings:
            print(f"    ⚠️  {w}")
    else:
        print(f"  ❌ {len(results['issues'])} issues found:")
        for issue in results["issues"][:10]:
            print(f"    - {issue}")

    return ok, results


def compare_outputs(realtime_jsonl: str, cascaded_jsonl: str) -> Dict:
    """Compare output structure between realtime and cascaded runs."""
    comparison = {"consistent": True, "differences": []}

    def load_entries(path):
        entries = []
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line))
        return entries

    rt_entries = load_entries(realtime_jsonl) if os.path.exists(realtime_jsonl) else []
    cs_entries = load_entries(cascaded_jsonl) if os.path.exists(cascaded_jsonl) else []

    if not rt_entries or not cs_entries:
        comparison["consistent"] = False
        comparison["differences"].append("Missing entries for comparison")
        return comparison

    # Compare field sets
    rt_fields = set(rt_entries[0].keys())
    cs_fields = set(cs_entries[0].keys())
    if rt_fields != cs_fields:
        comparison["consistent"] = False
        only_rt = rt_fields - cs_fields
        only_cs = cs_fields - rt_fields
        if only_rt:
            comparison["differences"].append(f"Only in realtime: {only_rt}")
        if only_cs:
            comparison["differences"].append(f"Only in cascaded: {only_cs}")
    else:
        print(f"\n  ✅ Field sets match: {sorted(rt_fields)}")

    # Compare query/response structure types
    for field in ["query", "response"]:
        for label, entries in [("realtime", rt_entries), ("cascaded", cs_entries)]:
            for i, e in enumerate(entries):
                if field in e:
                    val = e[field]
                    if isinstance(val, list):
                        for msg in val:
                            if not isinstance(msg, dict):
                                comparison["differences"].append(
                                    f"{label} entry {i}: {field} has non-dict message: {type(msg)}"
                                )
                                comparison["consistent"] = False

    return comparison


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="E2E full pipeline test")
    parser.add_argument("--mode", choices=["realtime", "cascaded", "both"], default="both",
                        help="Which pipeline mode to test (default: both)")
    parser.add_argument("--evaluators", default="default",
                        help="Evaluator selection (default/all/comma-list)")
    parser.add_argument("--skip-evaluation", action="store_true",
                        help="Skip Foundry evaluation (VoiceLive processing only)")
    parser.add_argument("--output-base", default=None,
                        help="Base output directory (default: output/e2e_test/)")
    args = parser.parse_args()

    print("=" * 60)
    print("Evaluation Harness — Full E2E Pipeline Test")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("=" * 60)

    # Check prerequisites
    if not DATASET_JSONL.exists():
        print(f"\n❌ Dataset not found: {DATASET_JSONL}")
        print("   Ensure sample_evaluation_input/Eiffel_Tower_Visit_1/ exists.")
        return 1

    endpoint = os.environ.get("AZURE_VOICELIVE_ENDPOINT") or os.environ.get("AZURE_VOICE_LIVE_ENDPOINT")
    if not endpoint:
        print("\n❌ AZURE_VOICELIVE_ENDPOINT not set — cannot run VoiceLive pipeline")
        return 1
    print(f"\nEndpoint: {endpoint[:40]}...")

    # Determine modes to run
    modes_to_run = ["realtime", "cascaded"] if args.mode == "both" else [args.mode]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_dir = args.output_base or str(HARNESS_DIR / "output" / "e2e_test")

    all_stats = {}
    output_paths = {}

    for mode in modes_to_run:
        out_dir = os.path.join(base_dir, f"{ts}_{mode}")
        os.makedirs(out_dir, exist_ok=True)

        success, jsonl_path, stats = run_pipeline(
            mode=mode,
            output_dir=out_dir,
            evaluators=args.evaluators,
            skip_evaluation=args.skip_evaluation,
        )
        all_stats[mode] = stats

        if success and jsonl_path:
            output_paths[mode] = jsonl_path
            ok, val_results = validate_output(jsonl_path, mode)
            all_stats[mode]["validation"] = val_results
            if not ok:
                all_stats[mode]["validation_passed"] = False
            else:
                all_stats[mode]["validation_passed"] = True
        else:
            all_stats[mode]["validation_passed"] = False

    # Cross-mode comparison
    if len(output_paths) == 2:
        print(f"\n{'━' * 60}")
        print("  Cross-Mode Comparison (realtime vs cascaded)")
        print(f"{'━' * 60}")
        comparison = compare_outputs(output_paths["realtime"], output_paths["cascaded"])
        if comparison["consistent"]:
            print("  ✅ Output structure consistent across modes")
        else:
            print("  ⚠️  Differences found:")
            for diff in comparison["differences"]:
                print(f"    - {diff}")

    # Summary
    print(f"\n{'=' * 60}")
    print("Summary")
    print(f"{'=' * 60}")
    all_passed = True
    for mode, stats in all_stats.items():
        label = MODES[mode]["label"]
        elapsed = stats.get("elapsed_seconds", "?")
        code = stats.get("exit_code", "?")
        valid = stats.get("validation_passed", False)
        status = "✅ PASS" if code == 0 and valid else "❌ FAIL"
        if code != 0 or not valid:
            all_passed = False
        print(f"  {label}: {status} ({elapsed}s, exit={code})")

    # Write stats
    stats_path = os.path.join(base_dir, f"{ts}_e2e_test_stats.json")
    with open(stats_path, 'w', encoding='utf-8') as f:
        json.dump(all_stats, f, indent=2, default=str)
    print(f"\nStats: {stats_path}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
