"""
Voice Live Evaluation Agent

An intelligent agent for automating Voice Live evaluation workflows using Azure AI Agents SDK.
Supports dataset validation, VoiceLive audio testing, and workflow orchestration through
natural language commands.

Key Principle: All API calls use Azure Identity - NO API KEYS.

Usage:
    python agent.py                          # Interactive mode
    python agent.py --message "Validate dataset X"  # Single message mode
    
Tracing/Logging:
    Set APPLICATIONINSIGHTS_CONNECTION_STRING for Azure Monitor tracing
    Otherwise, uses console tracing for local development
    Set EVAL_AGENT_LOG_LEVEL=DEBUG for verbose logging
"""

import os
import sys
import json
import subprocess
import threading
import queue
import time
import argparse
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import FunctionTool, ToolSet, AgentEventHandler

# Load .env file from the same directory as this script
SCRIPT_DIR = Path(__file__).parent
load_dotenv(SCRIPT_DIR / ".env")

# Add parent directory to path for imports
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

# Import tracing module - must be after path setup
from tracing import (
    setup_tracing, get_tracer, get_logger, get_conversation_logger,
    trace_tool_function, log_tool_execution, ToolCall, get_log_directory
)


# =============================================================================
# Agent Storage Configuration
# =============================================================================

def get_agent_output_directory() -> Path:
    """
    Get the agent's default output directory for evaluation results.
    
    Uses EVAL_AGENT_OUTPUT_DIR environment variable if set, otherwise defaults
    to ./output relative to the agent script directory.
    
    For cloud deployment, set EVAL_AGENT_OUTPUT_DIR to a cloud storage path
    (e.g., Azure Blob mounted path or shared file system).
    """
    env_path = os.environ.get("EVAL_AGENT_OUTPUT_DIR")
    if env_path:
        output_dir = Path(env_path)
    else:
        # Default to agent's local output directory
        output_dir = SCRIPT_DIR / "output"
    
    # Ensure directory exists
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


# =============================================================================
# Tool Functions - These wrap our existing validation/evaluation scripts
# =============================================================================

def validate_dataset_consistency(
    dataset_path: str,
    expected_turns: Optional[int] = None,
    ignore_comments: bool = False
) -> str:
    """
    Validates JSONL dataset for structural integrity and completeness.
    This is a MANDATORY check that must pass before running quality validation
    or voice agent evaluations.

    Args:
        dataset_path: Path to JSONL file or dataset folder
        expected_turns: If specified, validates all conversations have exactly N turns
        ignore_comments: Skip lines starting with // or # (non-standard JSONL)

    Returns:
        JSON string with validation results including status, errors, and warnings
    """
    dataset_name = Path(dataset_path).name
    print(f"\n⚙️  Running consistency validation on {dataset_name}...", flush=True)
    
    script_path = REPO_ROOT / "dataset_validator" / "validate_dataset_consistency.py"
    
    cmd = [sys.executable, str(script_path), dataset_path]
    if expected_turns is not None:
        cmd.extend(["--expected-turns", str(expected_turns)])
    if ignore_comments:
        cmd.append("--ignore-comments")
    
    # Set up environment with UTF-8 encoding
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=120,
            cwd=str(REPO_ROOT),
            env=env
        )
        
        status = "passed" if result.returncode == 0 else "failed"
        status_msg = f"✓ Consistency validation {status.upper()}" if status == "passed" else f"✗ Consistency validation {status.upper()}"
        print(f"{status_msg}", flush=True)
        
        return json.dumps({
            "action": "validate_dataset_consistency",
            "status": status,
            "status_message": f"{status_msg} for {dataset_name}",
            "exit_code": result.returncode,
            "output": result.stdout,
            "errors": result.stderr if result.returncode != 0 else None
        })
    except subprocess.TimeoutExpired:
        print("⚠ Consistency validation timed out", flush=True)
        return json.dumps({
            "action": "validate_dataset_consistency",
            "status": "error",
            "status_message": "⚠ Consistency validation timed out after 120 seconds",
            "error": "Validation timed out after 120 seconds"
        })
    except Exception as e:
        print(f"✗ Consistency validation error: {str(e)[:50]}", flush=True)
        return json.dumps({
            "action": "validate_dataset_consistency",
            "status": "error",
            "status_message": f"✗ Consistency validation error: {str(e)[:50]}",
            "error": str(e)
        })


def check_dataset_schema(dataset_path: str) -> str:
    """
    Analyzes a JSONL dataset to check for required and optional fields.
    Use this BEFORE running full validation to identify missing optional metadata
    that will use defaults during evaluation.
    
    Required fields (evaluation will FAIL without these):
    - WavPath or audio: Path to audio file
    
    Optional fields (evaluation uses defaults if missing):
    - Question/question: User query transcript (default: None)
    - Answer/answer: Expected response for evaluation (default: None)
    - tool_definitions: Available tools (default: [])
    - conversationID/conversation_id: Conversation grouping (default: 'default')
    - system_prompt: Agent instructions (default: script default)
    
    Args:
        dataset_path: Path to JSONL file or folder containing JSONL
        
    Returns:
        JSON with schema analysis, missing optional fields, and whether evaluation can proceed
    """
    log_tool_execution("check_dataset_schema", "started", {"dataset_path": dataset_path})
    print(f"\n⚙️  Checking dataset schema...", flush=True)
    
    script_path = REPO_ROOT / "dataset_validator" / "check_dataset_schema.py"
    
    cmd = [sys.executable, str(script_path), dataset_path, "--json"]
    
    # Set up environment with UTF-8 encoding
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=60,
            cwd=str(REPO_ROOT),
            env=env
        )
        
        # Parse JSON output from script
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            log_tool_execution("check_dataset_schema", "failed", {"error": "parse_error"})
            return json.dumps({
                "action": "check_dataset_schema",
                "status": "error",
                "status_message": "✗ Failed to parse schema check output",
                "error": result.stderr or result.stdout
            })
        
        # Add action field and create status message
        parsed["action"] = "check_dataset_schema"
        
        if parsed.get("status") == "passed":
            status_msg = f"✓ All fields present ({parsed.get('total_entries', 0)} entries)"
            print(status_msg, flush=True)
        elif parsed.get("status") == "warnings":
            missing_count = len(parsed.get("optional_missing", []))
            status_msg = f"⚠ Dataset valid but {missing_count} optional field(s) missing - will use defaults"
            print(status_msg, flush=True)
        elif parsed.get("status") == "failed":
            status_msg = "✗ Missing required fields - cannot proceed"
            print(status_msg, flush=True)
        else:
            status_msg = f"✗ Schema check error"
            print(status_msg, flush=True)
        
        parsed["status_message"] = status_msg
        parsed["can_proceed_with_evaluation"] = parsed.get("can_proceed", False)
        
        # Add recommendation for agent
        if not parsed.get("can_proceed"):
            parsed["recommendation"] = "STOP: Fix required fields before evaluation"
        elif parsed.get("has_optional_missing"):
            parsed["recommendation"] = "ASK USER: Optional fields missing - confirm to proceed with defaults"
        else:
            parsed["recommendation"] = "PROCEED: All fields present"
        
        log_tool_execution("check_dataset_schema", "completed", {
            "status": parsed.get("status"),
            "can_proceed": parsed.get("can_proceed"),
            "entries": parsed.get("total_entries", 0)
        })
        return json.dumps(parsed)
        
    except subprocess.TimeoutExpired:
        log_tool_execution("check_dataset_schema", "failed", {"error": "timeout"})
        print("⚠ Schema check timed out", flush=True)
        return json.dumps({
            "action": "check_dataset_schema",
            "status": "error",
            "status_message": "⚠ Schema check timed out after 60 seconds",
            "error": "Schema check timed out"
        })
    except Exception as e:
        log_tool_execution("check_dataset_schema", "failed", {"error": str(e)[:100]})
        print(f"✗ Schema check error: {str(e)[:50]}", flush=True)
        return json.dumps({
            "action": "check_dataset_schema",
            "status": "error",
            "status_message": f"✗ Schema check error: {str(e)[:50]}",
            "error": str(e)
        })


def validate_dataset_quality(
    dataset_path: str,
    strict: bool = False,
    verbose: bool = False,
    json_output: Optional[str] = None,
    ignore_comments: bool = False
) -> str:
    """
    Validates content quality and appropriateness of JSONL voice agent datasets.
    This is an ADVISORY check that should run AFTER consistency validation passes.
    
    Assesses system prompt relevance, tool definition appropriateness,
    question intent classification, and content quality metrics.

    Args:
        dataset_path: Path to JSONL file or dataset folder
        strict: Use strict keyword-only alignment matching (conservative ~50% vs ~88%)
        verbose: Show detailed per-conversation analysis
        json_output: Export results to JSON file path
        ignore_comments: Skip lines starting with // or # (non-standard JSONL)

    Returns:
        JSON string with quality assessment including alignment percentage and recommendations
    """
    dataset_name = Path(dataset_path).name
    print(f"\n⚙️  Running quality validation on {dataset_name}...", flush=True)
    
    script_path = REPO_ROOT / "dataset_validator" / "validate_dataset_quality.py"
    
    cmd = [sys.executable, str(script_path), dataset_path]
    if strict:
        cmd.append("--strict")
    if verbose:
        cmd.append("--verbose")
    if json_output:
        cmd.extend(["--json", json_output])
    if ignore_comments:
        cmd.append("--ignore-comments")
    
    # Set up environment with UTF-8 encoding
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=120,
            cwd=str(REPO_ROOT),
            env=env
        )
        
        status = "completed" if result.returncode == 0 else "failed"
        status_msg = f"✓ Quality validation {status.upper()}" if status == "completed" else f"✗ Quality validation {status.upper()}"
        print(f"{status_msg}", flush=True)
        
        return json.dumps({
            "action": "validate_dataset_quality",
            "status": status,
            "status_message": f"{status_msg} for {dataset_name}",
            "exit_code": result.returncode,
            "output": result.stdout,
            "errors": result.stderr if result.returncode != 0 else None
        })
    except subprocess.TimeoutExpired:
        print("⚠ Quality validation timed out", flush=True)
        return json.dumps({
            "action": "validate_dataset_quality",
            "status": "error",
            "status_message": "⚠ Quality validation timed out after 120 seconds",
            "error": "Quality validation timed out after 120 seconds"
        })
    except Exception as e:
        print(f"✗ Quality validation error: {str(e)[:50]}", flush=True)
        return json.dumps({
            "action": "validate_dataset_quality",
            "status": "error",
            "status_message": f"✗ Quality validation error: {str(e)[:50]}",
            "error": str(e)
        })


def _detect_session_mode(dataset_path: str) -> str:
    """
    Auto-detect the appropriate session mode based on dataset structure.
    
    - If dataset has conversationID field → 'per-conversation'
    - If dataset doesn't have conversationID → 'per-file'
    """
    try:
        path = Path(dataset_path)
        if path.suffix.lower() != '.jsonl':
            # Not a JSONL file, default to per-file
            return "per-file"
        
        # Check first few lines for conversationID field
        with open(path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                if i >= 5:  # Check first 5 lines
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if 'conversationID' in entry and entry['conversationID']:
                        return "per-conversation"
                except json.JSONDecodeError:
                    continue
        
        # No conversationID found
        return "per-file"
    except Exception:
        return "per-file"


def _count_dataset_entries(dataset_path: str) -> int:
    """Count the number of entries in a JSONL dataset."""
    try:
        path = Path(dataset_path)
        if path.suffix.lower() == '.jsonl':
            with open(path, 'r', encoding='utf-8') as f:
                return sum(1 for line in f if line.strip())
        return 0
    except Exception:
        return 0


def _run_subprocess_with_progress(cmd: list, timeout_seconds: int, env: dict, cwd: str) -> dict:
    """
    Run a subprocess with real-time progress tracking.
    Returns dict with status, output, progress_updates, and any errors.
    """
    progress_updates = []
    output_lines = []
    error_lines = []
    start_time = time.time()
    
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=cwd,
            env=env
        )
        
        # Use threads to read stdout and stderr without blocking
        stdout_queue = queue.Queue()
        stderr_queue = queue.Queue()
        
        def read_stdout():
            for line in process.stdout:
                stdout_queue.put(line)
            stdout_queue.put(None)  # Signal end
        
        def read_stderr():
            for line in process.stderr:
                stderr_queue.put(line)
            stderr_queue.put(None)  # Signal end
        
        stdout_thread = threading.Thread(target=read_stdout, daemon=True)
        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        
        # Track progress
        files_processed = 0
        current_file = ""
        stdout_done = False
        stderr_done = False
        report_url = None  # Capture Foundry portal URL if present
        
        while not (stdout_done and stderr_done):
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                process.kill()
                return {
                    "status": "timeout",
                    "output": "\n".join(output_lines[-50:]),
                    "errors": "\n".join(error_lines[-20:]),
                    "progress_updates": progress_updates,
                    "files_processed": files_processed,
                    "elapsed_seconds": elapsed,
                    "report_url": report_url
                }
            
            # Read from stdout
            try:
                while True:
                    line = stdout_queue.get_nowait()
                    if line is None:
                        stdout_done = True
                        break
                    output_lines.append(line.rstrip())
                    
                    # Parse progress info from output
                    lower_line = line.lower()
                    if 'processing' in lower_line or 'evaluating' in lower_line:
                        current_file = line.strip()
                        progress_updates.append({
                            "time": round(elapsed, 1),
                            "message": current_file[:100]
                        })
                    elif 'completed' in lower_line or 'finished' in lower_line or 'done' in lower_line:
                        files_processed += 1
                        progress_updates.append({
                            "time": round(elapsed, 1),
                            "message": f"Completed item {files_processed}"
                        })
                    
                    # Capture Foundry portal report URL
                    if 'report_url' in lower_line or 'report url' in lower_line:
                        # Extract URL from lines like "Eval Run Report URL: https://..."
                        import re
                        url_match = re.search(r'https?://[^\s]+', line)
                        if url_match:
                            report_url = url_match.group(0)
            except queue.Empty:
                pass
            
            # Read from stderr
            try:
                while True:
                    line = stderr_queue.get_nowait()
                    if line is None:
                        stderr_done = True
                        break
                    error_lines.append(line.rstrip())
            except queue.Empty:
                pass
            
            time.sleep(0.1)
        
        # Wait for process to complete
        process.wait()
        
        return {
            "status": "completed" if process.returncode == 0 else "failed",
            "exit_code": process.returncode,
            "output": "\n".join(output_lines[-100:]),  # Keep last 100 lines
            "errors": "\n".join(error_lines) if process.returncode != 0 else None,
            "progress_updates": progress_updates,
            "files_processed": files_processed,
            "elapsed_seconds": round(time.time() - start_time, 1),
            "report_url": report_url
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "progress_updates": progress_updates,
            "elapsed_seconds": round(time.time() - start_time, 1),
            "report_url": None
        }


def run_voicelive_evaluation(
    test_files_path: str,
    output_dir: Optional[str] = None,
    evaluation_dir: Optional[str] = None,
    session_mode: Optional[str] = None,
    session_suffix: Optional[str] = None,
    verbose: bool = False,
    timeout_minutes: int = 30,
    max_workers: Optional[int] = None,
    parallel: bool = True
) -> str:
    """
    Runs Azure VoiceLive audio evaluation tests using test audio files and datasets.
    Processes audio through VoiceLive API and captures evaluation metrics including
    transcription accuracy, response quality, latency, and tool usage.
    
    Supports parallel processing for faster evaluation of large datasets.

    IMPORTANT: Run dataset validation BEFORE using this function.

    Args:
        test_files_path: Path to audio test file (.wav) or dataset file (.jsonl)
        output_dir: Directory for audio output files (default: agent's output directory)
        evaluation_dir: Directory for evaluation result files (default: agent's output directory)
        session_mode: Session handling mode. If not specified, auto-detected:
                      - 'per-conversation': Auto-selected if dataset has conversationID field
                      - 'per-file': Auto-selected if no conversationID field
                      - 'single': Only used when explicitly requested by user (disables parallelism)
        session_suffix: Suffix for session tracking in batch mode (e.g., conv-1, session-2)
        verbose: Enable verbose/debug logging
        timeout_minutes: Maximum time to wait for evaluation (default: 30 minutes)
        max_workers: Number of parallel workers for processing sessions.
                     Default: 4 for local, can be increased for cloud execution.
                     Set to 1 for sequential processing. Ignored if session_mode='single'.
        parallel: Enable parallel processing (default: True). Set to False for sequential.

    Returns:
        JSON string with evaluation results including success status and output paths
    """
    # Use agent's default output directory if not specified
    agent_output = get_agent_output_directory()
    if output_dir is None:
        output_dir = str(agent_output)
    if evaluation_dir is None:
        evaluation_dir = str(agent_output)
    
    # Determine which script to use based on parallelism needs
    batch_processor_path = REPO_ROOT / "prototype_v1" / "batch_processor.py"
    single_script_path = REPO_ROOT / "prototype_v1" / "voice_agent_audio_input_evaluation.py"
    
    test_path = Path(test_files_path)
    
    # Check if dataset exists
    if not test_path.exists():
        print(f"\n✗ Dataset not found: {test_files_path}", flush=True)
        return json.dumps({
            "action": "run_voicelive_evaluation",
            "status": "error",
            "status_message": f"✗ Dataset not found: {test_files_path}",
            "error": f"Test files path does not exist: {test_files_path}"
        })
    
    # If path is a directory, find the .jsonl file inside
    if test_path.is_dir():
        jsonl_files = list(test_path.glob("*.jsonl"))
        if jsonl_files:
            test_path = jsonl_files[0]  # Use first .jsonl file found
            print(f"\n📁 Folder provided, using: {test_path.name}", flush=True)
        else:
            print(f"\n✗ No .jsonl file found in folder: {test_files_path}", flush=True)
            return json.dumps({
                "action": "run_voicelive_evaluation",
                "status": "error",
                "status_message": f"✗ No .jsonl file found in folder",
                "error": f"No .jsonl dataset file found in: {test_files_path}"
            })
    
    dataset_name = test_path.name
    test_files_path = str(test_path)
    
    # Count entries for progress tracking
    total_entries = _count_dataset_entries(test_files_path)
    
    # Auto-detect session mode if not specified
    if session_mode is None:
        session_mode = _detect_session_mode(test_files_path)
        auto_detected = True
    else:
        auto_detected = False
    
    # Determine effective worker count
    # Single mode always uses 1 worker (no parallelism by design)
    # Default to 4 workers for local execution (balance performance vs resource usage)
    if session_mode == 'single' or not parallel:
        effective_workers = 1
    elif max_workers is not None:
        effective_workers = max(1, max_workers)
    else:
        # Default: 4 workers for local, can be overridden via env var for cloud
        default_workers = int(os.environ.get('EVAL_AGENT_MAX_WORKERS', '4'))
        effective_workers = min(default_workers, total_entries)  # Don't exceed entry count
    
    # Decide whether to use batch processor or single script
    use_batch_processor = effective_workers > 1 and batch_processor_path.exists()
    
    # Log evaluation start with tracing
    log_tool_execution("run_voicelive_evaluation", "started", {
        "dataset": dataset_name,
        "entries": total_entries,
        "session_mode": session_mode,
        "auto_detected": auto_detected,
        "timeout_minutes": timeout_minutes,
        "max_workers": effective_workers,
        "parallel": use_batch_processor
    })
    
    mode_info = f" (auto-detected)" if auto_detected else ""
    parallel_info = f" | Workers: {effective_workers}" if effective_workers > 1 else ""
    print(f"\n⚙️  Starting VoiceLive evaluation on {dataset_name}...", flush=True)
    print(f"   Session mode: {session_mode}{mode_info}{parallel_info}", flush=True)
    print(f"   Entries: {total_entries}", flush=True)
    print(f"   Timeout: {timeout_minutes} minutes", flush=True)
    
    # Build command based on execution mode
    if use_batch_processor:
        # Use batch processor for parallel execution
        print(f"   Mode: Parallel (batch processor)", flush=True)
        cmd = [
            sys.executable, str(batch_processor_path),
            "--test-files", test_files_path,
            "--session-mode", session_mode,
            "--max-workers", str(effective_workers),
            "--timeout", str(timeout_minutes * 60),  # Convert to seconds
            "--output-dir", output_dir,
            "--evaluation", evaluation_dir
        ]
        if verbose:
            cmd.append("--verbose")
    else:
        # Use single evaluation script (sequential)
        print(f"   Mode: Sequential", flush=True)
        cmd = [
            sys.executable, str(single_script_path),
            "--test-files", test_files_path,
            "--output-dir", output_dir,
            "--evaluation", evaluation_dir,
            "--session-mode", session_mode
        ]
        if session_suffix:
            cmd.extend(["--session-suffix", session_suffix])
        if verbose:
            cmd.append("--verbose")
    
    # Set up environment with UTF-8 encoding
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    timeout_seconds = timeout_minutes * 60
    
    # Use progress tracking for the subprocess
    result = _run_subprocess_with_progress(cmd, timeout_seconds, env, str(REPO_ROOT))
    
    # Build response with progress info
    if result["status"] == "completed":
        status_msg = f"✓ Evaluation COMPLETED for {dataset_name}"
        if result.get("elapsed_seconds"):
            status_msg += f" ({result['elapsed_seconds']}s)"
        if effective_workers > 1:
            status_msg += f" [parallel: {effective_workers} workers]"
        print(f"\n{status_msg}", flush=True)
        
        # Display Foundry portal URL if available
        if result.get("report_url"):
            print(f"\n📊 View results in AI Foundry Portal:", flush=True)
            print(f"   {result['report_url']}", flush=True)
    elif result["status"] == "timeout":
        status_msg = f"⚠ Evaluation TIMED OUT after {timeout_minutes} minutes for {dataset_name}"
        print(f"\n{status_msg}", flush=True)
    elif result["status"] == "failed":
        status_msg = f"✗ Evaluation FAILED for {dataset_name}"
        print(f"\n{status_msg}", flush=True)
    else:
        status_msg = f"✗ Evaluation ERROR for {dataset_name}"
        print(f"\n{status_msg}", flush=True)
    
    # Log completion with metrics
    log_tool_execution("run_voicelive_evaluation", "completed", {
        "status": result["status"],
        "elapsed_seconds": result.get("elapsed_seconds"),
        "files_processed": result.get("files_processed", 0),
        "dataset": dataset_name,
        "max_workers": effective_workers,
        "report_url": result.get("report_url")
    })
    
    response = {
        "action": "run_voicelive_evaluation",
        "status": result["status"],
        "status_message": status_msg,
        "dataset": dataset_name,
        "total_entries": total_entries,
        "session_mode": session_mode,
        "session_mode_auto_detected": auto_detected,
        "max_workers": effective_workers,
        "parallel_mode": use_batch_processor,
        "elapsed_seconds": result.get("elapsed_seconds"),
        "files_processed": result.get("files_processed", 0),
        "progress_updates": result.get("progress_updates", [])[-10:],  # Last 10 progress updates
        "output": result.get("output", "")[-2000:],  # Last 2000 chars
        "errors": result.get("errors") if result["status"] != "completed" else None,
        "foundry_portal_url": result.get("report_url")  # AI Foundry Portal link for viewing results
    }
    
    if result["status"] == "timeout":
        response["hint"] = "The evaluation may still be running. Check the output directory for partial results."
    
    return json.dumps(response)


def list_datasets(folder_path: str = None) -> str:
    """
    Lists ALL available JSONL datasets in a folder for evaluation.
    
    IMPORTANT: Always present the COMPLETE list to users. Never summarize or truncate.
    Show every dataset with name, entry count, and folder location.

    Args:
        folder_path: Path to search for datasets. Defaults to common dataset locations.

    Returns:
        JSON string with COMPLETE list of found JSONL files and their basic info.
        Always includes all datasets - never truncated.
    """
    print(f"\n⚙️  Searching for datasets...", flush=True)
    
    search_paths = []
    
    if folder_path:
        search_paths.append(Path(folder_path))
    else:
        # Default search locations
        search_paths.extend([
            REPO_ROOT / "prototype_v1" / "sample_evaluation_input",
            REPO_ROOT / "prototype_v1" / "local_datasets",
            REPO_ROOT / "dataset_validator",
        ])
    
    datasets = []
    searched_locations = []
    for search_path in search_paths:
        searched_locations.append(str(search_path))
        if search_path.exists():
            for jsonl_file in search_path.rglob("*.jsonl"):
                try:
                    line_count = sum(1 for _ in open(jsonl_file, 'r', encoding='utf-8'))
                    # Check for conversationID to indicate session mode
                    has_conversation_id = _detect_session_mode(str(jsonl_file)) == "per-conversation"
                    datasets.append({
                        "path": str(jsonl_file),
                        "name": jsonl_file.stem,
                        "folder": str(jsonl_file.parent),
                        "entries": line_count,
                        "has_conversation_id": has_conversation_id,
                        "recommended_mode": "per-conversation" if has_conversation_id else "per-file"
                    })
                except Exception as e:
                    datasets.append({
                        "path": str(jsonl_file),
                        "name": jsonl_file.stem,
                        "error": str(e)
                    })
    
    existing_locations = len([p for p in search_paths if p.exists()])
    print(f"✓ Found {len(datasets)} datasets in {existing_locations} locations", flush=True)
    
    return json.dumps({
        "action": "list_datasets",
        "status": "success",
        "status_message": f"✓ Found {len(datasets)} datasets in {existing_locations} locations",
        "searched_locations": searched_locations,
        "datasets_found": len(datasets),
        "datasets": datasets
    })


def analyze_evaluation_results(results_path: str) -> str:
    """
    Analyzes VoiceLive evaluation output files to extract insights and metrics.
    
    Use this tool for evaluation OUTPUT files (from run_voicelive_evaluation), 
    NOT for input datasets. Evaluation outputs contain metrics like groundedness,
    relevance, task completion, latency, etc.
    
    Args:
        results_path: Path to evaluation output file (.jsonl) or directory containing results
        
    Returns:
        JSON string with analysis including aggregated metrics, insights, and recommendations
    """
    print(f"\n⚙️  Analyzing evaluation results...", flush=True)
    
    results_file = Path(results_path)
    
    if not results_file.exists():
        print(f"✗ File not found: {results_path}", flush=True)
        return json.dumps({
            "action": "analyze_evaluation_results",
            "status": "error",
            "status_message": f"✗ File not found: {results_path}",
            "error": f"Results file does not exist: {results_path}"
        })
    
    # If path is a directory, find the evaluation output file inside
    if results_file.is_dir():
        # Look for aggregate files first, then any .jsonl files
        aggregate_files = list(results_file.glob("*aggregate*.jsonl"))
        if aggregate_files:
            results_file = aggregate_files[0]
            print(f"📁 Folder provided, using: {results_file.name}", flush=True)
        else:
            jsonl_files = list(results_file.glob("*.jsonl"))
            if jsonl_files:
                results_file = jsonl_files[0]
                print(f"📁 Folder provided, using: {results_file.name}", flush=True)
            else:
                print(f"✗ No .jsonl file found in folder: {results_path}", flush=True)
                return json.dumps({
                    "action": "analyze_evaluation_results",
                    "status": "error",
                    "status_message": f"✗ No .jsonl file found in folder",
                    "error": f"No evaluation results file found in: {results_path}"
                })
    
    try:
        # Read the file - evaluation outputs can be concatenated JSON objects
        content = results_file.read_text(encoding='utf-8')
        
        # Parse concatenated JSON objects (common format for eval outputs)
        entries = []
        decoder = json.JSONDecoder()
        idx = 0
        while idx < len(content):
            content_sub = content[idx:].lstrip()
            if not content_sub:
                break
            try:
                obj, end = decoder.raw_decode(content_sub)
                entries.append(obj)
                idx += len(content) - len(content_sub) + end
            except json.JSONDecodeError:
                # Try JSONL format as fallback
                break
        
        # If concatenated JSON didn't work, try JSONL
        if not entries:
            for line in content.strip().split('\n'):
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        
        if not entries:
            print(f"✗ No valid entries found in file", flush=True)
            return json.dumps({
                "action": "analyze_evaluation_results",
                "status": "error", 
                "status_message": "✗ No valid entries found in file",
                "error": "Could not parse any valid JSON entries from the file"
            })
        
        # Dynamically collect ALL metrics from entries (including custom metrics)
        metrics_collected = {}  # Will be populated dynamically
        
        turns_analyzed = 0
        conversations = set()
        
        for entry in entries:
            # Track conversation IDs if present
            ds_item = entry.get('datasource_item', {})
            if isinstance(ds_item, dict):
                conv_id = ds_item.get('conversation_id') or ds_item.get('conversationID')
                if conv_id:
                    conversations.add(conv_id)
            
            # Extract ALL metrics from 'results' array (Foundry eval format)
            # This handles both built-in and custom metrics dynamically
            results_list = entry.get('results', [])
            if results_list:
                turns_analyzed += 1
                for result in results_list:
                    if not isinstance(result, dict):
                        continue
                    
                    # Get metric name - normalize to snake_case for consistency
                    metric_name = result.get('name', '')
                    if not metric_name:
                        continue
                    metric_key = metric_name.lower().replace('-', '_').replace(' ', '_')
                    
                    # Get score value
                    score = result.get('score')
                    if score is not None:
                        try:
                            score_float = float(score)
                            if metric_key not in metrics_collected:
                                metrics_collected[metric_key] = {
                                    'values': [],
                                    'original_name': metric_name,
                                    'passed_count': 0,
                                    'failed_count': 0
                                }
                            metrics_collected[metric_key]['values'].append(score_float)
                            
                            # Track pass/fail if available
                            if result.get('passed') is True:
                                metrics_collected[metric_key]['passed_count'] += 1
                            elif result.get('passed') is False:
                                metrics_collected[metric_key]['failed_count'] += 1
                        except (ValueError, TypeError):
                            pass
            
            # Extract latency and other metrics from datasource_item.metrics
            if isinstance(ds_item, dict):
                ds_metrics = ds_item.get('metrics', {})
                if isinstance(ds_metrics, dict):
                    for key, value in ds_metrics.items():
                        if value is None:
                            continue
                        try:
                            value_float = float(value)
                            metric_key = key.lower().replace('-', '_').replace(' ', '_')
                            if metric_key not in metrics_collected:
                                metrics_collected[metric_key] = {
                                    'values': [],
                                    'original_name': key,
                                    'passed_count': 0,
                                    'failed_count': 0
                                }
                            metrics_collected[metric_key]['values'].append(value_float)
                        except (ValueError, TypeError):
                            pass
            
            # Also extract metrics directly from entry (raw evaluation output format)
            direct_metrics = entry.get('metrics', {})
            if isinstance(direct_metrics, dict):
                turns_analyzed += 1  # Count as a turn if it has metrics
                for key, value in direct_metrics.items():
                    if value is None:
                        continue
                    try:
                        value_float = float(value)
                        metric_key = key.lower().replace('-', '_').replace(' ', '_')
                        if metric_key not in metrics_collected:
                            metrics_collected[metric_key] = {
                                'values': [],
                                'original_name': key,
                                'passed_count': 0,
                                'failed_count': 0
                            }
                        metrics_collected[metric_key]['values'].append(value_float)
                    except (ValueError, TypeError):
                        pass
        
        # Calculate aggregates for all discovered metrics
        aggregated = {}
        for metric_key, data in metrics_collected.items():
            values = data['values']
            if values:
                metric_info = {
                    "name": data['original_name'],
                    "mean": round(sum(values) / len(values), 3),
                    "min": round(min(values), 3),
                    "max": round(max(values), 3),
                    "count": len(values)
                }
                # Include pass/fail stats if available
                if data['passed_count'] > 0 or data['failed_count'] > 0:
                    total = data['passed_count'] + data['failed_count']
                    metric_info["passed"] = data['passed_count']
                    metric_info["failed"] = data['failed_count']
                    metric_info["pass_rate"] = round(data['passed_count'] / total, 3) if total > 0 else None
                
                aggregated[metric_key] = metric_info
        
        # Generate insights based on common metrics (if present)
        insights = []
        
        # Quality metrics (typically 1-5 scale)
        quality_metrics = ['groundedness', 'relevance', 'response_completeness', 'intent_resolution', 'coherence', 'fluency']
        for metric in quality_metrics:
            if metric in aggregated:
                mean = aggregated[metric]['mean']
                name = aggregated[metric]['name']
                if mean >= 4.0:
                    insights.append(f"✓ Strong {name} ({mean}/5)")
                elif mean < 3.0:
                    insights.append(f"⚠ Low {name} ({mean}/5) - may need improvement")
        
        # Binary/rate metrics (0-1 scale)
        rate_metrics = ['task_completion', 'task_adherence', 'tool_call_success', 'tool_output_utilization']
        for metric in rate_metrics:
            if metric in aggregated:
                mean = aggregated[metric]['mean']
                name = aggregated[metric]['name']
                if mean >= 0.9:
                    insights.append(f"✓ Excellent {name} ({mean*100:.0f}%)")
                elif mean < 0.7:
                    insights.append(f"⚠ {name} is below 70% ({mean*100:.0f}%) - review logic")
        
        # Latency metrics
        latency_keys = [k for k in aggregated.keys() if 'latency' in k.lower() or 'response_time' in k.lower()]
        for metric in latency_keys:
            mean = aggregated[metric]['mean']
            name = aggregated[metric]['name']
            if mean > 3.0:
                insights.append(f"⚠ High {name}: {mean:.2f}s average")
            else:
                insights.append(f"✓ Good {name}: {mean:.2f}s average")
        
        # Custom metrics - report any with low pass rates
        for metric_key, data in aggregated.items():
            if metric_key not in quality_metrics + rate_metrics + latency_keys:
                if 'pass_rate' in data and data['pass_rate'] is not None:
                    if data['pass_rate'] < 0.8:
                        insights.append(f"⚠ {data['name']} pass rate: {data['pass_rate']*100:.0f}%")
        
        print(f"✓ Analyzed {turns_analyzed} turns, {len(aggregated)} metrics from {len(conversations) or 1} conversation(s)", flush=True)
        
        return json.dumps({
            "action": "analyze_evaluation_results",
            "status": "success",
            "status_message": f"✓ Analyzed {turns_analyzed} turns with {len(aggregated)} metrics",
            "file": str(results_file),
            "turns_analyzed": turns_analyzed,
            "conversations": len(conversations) if conversations else 1,
            "metrics_count": len(aggregated),
            "metrics": aggregated,
            "insights": insights
        })
        
    except Exception as e:
        print(f"✗ Analysis error: {str(e)[:50]}", flush=True)
        return json.dumps({
            "action": "analyze_evaluation_results",
            "status": "error",
            "status_message": f"✗ Analysis error: {str(e)[:50]}",
            "error": str(e)
        })


# =============================================================================
# Agent Setup
# =============================================================================

AGENT_INSTRUCTIONS = """You are the Voice Live Evaluation Agent, an intelligent assistant that helps users 
validate datasets and run voice agent evaluations.

## Your Capabilities

1. **Dataset Schema Check** (RECOMMENDED before validation)
   - check_dataset_schema: Quick check for required vs optional fields
   - Only WavPath/audio is REQUIRED - all other fields are optional with defaults
   - If optional fields missing, ASK USER if they want to proceed with defaults

2. **Dataset Validation** (MANDATORY before evaluations)
   - validate_dataset_consistency: Structural integrity checks
   - validate_dataset_quality: Content quality assessment (advisory)

3. **VoiceLive Evaluation**
   - run_voicelive_evaluation: Execute audio tests through VoiceLive API
   - Session mode is AUTO-DETECTED based on dataset structure
   - Default timeout is 30 minutes (use timeout_minutes parameter for longer evaluations)
   - **PARALLEL PROCESSING**: By default uses 4 workers for faster evaluation
     - Use max_workers parameter to adjust (e.g., max_workers=8 for more parallelism)
     - Use max_workers=1 or parallel=False for sequential processing
     - Single session mode always runs sequentially (no parallelism)

4. **Results Analysis**
   - analyze_evaluation_results: Analyze evaluation OUTPUT files (not input datasets!)
   - Extracts metrics like groundedness, relevance, latency, task completion
   - Provides insights and recommendations

5. **Dataset Discovery**
   - list_datasets: Find available datasets in the repository

## Required vs Optional Dataset Fields

**REQUIRED (evaluation fails without these):**
- `WavPath` or `audio`: Path to audio file

**OPTIONAL (uses defaults if missing):**
- `Question`/`question`: User query transcript (default: None)
- `Answer`/`answer`: Expected response for evaluation (default: None, skips ResponseCompleteness)
- `tool_definitions`: Available tools (default: [] no tools)
- `conversationID`/`conversation_id`: Conversation grouping (default: 'default')
- `system_prompt`: Agent instructions (default: script default prompt)

When optional fields are missing, ALWAYS ask the user if they want to proceed with defaults
before running the evaluation.

## Important: Input Datasets vs Output Results

- **Input datasets** (`.jsonl` in sample_evaluation_input/): Use `check_dataset_schema`, `validate_dataset_consistency`, `validate_dataset_quality`
- **Evaluation outputs** (`.jsonl` in output/ folders): Use `analyze_evaluation_results`

Do NOT use validation tools on evaluation output files - they have different formats!

## Session Mode Selection (AUTO-DETECTED)

The session_mode is automatically detected based on dataset structure. DO NOT specify session_mode 
unless the user explicitly requests a specific mode:

- **per-conversation** (auto-selected when dataset has `conversationID` field): Each unique 
  conversationID gets its own session, maintaining context within multi-turn conversations.

- **per-file** (auto-selected when dataset has NO `conversationID` field): Each file evaluated 
  in isolation with no shared context.

- **single** (ONLY when user explicitly requests): All files in one continuous session. 
  NEVER use this mode unless the user specifically asks for it.

**IMPORTANT**: Let the function auto-detect the mode. Only pass session_mode parameter if the 
user explicitly says something like "use single session mode" or "run in single mode".

## Workflow Rules

1. **Check schema before evaluation**: When asked to evaluate, FIRST run check_dataset_schema.
   - If required fields missing → STOP and explain
   - If optional fields missing → ASK USER if they want to proceed with defaults
   - If user confirms or all fields present → proceed to validation

2. **Validate before evaluation**: Run validate_dataset_consistency. If it fails with real 
   errors (not just missing optional fields), explain and stop.

3. **Quality is advisory**: validate_dataset_quality provides insights but doesn't block.

4. **Be helpful with errors**: Explain what's missing/wrong and suggest fixes.

5. **Report progress**: Explain what you're doing at each step.

6. **Always show complete dataset lists**: Never truncate dataset listings.

## Status Messages and Progress Reporting

**IMPORTANT**: Each tool returns a `status_message` field with a quick summary. Always include 
these in your response to keep users informed:
- ✓ indicates success
- ⚠ indicates warnings or timeouts
- ✗ indicates failures

For long-running evaluations, the tool provides:
- `elapsed_seconds`: How long the evaluation took
- `files_processed`: Number of items completed
- `progress_updates`: List of progress milestones

When running evaluations, inform users:
1. That the evaluation is starting and may take several minutes
2. The session mode being used (and whether it was auto-detected)
3. Progress updates if available
4. Final status and where to find results

## Example Workflows

User: "Validate my dataset at C:\\datasets\\test.jsonl"
→ Run check_dataset_schema first
→ If optional fields missing, inform user what's missing and their defaults
→ Run validate_dataset_consistency
→ Run validate_dataset_quality
→ Report comprehensive results

User: "Run full evaluation on dataset X"  
→ Run check_dataset_schema
→ If optional fields missing (e.g., no system_prompt, no conversationID):
  - Tell user: "Dataset is missing optional fields: system_prompt (will use default), 
    conversationID (will treat all as one conversation). Do you want to proceed?"
  - Wait for user confirmation
→ If user confirms OR all fields present:
  - Run validate_dataset_consistency
  - Run validate_dataset_quality (advisory)
  - Run run_voicelive_evaluation
  - Report results

User: "Run evaluation on dataset X using single session mode"
→ Check schema, validate, then run with session_mode="single"

User: "Run evaluation with 8 workers" or "Run faster with more parallelism"
→ Check schema, validate, then run with max_workers=8

User: "Run evaluation sequentially" or "Run without parallelism"
→ Check schema, validate, then run with parallel=False or max_workers=1

User: "What datasets are available?"
→ Run list_datasets
→ Present ALL datasets found (never summarize or truncate)
→ Show name, entry count, and folder for each

User: "Analyze my evaluation results"
→ Run analyze_evaluation_results on the output file
→ Present metrics and insights

User: "Analyze my evaluation results" or "What insights from the evaluation?"
→ Run analyze_evaluation_results on the output file
→ Present metrics (groundedness, relevance, task completion, latency)
→ Provide insights and recommendations

## Parallel Processing

The evaluation supports parallel processing for faster execution of large datasets:

- **Default**: 4 workers (balanced for local execution)
- **max_workers parameter**: User can request specific number (e.g., "run with 8 workers")
- **Single mode**: Always sequential (1 worker) regardless of max_workers
- **EVAL_AGENT_MAX_WORKERS env var**: Sets default for cloud deployments (e.g., 16)

When reporting results, always mention if parallel processing was used and how many workers.

## Authentication Note
All Azure API calls use Azure Identity (DefaultAzureCredential). No API keys are used.
"""


def create_agent(client: AgentsClient, model: str) -> tuple:
    """Create the evaluation agent with function tools."""
    
    # Define function tools
    functions = FunctionTool(functions=[
        check_dataset_schema,
        validate_dataset_consistency,
        validate_dataset_quality,
        run_voicelive_evaluation,
        list_datasets,
        analyze_evaluation_results,
    ])
    
    # Create toolset for auto-execution
    toolset = ToolSet()
    toolset.add(functions)
    
    # IMPORTANT: Enable auto function calls on the client
    # This registers our functions for automatic execution when the agent calls them
    client.enable_auto_function_calls(toolset)
    
    # Create agent
    agent = client.create_agent(
        model=model,
        name="voicelive-evaluation-agent",
        instructions=AGENT_INSTRUCTIONS,
        toolset=toolset,
    )
    
    print(f"Agent created with {len(functions.definitions)} tools: " + 
          ", ".join(d['function']['name'] for d in functions.definitions))
    
    return agent, toolset


def run_conversation(client: AgentsClient, agent, toolset: ToolSet, user_message: str) -> str:
    """Run a single conversation turn with the agent."""
    
    # Create thread
    thread = client.threads.create()
    
    # Add user message
    client.messages.create(
        thread_id=thread.id,
        role="user",
        content=user_message,
    )
    
    # Run agent with toolset for auto-execution of functions
    run = client.runs.create_and_process(
        thread_id=thread.id,
        agent_id=agent.id,
        toolset=toolset,
    )
    
    # Get response
    if run.status == "completed":
        messages = client.messages.list(thread_id=thread.id, order="desc")
        for msg in messages:
            if msg.role == "assistant":
                return msg.content[0].text.value
        return "No response generated."
    else:
        error_info = f"Run failed with status: {run.status}"
        if hasattr(run, 'last_error') and run.last_error:
            error_info += f"\nError: {run.last_error.code} - {run.last_error.message}"
        return error_info


class StreamingEventHandler(AgentEventHandler):
    """Event handler for streaming agent responses with status updates."""
    
    def __init__(self):
        super().__init__()
        self.current_text = ""
        self.tool_calls_in_progress = []
    
    def on_message_delta(self, delta):
        """Handle streaming text deltas."""
        if hasattr(delta, 'text') and delta.text:
            text = delta.text.value if hasattr(delta.text, 'value') else str(delta.text)
            print(text, end="", flush=True)
            self.current_text += text
    
    def on_thread_run_requires_action(self, data):
        """Handle when agent requires tool execution."""
        if hasattr(data, 'required_action') and data.required_action:
            action = data.required_action
            if hasattr(action, 'submit_tool_outputs') and action.submit_tool_outputs:
                tool_calls = action.submit_tool_outputs.tool_calls
                for tc in tool_calls:
                    if hasattr(tc, 'function') and tc.function:
                        func_name = tc.function.name
                        print(f"\n⚙️  Executing: {func_name}...", flush=True)
                        self.tool_calls_in_progress.append(func_name)
    
    def on_error(self, data):
        """Handle errors."""
        print(f"\n❌ Error: {data}", flush=True)
    
    def on_done(self):
        """Handle completion."""
        pass


def interactive_mode(client: AgentsClient, agent, toolset: ToolSet):
    """Run interactive conversation loop with streaming responses."""
    logger = get_logger(__name__)
    conv_logger = get_conversation_logger()
    
    # Set up conversation logging
    conv_logger.set_system_message(AGENT_INSTRUCTIONS[:500])  # First 500 chars
    thread_id = conv_logger.new_thread()
    
    print("\n" + "="*60)
    print("Voice Live Evaluation Agent")
    print("="*60)
    print("Type your requests in natural language.")
    print("Examples:")
    print("  - 'What datasets are available?'")
    print("  - 'Validate the dataset at path/to/dataset.jsonl'")
    print("  - 'Run full evaluation on dataset X'")
    print(f"\nConversation logs: {get_log_directory()}")
    print("\nType 'quit' or 'exit' to end the session.")
    print("="*60 + "\n")
    
    # Create persistent thread for conversation
    thread = client.threads.create()
    
    while True:
        try:
            user_input = input("You: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("\nGoodbye!")
                break
            
            # Start a new run for this turn
            run_id = conv_logger.start_run()
            tool_calls_logged = []
            
            # Add user message
            client.messages.create(
                thread_id=thread.id,
                role="user",
                content=user_input,
            )
            
            # Run agent with streaming for real-time feedback
            print("\nAgent: ", end="", flush=True)
            assistant_response = ""
            
            # Try streaming first, fall back to non-streaming if it fails
            try:
                handler = StreamingEventHandler()
                with client.runs.stream(
                    thread_id=thread.id,
                    agent_id=agent.id,
                    event_handler=handler,
                    toolset=toolset,
                ) as stream:
                    stream.until_done()
                
                assistant_response = handler.current_text
                
                # Log any tool calls from the handler
                for tc_name in handler.tool_calls_in_progress:
                    tool_calls_logged.append(ToolCall(
                        id=f"tc_{len(tool_calls_logged)}",
                        name=tc_name,
                        arguments={},
                        status="completed"
                    ))
                
                # If streaming didn't produce text (e.g., tool execution only),
                # fetch the final response
                if not handler.current_text.strip():
                    messages = client.messages.list(thread_id=thread.id, order="desc")
                    for msg in messages:
                        if msg.role == "assistant":
                            assistant_response = msg.content[0].text.value
                            print(assistant_response)
                            break
            except Exception as stream_error:
                logger.debug(f"Streaming failed, falling back: {stream_error}")
                # Fall back to non-streaming mode
                run = client.runs.create_and_process(
                    thread_id=thread.id,
                    agent_id=agent.id,
                    toolset=toolset,
                )
                
                if run.status == "completed":
                    messages = client.messages.list(thread_id=thread.id, order="desc")
                    for msg in messages:
                        if msg.role == "assistant":
                            assistant_response = msg.content[0].text.value
                            print(assistant_response)
                            break
                else:
                    assistant_response = f"Run failed with status: {run.status}"
                    print(assistant_response)
            
            # Log conversation turn for evaluation
            conv_logger.log_turn(
                user_input=user_input,
                assistant_output=assistant_response,
                tool_calls=tool_calls_logged,
                metadata={
                    "thread_id": thread.id,
                    "agent_id": agent.id,
                }
            )
            
            print()
            
        except KeyboardInterrupt:
            print("\n\nInterrupted. Goodbye!")
            break
        except Exception as e:
            logger.error(f"Error in conversation: {e}")
            print(f"\nError: {e}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Voice Live Evaluation Agent")
    parser.add_argument("--message", "-m", help="Single message to process (non-interactive)")
    parser.add_argument("--endpoint", help="Azure AI Project endpoint (or set PROJECT_ENDPOINT env var)")
    parser.add_argument("--model", help="Model deployment name (or set MODEL_DEPLOYMENT_NAME env var)")
    parser.add_argument("--trace-console", action="store_true", 
                        help="Force console tracing even if Azure Monitor is configured")
    parser.add_argument("--trace-content", action="store_true",
                        help="Include message content in traces (may contain PII)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable verbose logging (DEBUG level)")
    args = parser.parse_args()
    
    # Set log level if verbose
    if args.verbose:
        os.environ["EVAL_AGENT_LOG_LEVEL"] = "DEBUG"
    
    # Initialize tracing
    is_cloud = setup_tracing(
        service_name="voicelive-evaluation-agent",
        force_console=args.trace_console,
        enable_content_capture=args.trace_content,
    )
    
    logger = get_logger(__name__)
    tracer = get_tracer(__name__)
    
    # Get configuration
    endpoint = args.endpoint or os.environ.get("PROJECT_ENDPOINT")
    model = args.model or os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4o-mini")
    
    if not endpoint:
        logger.error("PROJECT_ENDPOINT not configured")
        print("Error: PROJECT_ENDPOINT environment variable or --endpoint argument required.")
        print("\nSet it with:")
        print('  $env:PROJECT_ENDPOINT = "https://<resource>.services.ai.azure.com/api/projects/<project>"')
        sys.exit(1)
    
    # Start main session span
    with tracer.start_as_current_span("agent.main") as main_span:
        main_span.set_attribute("agent.model", model)
        main_span.set_attribute("agent.mode", "single" if args.message else "interactive")
        main_span.set_attribute("tracing.cloud_enabled", is_cloud)
        
        # Create client with Azure Identity
        logger.info(f"Connecting to Azure AI Foundry (cloud_tracing={is_cloud})")
        print("Connecting to Azure AI Foundry...")
        credential = DefaultAzureCredential()
        client = AgentsClient(
            endpoint=endpoint,
            credential=credential,
        )
        
        # Create agent
        logger.info(f"Creating agent with model: {model}")
        print(f"Creating agent with model: {model}")
        agent, toolset = create_agent(client, model)
        main_span.set_attribute("agent.id", agent.id)
        logger.info(f"Agent created: {agent.id}")
        print(f"Agent created: {agent.id}")
        
        try:
            if args.message:
                # Single message mode
                with tracer.start_as_current_span("agent.single_message") as msg_span:
                    msg_span.set_attribute("message.length", len(args.message))
                    response = run_conversation(client, agent, toolset, args.message)
                    print(response)
            else:
                # Interactive mode
                interactive_mode(client, agent, toolset)
        finally:
            # Cleanup
            logger.info("Cleaning up agent")
            print("\nCleaning up agent...")
            client.delete_agent(agent.id)
            print("Done.")


if __name__ == "__main__":
    main()
