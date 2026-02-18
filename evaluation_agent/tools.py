"""
Tool Implementations for VoiceLive Evaluation Agent v3

Contains the actual implementation of all agent tools. These are called by
the runner when the agent invokes a tool.

The implementations are similar to v1/v2 but designed for the Foundry Agent Service
architecture where tool execution is decoupled from agent orchestration.
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import Optional

# Path resolution
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent

# Import cloud storage
from cloud_storage import is_cloud_mode, get_storage_client, CloudStorageClient


def get_scripts_dir() -> Path:
    """Get the directory containing evaluation scripts."""
    if is_cloud_mode():
        return SCRIPT_DIR / "scripts"
    return REPO_ROOT / "prototype_v1"


def get_validators_dir() -> Path:
    """Get the directory containing validator scripts."""
    if is_cloud_mode():
        return SCRIPT_DIR / "scripts" / "validators"
    return REPO_ROOT / "dataset_validator"


def get_output_directory() -> Path:
    """Get the output directory for evaluation results."""
    env_path = os.environ.get("EVAL_AGENT_OUTPUT_DIR")
    if env_path:
        output_dir = Path(env_path)
    else:
        output_dir = SCRIPT_DIR / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def resolve_dataset_path(dataset_path: str) -> tuple[str, Optional[CloudStorageClient]]:
    """
    Resolve a dataset path, downloading from blob storage if needed.
    
    Returns:
        Tuple of (local_path, storage_client or None)
    """
    # Check if it's a blob path (container/path format)
    if is_cloud_mode() and "/" in dataset_path and not Path(dataset_path).exists():
        try:
            storage = get_storage_client()
            if storage:
                # Extract blob path (remove container prefix if present)
                blob_path = dataset_path
                if blob_path.startswith("datasets/"):
                    blob_path = blob_path[len("datasets/"):]
                
                print(f"   📥 Downloading from blob storage: {blob_path}", flush=True)
                local_path = storage.download_dataset(blob_path)
                return local_path, storage
        except Exception as e:
            print(f"   ⚠️ Could not download from blob: {e}", flush=True)
    
    return dataset_path, None


# =============================================================================
# Tool Implementations
# =============================================================================

def check_dataset_schema(dataset_path: str) -> dict:
    """Check dataset schema for required and optional fields."""
    print(f"\n⚙️  Checking dataset schema...", flush=True)
    
    script_path = get_validators_dir() / "check_dataset_schema.py"
    cmd = [sys.executable, str(script_path), dataset_path, "--json"]
    
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=60, cwd=str(REPO_ROOT), env=env
        )
        
        try:
            output_data = json.loads(result.stdout)
            status = output_data.get("status", "unknown")
            can_proceed = output_data.get("can_proceed", False)
        except json.JSONDecodeError:
            status = "passed" if result.returncode == 0 else "failed"
            can_proceed = result.returncode == 0
            output_data = {"raw_output": result.stdout}
        
        return {
            "action": "check_dataset_schema",
            "status": status,
            "can_proceed": can_proceed,
            "output": output_data,
            "errors": result.stderr if result.returncode != 0 else None
        }
    except Exception as e:
        return {"action": "check_dataset_schema", "status": "error", "error": str(e)}


def validate_dataset_consistency(
    dataset_path: str,
    expected_turns: Optional[int] = None,
    ignore_comments: bool = False
) -> dict:
    """Validate dataset structural integrity."""
    print(f"\n⚙️  Running consistency validation...", flush=True)
    
    script_path = get_validators_dir() / "validate_dataset_consistency.py"
    cmd = [sys.executable, str(script_path), dataset_path]
    
    if expected_turns is not None:
        cmd.extend(["--expected-turns", str(expected_turns)])
    if ignore_comments:
        cmd.append("--ignore-comments")
    
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=120, cwd=str(REPO_ROOT), env=env
        )
        
        status = "passed" if result.returncode == 0 else "failed"
        print(f"{'✓' if status == 'passed' else '✗'} Consistency validation {status.upper()}", flush=True)
        
        return {
            "action": "validate_dataset_consistency",
            "status": status,
            "output": result.stdout,
            "errors": result.stderr if result.returncode != 0 else None
        }
    except subprocess.TimeoutExpired:
        return {"action": "validate_dataset_consistency", "status": "timeout", "error": "Timed out after 120s"}
    except Exception as e:
        return {"action": "validate_dataset_consistency", "status": "error", "error": str(e)}


def validate_dataset_quality(
    dataset_path: str,
    strict: bool = False,
    verbose: bool = False
) -> dict:
    """Assess dataset content quality."""
    print(f"\n⚙️  Running quality validation...", flush=True)
    
    script_path = get_validators_dir() / "validate_dataset_quality.py"
    cmd = [sys.executable, str(script_path), dataset_path]
    
    if strict:
        cmd.append("--strict")
    if verbose:
        cmd.append("--verbose")
    
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=120, cwd=str(REPO_ROOT), env=env
        )
        
        status = "completed" if result.returncode == 0 else "failed"
        print(f"{'✓' if status == 'completed' else '✗'} Quality validation {status.upper()}", flush=True)
        
        return {
            "action": "validate_dataset_quality",
            "status": status,
            "output": result.stdout,
            "errors": result.stderr if result.returncode != 0 else None
        }
    except Exception as e:
        return {"action": "validate_dataset_quality", "status": "error", "error": str(e)}


def get_evaluation_recommendations(dataset_path: str) -> dict:
    """Analyze dataset and recommend evaluation settings."""
    print(f"\n⚙️  Analyzing dataset for evaluation settings...", flush=True)
    
    test_path = Path(dataset_path)
    
    # Handle folder path
    if test_path.is_dir():
        jsonl_files = list(test_path.glob("*.jsonl"))
        if jsonl_files:
            test_path = jsonl_files[0]
        else:
            return {"action": "get_evaluation_recommendations", "status": "error", "error": "No .jsonl file found"}
    
    if not test_path.exists():
        return {"action": "get_evaluation_recommendations", "status": "error", "error": f"Dataset not found: {dataset_path}"}
    
    try:
        entry_count = 0
        audio_count = 0
        
        with open(test_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('//') or line.startswith('#'):
                    continue
                try:
                    entry = json.loads(line)
                    entry_count += 1
                    if entry.get('WavPath') or entry.get('audio'):
                        audio_count += 1
                except json.JSONDecodeError:
                    pass
        
        # Calculate recommendations
        MAX_WORKERS = 8
        time_per_entry = 45 if audio_count > 0 else 20
        
        if entry_count <= 10:
            recommended_workers = 1
        elif entry_count <= 25:
            recommended_workers = 2
        elif entry_count <= 50:
            recommended_workers = 4
        elif entry_count <= 100:
            recommended_workers = 6
        else:
            recommended_workers = MAX_WORKERS
        
        total_time = (entry_count * time_per_entry) / recommended_workers * 1.5
        recommended_timeout = max(15, int(total_time / 60) + 5)
        recommended_timeout = min(recommended_timeout, 120)
        
        size_category = "small" if entry_count <= 25 else "medium" if entry_count <= 75 else "large"
        needs_confirmation = entry_count > 50 or recommended_timeout > 30
        
        print(f"{'⚠️' if needs_confirmation else '📊'}  {size_category.capitalize()} dataset ({entry_count} entries)", flush=True)
        print(f"   Recommended: timeout_minutes={recommended_timeout}, max_workers={recommended_workers}", flush=True)
        
        return {
            "action": "get_evaluation_recommendations",
            "status": "success",
            "dataset_analysis": {
                "entry_count": entry_count,
                "audio_count": audio_count,
                "size_category": size_category,
            },
            "recommendations": {
                "timeout_minutes": recommended_timeout,
                "max_workers": recommended_workers,
                "parallel": entry_count > 10,
            },
            "needs_user_confirmation": needs_confirmation,
            "worker_limits": {
                "max_recommended": MAX_WORKERS,
                "note": "Going above 8 workers may cause API rate limiting"
            }
        }
    except Exception as e:
        return {"action": "get_evaluation_recommendations", "status": "error", "error": str(e)}


def run_voicelive_evaluation(
    test_files_path: str,
    output_dir: Optional[str] = None,
    session_mode: Optional[str] = None,
    timeout_minutes: int = 30,
    max_workers: Optional[int] = None,
    parallel: bool = True
) -> dict:
    """Run VoiceLive evaluation."""
    print(f"\n⚙️  Starting VoiceLive evaluation...", flush=True)
    
    if output_dir is None:
        output_dir = str(get_output_directory())
    
    scripts_dir = get_scripts_dir()
    batch_processor = scripts_dir / "batch_processor.py"
    single_script = scripts_dir / "voice_agent_audio_input_evaluation.py"
    
    # Resolve dataset path (download from blob if needed)
    local_test_path, storage_client = resolve_dataset_path(test_files_path)
    test_path = Path(local_test_path)
    
    if not test_path.exists():
        return {"action": "run_voicelive_evaluation", "status": "error", "error": f"Dataset not found: {test_files_path}"}
    
    # Find JSONL in folder
    if test_path.is_dir():
        jsonl_files = list(test_path.glob("*.jsonl"))
        if jsonl_files:
            test_path = jsonl_files[0]
        else:
            return {"action": "run_voicelive_evaluation", "status": "error", "error": "No .jsonl file found"}
    
    # Build command
    effective_workers = max_workers or 4
    if not parallel:
        effective_workers = 1
    
    if effective_workers > 1 and batch_processor.exists():
        cmd = [
            sys.executable, str(batch_processor),
            "--input", str(test_path),
            "--output-dir", output_dir,
            "--eval-dir", output_dir,
            "--workers", str(effective_workers),
            "--timeout", str(timeout_minutes * 60),
        ]
        if session_mode:
            cmd.extend(["--session-mode", session_mode])
    else:
        cmd = [
            sys.executable, str(single_script),
            "--input", str(test_path),
            "--output-dir", output_dir,
        ]
    
    print(f"   Workers: {effective_workers} | Timeout: {timeout_minutes}m", flush=True)
    
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=timeout_minutes * 60, cwd=str(REPO_ROOT), env=env
        )
        
        status = "completed" if result.returncode == 0 else "failed"
        print(f"{'✓' if status == 'completed' else '✗'} Evaluation {status.upper()}", flush=True)
        
        # Extract report URL if present
        report_url = None
        for line in result.stdout.split('\n'):
            if 'report_url' in line.lower() or 'portal' in line.lower():
                report_url = line
                break
        
        # Upload results to blob storage if in cloud mode
        blob_urls = []
        if is_cloud_mode() and status == "completed":
            try:
                storage = get_storage_client()
                if storage:
                    import datetime
                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                    blob_prefix = f"results/{timestamp}"
                    print(f"   📤 Uploading results to blob storage: {blob_prefix}/", flush=True)
                    blob_urls = storage.upload_directory(output_dir, blob_prefix, extensions=['.jsonl', '.json', '.txt'])
                    print(f"   ✓ Uploaded {len(blob_urls)} files", flush=True)
            except Exception as e:
                print(f"   ⚠️ Could not upload results: {e}", flush=True)
        
        return {
            "action": "run_voicelive_evaluation",
            "status": status,
            "output_dir": output_dir,
            "workers": effective_workers,
            "output": result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout,
            "report_url": report_url,
            "blob_urls": blob_urls if blob_urls else None,
            "errors": result.stderr if result.returncode != 0 else None
        }
    except subprocess.TimeoutExpired:
        return {"action": "run_voicelive_evaluation", "status": "timeout", "error": f"Timed out after {timeout_minutes} minutes"}
    except Exception as e:
        return {"action": "run_voicelive_evaluation", "status": "error", "error": str(e)}


def list_datasets(folder_path: Optional[str] = None) -> dict:
    """List available datasets."""
    print(f"\n⚙️  Searching for datasets...", flush=True)
    
    # Cloud mode: list from blob storage
    if is_cloud_mode():
        try:
            storage = get_storage_client()
            if storage:
                blobs = storage.list_datasets(prefix=folder_path or "")
                datasets = [
                    {
                        "path": blob.full_path,
                        "name": Path(blob.name).stem,
                        "folder": str(Path(blob.name).parent),
                        "size_bytes": blob.size,
                        "last_modified": blob.last_modified,
                        "storage": "azure_blob"
                    }
                    for blob in blobs
                ]
                print(f"✓ Found {len(datasets)} datasets in blob storage", flush=True)
                return {
                    "action": "list_datasets",
                    "status": "success",
                    "storage_mode": "cloud",
                    "datasets_found": len(datasets),
                    "datasets": datasets
                }
        except Exception as e:
            print(f"⚠️  Cloud storage error, falling back to local: {e}", flush=True)
    
    # Local mode: search filesystem
    search_paths = []
    
    if folder_path:
        search_paths.append(Path(folder_path))
    else:
        search_paths.extend([
            REPO_ROOT / "prototype_v1" / "sample_evaluation_input",
            REPO_ROOT / "prototype_v1" / "local_datasets",
            REPO_ROOT / "dataset_validator",
            SCRIPT_DIR / "datasets",  # Local datasets folder
        ])
    
    datasets = []
    for search_path in search_paths:
        if search_path.exists():
            for jsonl_file in search_path.rglob("*.jsonl"):
                try:
                    line_count = sum(1 for _ in open(jsonl_file, 'r', encoding='utf-8'))
                    datasets.append({
                        "path": str(jsonl_file),
                        "name": jsonl_file.stem,
                        "folder": str(jsonl_file.parent),
                        "entries": line_count,
                        "storage": "local"
                    })
                except Exception:
                    datasets.append({"path": str(jsonl_file), "name": jsonl_file.stem, "error": "Could not read"})
    
    print(f"✓ Found {len(datasets)} datasets", flush=True)
    
    return {
        "action": "list_datasets",
        "status": "success",
        "storage_mode": "local",
        "datasets_found": len(datasets),
        "datasets": datasets
    }


def analyze_evaluation_results(results_path: str) -> dict:
    """Analyze evaluation output files."""
    print(f"\n⚙️  Analyzing evaluation results...", flush=True)
    
    results_path = Path(results_path)
    
    if not results_path.exists():
        return {"action": "analyze_evaluation_results", "status": "error", "error": f"Path not found: {results_path}"}
    
    # Find aggregate file
    if results_path.is_dir():
        aggregate_files = list(results_path.glob("*aggregate*.jsonl"))
        if aggregate_files:
            results_path = aggregate_files[0]
        else:
            jsonl_files = list(results_path.glob("*.jsonl"))
            if jsonl_files:
                results_path = jsonl_files[0]
            else:
                return {"action": "analyze_evaluation_results", "status": "error", "error": "No JSONL files found"}
    
    try:
        entries = []
        with open(results_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        
        if not entries:
            return {"action": "analyze_evaluation_results", "status": "error", "error": "No valid entries found"}
        
        # Extract metrics
        metrics = {}
        for entry in entries:
            for key, value in entry.items():
                if isinstance(value, (int, float)):
                    if key not in metrics:
                        metrics[key] = []
                    metrics[key].append(value)
        
        # Calculate averages
        summary = {}
        for key, values in metrics.items():
            summary[key] = {
                "avg": sum(values) / len(values),
                "min": min(values),
                "max": max(values),
                "count": len(values)
            }
        
        print(f"✓ Analyzed {len(entries)} entries, {len(metrics)} metrics", flush=True)
        
        return {
            "action": "analyze_evaluation_results",
            "status": "success",
            "file": str(results_path),
            "entries_analyzed": len(entries),
            "metrics_found": len(metrics),
            "summary": summary
        }
    except Exception as e:
        return {"action": "analyze_evaluation_results", "status": "error", "error": str(e)}


# =============================================================================
# Config Management Tools (HTTP calls to Azure Functions)
# =============================================================================

def _call_functions_api(endpoint: str, payload: dict = None) -> dict:
    """Call Azure Functions API endpoint."""
    import urllib.request
    import urllib.error
    
    functions_url = os.environ.get("AZURE_FUNCTIONS_URL")
    functions_key = os.environ.get("AZURE_FUNCTIONS_KEY")
    
    if not functions_url:
        return {"error": "AZURE_FUNCTIONS_URL not configured"}
    
    url = f"{functions_url}/api/{endpoint}"
    headers = {"Content-Type": "application/json"}
    if functions_key:
        headers["x-functions-key"] = functions_key
    
    try:
        data = json.dumps(payload or {}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else str(e)
        return {"error": f"HTTP {e.code}: {body}"}
    except Exception as e:
        return {"error": str(e)}


def list_session_configs() -> dict:
    """List available VoiceLive session configurations."""
    print(f"\n⚙️  Listing session configs...", flush=True)
    result = _call_functions_api("list_session_configs")
    if "error" not in result:
        print(f"✓ Found {result.get('configs_found', 0)} configs", flush=True)
    return result


def get_session_config(name: str) -> dict:
    """Get a specific VoiceLive session configuration."""
    print(f"\n⚙️  Getting config '{name}'...", flush=True)
    return _call_functions_api("get_session_config", {"name": name})


def create_session_config(
    name: str,
    description: str = None,
    model: str = None,
    sample_rate: int = None,
    voice_name: str = None,
    voice_type: str = None,
    vad_type: str = None,
    vad_threshold: float = None,
    silence_duration_ms: int = None,
    eou_detection: bool = None,
    eou_model: str = None,
    transcription_model: str = None,
    noise_reduction: str = None,
    echo_cancellation: str = None,
    is_default: bool = None
) -> dict:
    """Create a new VoiceLive session configuration."""
    print(f"\n⚙️  Creating config '{name}'...", flush=True)
    
    payload = {"name": name}
    if description is not None: payload["description"] = description
    if model is not None: payload["model"] = model
    if sample_rate is not None: payload["sample_rate"] = sample_rate
    if voice_name is not None: payload["voice_name"] = voice_name
    if voice_type is not None: payload["voice_type"] = voice_type
    if vad_type is not None: payload["vad_type"] = vad_type
    if vad_threshold is not None: payload["vad_threshold"] = vad_threshold
    if silence_duration_ms is not None: payload["silence_duration_ms"] = silence_duration_ms
    if eou_detection is not None: payload["eou_detection"] = eou_detection
    if eou_model is not None: payload["eou_model"] = eou_model
    if transcription_model is not None: payload["transcription_model"] = transcription_model
    if noise_reduction is not None: payload["noise_reduction"] = noise_reduction
    if echo_cancellation is not None: payload["echo_cancellation"] = echo_cancellation
    if is_default is not None: payload["is_default"] = is_default
    
    result = _call_functions_api("create_session_config", payload)
    if "error" not in result:
        print(f"✓ Config '{name}' created", flush=True)
    return result


def update_session_config(
    name: str,
    description: str = None,
    model: str = None,
    sample_rate: int = None,
    voice_name: str = None,
    voice_type: str = None,
    vad_type: str = None,
    vad_threshold: float = None,
    silence_duration_ms: int = None,
    eou_detection: bool = None,
    eou_model: str = None,
    transcription_model: str = None,
    noise_reduction: str = None,
    echo_cancellation: str = None,
    is_default: bool = None
) -> dict:
    """Update an existing VoiceLive session configuration."""
    print(f"\n⚙️  Updating config '{name}'...", flush=True)
    
    payload = {"name": name}
    if description is not None: payload["description"] = description
    if model is not None: payload["model"] = model
    if sample_rate is not None: payload["sample_rate"] = sample_rate
    if voice_name is not None: payload["voice_name"] = voice_name
    if voice_type is not None: payload["voice_type"] = voice_type
    if vad_type is not None: payload["vad_type"] = vad_type
    if vad_threshold is not None: payload["vad_threshold"] = vad_threshold
    if silence_duration_ms is not None: payload["silence_duration_ms"] = silence_duration_ms
    if eou_detection is not None: payload["eou_detection"] = eou_detection
    if eou_model is not None: payload["eou_model"] = eou_model
    if transcription_model is not None: payload["transcription_model"] = transcription_model
    if noise_reduction is not None: payload["noise_reduction"] = noise_reduction
    if echo_cancellation is not None: payload["echo_cancellation"] = echo_cancellation
    if is_default is not None: payload["is_default"] = is_default
    
    result = _call_functions_api("update_session_config", payload)
    if "error" not in result:
        print(f"✓ Config '{name}' updated", flush=True)
    return result


def delete_session_config(name: str) -> dict:
    """Delete a VoiceLive session configuration."""
    print(f"\n⚙️  Deleting config '{name}'...", flush=True)
    result = _call_functions_api("delete_session_config", {"name": name})
    if "error" not in result:
        print(f"✓ Config '{name}' deleted", flush=True)
    return result


# Tool registry for runner
TOOLS = {
    "check_dataset_schema": check_dataset_schema,
    "validate_dataset_consistency": validate_dataset_consistency,
    "validate_dataset_quality": validate_dataset_quality,
    "get_evaluation_recommendations": get_evaluation_recommendations,
    "run_voicelive_evaluation": run_voicelive_evaluation,
    "list_datasets": list_datasets,
    "analyze_evaluation_results": analyze_evaluation_results,
    "list_session_configs": list_session_configs,
    "get_session_config": get_session_config,
    "create_session_config": create_session_config,
    "update_session_config": update_session_config,
    "delete_session_config": delete_session_config,
}


def execute_tool(tool_name: str, arguments: dict) -> dict:
    """Execute a tool by name with given arguments."""
    if tool_name not in TOOLS:
        return {"error": f"Unknown tool: {tool_name}"}
    
    try:
        return TOOLS[tool_name](**arguments)
    except Exception as e:
        return {"error": f"Tool execution failed: {str(e)}"}
