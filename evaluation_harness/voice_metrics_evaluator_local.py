"""
Voice Metrics Evaluator - Local Testing Script

This script demonstrates how to run the voice metrics evaluators locally
without requiring Azure AI Foundry. Useful for:
- Quick local analysis during development
- Testing evaluation logic before Foundry deployment
- Debugging and validating aggregate data files

Usage:
    python voice_metrics_evaluator_local.py <path_to_aggregate_jsonl>
    
    # Or with Python:
    from voice_metrics_evaluator_local import run_local_evaluation
    stats = run_local_evaluation("path/to/aggregate.jsonl")

Author: Voice Live Evaluation Team
Date: January 2026
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

# Import from the main evaluator module
from voice_metrics_evaluator import (
    analyze_voice_metrics_locally,
    print_voice_metrics_summary,
    EVALUATOR_CONFIGS,
)


def run_local_evaluation(
    data_path: str,
    verbose: bool = False,
    output_file: Optional[str] = None
) -> Dict[str, Any]:
    """
    Run voice metrics evaluation locally on an aggregate JSONL file.
    
    Args:
        data_path: Path to the aggregate JSONL file containing evaluation data
        verbose: If True, print detailed per-record analysis
        output_file: Optional path to save detailed results as JSON
        
    Returns:
        Dict containing aggregated statistics and pass rates
    """
    # Validate input file
    data_path = Path(data_path)
    if not data_path.exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")
    
    if not str(data_path).endswith('.jsonl'):
        print(f"Warning: Expected .jsonl file, got: {data_path.suffix}")
    
    print(f"\n{'='*70}")
    print("VOICE METRICS LOCAL EVALUATION")
    print(f"{'='*70}")
    print(f"Input file: {data_path}")
    print(f"File size: {data_path.stat().st_size / 1024:.1f} KB")
    
    # Load and count records
    with open(data_path, 'r', encoding='utf-8') as f:
        records = [json.loads(line) for line in f if line.strip()]
    print(f"Records loaded: {len(records)}")
    
    # Run analysis
    stats = analyze_voice_metrics_locally(records)
    
    # Verbose output - show per-record details
    if verbose:
        print(f"\n{'-'*70}")
        print("PER-RECORD DETAILS")
        print(f"{'-'*70}")
        
        for i, record in enumerate(records):
            metrics = record.get('metrics', {})
            query = record.get('query', [])
            
            # Extract metrics
            trans_lat = metrics.get('turn-audio-transcription-latency-in-seconds')
            resp_lat = metrics.get('turn-audio-resonse-latency-in-seconds')
            audio_recv = metrics.get('audio_response_received')
            actual_turn = metrics.get('logical_turn_number')
            
            # Count expected turn from query
            expected_turn = sum(1 for msg in query if isinstance(msg, dict) and msg.get('role') == 'user')
            
            # Get user message preview
            user_msg = "N/A"
            for msg in reversed(query):
                if isinstance(msg, dict) and msg.get('role') == 'user':
                    content = msg.get('content', '')
                    if isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and c.get('type') == 'text':
                                user_msg = c.get('text', '')[:50]
                                break
                    elif isinstance(content, str):
                        user_msg = content[:50]
                    break
            
            print(f"\nRecord {i+1}:")
            print(f"  Query: \"{user_msg}...\"" if len(user_msg) == 50 else f"  Query: \"{user_msg}\"")
            print(f"  Transcription Latency: {trans_lat:.3f}s" if trans_lat else "  Transcription Latency: N/A")
            print(f"  Response Latency: {resp_lat:.3f}s" if resp_lat else "  Response Latency: N/A")
            print(f"  Audio Delivered: {audio_recv}")
            print(f"  Turn: expected={expected_turn}, actual={actual_turn}")
    
    # Print summary
    print_voice_metrics_summary(stats)
    
    # Save detailed results if requested
    if output_file:
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create detailed output
        detailed_results = {
            "input_file": str(data_path),
            "total_records": stats['total_records'],
            "individual_pass_rates": stats.get('individual_pass_rates', {}),
            "transcription_latency": stats['transcription_latency'],
            "response_latency": stats['response_latency'],
            "audio_delivery": stats['audio_delivery'],
            "turn_alignment": stats.get('turn_alignment', {}),
            "turns": stats['turns'],
            "io_balance": stats.get('io_balance', {}),
            "legacy_combined_pass_rate": stats['estimated_pass_rate'],
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(detailed_results, f, indent=2)
        print(f"\nDetailed results saved to: {output_path}")
    
    return stats


def simulate_evaluator_grades(data_path: str) -> Dict[str, List[Dict]]:
    """
    Simulate running each individual evaluator locally.
    Returns the grade results as they would appear in Foundry.
    
    Args:
        data_path: Path to the aggregate JSONL file
        
    Returns:
        Dict with evaluator names as keys and lists of grade results as values
    """
    # Load data
    with open(data_path, 'r', encoding='utf-8') as f:
        records = [json.loads(line) for line in f if line.strip()]
    
    results = {
        "transcription_latency": [],
        "response_latency": [],
        "audio_delivery": [],
        "turn_alignment": [],
    }
    
    for record in records:
        metrics = record.get('metrics', {})
        query = record.get('query', [])
        
        # Extract metrics
        trans_lat = metrics.get('turn-audio-transcription-latency-in-seconds')
        resp_lat = metrics.get('turn-audio-resonse-latency-in-seconds')
        audio_recv = metrics.get('audio_response_received')
        actual_turn = metrics.get('logical_turn_number')
        inputs_in_turn = metrics.get('inputs_in_turn')
        
        # Count expected turn
        expected_turn = sum(1 for msg in query if isinstance(msg, dict) and msg.get('role') == 'user')
        
        # Simulate Transcription Latency Evaluator
        if trans_lat is not None:
            if trans_lat <= 0.3:
                grade = {"result": 1.0, "label": "excellent", "latency_seconds": trans_lat}
            elif trans_lat <= 0.5:
                grade = {"result": 0.8, "label": "good", "latency_seconds": trans_lat}
            elif trans_lat <= 1.0:
                grade = {"result": 0.5, "label": "acceptable", "latency_seconds": trans_lat}
            else:
                grade = {"result": 0.2, "label": "slow", "latency_seconds": trans_lat}
            results["transcription_latency"].append(grade)
        
        # Simulate Response Latency Evaluator
        if resp_lat is not None:
            if resp_lat <= 1.0:
                grade = {"result": 1.0, "label": "excellent", "latency_seconds": resp_lat}
            elif resp_lat <= 2.0:
                grade = {"result": 0.8, "label": "good", "latency_seconds": resp_lat}
            elif resp_lat <= 3.0:
                grade = {"result": 0.5, "label": "acceptable", "latency_seconds": resp_lat}
            else:
                grade = {"result": 0.2, "label": "slow", "latency_seconds": resp_lat}
            results["response_latency"].append(grade)
        
        # Simulate Audio Delivery Evaluator
        if audio_recv is not None:
            if audio_recv is True or str(audio_recv).lower() == 'true':
                grade = {"result": 1.0, "label": "delivered"}
            else:
                grade = {"result": 0.0, "label": "not_delivered"}
            results["audio_delivery"].append(grade)
        
        # Simulate Turn Alignment Evaluator
        if expected_turn and actual_turn:
            actual = int(actual_turn)
            expected = int(expected_turn)
            
            if actual == expected:
                grade = {"result": 1.0, "label": "aligned", "expected": expected, "actual": actual}
            elif actual == expected + 1 and inputs_in_turn and int(inputs_in_turn) > 1:
                grade = {"result": 0.8, "label": "shifted", "expected": expected, "actual": actual}
            elif actual > expected:
                grade = {"result": max(0.3, 1.0 - (actual - expected) * 0.2), "label": "extra_turns", "expected": expected, "actual": actual}
            else:
                grade = {"result": max(0.3, 1.0 - (expected - actual) * 0.2), "label": "missing_turns", "expected": expected, "actual": actual}
            results["turn_alignment"].append(grade)
    
    return results


def print_simulated_grades(grades: Dict[str, List[Dict]]) -> None:
    """Print simulated evaluator grades in a readable format."""
    print(f"\n{'='*70}")
    print("SIMULATED EVALUATOR GRADES (as would appear in Foundry)")
    print(f"{'='*70}")
    
    for evaluator_name, grade_list in grades.items():
        config = EVALUATOR_CONFIGS.get(evaluator_name, {})
        display_name = config.get('display_name', evaluator_name)
        
        print(f"\n{display_name}")
        print(f"{'-'*50}")
        
        if not grade_list:
            print("  No grades")
            continue
        
        # Calculate pass rate
        pass_count = sum(1 for g in grade_list if g.get('result', 0) >= 0.5)
        total = len(grade_list)
        pass_rate = pass_count / total if total > 0 else 0
        
        # Count by label
        label_counts = {}
        for g in grade_list:
            label = g.get('label', 'unknown')
            label_counts[label] = label_counts.get(label, 0) + 1
        
        print(f"  Total grades: {total}")
        print(f"  Pass rate: {pass_rate*100:.1f}%")
        print(f"  Label distribution:")
        for label, count in sorted(label_counts.items()):
            print(f"    - {label}: {count}")


def main():
    """Main entry point for command-line usage."""
    parser = argparse.ArgumentParser(
        description="Run voice metrics evaluation locally on aggregate JSONL files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python voice_metrics_evaluator_local.py path/to/aggregate.jsonl
  
  # Verbose output with per-record details
  python voice_metrics_evaluator_local.py path/to/aggregate.jsonl --verbose
  
  # Save detailed results to JSON
  python voice_metrics_evaluator_local.py path/to/aggregate.jsonl --output results.json
  
  # Simulate individual evaluator grades
  python voice_metrics_evaluator_local.py path/to/aggregate.jsonl --simulate-grades
        """
    )
    
    parser.add_argument(
        "data_path",
        help="Path to the aggregate JSONL file to evaluate"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print detailed per-record analysis"
    )
    parser.add_argument(
        "--output", "-o",
        help="Save detailed results to JSON file"
    )
    parser.add_argument(
        "--simulate-grades", "-s",
        action="store_true",
        help="Simulate and print individual evaluator grades"
    )
    
    args = parser.parse_args()
    
    try:
        # Run main evaluation
        stats = run_local_evaluation(
            data_path=args.data_path,
            verbose=args.verbose,
            output_file=args.output
        )
        
        # Optionally simulate grades
        if args.simulate_grades:
            grades = simulate_evaluator_grades(args.data_path)
            print_simulated_grades(grades)
        
        # Return exit code based on pass rate
        ipr = stats.get('individual_pass_rates', {})
        all_pass = all(
            pr.get('pass_rate', 0) >= 0.9
            for pr in ipr.values()
            if pr.get('total', 0) > 0
        )
        
        if all_pass:
            print("\n✓ All evaluators have >=90% pass rate")
            sys.exit(0)
        else:
            print("\n⚠ Some evaluators have <90% pass rate")
            sys.exit(1)
            
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(2)
    except Exception as e:
        print(f"Error during evaluation: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(3)


if __name__ == "__main__":
    main()
