"""
Azure Functions HTTP Triggers for VoiceLive Evaluation Tools

These functions expose the evaluation tools as HTTP endpoints that can be
called by the Foundry Agent via OpenAPI tool integration.

Each function corresponds to one agent tool:
- POST /api/check_dataset_schema
- POST /api/validate_dataset_consistency
- POST /api/validate_dataset_quality
- POST /api/get_evaluation_recommendations
- POST /api/run_voicelive_evaluation
- POST /api/list_datasets
- POST /api/analyze_evaluation_results
"""

import os
import json
import logging
import tempfile
from pathlib import Path

import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

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


def download_dataset(blob_path: str) -> str:
    """Download dataset from blob storage to temp file."""
    client = get_blob_client()
    if not client:
        raise ValueError("AZURE_STORAGE_ACCOUNT not configured")
    
    container = os.environ.get("AZURE_STORAGE_DATASETS_CONTAINER", "datasets")
    blob_client = client.get_container_client(container).get_blob_client(blob_path)
    
    suffix = Path(blob_path).suffix or ".jsonl"
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
        
        # Analyze schema
        required_fields = {"ConversationId", "Turns"}
        optional_fields = {"SystemPrompt", "Voice", "Temperature", "Modality"}
        turn_fields = {"Role", "Content"}
        
        found_required = set()
        found_optional = set()
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
                    
                    for field in required_fields:
                        if field in entry:
                            found_required.add(field)
                        else:
                            missing_required.add(field)
                    
                    for field in optional_fields:
                        if field in entry:
                            found_optional.add(field)
                except json.JSONDecodeError:
                    pass
        
        # Cleanup temp file
        os.unlink(local_path)
        
        status = "passed" if not missing_required else "failed"
        
        return func.HttpResponse(
            json.dumps({
                "action": "check_dataset_schema",
                "status": status,
                "can_proceed": status == "passed",
                "entries_analyzed": entry_count,
                "required_fields": {
                    "found": list(found_required),
                    "missing": list(missing_required)
                },
                "optional_fields": {
                    "found": list(found_optional),
                    "missing": list(optional_fields - found_optional)
                }
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
        expected_turns = body.get("expected_turns")
        
        if not dataset_path:
            return func.HttpResponse(
                json.dumps({"error": "dataset_path required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        local_path = download_dataset(dataset_path)
        
        # Validate structure
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
                    
                    # Check required fields
                    if "ConversationId" not in entry:
                        errors.append(f"Line {line_num}: Missing ConversationId")
                    else:
                        cid = entry["ConversationId"]
                        if cid in conversation_ids:
                            errors.append(f"Line {line_num}: Duplicate ConversationId '{cid}'")
                        conversation_ids.add(cid)
                    
                    if "Turns" not in entry:
                        errors.append(f"Line {line_num}: Missing Turns")
                    elif not isinstance(entry["Turns"], list):
                        errors.append(f"Line {line_num}: Turns must be array")
                    elif expected_turns and len(entry["Turns"]) != expected_turns:
                        warnings.append(f"Line {line_num}: Expected {expected_turns} turns, got {len(entry['Turns'])}")
                    
                except json.JSONDecodeError as e:
                    errors.append(f"Line {line_num}: Invalid JSON - {e}")
        
        os.unlink(local_path)
        
        status = "passed" if not errors else "failed"
        
        return func.HttpResponse(
            json.dumps({
                "action": "validate_dataset_consistency",
                "status": status,
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
        
        # Quality checks
        issues = []
        entry_count = 0
        total_turns = 0
        empty_contents = 0
        
        with open(local_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('//') or line.startswith('#'):
                    continue
                
                try:
                    entry = json.loads(line)
                    entry_count += 1
                    
                    turns = entry.get("Turns", [])
                    total_turns += len(turns)
                    
                    for i, turn in enumerate(turns):
                        content = turn.get("Content", "")
                        if not content or not content.strip():
                            empty_contents += 1
                            issues.append(f"Conv {entry.get('ConversationId')}, Turn {i}: Empty content")
                
                except json.JSONDecodeError:
                    pass
        
        os.unlink(local_path)
        
        quality_score = max(0, 100 - (empty_contents * 5) - (len(issues) * 2))
        
        return func.HttpResponse(
            json.dumps({
                "action": "validate_dataset_quality",
                "status": "completed",
                "entries_analyzed": entry_count,
                "total_turns": total_turns,
                "quality_score": quality_score,
                "issues_found": len(issues),
                "issues": issues[:10],  # Sample
                "empty_contents": empty_contents
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


@app.route(route="run_voicelive_evaluation", methods=["POST"])
def run_voicelive_evaluation(req: func.HttpRequest) -> func.HttpResponse:
    """
    Run VoiceLive evaluation.
    
    NOTE: This is a placeholder. Full evaluation requires:
    - Longer execution time than Functions allow (10 min limit)
    - Consider using Durable Functions or Container Apps for this
    """
    logging.info("run_voicelive_evaluation called")
    
    return func.HttpResponse(
        json.dumps({
            "action": "run_voicelive_evaluation",
            "status": "not_implemented",
            "error": "Full evaluation requires longer execution time. Use Container Apps deployment or Durable Functions.",
            "recommendation": "For evaluations, deploy the runner to Azure Container Apps instead of Functions."
        }),
        status_code=501,
        mimetype="application/json"
    )


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
