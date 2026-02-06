"""
Azure Functions HTTP Triggers for VoiceLive Evaluation Tools

These functions expose the evaluation tools as HTTP endpoints that can be
called by the Foundry Agent via OpenAPI tool integration.

Authentication:
- Uses Function Key auth (x-functions-key header)
- Create a Foundry connection with the function key for production use
- Anonymous fallback available via ALLOW_ANONYMOUS=true env var

Each function corresponds to one agent tool:
- POST /api/check_dataset_schema
- POST /api/validate_dataset_consistency
- POST /api/validate_dataset_quality
- POST /api/get_evaluation_recommendations
- POST /api/run_voicelive_evaluation (Durable - starts async job)
- POST /api/check_evaluation_status (Durable - polls job status)
- POST /api/list_datasets
- POST /api/analyze_evaluation_results
"""

import os
import json
import logging
import tempfile
from pathlib import Path
from datetime import datetime

import azure.functions as func
import azure.durable_functions as df
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

# Use FUNCTION auth level - requires x-functions-key header or ?code= query param
# For anonymous access (testing), set ALLOW_ANONYMOUS=true in app settings
allow_anonymous = os.environ.get("ALLOW_ANONYMOUS", "false").lower() == "true"
auth_level = func.AuthLevel.ANONYMOUS if allow_anonymous else func.AuthLevel.FUNCTION

app = func.FunctionApp(http_auth_level=auth_level)

# Initialize blob client
def get_blob_client():
    account = os.environ.get("AZURE_STORAGE_ACCOUNT")
    if not account:
        return None
    credential = DefaultAzureCredential()
    return BlobServiceClient(
        f"https://{account}.blob.core.windows.net",
        credential=credential
    )


# =============================================================================
# Unified Blob Path Handling
# =============================================================================

def normalize_blob_path(blob_path: str, container_name: str) -> str:
    """
    Normalize a blob path to handle various input formats from the agent.
    
    Handles:
        - "name" (just name)
        - "folder/file.ext" (relative path)
        - "container/folder/file.ext" (with container prefix)
        - "/container/folder/file.ext" (with leading slash)
        - Whitespace and quotes
    
    Args:
        blob_path: The path as received from the agent
        container_name: The container name to strip if present
        
    Returns:
        Normalized path within the container (no container prefix)
    """
    if not blob_path:
        return ""
    
    # Strip whitespace and quotes
    blob_path = blob_path.strip().strip('"\'')
    
    # Strip leading slashes
    blob_path = blob_path.lstrip('/')
    
    # Strip container prefix if present (e.g., "datasets/..." or "outputs/...")
    if blob_path.startswith(f"{container_name}/"):
        blob_path = blob_path[len(container_name) + 1:]
    
    return blob_path


def find_blob_flexible(
    container_client, 
    search_path: str, 
    extensions: list = None,
    prefer_patterns: list = None
) -> str:
    """
    Flexibly find a blob matching the search path.
    
    Tries multiple strategies:
    1. Exact match (if path has extension)
    2. Prefix match (list blobs starting with path)
    3. Common patterns (path/path.ext, path.ext)
    4. Fuzzy search (partial name match)
    
    Args:
        container_client: Azure blob container client
        search_path: Normalized path to search for
        extensions: List of extensions to look for (e.g., [".jsonl", ".json"])
        prefer_patterns: List of patterns to prefer (e.g., ["aggregate", "results"])
        
    Returns:
        The actual blob name, or raises ValueError if not found
    """
    extensions = extensions or [".jsonl", ".json"]
    prefer_patterns = prefer_patterns or []
    
    # Strategy 1: Exact match if has extension
    has_extension = any(search_path.endswith(ext) for ext in extensions)
    if has_extension:
        try:
            blob_client = container_client.get_blob_client(search_path)
            blob_client.get_blob_properties()  # Check if exists
            return search_path
        except Exception:
            # Remove extension and try other strategies
            for ext in extensions:
                if search_path.endswith(ext):
                    search_path = search_path[:-len(ext)]
                    break
    
    # Strategy 2: Prefix match - list blobs starting with path
    matching_blobs = []
    for blob in container_client.list_blobs(name_starts_with=search_path):
        if any(blob.name.endswith(ext) for ext in extensions):
            matching_blobs.append(blob.name)
    
    if matching_blobs:
        # If we have preferred patterns, try to match those first
        for pattern in prefer_patterns:
            for blob_name in matching_blobs:
                if pattern.lower() in blob_name.lower():
                    return blob_name
        # Otherwise return first match
        return matching_blobs[0]
    
    # Strategy 3: Try common path patterns
    base_name = Path(search_path).name if search_path else search_path
    patterns_to_try = []
    for ext in extensions:
        patterns_to_try.extend([
            f"{search_path}/{search_path}{ext}",
            f"{search_path}{ext}",
            f"{search_path}/{base_name}{ext}",
            f"{base_name}/{base_name}{ext}",
            f"{base_name}{ext}",
        ])
    
    for pattern in patterns_to_try:
        try:
            blob_client = container_client.get_blob_client(pattern)
            blob_client.get_blob_properties()
            return pattern
        except Exception:
            continue
    
    # Strategy 4: Fuzzy search - partial name match across all blobs
    search_term = base_name.lower() if base_name else search_path.lower()
    for blob in container_client.list_blobs():
        if search_term in blob.name.lower():
            if any(blob.name.endswith(ext) for ext in extensions):
                return blob.name
    
    raise ValueError(f"Blob not found: {search_path}")


def download_blob_flexible(
    container_name: str,
    blob_path: str,
    extensions: list = None,
    prefer_patterns: list = None
) -> tuple:
    """
    Download a blob with flexible path matching.
    
    Args:
        container_name: Container to search in
        blob_path: Path as received from agent
        extensions: File extensions to look for
        prefer_patterns: Patterns to prefer when multiple matches
        
    Returns:
        Tuple of (local_file_path, actual_blob_name)
    """
    client = get_blob_client()
    if not client:
        raise ValueError("AZURE_STORAGE_ACCOUNT not configured")
    
    container_client = client.get_container_client(container_name)
    
    # Normalize and find the blob
    normalized_path = normalize_blob_path(blob_path, container_name)
    actual_blob = find_blob_flexible(
        container_client, 
        normalized_path, 
        extensions=extensions,
        prefer_patterns=prefer_patterns
    )
    
    # Download to temp file
    blob_client = container_client.get_blob_client(actual_blob)
    suffix = Path(actual_blob).suffix or ".tmp"
    
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        download_stream = blob_client.download_blob()
        f.write(download_stream.readall())
        return f.name, actual_blob


# Legacy function - now uses unified approach
def normalize_dataset_path(dataset_path: str) -> str:
    """Normalize dataset path. Uses unified normalize_blob_path."""
    container = os.environ.get("AZURE_STORAGE_DATASETS_CONTAINER", "datasets")
    return normalize_blob_path(dataset_path, container)


def download_dataset(dataset_path: str) -> str:
    """Download dataset from blob storage to temp file.
    
    Flexibly handles any path format the agent might send.
    Uses unified blob path handling.
    """
    container = os.environ.get("AZURE_STORAGE_DATASETS_CONTAINER", "datasets")
    local_path, _ = download_blob_flexible(
        container_name=container,
        blob_path=dataset_path,
        extensions=[".jsonl"],
    )
    return local_path


def download_results(results_path: str) -> tuple:
    """Download results from blob storage to temp file.
    
    Flexibly handles any path format the agent might send.
    Prefers aggregate files when multiple matches.
    
    Returns:
        Tuple of (local_file_path, actual_blob_name)
    """
    container = os.environ.get("AZURE_STORAGE_OUTPUTS_CONTAINER", "outputs")
    return download_blob_flexible(
        container_name=container,
        blob_path=results_path,
        extensions=[".jsonl", ".json"],
        prefer_patterns=["aggregate", "results", "overall"],
    )


def upload_results(local_path: str, blob_path: str) -> str:
    """Upload results to blob storage."""
    client = get_blob_client()
    if not client:
        return local_path
    
    container = os.environ.get("AZURE_STORAGE_OUTPUTS_CONTAINER", "outputs")
    blob_client = client.get_container_client(container).get_blob_client(blob_path)
    
    with open(local_path, "rb") as f:
        blob_client.upload_blob(f, overwrite=True)
    
    return blob_client.url


# =============================================================================
# Tool Functions
# =============================================================================

@app.route(route="list_datasets", methods=["POST"])
def list_datasets(req: func.HttpRequest) -> func.HttpResponse:
    """List available datasets in blob storage."""
    logging.info("list_datasets called")
    
    try:
        body = req.get_json() if req.get_body() else {}
        prefix = body.get("folder_path", "")
        
        client = get_blob_client()
        if not client:
            return func.HttpResponse(
                json.dumps({"error": "AZURE_STORAGE_ACCOUNT not configured"}),
                status_code=500,
                mimetype="application/json"
            )
        
        container = os.environ.get("AZURE_STORAGE_DATASETS_CONTAINER", "datasets")
        container_client = client.get_container_client(container)
        
        datasets = []
        for blob in container_client.list_blobs(name_starts_with=prefix):
            if blob.name.endswith(".jsonl"):
                datasets.append({
                    "path": f"{container}/{blob.name}",
                    "name": Path(blob.name).stem,
                    "size_bytes": blob.size,
                    "last_modified": str(blob.last_modified),
                })
        
        return func.HttpResponse(
            json.dumps({
                "action": "list_datasets",
                "status": "success",
                "datasets_found": len(datasets),
                "datasets": datasets
            }),
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"list_datasets error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="check_dataset_schema", methods=["POST"])
def check_dataset_schema(req: func.HttpRequest) -> func.HttpResponse:
    """Check dataset schema for required and optional fields."""
    logging.info("check_dataset_schema called")
    
    try:
        body = req.get_json()
        dataset_path = body.get("dataset_path")
        
        if not dataset_path:
            return func.HttpResponse(
                json.dumps({"error": "dataset_path required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Download from blob if needed
        local_path = download_dataset(dataset_path)
        
        # Analyze schema - matches validators/check_dataset_schema.py
        # Required: audio_path (WavPath or audio)
        # Optional: question, answer, tool_definitions, conversation_id, system_prompt
        required_field_aliases = {
            "audio_path": ["WavPath", "audio"],
        }
        optional_field_aliases = {
            "question": ["Question", "question"],
            "answer": ["Answer", "answer"],
            "tool_definitions": ["tool_definitions"],
            "conversation_id": ["conversationID", "conversation_id"],
            "system_prompt": ["system_prompt"],
        }
        
        found_required = {}
        found_optional = {}
        missing_required = set()
        entry_count = 0
        
        with open(local_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('//') or line.startswith('#'):
                    continue
                try:
                    entry = json.loads(line)
                    entry_count += 1
                    
                    # Check required fields (any alias counts)
                    for field_name, aliases in required_field_aliases.items():
                        for alias in aliases:
                            if alias in entry:
                                found_required[field_name] = alias
                                break
                        else:
                            if entry_count == 1:  # Only track missing on first entry
                                missing_required.add(field_name)
                    
                    # Check optional fields
                    for field_name, aliases in optional_field_aliases.items():
                        for alias in aliases:
                            if alias in entry:
                                found_optional[field_name] = alias
                                break
                except json.JSONDecodeError:
                    pass
        
        # Cleanup temp file
        os.unlink(local_path)
        
        # Can proceed if required field (audio_path) is present
        status = "passed" if not missing_required else "failed"
        
        return func.HttpResponse(
            json.dumps({
                "action": "check_dataset_schema",
                "status": status,
                "can_proceed": True,  # Always allow proceeding - optional fields use defaults
                "entries_analyzed": entry_count,
                "required_fields": {
                    "found": list(found_required.keys()),
                    "field_names_used": found_required,
                    "missing": list(missing_required)
                },
                "optional_fields": {
                    "found": list(found_optional.keys()),
                    "field_names_used": found_optional,
                    "missing": [f for f in optional_field_aliases.keys() if f not in found_optional]
                },
                "recommendation": "Dataset is valid for evaluation. Missing optional fields will use defaults."
            }),
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"check_dataset_schema error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="validate_dataset_consistency", methods=["POST"])
def validate_dataset_consistency(req: func.HttpRequest) -> func.HttpResponse:
    """Validate dataset structural integrity."""
    logging.info("validate_dataset_consistency called")
    
    try:
        body = req.get_json()
        dataset_path = body.get("dataset_path")
        
        if not dataset_path:
            return func.HttpResponse(
                json.dumps({"error": "dataset_path required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        local_path = download_dataset(dataset_path)
        
        # Validate structure - matches validators/validate_dataset_consistency.py
        errors = []
        warnings = []
        entry_count = 0
        conversation_ids = set()
        
        with open(local_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith('//') or line.startswith('#'):
                    continue
                
                try:
                    entry = json.loads(line)
                    entry_count += 1
                    
                    # Check for audio path (required)
                    audio_path = entry.get("WavPath") or entry.get("audio")
                    if not audio_path:
                        errors.append(f"Line {line_num}: Missing audio path (WavPath or audio)")
                    
                    # Track conversation IDs if present
                    cid = entry.get("conversationID") or entry.get("conversation_id") or "default"
                    conversation_ids.add(cid)
                    
                    # Check for duplicate entries (same audio path)
                    # (simplified check)
                    
                except json.JSONDecodeError as e:
                    errors.append(f"Line {line_num}: Invalid JSON - {e}")
        
        os.unlink(local_path)
        
        status = "passed" if not errors else "failed"
        
        return func.HttpResponse(
            json.dumps({
                "action": "validate_dataset_consistency",
                "status": status,
                "can_proceed": len(errors) == 0,
                "entries_validated": entry_count,
                "unique_conversations": len(conversation_ids),
                "errors": errors[:20],  # Limit to first 20
                "warnings": warnings[:20],
                "error_count": len(errors),
                "warning_count": len(warnings)
            }),
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"validate_dataset_consistency error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="validate_dataset_quality", methods=["POST"])
def validate_dataset_quality(req: func.HttpRequest) -> func.HttpResponse:
    """Assess dataset content quality."""
    logging.info("validate_dataset_quality called")
    
    try:
        body = req.get_json()
        dataset_path = body.get("dataset_path")
        
        if not dataset_path:
            return func.HttpResponse(
                json.dumps({"error": "dataset_path required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        local_path = download_dataset(dataset_path)
        
        # Quality checks - based on actual dataset schema
        issues = []
        entry_count = 0
        has_audio = 0
        has_question = 0
        has_answer = 0
        
        with open(local_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('//') or line.startswith('#'):
                    continue
                
                try:
                    entry = json.loads(line)
                    entry_count += 1
                    
                    # Check audio path
                    audio = entry.get("WavPath") or entry.get("audio")
                    if audio:
                        has_audio += 1
                    else:
                        issues.append(f"Entry {entry_count}: Missing audio path")
                    
                    # Check question (optional but useful)
                    if entry.get("Question") or entry.get("question"):
                        has_question += 1
                    
                    # Check answer (optional but useful for evaluation)
                    if entry.get("Answer") or entry.get("answer"):
                        has_answer += 1
                
                except json.JSONDecodeError:
                    issues.append(f"Entry {entry_count}: Invalid JSON")
        
        os.unlink(local_path)
        
        # Calculate quality score based on completeness
        audio_ratio = has_audio / entry_count if entry_count > 0 else 0
        question_ratio = has_question / entry_count if entry_count > 0 else 0
        answer_ratio = has_answer / entry_count if entry_count > 0 else 0
        
        quality_score = int((audio_ratio * 50) + (question_ratio * 25) + (answer_ratio * 25))
        
        return func.HttpResponse(
            json.dumps({
                "action": "validate_dataset_quality",
                "status": "completed",
                "can_proceed": audio_ratio == 1.0,  # Can proceed if all entries have audio
                "entries_analyzed": entry_count,
                "quality_score": quality_score,
                "completeness": {
                    "audio_paths": f"{has_audio}/{entry_count}",
                    "questions": f"{has_question}/{entry_count}",
                    "answers": f"{has_answer}/{entry_count}"
                },
                "issues_found": len(issues),
                "issues": issues[:10],  # Sample
                "recommendation": "Dataset is ready for evaluation." if audio_ratio == 1.0 else "Some entries missing audio path."
            }),
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"validate_dataset_quality error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="get_evaluation_recommendations", methods=["POST"])
def get_evaluation_recommendations(req: func.HttpRequest) -> func.HttpResponse:
    """Get recommended evaluation settings for a dataset."""
    logging.info("get_evaluation_recommendations called")
    
    try:
        body = req.get_json()
        dataset_path = body.get("dataset_path")
        
        if not dataset_path:
            return func.HttpResponse(
                json.dumps({"error": "dataset_path required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        local_path = download_dataset(dataset_path)
        
        entry_count = 0
        audio_count = 0
        
        with open(local_path, 'r', encoding='utf-8') as f:
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
        
        os.unlink(local_path)
        
        # Calculate recommendations
        MAX_WORKERS = 8
        
        if entry_count <= 10:
            workers = 1
        elif entry_count <= 25:
            workers = 2
        elif entry_count <= 50:
            workers = 4
        elif entry_count <= 100:
            workers = 6
        else:
            workers = MAX_WORKERS
        
        time_per_entry = 45 if audio_count > 0 else 20
        total_time = (entry_count * time_per_entry) / workers * 1.5
        timeout = min(120, max(15, int(total_time / 60) + 5))
        
        size_category = "small" if entry_count <= 25 else "medium" if entry_count <= 75 else "large"
        
        return func.HttpResponse(
            json.dumps({
                "action": "get_evaluation_recommendations",
                "status": "success",
                "dataset_analysis": {
                    "entry_count": entry_count,
                    "audio_count": audio_count,
                    "size_category": size_category
                },
                "recommendations": {
                    "timeout_minutes": timeout,
                    "max_workers": workers,
                    "parallel": entry_count > 10
                },
                "needs_user_confirmation": entry_count > 50
            }),
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"get_evaluation_recommendations error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


# =============================================================================
# Durable Functions for Long-Running Evaluation
# =============================================================================

# Create a separate blueprint for durable functions
bp = df.Blueprint()

@bp.orchestration_trigger(context_name="context")
def evaluation_orchestrator(context: df.DurableOrchestrationContext):
    """Orchestrator that runs the evaluation workflow."""
    # Get input parameters
    params = context.get_input()
    dataset_path = params.get("dataset_path")
    max_workers = params.get("max_workers", 4)
    session_mode = params.get("session_mode", "per-conversation")
    evaluators = params.get("evaluators", None)  # None means use all defaults
    run_voicelive_tests = params.get("run_voicelive_tests", True)
    eval_group_id = params.get("eval_group_id")  # Optional: reuse existing eval group
    foundry_dataset_id = params.get("foundry_dataset_id")  # Optional: reuse existing dataset
    
    # Step 1: Download and prepare dataset
    prep_result = yield context.call_activity("prepare_evaluation", {
        "dataset_path": dataset_path,
        "instance_id": context.instance_id
    })
    
    if prep_result.get("error"):
        return {"status": "failed", "error": prep_result["error"]}
    
    # Step 2: Run evaluation (this is the long-running part)
    # Pass dataset_path so execute_evaluation can download directly
    eval_result = yield context.call_activity("execute_evaluation", {
        "dataset_path": dataset_path,
        "output_path": prep_result["output_path"],
        "max_workers": max_workers,
        "session_mode": session_mode,
        "instance_id": context.instance_id,
        "evaluators": evaluators,
        "run_voicelive_tests": run_voicelive_tests,
        "eval_group_id": eval_group_id,
        "foundry_dataset_id": foundry_dataset_id
    })
    
    # Step 3: Upload results and cleanup
    final_result = yield context.call_activity("finalize_evaluation", {
        "output_path": prep_result["output_path"],
        "instance_id": context.instance_id,
        "eval_result": eval_result
    })
    
    return final_result


@bp.activity_trigger(input_name="params")
def prepare_evaluation(params: dict) -> dict:
    """Prepare output directory for evaluation. Download happens in execute_evaluation."""
    try:
        instance_id = params["instance_id"]
        
        # Create output directory
        output_dir = f"/tmp/eval_{instance_id}"
        os.makedirs(output_dir, exist_ok=True)
        
        return {
            "status": "prepared",
            "output_path": output_dir
        }
    except Exception as e:
        logging.error(f"prepare_evaluation error: {e}")
        return {"error": str(e)}


# Default evaluators list - aligned with prototype_v1
DEFAULT_EVALUATORS = [
    "intent_resolution",
    "task_adherence", 
    "task_completion",
    "response_completeness",
    "groundedness",
    "relevance",
    "tool_call_accuracy",
    "tool_selection",
    "tool_input_accuracy",
    "tool_output_utilization",
]

def get_testing_criteria(evaluators: list, model_deployment: str, reasoning_deployment: str) -> list:
    """Build testing criteria for specified evaluators."""
    
    # Map evaluator names to their configurations
    evaluator_configs = {
        "intent_resolution": {
            "type": "azure_ai_evaluator",
            "name": "intent_resolution",
            "evaluator_name": "builtin.intent_resolution",
            "initialization_parameters": {
                "deployment_name": reasoning_deployment,
                "is_reasoning_model": True
            },
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
                "tool_definitions": "{{item.tool_definitions}}",
            },
        },
        "task_adherence": {
            "type": "azure_ai_evaluator",
            "name": "task_adherence",
            "evaluator_name": "builtin.task_adherence",
            "initialization_parameters": {
                "deployment_name": reasoning_deployment,
                "is_reasoning_model": True
            },
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
                "tool_definitions": "{{item.tool_definitions}}",
            },
        },
        "task_completion": {
            "type": "azure_ai_evaluator",
            "name": "task_completion",
            "evaluator_name": "builtin.task_completion",
            "initialization_parameters": {
                "deployment_name": reasoning_deployment,
                "is_reasoning_model": True
            },
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
                "tool_definitions": "{{item.tool_definitions}}",
            },
        },
        "response_completeness": {
            "type": "azure_ai_evaluator",
            "name": "response_completeness",
            "evaluator_name": "builtin.response_completeness",
            "initialization_parameters": {
                "deployment_name": reasoning_deployment,
                "is_reasoning_model": True
            },
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
                "ground_truth": "{{item.ground_truth}}",
                "tool_definitions": "{{item.tool_definitions}}",
            },
        },
        "groundedness": {
            "type": "azure_ai_evaluator",
            "name": "groundedness",
            "evaluator_name": "builtin.groundedness",
            "initialization_parameters": {
                "deployment_name": model_deployment,
            },
            "data_mapping": {
                "query": "{{item.query}}",
                "tool_definitions": "{{item.tool_definitions}}",
                "response": "{{item.response}}",
            },
        },
        "relevance": {
            "type": "azure_ai_evaluator",
            "name": "relevance",
            "evaluator_name": "builtin.relevance",
            "initialization_parameters": {
                "deployment_name": reasoning_deployment,
                "is_reasoning_model": True
            },
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
            },
        },
        "tool_call_accuracy": {
            "type": "azure_ai_evaluator",
            "name": "tool_call_accuracy",
            "evaluator_name": "builtin.tool_call_accuracy",
            "initialization_parameters": {
                "deployment_name": reasoning_deployment,
                "is_reasoning_model": True
            },
            "data_mapping": {
                "query": "{{item.query}}",
                "tool_definitions": "{{item.tool_definitions}}",
                "tool_calls": "{{item.tool_calls}}",
                "response": "{{item.response}}",
            },
        },
        "tool_selection": {
            "type": "azure_ai_evaluator",
            "name": "tool_selection",
            "evaluator_name": "builtin.tool_selection",
            "initialization_parameters": {
                "deployment_name": reasoning_deployment,
                "is_reasoning_model": True
            },
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
                "tool_calls": "{{item.tool_calls}}",
                "tool_definitions": "{{item.tool_definitions}}",
            },
        },
        "tool_input_accuracy": {
            "type": "azure_ai_evaluator",
            "name": "tool_input_accuracy",
            "evaluator_name": "builtin.tool_input_accuracy",
            "initialization_parameters": {
                "deployment_name": reasoning_deployment,
                "is_reasoning_model": True
            },
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
                "tool_definitions": "{{item.tool_definitions}}",
            },
        },
        "tool_output_utilization": {
            "type": "azure_ai_evaluator",
            "name": "tool_output_utilization",
            "evaluator_name": "builtin.tool_output_utilization",
            "initialization_parameters": {
                "deployment_name": reasoning_deployment,
                "is_reasoning_model": True
            },
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
                "tool_calls": "{{item.tool_calls}}",
                "tool_definitions": "{{item.tool_definitions}}",
            },
        },
        "fluency": {
            "type": "azure_ai_evaluator",
            "name": "fluency",
            "evaluator_name": "builtin.fluency",
            "initialization_parameters": {
                "deployment_name": model_deployment,
            },
            "data_mapping": {
                "response": "{{item.response}}",
            },
        },
        "coherence": {
            "type": "azure_ai_evaluator",
            "name": "coherence",
            "evaluator_name": "builtin.coherence",
            "initialization_parameters": {
                "deployment_name": model_deployment,
            },
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
            },
        },
    }
    
    # Filter to requested evaluators
    criteria = []
    for name in evaluators:
        if name in evaluator_configs:
            criteria.append(evaluator_configs[name])
        else:
            logging.warning(f"Unknown evaluator: {name}")
    
    return criteria


def run_foundry_evaluation(dataset_path: str, output_path: str, instance_id: str, 
                           evaluators: list = None, eval_group_id: str = None,
                           foundry_dataset_id: str = None) -> dict:
    """
    Run Azure AI Foundry evaluation on a dataset.
    
    Args:
        dataset_path: Local path to JSONL evaluation dataset
        output_path: Directory for output files
        instance_id: Unique identifier for this evaluation run
        evaluators: List of evaluator names to run (None = use defaults)
        eval_group_id: Optional existing eval group ID to reuse (skip creating new)
        foundry_dataset_id: Optional existing Foundry dataset ID to reuse (skip uploading)
    
    Returns:
        dict with eval_id, eval_run_id, portal_url, and metrics summary
    """
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential
    
    # Get configuration from environment
    project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT") or os.environ.get("PROJECT_ENDPOINT")
    model_deployment = os.environ.get("AOAI_DEPLOYMENT_NAME", "gpt-4.1-mini")
    reasoning_deployment = os.environ.get("AOAI_REASONING_DEPLOYMENT_NAME", model_deployment)
    
    if not project_endpoint:
        logging.warning("No PROJECT_ENDPOINT configured - skipping Foundry evaluation")
        return {"status": "skipped", "reason": "No PROJECT_ENDPOINT configured"}
    
    # Use provided evaluators or defaults
    eval_list = evaluators if evaluators else DEFAULT_EVALUATORS
    
    try:
        # Create project client
        project_client = AIProjectClient(
            credential=DefaultAzureCredential(),
            endpoint=project_endpoint
        )
        
        # Get OpenAI client (beta SDK uses environment variable OPENAI_API_VERSION automatically)
        openai_client = project_client.get_openai_client()
        
        # Build testing criteria for selected evaluators
        testing_criteria = get_testing_criteria(eval_list, model_deployment, reasoning_deployment)
        
        if not testing_criteria:
            return {"status": "skipped", "reason": "No valid evaluators specified"}
        
        # Data source config for agent evaluation
        data_source_config = {
            "type": "custom",
            "item_schema": {
                "type": "object",
                "properties": {
                    "query": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "object"}}]},
                    "tool_definitions": {
                        "anyOf": [{"type": "object"}, {"type": "array", "items": {"type": "object"}}]
                    },
                    "tool_calls": {"anyOf": [{"type": "object"}, {"type": "array", "items": {"type": "object"}}]},
                    "response": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "object"}}]},
                    "ground_truth": {"type": "string"},
                },
                "required": ["query", "response"],
            },
            "include_sample_schema": True,
        }
        
        # Create or reuse eval group
        if eval_group_id:
            # Reuse existing eval group
            eval_id = eval_group_id
            logging.info(f"Reusing existing eval group: {eval_id}")
        else:
            # Create new eval group
            eval_name = f"voicelive-eval-{instance_id[:8]}"
            eval_object = openai_client.evals.create(
                name=eval_name,
                data_source_config=data_source_config,
                testing_criteria=testing_criteria,
            )
            eval_id = eval_object.id
            logging.info(f"Created eval group: {eval_id}")
        
        # Upload or reuse dataset
        if foundry_dataset_id:
            # Reuse existing Foundry dataset
            dataset_id = foundry_dataset_id
            logging.info(f"Reusing existing Foundry dataset: {dataset_id}")
        else:
            # Upload dataset with auto-versioning (like prototype)
            dataset_name = f"eval-dataset-{instance_id[:8]}"
            try:
                # Check for existing versions
                existing = list(project_client.datasets.list())
                existing_versions = [d for d in existing if d.name == dataset_name]
                if existing_versions:
                    new_version = str(max(int(d.version) for d in existing_versions) + 1)
                else:
                    new_version = "1"
            except Exception:
                new_version = "1"
            
            dataset = project_client.datasets.upload_file(
                name=dataset_name,
                version=new_version,
                file_path=dataset_path
            )
            dataset_id = dataset.id
            logging.info(f"Uploaded dataset: {dataset_id} (version {new_version})")
        
        # Create and run evaluation
        from openai.types.evals.create_eval_jsonl_run_data_source_param import (
            CreateEvalJSONLRunDataSourceParam,
            SourceFileID,
        )
        
        data_source = CreateEvalJSONLRunDataSourceParam(
            type="jsonl",
            source=SourceFileID(type="file_id", id=dataset_id),
        )
        
        eval_run = openai_client.evals.runs.create(
            eval_id=eval_id,
            name=f"run-{instance_id[:8]}",
            metadata={"instance_id": instance_id, "source": "voicelive-agent-v3"},
            data_source=data_source
        )
        eval_run_id = eval_run.id
        logging.info(f"Created eval run: {eval_run_id}")
        
        # Wait for completion (with timeout)
        import time
        max_wait = 600  # 10 minutes
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            run_status = openai_client.evals.runs.retrieve(run_id=eval_run_id, eval_id=eval_id)
            if run_status.status in ["completed", "failed"]:
                break
            time.sleep(10)
        
        # Get portal URL from the run object
        portal_url = getattr(run_status, 'report_url', None)
        logging.info(f"SDK report_url: {portal_url}")
        
        # The SDK report_url should be correct format:
        # https://ai.azure.com/nextgen/r/{project}/build/evaluations/{eval_id}/run/{run_id}
        if not portal_url:
            # Fallback: construct minimal working URL
            portal_url = f"https://ai.azure.com/build/evaluations/{eval_id}"
        
        logging.info(f"Final portal URL: {portal_url}")
        
        # Get results
        metrics_summary = {}
        if run_status.status == "completed":
            try:
                output_items = list(openai_client.evals.runs.output_items.list(
                    run_id=eval_run_id, eval_id=eval_id
                ))
                
                # Aggregate metrics
                metric_scores = {}
                metric_counts = {}
                for item in output_items:
                    results = item.results if hasattr(item, 'results') else []
                    for result in results:
                        name = result.name if hasattr(result, 'name') else result.get("name", "unknown")
                        score = result.score if hasattr(result, 'score') else result.get("score")
                        if isinstance(score, (int, float)):
                            if name not in metric_scores:
                                metric_scores[name] = 0
                                metric_counts[name] = 0
                            metric_scores[name] += score
                            metric_counts[name] += 1
                
                metrics_summary = {
                    name: round(metric_scores[name] / metric_counts[name], 3)
                    for name in metric_scores
                }
                
                # Write detailed results to output
                results_file = os.path.join(output_path, "eval_results.jsonl")
                with open(results_file, 'w', encoding='utf-8') as f:
                    for item in output_items:
                        f.write(json.dumps(item.model_dump(), indent=None) + '\n')
                        
            except Exception as e:
                logging.error(f"Error getting eval results: {e}")
        
        return {
            "status": run_status.status,
            "eval_id": eval_id,
            "eval_run_id": eval_run_id,
            "foundry_portal_url": portal_url,
            "evaluators_run": eval_list,
            "metrics_summary": metrics_summary,
        }
        
    except Exception as e:
        logging.error(f"Foundry evaluation error: {e}")
        return {"status": "failed", "error": str(e)}


@bp.activity_trigger(input_name="params")
def execute_evaluation(params: dict) -> dict:
    """Execute the actual evaluation (long-running)."""
    try:
        # Get dataset_path from params (download here to avoid temp file issues across workers)
        dataset_path = params["dataset_path"]
        output_path = params["output_path"]
        max_workers = params.get("max_workers", 4)
        session_mode = params.get("session_mode", "per-conversation")
        instance_id = params["instance_id"]
        evaluators = params.get("evaluators")  # List or None
        run_voicelive_tests = params.get("run_voicelive_tests", True)
        eval_group_id = params.get("eval_group_id")  # Optional: reuse existing eval group
        foundry_dataset_id = params.get("foundry_dataset_id")  # Optional: reuse existing dataset
        
        # Download dataset here (not in prepare_evaluation) to avoid temp file issues
        # Detect which container the file is in based on path patterns
        if dataset_path.startswith("voicelive_jobs/") or dataset_path.startswith("outputs/voicelive_jobs/") or "/voicelive_jobs/" in dataset_path:
            local_path, _ = download_results(dataset_path)
        else:
            local_path = download_dataset(dataset_path)
        
        # Count entries in dataset
        entry_count = 0
        entries = []
        with open(local_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith(('/', '#')):
                    entry_count += 1
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        
        logging.info(f"Dataset has {entry_count} entries")
        
        # Determine dataset type and validate format
        # Check if this is an "evaluation-ready" dataset (has query/response)
        # or a "raw audio" dataset (has WavPath but needs VoiceLive processing)
        has_audio_files = any(e.get("WavPath") or e.get("audio_path") for e in entries)
        has_eval_data = any(e.get("query") and e.get("response") for e in entries)
        
        voicelive_results = None
        if run_voicelive_tests and has_audio_files and not has_eval_data:
            # Dataset has audio files but no query/response - needs VoiceLive Container App
            # Use the VoiceLive Container App to process audio and generate evaluation dataset
            logging.warning("Dataset contains raw audio files without evaluation data")
            voicelive_results = {
                "status": "not_supported",
                "reason": "Dataset has audio files but no query/response. Use the VoiceLive Container App "
                         "(ca-voicelive-processor) to process audio files first, then run evaluation on "
                         "the generated output in the outputs container."
            }
            # We can still try to run Foundry evaluation on the raw data
        elif has_eval_data:
            logging.info("Dataset is evaluation-ready (has query/response fields)")
            voicelive_results = {"status": "not_needed", "reason": "Dataset already has evaluation data"}
        else:
            logging.info("Dataset structure unclear - proceeding with Foundry evaluation")
            voicelive_results = {"status": "skipped", "reason": "No audio files or existing eval data detected"}
        
        # Step 2: Run Foundry evaluators on the dataset
        eval_results = run_foundry_evaluation(
            dataset_path=local_path,
            output_path=output_path,
            instance_id=instance_id,
            evaluators=evaluators,
            eval_group_id=eval_group_id,
            foundry_dataset_id=foundry_dataset_id
        )
        
        # Combine results
        results = {
            "status": "completed",
            "entries_evaluated": entry_count,
            "instance_id": instance_id,
            "timestamp": datetime.utcnow().isoformat(),
            "voicelive_tests": voicelive_results,
            "foundry_evaluation": eval_results,
            "foundry_portal_url": eval_results.get("foundry_portal_url"),
            "metrics": eval_results.get("metrics_summary", {}),
        }
        
        # Write results to output
        results_file = os.path.join(output_path, "results.json")
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        return results
        
    except Exception as e:
        logging.error(f"execute_evaluation error: {e}")
        return {"status": "failed", "error": str(e)}


@bp.activity_trigger(input_name="params")
def finalize_evaluation(params: dict) -> dict:
    """Upload results to blob storage and cleanup."""
    try:
        output_path = params["output_path"]
        instance_id = params["instance_id"]
        eval_result = params["eval_result"]
        
        # Upload results to blob storage
        client = get_blob_client()
        if client:
            container = os.environ.get("AZURE_STORAGE_OUTPUTS_CONTAINER", "outputs")
            container_client = client.get_container_client(container)
            
            results_file = os.path.join(output_path, "results.json")
            if os.path.exists(results_file):
                blob_path = f"evaluations/{instance_id}/results.json"
                blob_client = container_client.get_blob_client(blob_path)
                with open(results_file, 'rb') as f:
                    blob_client.upload_blob(f, overwrite=True)
                
                eval_result["results_blob_path"] = f"{container}/{blob_path}"
        
        # Cleanup temp files
        import shutil
        if os.path.exists(output_path):
            shutil.rmtree(output_path, ignore_errors=True)
        
        return eval_result
        
    except Exception as e:
        logging.error(f"finalize_evaluation error: {e}")
        return {"status": "completed_with_errors", "error": str(e), **params.get("eval_result", {})}


# HTTP trigger to start evaluation (Durable Functions client)
@app.route(route="run_voicelive_evaluation", methods=["POST"])
@app.durable_client_input(client_name="client")
async def run_voicelive_evaluation(req: func.HttpRequest, client) -> func.HttpResponse:
    """
    Start a VoiceLive evaluation job (async with Durable Functions).
    
    Returns an instance_id that can be used to check status.
    """
    logging.info("run_voicelive_evaluation called")
    
    try:
        body = req.get_json()
        dataset_path = body.get("test_files_path") or body.get("dataset_path")
        
        if not dataset_path:
            return func.HttpResponse(
                json.dumps({"error": "dataset_path or test_files_path required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Start the orchestration with all parameters
        instance_id = await client.start_new(
            "evaluation_orchestrator",
            client_input={
                "dataset_path": dataset_path,
                "max_workers": body.get("max_workers", 4),
                "session_mode": body.get("session_mode", "per-conversation"),
                "evaluators": body.get("evaluators"),  # List of evaluator names or None for all
                "run_voicelive_tests": body.get("run_voicelive_tests", True),
                # Optional: reuse existing Foundry resources
                "eval_group_id": body.get("eval_group_id"),  # Reuse existing eval group
                "foundry_dataset_id": body.get("foundry_dataset_id"),  # Reuse existing Foundry dataset
            }
        )
        
        logging.info(f"Started evaluation orchestration: {instance_id}")
        
        return func.HttpResponse(
            json.dumps({
                "action": "run_voicelive_evaluation",
                "status": "started",
                "instance_id": instance_id,
                "message": "Evaluation started. Use check_evaluation_status to monitor progress.",
                "check_status_instruction": f"Call check_evaluation_status with instance_id: {instance_id}"
            }),
            mimetype="application/json"
        )
        
    except Exception as e:
        logging.error(f"run_voicelive_evaluation error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="check_evaluation_status", methods=["POST"])
@app.durable_client_input(client_name="client")
async def check_evaluation_status(req: func.HttpRequest, client) -> func.HttpResponse:
    """
    Check the status of a running evaluation job.
    """
    logging.info("check_evaluation_status called")
    
    try:
        body = req.get_json()
        instance_id = body.get("instance_id")
        
        if not instance_id:
            return func.HttpResponse(
                json.dumps({"error": "instance_id required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Get orchestration status
        status = await client.get_status(instance_id)
        
        if status is None:
            return func.HttpResponse(
                json.dumps({
                    "action": "check_evaluation_status",
                    "instance_id": instance_id,
                    "status": "not_found",
                    "message": "No evaluation found with this instance_id"
                }),
                status_code=404,
                mimetype="application/json"
            )
        
        runtime_status = status.runtime_status.name if status.runtime_status else "Unknown"
        
        response = {
            "action": "check_evaluation_status",
            "instance_id": instance_id,
            "status": runtime_status.lower(),
            "created_time": status.created_time.isoformat() if status.created_time else None,
            "last_updated_time": status.last_updated_time.isoformat() if status.last_updated_time else None,
        }
        
        if runtime_status == "Completed":
            response["output"] = status.output
            response["message"] = "Evaluation completed successfully."
            # Extract and highlight portal URL for agent
            if status.output and isinstance(status.output, dict):
                portal_url = status.output.get("foundry_portal_url")
                if portal_url:
                    response["foundry_portal_url"] = portal_url
                    response["message"] = f"Evaluation completed. View detailed results at: {portal_url}"
                # Also include metrics summary at top level for easy access
                metrics = status.output.get("metrics")
                if metrics:
                    response["metrics_summary"] = metrics
        elif runtime_status == "Failed":
            response["error"] = str(status.output) if status.output else "Unknown error"
            response["message"] = "Evaluation failed."
        elif runtime_status == "Running":
            response["message"] = "Evaluation is still running. Check again in a few moments."
        elif runtime_status == "Pending":
            response["message"] = "Evaluation is queued and will start soon."
        
        return func.HttpResponse(
            json.dumps(response),
            mimetype="application/json"
        )
        
    except Exception as e:
        logging.error(f"check_evaluation_status error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


# Register the blueprint with the app
app.register_blueprint(bp)


@app.route(route="analyze_evaluation_results", methods=["POST"])
def analyze_evaluation_results(req: func.HttpRequest) -> func.HttpResponse:
    """Analyze evaluation output files.
    
    Uses unified flexible path handling to find results.
    """
    logging.info("analyze_evaluation_results called")
    
    try:
        body = req.get_json()
        results_path = body.get("results_path")
        
        if not results_path:
            return func.HttpResponse(
                json.dumps({"error": "results_path required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Use unified flexible download
        try:
            local_path, actual_blob = download_results(results_path)
        except ValueError as e:
            return func.HttpResponse(
                json.dumps({
                    "error": "No results files found",
                    "search_path": results_path,
                    "message": str(e)
                }),
                status_code=404,
                mimetype="application/json"
            )
        
        # Read and analyze the file
        with open(local_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Cleanup temp file
        os.unlink(local_path)
        
        # Try to parse as JSON first (new format), then as JSONL (legacy)
        entries = []
        results_data = None
        try:
            results_data = json.loads(content)
            # If it's the new evaluation results format with foundry_evaluation
            if isinstance(results_data, dict):
                return func.HttpResponse(
                    json.dumps({
                        "action": "analyze_evaluation_results",
                        "status": "success",
                        "file": actual_blob,
                        "evaluation_status": results_data.get("status", "unknown"),
                        "entries_evaluated": results_data.get("entries_evaluated", 0),
                        "foundry_portal_url": results_data.get("foundry_evaluation", {}).get("foundry_portal_url"),
                        "evaluators_run": results_data.get("foundry_evaluation", {}).get("evaluators_run", []),
                        "metrics_summary": results_data.get("foundry_evaluation", {}).get("metrics_summary", {}),
                        "voicelive_status": results_data.get("voicelive_tests", {}).get("status", "unknown"),
                        "timestamp": results_data.get("timestamp")
                    }),
                    mimetype="application/json"
                )
            elif isinstance(results_data, list):
                entries = results_data
        except json.JSONDecodeError:
            # Try JSONL format
            for line in content.split('\n'):
                if line.strip():
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        
        # Extract metrics
        metrics = {}
        for entry in entries:
            for key, value in entry.items():
                if isinstance(value, (int, float)):
                    if key not in metrics:
                        metrics[key] = []
                    metrics[key].append(value)
        
        summary = {}
        for key, values in metrics.items():
            summary[key] = {
                "avg": sum(values) / len(values),
                "min": min(values),
                "max": max(values),
                "count": len(values)
            }
        
        return func.HttpResponse(
            json.dumps({
                "action": "analyze_evaluation_results",
                "status": "success",
                "file": actual_blob,
                "entries_analyzed": len(entries),
                "metrics_found": len(metrics),
                "summary": summary
            }),
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"analyze_evaluation_results error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


# =============================================================================
# Foundry Resource Management Endpoints
# =============================================================================

@app.route(route="list_evaluation_groups", methods=["POST", "GET"])
def list_evaluation_groups(req: func.HttpRequest) -> func.HttpResponse:
    """List all evaluation groups in the Foundry project."""
    logging.info("list_evaluation_groups called")
    
    try:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential
        
        project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT") or os.environ.get("PROJECT_ENDPOINT")
        if not project_endpoint:
            return func.HttpResponse(
                json.dumps({"error": "PROJECT_ENDPOINT not configured"}),
                status_code=500,
                mimetype="application/json"
            )
        
        project_client = AIProjectClient(
            credential=DefaultAzureCredential(),
            endpoint=project_endpoint
        )
        openai_client = project_client.get_openai_client()
        
        # List all evaluation groups
        eval_groups = list(openai_client.evals.list())
        
        groups_list = []
        for group in eval_groups:
            groups_list.append({
                "id": group.id,
                "name": group.name,
                "created_at": getattr(group, 'created_at', None),
            })
        
        return func.HttpResponse(
            json.dumps({
                "action": "list_evaluation_groups",
                "count": len(groups_list),
                "evaluation_groups": groups_list
            }),
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"list_evaluation_groups error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="list_foundry_datasets", methods=["POST", "GET"])
def list_foundry_datasets(req: func.HttpRequest) -> func.HttpResponse:
    """List all datasets in the Foundry project."""
    logging.info("list_foundry_datasets called")
    
    try:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential
        
        project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT") or os.environ.get("PROJECT_ENDPOINT")
        if not project_endpoint:
            return func.HttpResponse(
                json.dumps({"error": "PROJECT_ENDPOINT not configured"}),
                status_code=500,
                mimetype="application/json"
            )
        
        project_client = AIProjectClient(
            credential=DefaultAzureCredential(),
            endpoint=project_endpoint
        )
        
        # List all datasets
        datasets = list(project_client.datasets.list())
        
        datasets_list = []
        for dataset in datasets:
            # Get versions for this dataset
            try:
                versions = list(project_client.datasets.list_versions(name=dataset.name))
                version_count = len(versions)
                latest_version = max(int(v.version) for v in versions) if versions else 0
            except Exception:
                version_count = 0
                latest_version = 0
            
            datasets_list.append({
                "id": dataset.id,
                "name": dataset.name,
                "version_count": version_count,
                "latest_version": latest_version,
            })
        
        return func.HttpResponse(
            json.dumps({
                "action": "list_foundry_datasets",
                "count": len(datasets_list),
                "datasets": datasets_list
            }),
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"list_foundry_datasets error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="delete_evaluation_groups", methods=["POST"])
def delete_evaluation_groups(req: func.HttpRequest) -> func.HttpResponse:
    """Delete evaluation groups matching a search string."""
    logging.info("delete_evaluation_groups called")
    
    try:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential
        
        body = req.get_json()
        search_string = body.get("search_string")
        eval_group_id = body.get("eval_group_id")  # Delete specific ID
        
        if not search_string and not eval_group_id:
            return func.HttpResponse(
                json.dumps({"error": "Either search_string or eval_group_id required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT") or os.environ.get("PROJECT_ENDPOINT")
        if not project_endpoint:
            return func.HttpResponse(
                json.dumps({"error": "PROJECT_ENDPOINT not configured"}),
                status_code=500,
                mimetype="application/json"
            )
        
        project_client = AIProjectClient(
            credential=DefaultAzureCredential(),
            endpoint=project_endpoint
        )
        openai_client = project_client.get_openai_client()
        
        deleted = []
        skipped = []
        
        if eval_group_id:
            # Delete specific group by ID
            try:
                openai_client.evals.delete(eval_id=eval_group_id)
                deleted.append({"id": eval_group_id})
            except Exception as e:
                skipped.append({"id": eval_group_id, "error": str(e)})
        else:
            # Delete groups matching search string
            eval_groups = list(openai_client.evals.list())
            for group in eval_groups:
                if search_string in (group.name or ""):
                    try:
                        openai_client.evals.delete(eval_id=group.id)
                        deleted.append({"id": group.id, "name": group.name})
                    except Exception as e:
                        skipped.append({"id": group.id, "name": group.name, "error": str(e)})
                else:
                    skipped.append({"id": group.id, "name": group.name, "reason": "No match"})
        
        return func.HttpResponse(
            json.dumps({
                "action": "delete_evaluation_groups",
                "deleted_count": len(deleted),
                "skipped_count": len(skipped),
                "deleted": deleted,
                "skipped": skipped
            }),
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"delete_evaluation_groups error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="delete_foundry_datasets", methods=["POST"])
def delete_foundry_datasets(req: func.HttpRequest) -> func.HttpResponse:
    """Delete Foundry datasets matching a search string."""
    logging.info("delete_foundry_datasets called")
    
    try:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential
        
        body = req.get_json()
        search_string = body.get("search_string")
        dataset_name = body.get("dataset_name")  # Delete specific dataset
        version = body.get("version")  # Optional: delete specific version
        
        if not search_string and not dataset_name:
            return func.HttpResponse(
                json.dumps({"error": "Either search_string or dataset_name required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT") or os.environ.get("PROJECT_ENDPOINT")
        if not project_endpoint:
            return func.HttpResponse(
                json.dumps({"error": "PROJECT_ENDPOINT not configured"}),
                status_code=500,
                mimetype="application/json"
            )
        
        project_client = AIProjectClient(
            credential=DefaultAzureCredential(),
            endpoint=project_endpoint
        )
        
        deleted = []
        skipped = []
        
        if dataset_name:
            # Delete specific dataset
            try:
                if version:
                    # Delete specific version
                    project_client.datasets.delete(name=dataset_name, version=version)
                    deleted.append({"name": dataset_name, "version": version})
                else:
                    # Delete all versions
                    versions = list(project_client.datasets.list_versions(name=dataset_name))
                    for v in versions:
                        project_client.datasets.delete(name=dataset_name, version=v.version)
                        deleted.append({"name": dataset_name, "version": v.version})
            except Exception as e:
                skipped.append({"name": dataset_name, "error": str(e)})
        else:
            # Delete datasets matching search string
            datasets = list(project_client.datasets.list())
            for dataset in datasets:
                if search_string in (dataset.name or ""):
                    try:
                        versions = list(project_client.datasets.list_versions(name=dataset.name))
                        for v in versions:
                            project_client.datasets.delete(name=dataset.name, version=v.version)
                            deleted.append({"name": dataset.name, "version": v.version})
                    except Exception as e:
                        skipped.append({"name": dataset.name, "error": str(e)})
                else:
                    skipped.append({"name": dataset.name, "reason": "No match"})
        
        return func.HttpResponse(
            json.dumps({
                "action": "delete_foundry_datasets",
                "deleted_count": len(deleted),
                "skipped_count": len(skipped),
                "deleted": deleted,
                "skipped": [s for s in skipped if "error" in s]  # Only show errors, not non-matches
            }),
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"delete_foundry_datasets error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )
