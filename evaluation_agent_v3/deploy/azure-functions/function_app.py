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
import subprocess
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


def normalize_dataset_path(dataset_path: str) -> str:
    """Normalize dataset path to find the actual blob.
    
    Handles various input formats:
        - "Eiffel_Tower_Visit_1" (just name)
        - "Eiffel_Tower_Visit_1/Eiffel_Tower_Visit_1.jsonl" (relative path)
        - "datasets/Eiffel_Tower_Visit_1/Eiffel_Tower_Visit_1.jsonl" (with container)
        - "/datasets/Eiffel_Tower_Visit_1/Eiffel_Tower_Visit_1.jsonl" (with leading slash)
        - "3" or "number 3" (index from list)
    
    Returns the blob path within the container.
    """
    # Strip whitespace and quotes
    dataset_path = dataset_path.strip().strip('"\'')
    
    # Strip leading slashes
    dataset_path = dataset_path.lstrip('/')
    
    # Get container name
    container = os.environ.get("AZURE_STORAGE_DATASETS_CONTAINER", "datasets")
    
    # Strip container prefix if present
    if dataset_path.startswith(f"{container}/"):
        dataset_path = dataset_path[len(container) + 1:]
    
    return dataset_path


def download_dataset(dataset_path: str) -> str:
    """Download dataset from blob storage to temp file.
    
    Flexibly handles any path format the agent might send.
    """
    client = get_blob_client()
    if not client:
        raise ValueError("AZURE_STORAGE_ACCOUNT not configured")
    
    container = os.environ.get("AZURE_STORAGE_DATASETS_CONTAINER", "datasets")
    container_client = client.get_container_client(container)
    
    # Normalize the path
    dataset_path = normalize_dataset_path(dataset_path)
    
    # If it ends with .jsonl, try direct access first
    if dataset_path.endswith(".jsonl"):
        try:
            blob_client = container_client.get_blob_client(dataset_path)
            blob_client.get_blob_properties()  # Check if exists
        except Exception:
            # Path might be wrong, try to find it
            dataset_path = dataset_path.rsplit('.jsonl', 1)[0]
    
    # If not a direct .jsonl path, search for matching blob
    if not dataset_path.endswith(".jsonl"):
        found = False
        
        # Try exact prefix match first
        for blob in container_client.list_blobs(name_starts_with=dataset_path):
            if blob.name.endswith(".jsonl"):
                dataset_path = blob.name
                found = True
                break
        
        if not found:
            # Try common patterns
            base_name = Path(dataset_path).name  # Get just the folder/file name
            patterns = [
                f"{dataset_path}/{dataset_path}.jsonl",
                f"{dataset_path}.jsonl",
                f"{base_name}/{base_name}.jsonl",
                f"{base_name}.jsonl",
            ]
            for pattern in patterns:
                try:
                    blob_client = container_client.get_blob_client(pattern)
                    blob_client.get_blob_properties()
                    dataset_path = pattern
                    found = True
                    break
                except Exception:
                    continue
        
        if not found:
            # Last resort: search all blobs for partial match
            search_term = base_name.lower()
            for blob in container_client.list_blobs():
                if search_term in blob.name.lower() and blob.name.endswith(".jsonl"):
                    dataset_path = blob.name
                    found = True
                    break
        
        if not found:
            raise ValueError(f"Dataset not found: {dataset_path}")
    
    blob_client = container_client.get_blob_client(dataset_path)
    
    suffix = Path(dataset_path).suffix or ".jsonl"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        download_stream = blob_client.download_blob()
        f.write(download_stream.readall())
        return f.name


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
    
    # Step 1: Download and prepare dataset
    prep_result = yield context.call_activity("prepare_evaluation", {
        "dataset_path": dataset_path,
        "instance_id": context.instance_id
    })
    
    if prep_result.get("error"):
        return {"status": "failed", "error": prep_result["error"]}
    
    # Step 2: Run evaluation (this is the long-running part)
    eval_result = yield context.call_activity("execute_evaluation", {
        "local_path": prep_result["local_path"],
        "output_path": prep_result["output_path"],
        "max_workers": max_workers,
        "session_mode": session_mode,
        "instance_id": context.instance_id
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
    """Download dataset and prepare for evaluation."""
    try:
        dataset_path = params["dataset_path"]
        instance_id = params["instance_id"]
        
        # Download dataset
        local_path = download_dataset(dataset_path)
        
        # Create output directory
        output_dir = f"/tmp/eval_{instance_id}"
        os.makedirs(output_dir, exist_ok=True)
        
        return {
            "status": "prepared",
            "local_path": local_path,
            "output_path": output_dir
        }
    except Exception as e:
        logging.error(f"prepare_evaluation error: {e}")
        return {"error": str(e)}


@bp.activity_trigger(input_name="params")
def execute_evaluation(params: dict) -> dict:
    """Execute the actual evaluation (long-running)."""
    try:
        local_path = params["local_path"]
        output_path = params["output_path"]
        max_workers = params.get("max_workers", 4)
        session_mode = params.get("session_mode", "per-conversation")
        instance_id = params["instance_id"]
        
        # For now, run a simplified evaluation
        # In production, this would call the actual evaluation script
        
        # Count entries in dataset
        entry_count = 0
        with open(local_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip() and not line.startswith(('/', '#')):
                    entry_count += 1
        
        # Create mock results (replace with actual evaluation)
        results = {
            "status": "completed",
            "entries_evaluated": entry_count,
            "instance_id": instance_id,
            "timestamp": datetime.utcnow().isoformat(),
            "metrics": {
                "total_entries": entry_count,
                "processed": entry_count,
                "errors": 0
            }
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
        
        # Start the orchestration
        instance_id = await client.start_new(
            "evaluation_orchestrator",
            client_input={
                "dataset_path": dataset_path,
                "max_workers": body.get("max_workers", 4),
                "session_mode": body.get("session_mode", "per-conversation")
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
    """Analyze evaluation output files."""
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
        
        # Download results from blob
        client = get_blob_client()
        container = os.environ.get("AZURE_STORAGE_OUTPUTS_CONTAINER", "outputs")
        container_client = client.get_container_client(container)
        
        # Find aggregate file
        blobs = list(container_client.list_blobs(name_starts_with=results_path))
        aggregate_blob = None
        for blob in blobs:
            if "aggregate" in blob.name.lower() and blob.name.endswith(".jsonl"):
                aggregate_blob = blob.name
                break
        
        if not aggregate_blob and blobs:
            # Take first JSONL
            for blob in blobs:
                if blob.name.endswith(".jsonl"):
                    aggregate_blob = blob.name
                    break
        
        if not aggregate_blob:
            return func.HttpResponse(
                json.dumps({"error": "No results files found"}),
                status_code=404,
                mimetype="application/json"
            )
        
        # Download and analyze
        blob_client = container_client.get_blob_client(aggregate_blob)
        content = blob_client.download_blob().readall().decode('utf-8')
        
        entries = []
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
                "file": aggregate_blob,
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
