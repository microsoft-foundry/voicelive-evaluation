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
import secrets
from pathlib import Path
from datetime import datetime, timedelta
import uuid

import azure.functions as func
import azure.durable_functions as df
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.data.tables import TableServiceClient, TableClient

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
# Config Journal & Eval Group Naming
# =============================================================================

def get_table_client(table_name: str) -> TableClient:
    """Get Azure Table client for config journaling."""
    account = os.environ.get("AZURE_STORAGE_ACCOUNT")
    if not account:
        return None
    credential = DefaultAzureCredential()
    return TableClient(
        endpoint=f"https://{account}.table.core.windows.net",
        table_name=table_name,
        credential=credential
    )


def generate_eval_group_name(session_config: dict = None) -> str:
    """
    Generate eval group name based on VoiceLive session config.
    
    Format: {model}_{voice}_{vad}_{eod}
    Example: gpt-realtime_alloy_0.5_500
    """
    if not session_config:
        # Use defaults
        session_config = {
            "model": "gpt-realtime",
            "voice": "alloy",
            "vad_threshold": "0.5",
            "end_of_speech_timeout": "500"
        }
    
    model = session_config.get("model", "gpt-realtime")
    voice = session_config.get("voice", "alloy")
    vad = session_config.get("vad_threshold", "0.5")
    eod = session_config.get("end_of_speech_timeout", "500")
    
    # Clean up model name (remove version suffixes for grouping)
    model_clean = model.replace("-", "").replace(".", "")
    
    return f"{model_clean}_{voice}_{vad}_{eod}"


def generate_run_name(dataset_name: str, dataset_version: str, evaluators: list) -> str:
    """
    Generate run name with timestamp and dataset reference.
    
    Format: YYYYMMDD-HHMMSS-xxx │ {dataset}_v{version} │ {evaluator_summary}
    Example: 20260206-122000-x7k │ Eiffel_Tower_Visit_1_v1 │ all
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    random_suffix = secrets.token_hex(2)[:3]  # 3 char hex
    
    # Summarize evaluators
    if not evaluators or len(evaluators) >= 10:
        eval_summary = "all"
    elif len(evaluators) >= 5:
        eval_summary = "default"
    else:
        eval_summary = "subset"
    
    # Clean dataset name (extract base name)
    dataset_base = Path(dataset_name).stem if dataset_name else "dataset"
    
    return f"{timestamp}-{random_suffix} │ {dataset_base}_v{dataset_version} │ {eval_summary}"


def journal_eval_group(eval_group_name: str, session_config: dict, eval_group_id: str = None) -> bool:
    """
    Record eval group creation in config journal.
    
    Creates entry in Azure Table Storage for tracking config → eval group mapping.
    """
    try:
        table_client = get_table_client("configjournal")
        if not table_client:
            logging.warning("Table storage not configured for journaling")
            return False
        
        timestamp = datetime.utcnow().isoformat()
        
        entity = {
            "PartitionKey": "evalgroups",
            "RowKey": f"{eval_group_name}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            "EvalGroupName": eval_group_name,
            "EvalGroupId": eval_group_id or "",
            "Model": session_config.get("model", ""),
            "Voice": session_config.get("voice", ""),
            "VadThreshold": str(session_config.get("vad_threshold", "")),
            "EndOfSpeechTimeout": str(session_config.get("end_of_speech_timeout", "")),
            "CreatedAt": timestamp,
        }
        
        table_client.upsert_entity(entity)
        logging.info(f"Journaled eval group: {eval_group_name}")
        return True
        
    except Exception as e:
        logging.warning(f"Failed to journal eval group: {e}")
        return False


def get_session_configs() -> list:
    """Get available session configs from Table Storage."""
    try:
        table_client = get_table_client("sessionconfigs")
        if not table_client:
            return []
        
        configs = []
        for entity in table_client.query_entities("PartitionKey eq 'voicelive'"):
            config = {
                "name": entity.get("Name", entity["RowKey"]),
                "description": entity.get("Description", ""),
                "model": entity.get("Model", "gpt-realtime"),
                "sample_rate": int(entity.get("SampleRate", 24000)),
                "voice_name": entity.get("VoiceName", "alloy"),
                "voice_type": entity.get("VoiceType", "preset"),
                "vad_type": entity.get("VadType", "azure_semantic_vad_multilingual"),
                "vad_threshold": entity.get("VadThreshold"),  # None = SDK default
                "silence_duration_ms": entity.get("SilenceDurationMs"),  # None = SDK default
                "eou_detection": entity.get("EouDetection", "true").lower() == "true",
                "eou_model": entity.get("EouModel", "azure_semantic_v1_multilingual"),
                "transcription_model": entity.get("TranscriptionModel", "gpt-4o-transcribe"),
                "noise_reduction": entity.get("NoiseReduction", "azure_deep_noise_suppression"),
                "echo_cancellation": entity.get("EchoCancellation", "server_echo_cancellation"),
                "is_default": entity.get("IsDefault", "false").lower() == "true",
            }
            # Convert threshold to float if present
            if config["vad_threshold"]:
                try:
                    config["vad_threshold"] = float(config["vad_threshold"])
                except (ValueError, TypeError):
                    config["vad_threshold"] = None
            # Convert silence_duration_ms to int if present
            if config["silence_duration_ms"]:
                try:
                    config["silence_duration_ms"] = int(config["silence_duration_ms"])
                except (ValueError, TypeError):
                    config["silence_duration_ms"] = None
            configs.append(config)
        return configs
        
    except Exception as e:
        logging.warning(f"Failed to get session configs: {e}")
        return []


def get_session_config_by_name(name: str) -> dict:
    """Get a specific session config by name."""
    try:
        table_client = get_table_client("sessionconfigs")
        if not table_client:
            return None
        
        entity = table_client.get_entity(partition_key="voicelive", row_key=name)
        config = {
            "name": entity.get("Name", entity["RowKey"]),
            "description": entity.get("Description", ""),
            "model": entity.get("Model", "gpt-realtime"),
            "sample_rate": int(entity.get("SampleRate", 24000)),
            "voice_name": entity.get("VoiceName", "alloy"),
            "voice_type": entity.get("VoiceType", "preset"),
            "vad_type": entity.get("VadType", "azure_semantic_vad_multilingual"),
            "vad_threshold": entity.get("VadThreshold"),
            "silence_duration_ms": entity.get("SilenceDurationMs"),
            "eou_detection": entity.get("EouDetection", "true").lower() == "true",
            "eou_model": entity.get("EouModel", "azure_semantic_v1_multilingual"),
            "transcription_model": entity.get("TranscriptionModel", "gpt-4o-transcribe"),
            "noise_reduction": entity.get("NoiseReduction", "azure_deep_noise_suppression"),
            "echo_cancellation": entity.get("EchoCancellation", "server_echo_cancellation"),
            "is_default": entity.get("IsDefault", "false").lower() == "true",
        }
        if config["vad_threshold"]:
            try:
                config["vad_threshold"] = float(config["vad_threshold"])
            except (ValueError, TypeError):
                config["vad_threshold"] = None
        if config["silence_duration_ms"]:
            try:
                config["silence_duration_ms"] = int(config["silence_duration_ms"])
            except (ValueError, TypeError):
                config["silence_duration_ms"] = None
        return config
    except Exception as e:
        logging.warning(f"Failed to get session config '{name}': {e}")
        return None


def upsert_session_config(config: dict) -> bool:
    """Create or update a session config."""
    try:
        table_client = get_table_client("sessionconfigs")
        if not table_client:
            return False
        
        name = config.get("name")
        if not name:
            return False
        
        entity = {
            "PartitionKey": "voicelive",
            "RowKey": name,
            "Name": name,
            "Description": config.get("description", ""),
            "Model": config.get("model", "gpt-realtime"),
            "SampleRate": str(config.get("sample_rate", 24000)),
            "VoiceName": config.get("voice_name", "alloy"),
            "VoiceType": config.get("voice_type", "preset"),
            "VadType": config.get("vad_type", "azure_semantic_vad_multilingual"),
            "VadThreshold": str(config["vad_threshold"]) if config.get("vad_threshold") is not None else "",
            "SilenceDurationMs": str(config["silence_duration_ms"]) if config.get("silence_duration_ms") is not None else "",
            "EouDetection": "true" if config.get("eou_detection", True) else "false",
            "EouModel": config.get("eou_model", "azure_semantic_v1_multilingual"),
            "TranscriptionModel": config.get("transcription_model", "gpt-4o-transcribe"),
            "NoiseReduction": config.get("noise_reduction", "azure_deep_noise_suppression"),
            "EchoCancellation": config.get("echo_cancellation", "server_echo_cancellation"),
            "IsDefault": "true" if config.get("is_default", False) else "false",
        }
        
        table_client.upsert_entity(entity)
        logging.info(f"Upserted session config: {name}")
        return True
    except Exception as e:
        logging.error(f"Failed to upsert session config: {e}")
        return False


def delete_session_config(name: str) -> bool:
    """Delete a session config."""
    try:
        table_client = get_table_client("sessionconfigs")
        if not table_client:
            return False
        
        table_client.delete_entity(partition_key="voicelive", row_key=name)
        logging.info(f"Deleted session config: {name}")
        return True
    except Exception as e:
        logging.error(f"Failed to delete session config '{name}': {e}")
        return False


# =============================================================================
# Config Management Endpoints
# =============================================================================

@app.route(route="list_session_configs", methods=["POST"])
def list_session_configs_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    """List available VoiceLive session configurations."""
    logging.info("list_session_configs called")
    
    try:
        configs = get_session_configs()
        
        # Find default config
        default_config = next((c for c in configs if c.get("is_default")), None)
        
        return func.HttpResponse(
            json.dumps({
                "action": "list_session_configs",
                "status": "success",
                "configs_found": len(configs),
                "default_config": default_config["name"] if default_config else None,
                "configs": configs
            }),
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"list_session_configs error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="get_session_config", methods=["POST"])
def get_session_config_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    """Get a specific VoiceLive session configuration by name."""
    logging.info("get_session_config called")
    
    try:
        body = req.get_json() if req.get_body() else {}
        name = body.get("name")
        
        if not name:
            return func.HttpResponse(
                json.dumps({"error": "Missing required parameter: name"}),
                status_code=400,
                mimetype="application/json"
            )
        
        config = get_session_config_by_name(name)
        
        if not config:
            return func.HttpResponse(
                json.dumps({"error": f"Config not found: {name}"}),
                status_code=404,
                mimetype="application/json"
            )
        
        return func.HttpResponse(
            json.dumps({
                "action": "get_session_config",
                "status": "success",
                "config": config
            }),
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"get_session_config error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="create_session_config", methods=["POST"])
def create_session_config_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    """Create a new VoiceLive session configuration."""
    logging.info("create_session_config called")
    
    try:
        body = req.get_json() if req.get_body() else {}
        
        name = body.get("name")
        if not name:
            return func.HttpResponse(
                json.dumps({"error": "Missing required parameter: name"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Check if config already exists
        existing = get_session_config_by_name(name)
        if existing:
            return func.HttpResponse(
                json.dumps({"error": f"Config already exists: {name}. Use update_session_config to modify."}),
                status_code=409,
                mimetype="application/json"
            )
        
        # Build config with defaults
        config = {
            "name": name,
            "description": body.get("description", ""),
            "model": body.get("model", "gpt-realtime"),
            "sample_rate": body.get("sample_rate", 24000),
            "voice_name": body.get("voice_name", "alloy"),
            "voice_type": body.get("voice_type", "preset"),
            "vad_type": body.get("vad_type", "azure_semantic_vad_multilingual"),
            "vad_threshold": body.get("vad_threshold"),  # None = SDK default
            "silence_duration_ms": body.get("silence_duration_ms"),  # None = SDK default
            "eou_detection": body.get("eou_detection", True),
            "eou_model": body.get("eou_model", "azure_semantic_v1_multilingual"),
            "transcription_model": body.get("transcription_model", "gpt-4o-transcribe"),
            "noise_reduction": body.get("noise_reduction", "azure_deep_noise_suppression"),
            "echo_cancellation": body.get("echo_cancellation", "server_echo_cancellation"),
            "is_default": body.get("is_default", False),
        }
        
        success = upsert_session_config(config)
        
        if not success:
            return func.HttpResponse(
                json.dumps({"error": "Failed to create config"}),
                status_code=500,
                mimetype="application/json"
            )
        
        return func.HttpResponse(
            json.dumps({
                "action": "create_session_config",
                "status": "success",
                "config": config
            }),
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"create_session_config error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="update_session_config", methods=["POST"])
def update_session_config_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    """Update an existing VoiceLive session configuration."""
    logging.info("update_session_config called")
    
    try:
        body = req.get_json() if req.get_body() else {}
        
        name = body.get("name")
        if not name:
            return func.HttpResponse(
                json.dumps({"error": "Missing required parameter: name"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Get existing config
        existing = get_session_config_by_name(name)
        if not existing:
            return func.HttpResponse(
                json.dumps({"error": f"Config not found: {name}. Use create_session_config to create new."}),
                status_code=404,
                mimetype="application/json"
            )
        
        # Merge with existing config (only update provided fields)
        config = existing.copy()
        for key in ["description", "model", "sample_rate", "voice_name", "voice_type", 
                    "vad_type", "vad_threshold", "silence_duration_ms", "eou_detection",
                    "eou_model", "transcription_model", "noise_reduction", "echo_cancellation", "is_default"]:
            if key in body:
                config[key] = body[key]
        
        success = upsert_session_config(config)
        
        if not success:
            return func.HttpResponse(
                json.dumps({"error": "Failed to update config"}),
                status_code=500,
                mimetype="application/json"
            )
        
        return func.HttpResponse(
            json.dumps({
                "action": "update_session_config",
                "status": "success",
                "config": config
            }),
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"update_session_config error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="delete_session_config", methods=["POST"])
def delete_session_config_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    """Delete a VoiceLive session configuration."""
    logging.info("delete_session_config called")
    
    try:
        body = req.get_json() if req.get_body() else {}
        
        name = body.get("name")
        if not name:
            return func.HttpResponse(
                json.dumps({"error": "Missing required parameter: name"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Prevent deletion of default config
        if name == "default":
            return func.HttpResponse(
                json.dumps({"error": "Cannot delete the 'default' config"}),
                status_code=400,
                mimetype="application/json"
            )
        
        success = delete_session_config(name)
        
        if not success:
            return func.HttpResponse(
                json.dumps({"error": f"Failed to delete config: {name}"}),
                status_code=500,
                mimetype="application/json"
            )
        
        return func.HttpResponse(
            json.dumps({
                "action": "delete_session_config",
                "status": "success",
                "deleted": name
            }),
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"delete_session_config error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


# =============================================================================
# Tool Functions
# =============================================================================

@app.route(route="list_datasets", methods=["POST"])
def list_datasets(req: func.HttpRequest) -> func.HttpResponse:
    """List available datasets. Combines VoiceLive (blob) and evaluation (Foundry) datasets."""
    logging.info("list_datasets called")
    
    try:
        body = req.get_json() if req.get_body() else {}
        prefix = body.get("folder_path", "")
        dataset_type = body.get("dataset_type", "all")  # voicelive, evaluation, all
        
        all_datasets = []
        
        # List VoiceLive datasets from blob storage
        if dataset_type in ("voicelive", "all"):
            client = get_blob_client()
            if client:
                container = os.environ.get("AZURE_STORAGE_DATASETS_CONTAINER", "datasets")
                container_client = client.get_container_client(container)
                
                for blob in container_client.list_blobs(name_starts_with=prefix):
                    if blob.name.endswith(".jsonl"):
                        all_datasets.append({
                            "path": f"{container}/{blob.name}",
                            "name": Path(blob.name).stem,
                            "type": "voicelive",
                            "store": "blob",
                            "size_bytes": blob.size,
                            "last_modified": str(blob.last_modified),
                        })
        
        # List evaluation datasets from Foundry
        if dataset_type in ("evaluation", "all"):
            try:
                from azure.ai.projects import AIProjectClient
                
                project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT") or os.environ.get("PROJECT_ENDPOINT")
                if project_endpoint:
                    project_client = AIProjectClient(
                        credential=DefaultAzureCredential(),
                        endpoint=project_endpoint
                    )
                    
                    for dataset in project_client.datasets.list():
                        try:
                            versions = list(project_client.datasets.list_versions(name=dataset.name))
                            version_count = len(versions)
                            latest_version = max(int(v.version) for v in versions) if versions else 0
                        except Exception:
                            version_count = 0
                            latest_version = 0
                        
                        all_datasets.append({
                            "path": dataset.id,
                            "name": dataset.name,
                            "type": "evaluation",
                            "store": "foundry",
                            "version_count": version_count,
                            "latest_version": latest_version,
                        })
            except Exception as e:
                logging.warning(f"Could not list Foundry datasets: {e}")
        
        return func.HttpResponse(
            json.dumps({
                "action": "list_datasets",
                "status": "success",
                "dataset_type_filter": dataset_type,
                "datasets_found": len(all_datasets),
                "datasets": all_datasets
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


@app.route(route="get_upload_url", methods=["POST"])
def get_upload_url(req: func.HttpRequest) -> func.HttpResponse:
    """Generate a SAS URL for uploading a dataset file.
    
    Returns a time-limited write-only URL for direct upload to blob staging.
    After upload, call finalize_upload to validate and route the file.
    """
    logging.info("get_upload_url called")
    
    try:
        body = req.get_json()
        dataset_name = body.get("dataset_name")
        dataset_type = body.get("dataset_type")  # voicelive or evaluation
        file_extension = body.get("file_extension", ".jsonl")
        
        if not dataset_name:
            return func.HttpResponse(
                json.dumps({"error": "dataset_name required"}),
                status_code=400,
                mimetype="application/json"
            )
        if dataset_type not in ("voicelive", "evaluation"):
            return func.HttpResponse(
                json.dumps({"error": "dataset_type must be 'voicelive' or 'evaluation'"}),
                status_code=400,
                mimetype="application/json"
            )
        
        account_name = os.environ.get("AZURE_STORAGE_ACCOUNT")
        if not account_name:
            return func.HttpResponse(
                json.dumps({"error": "AZURE_STORAGE_ACCOUNT not configured"}),
                status_code=500,
                mimetype="application/json"
            )
        
        upload_id = str(uuid.uuid4())
        container = os.environ.get("AZURE_STORAGE_DATASETS_CONTAINER", "datasets")
        staging_blob = f"staging/{upload_id}/{dataset_name}{file_extension}"
        
        # Generate user delegation SAS using managed identity
        credential = DefaultAzureCredential()
        blob_client = BlobServiceClient(
            account_url=f"https://{account_name}.blob.core.windows.net",
            credential=credential
        )
        
        # Get user delegation key for SAS
        from datetime import timezone
        start_time = datetime.now(timezone.utc)
        expiry_time = start_time + timedelta(minutes=30)
        
        delegation_key = blob_client.get_user_delegation_key(
            key_start_time=start_time,
            key_expiry_time=expiry_time
        )
        
        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=container,
            blob_name=staging_blob,
            user_delegation_key=delegation_key,
            permission=BlobSasPermissions(write=True, create=True),
            expiry=expiry_time,
            start=start_time,
        )
        
        upload_url = f"https://{account_name}.blob.core.windows.net/{container}/{staging_blob}?{sas_token}"
        
        return func.HttpResponse(
            json.dumps({
                "action": "get_upload_url",
                "upload_id": upload_id,
                "upload_url": upload_url,
                "staging_path": staging_blob,
                "dataset_name": dataset_name,
                "dataset_type": dataset_type,
                "expires_in_minutes": 30,
                "instructions": "Upload your file to the upload_url using a PUT request with x-ms-blob-type: BlockBlob header. Then call finalize_upload with the upload_id."
            }),
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"get_upload_url error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="finalize_upload", methods=["POST"])
def finalize_upload(req: func.HttpRequest) -> func.HttpResponse:
    """Finalize a dataset upload: validate and route to the correct store.
    
    For voicelive: extracts zip to datasets/{name}/, validates audio+JSONL.
    For evaluation: validates JSONL (query/response), uploads to Foundry datasets.
    """
    logging.info("finalize_upload called")
    
    try:
        body = req.get_json()
        upload_id = body.get("upload_id")
        dataset_name = body.get("dataset_name")
        dataset_type = body.get("dataset_type")  # voicelive or evaluation
        
        if not upload_id or not dataset_name or not dataset_type:
            return func.HttpResponse(
                json.dumps({"error": "upload_id, dataset_name, and dataset_type required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        client = get_blob_client()
        if not client:
            return func.HttpResponse(
                json.dumps({"error": "AZURE_STORAGE_ACCOUNT not configured"}),
                status_code=500,
                mimetype="application/json"
            )
        
        container = os.environ.get("AZURE_STORAGE_DATASETS_CONTAINER", "datasets")
        container_client = client.get_container_client(container)
        
        # Find the staged file
        staging_prefix = f"staging/{upload_id}/"
        staged_blobs = list(container_client.list_blobs(name_starts_with=staging_prefix))
        if not staged_blobs:
            return func.HttpResponse(
                json.dumps({"error": f"No staged file found for upload_id: {upload_id}"}),
                status_code=404,
                mimetype="application/json"
            )
        
        staged_blob = staged_blobs[0]
        
        # Download staged file to temp
        blob_data = container_client.get_blob_client(staged_blob.name).download_blob()
        suffix = Path(staged_blob.name).suffix
        
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(blob_data.readall())
            tmp_path = tmp.name
        
        result = {}
        
        if dataset_type == "voicelive":
            result = _finalize_voicelive_upload(tmp_path, dataset_name, container_client, suffix)
        elif dataset_type == "evaluation":
            result = _finalize_eval_upload(tmp_path, dataset_name)
        else:
            result = {"error": f"Unknown dataset_type: {dataset_type}"}
        
        # Cleanup temp file and staging blob
        os.unlink(tmp_path)
        try:
            container_client.get_blob_client(staged_blob.name).delete_blob()
        except Exception:
            pass
        
        if "error" in result:
            return func.HttpResponse(
                json.dumps(result),
                status_code=400,
                mimetype="application/json"
            )
        
        return func.HttpResponse(
            json.dumps({
                "action": "finalize_upload",
                "status": "success",
                "dataset_name": dataset_name,
                "dataset_type": dataset_type,
                **result
            }),
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"finalize_upload error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


def _finalize_voicelive_upload(tmp_path: str, dataset_name: str, container_client, suffix: str) -> dict:
    """Extract and validate a VoiceLive dataset upload (zip or JSONL)."""
    import zipfile
    
    dest_prefix = f"{dataset_name}/"
    files_uploaded = []
    
    if suffix == ".zip":
        # Extract zip to datasets/{name}/
        with zipfile.ZipFile(tmp_path, 'r') as zf:
            jsonl_files = [f for f in zf.namelist() if f.endswith(".jsonl")]
            wav_files = [f for f in zf.namelist() if f.endswith(".wav")]
            
            if not jsonl_files:
                return {"error": "Zip must contain at least one .jsonl manifest file"}
            
            for name in zf.namelist():
                if name.endswith('/'):
                    continue
                blob_name = f"{dest_prefix}{Path(name).name}"
                data = zf.read(name)
                container_client.get_blob_client(blob_name).upload_blob(data, overwrite=True)
                files_uploaded.append(blob_name)
        
        return {
            "files_uploaded": len(files_uploaded),
            "jsonl_files": len(jsonl_files),
            "wav_files": len(wav_files),
            "blob_prefix": dest_prefix,
        }
    elif suffix == ".jsonl":
        # Upload JSONL directly
        blob_name = f"{dest_prefix}{dataset_name}.jsonl"
        with open(tmp_path, 'rb') as f:
            container_client.get_blob_client(blob_name).upload_blob(f, overwrite=True)
        return {"files_uploaded": 1, "blob_path": blob_name}
    else:
        return {"error": f"Unsupported file type: {suffix}. Expected .zip or .jsonl"}


def _finalize_eval_upload(tmp_path: str, dataset_name: str) -> dict:
    """Validate and upload an evaluation dataset to Foundry."""
    # Validate JSONL structure first
    errors = []
    entry_count = 0
    with open(tmp_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('//') or line.startswith('#'):
                continue
            try:
                entry = json.loads(line)
                entry_count += 1
                if not entry.get("query"):
                    errors.append(f"Line {line_num}: Missing 'query'")
                if not entry.get("response"):
                    errors.append(f"Line {line_num}: Missing 'response'")
            except json.JSONDecodeError as e:
                errors.append(f"Line {line_num}: Invalid JSON - {e}")
    
    if errors:
        return {"error": "Validation failed", "validation_errors": errors[:20], "error_count": len(errors)}
    
    if entry_count == 0:
        return {"error": "Dataset is empty"}
    
    # Upload to Foundry datasets
    from azure.ai.projects import AIProjectClient
    
    project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT") or os.environ.get("PROJECT_ENDPOINT")
    if not project_endpoint:
        return {"error": "PROJECT_ENDPOINT not configured"}
    
    project_client = AIProjectClient(
        credential=DefaultAzureCredential(),
        endpoint=project_endpoint
    )
    
    # Foundry handles versioning natively — same name = new version
    dataset = project_client.datasets.upload_file(
        name=dataset_name,
        file_path=tmp_path,
        description=f"Evaluation dataset: {entry_count} entries",
    )
    
    return {
        "foundry_dataset_id": dataset.id,
        "name": dataset.name,
        "version": dataset.version,
        "entries": entry_count,
        "message": f"Uploaded to Foundry as '{dataset_name}' (version auto-assigned)"
    }


@app.route(route="check_dataset_schema", methods=["POST"])
def check_dataset_schema(req: func.HttpRequest) -> func.HttpResponse:
    """Check dataset schema and detect dataset type (voicelive or evaluation)."""
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
        
        # Field groups for type detection
        voicelive_fields = {"WavPath": 0, "audio": 0, "Question": 0, "Answer": 0,
                           "conversationID": 0, "conversation_id": 0, "system_prompt": 0}
        eval_fields = {"query": 0, "response": 0, "ground_truth": 0, "context": 0,
                      "tool_calls": 0, "tool_definitions": 0}
        all_field_names = set()
        entry_count = 0
        
        with open(local_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('//') or line.startswith('#'):
                    continue
                try:
                    entry = json.loads(line)
                    entry_count += 1
                    all_field_names.update(entry.keys())
                    
                    for field in voicelive_fields:
                        if field in entry:
                            voicelive_fields[field] += 1
                    for field in eval_fields:
                        if field in entry:
                            eval_fields[field] += 1
                except json.JSONDecodeError:
                    pass
        
        os.unlink(local_path)
        
        # Detect dataset type
        has_audio = (voicelive_fields["WavPath"] + voicelive_fields["audio"]) > 0
        has_eval = eval_fields["query"] > 0 and eval_fields["response"] > 0
        
        if has_audio and not has_eval:
            dataset_type = "voicelive"
            recommendation = "VoiceLive audio dataset. Use validate_voicelive_dataset to validate, then run_voicelive_audio_tests to process."
        elif has_eval and not has_audio:
            dataset_type = "evaluation"
            recommendation = "Evaluation-ready dataset. Use validate_eval_dataset to validate, then run_voicelive_evaluation to evaluate."
        elif has_audio and has_eval:
            dataset_type = "hybrid"
            recommendation = "Dataset has both audio and evaluation fields. Can be used for either workflow."
        else:
            dataset_type = "unknown"
            recommendation = "Dataset type unclear. Expected either WavPath/audio (VoiceLive) or query/response (evaluation) fields."
        
        return func.HttpResponse(
            json.dumps({
                "action": "check_dataset_schema",
                "dataset_type": dataset_type,
                "entries_analyzed": entry_count,
                "fields_found": sorted(list(all_field_names)),
                "voicelive_fields": {k: v for k, v in voicelive_fields.items() if v > 0},
                "evaluation_fields": {k: v for k, v in eval_fields.items() if v > 0},
                "recommendation": recommendation,
            }),
            mimetype="application/json"
        )
    except ValueError as e:
        error_msg = str(e)
        logging.warning(f"check_dataset_schema not found: {error_msg}")
        status_code = 404 if "not found" in error_msg.lower() else 400
        return func.HttpResponse(
            json.dumps({"error": error_msg}),
            status_code=status_code,
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"check_dataset_schema error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="validate_voicelive_dataset", methods=["POST"])
def validate_voicelive_dataset(req: func.HttpRequest) -> func.HttpResponse:
    """Validate a VoiceLive audio dataset (requires WavPath/audio fields)."""
    logging.info("validate_voicelive_dataset called")
    
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
                "action": "validate_voicelive_dataset",
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
    except ValueError as e:
        error_msg = str(e)
        logging.warning(f"validate_voicelive_dataset not found: {error_msg}")
        status_code = 404 if "not found" in error_msg.lower() else 400
        return func.HttpResponse(
            json.dumps({"error": error_msg}),
            status_code=status_code,
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"validate_voicelive_dataset error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="validate_dataset_consistency", methods=["POST"])
def validate_dataset_consistency(req: func.HttpRequest) -> func.HttpResponse:
    """Backward-compat alias for validate_voicelive_dataset."""
    return validate_voicelive_dataset(req)


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
    except ValueError as e:
        error_msg = str(e)
        logging.warning(f"validate_dataset_quality not found: {error_msg}")
        status_code = 404 if "not found" in error_msg.lower() else 400
        return func.HttpResponse(
            json.dumps({"error": error_msg}),
            status_code=status_code,
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"validate_dataset_quality error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="validate_eval_dataset", methods=["POST"])
def validate_eval_dataset(req: func.HttpRequest) -> func.HttpResponse:
    """Validate an evaluation-ready dataset (query/response JSONL).
    
    This validates datasets intended for direct Foundry evaluation,
    NOT VoiceLive audio datasets. Use validate_voicelive_dataset for audio.
    """
    logging.info("validate_eval_dataset called")
    
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
        
        errors = []
        warnings = []
        entry_count = 0
        
        # Field presence counters
        has_query = 0
        has_response = 0
        has_ground_truth = 0
        has_context = 0
        has_tool_calls = 0
        has_tool_definitions = 0
        
        with open(local_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith('//') or line.startswith('#'):
                    continue
                
                try:
                    entry = json.loads(line)
                    entry_count += 1
                    
                    # Required: query and response
                    if entry.get("query"):
                        has_query += 1
                    else:
                        errors.append(f"Line {line_num}: Missing required field 'query'")
                    
                    if entry.get("response"):
                        has_response += 1
                    else:
                        errors.append(f"Line {line_num}: Missing required field 'response'")
                    
                    # Optional enrichment fields
                    if entry.get("ground_truth"):
                        has_ground_truth += 1
                    if entry.get("context"):
                        has_context += 1
                    if entry.get("tool_calls"):
                        has_tool_calls += 1
                    if entry.get("tool_definitions"):
                        has_tool_definitions += 1
                    
                    # Warn if entry has audio fields (wrong dataset type)
                    if entry.get("WavPath") or entry.get("audio"):
                        warnings.append(f"Line {line_num}: Contains audio path — use validate_voicelive_dataset instead")
                    
                except json.JSONDecodeError as e:
                    errors.append(f"Line {line_num}: Invalid JSON - {e}")
        
        os.unlink(local_path)
        
        status = "passed" if not errors else "failed"
        
        return func.HttpResponse(
            json.dumps({
                "action": "validate_eval_dataset",
                "dataset_type": "evaluation",
                "status": status,
                "can_proceed": len(errors) == 0,
                "entries_validated": entry_count,
                "required_fields": {
                    "query": f"{has_query}/{entry_count}",
                    "response": f"{has_response}/{entry_count}",
                },
                "optional_fields": {
                    "ground_truth": f"{has_ground_truth}/{entry_count}",
                    "context": f"{has_context}/{entry_count}",
                    "tool_calls": f"{has_tool_calls}/{entry_count}",
                    "tool_definitions": f"{has_tool_definitions}/{entry_count}",
                },
                "errors": errors[:20],
                "warnings": warnings[:10],
                "error_count": len(errors),
                "warning_count": len(warnings),
            }),
            mimetype="application/json"
        )
    except ValueError as e:
        error_msg = str(e)
        logging.warning(f"validate_eval_dataset not found: {error_msg}")
        status_code = 404 if "not found" in error_msg.lower() else 400
        return func.HttpResponse(
            json.dumps({"error": error_msg}),
            status_code=status_code,
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"validate_eval_dataset error: {e}")
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
    except ValueError as e:
        error_msg = str(e)
        logging.warning(f"get_evaluation_recommendations not found: {error_msg}")
        status_code = 404 if "not found" in error_msg.lower() else 400
        return func.HttpResponse(
            json.dumps({"error": error_msg}),
            status_code=status_code,
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
    session_config = params.get("session_config")  # VoiceLive session config for naming
    dataset_name = params.get("dataset_name")  # Dataset name for run naming
    
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
        "foundry_dataset_id": foundry_dataset_id,
        "session_config": session_config,
        "dataset_name": dataset_name
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
                           foundry_dataset_id: str = None, session_config: dict = None,
                           dataset_name: str = None, dataset_version: str = "1") -> dict:
    """
    Run Azure AI Foundry evaluation on a dataset.
    
    Args:
        dataset_path: Local path to JSONL evaluation dataset
        output_path: Directory for output files
        instance_id: Unique identifier for this evaluation run
        evaluators: List of evaluator names to run (None = use defaults)
        eval_group_id: Optional existing eval group ID to reuse (skip creating new)
        foundry_dataset_id: Optional existing Foundry dataset ID to reuse (skip uploading)
        session_config: VoiceLive session config for eval group naming
        dataset_name: Dataset name for run naming
        dataset_version: Dataset version for run naming
    
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
            eval_group_name = None
        else:
            # Create new eval group with config-based name
            eval_group_name = generate_eval_group_name(session_config)
            eval_object = openai_client.evals.create(
                name=eval_group_name,
                data_source_config=data_source_config,
                testing_criteria=testing_criteria,
            )
            eval_id = eval_object.id
            logging.info(f"Created eval group: {eval_group_name} ({eval_id})")
            
            # Journal the config -> eval group mapping
            journal_eval_group(eval_group_name, session_config or {}, eval_id)
        
        # Upload or reuse dataset
        if foundry_dataset_id:
            # Reuse existing Foundry dataset
            dataset_id = foundry_dataset_id
            logging.info(f"Reusing existing Foundry dataset: {dataset_id}")
            new_version = dataset_version
        else:
            # Upload dataset with auto-versioning (like prototype)
            ds_name = dataset_name or f"eval-dataset-{instance_id[:8]}"
            try:
                # Check for existing versions
                existing = list(project_client.datasets.list())
                existing_versions = [d for d in existing if d.name == ds_name]
                if existing_versions:
                    new_version = str(max(int(d.version) for d in existing_versions) + 1)
                else:
                    new_version = "1"
            except Exception:
                new_version = "1"
            
            dataset = project_client.datasets.upload_file(
                name=ds_name,
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
        
        # Generate run name with dataset version reference
        run_name = generate_run_name(
            dataset_name=dataset_name or ds_name,
            dataset_version=new_version,
            evaluators=eval_list
        )
        
        eval_run = openai_client.evals.runs.create(
            eval_id=eval_id,
            name=run_name,
            metadata={
                "instance_id": instance_id,
                "source": "voicelive-agent-v3",
                "dataset_version": new_version,
                "evaluators": ",".join(eval_list) if eval_list else "all"
            },
            data_source=data_source
        )
        eval_run_id = eval_run.id
        logging.info(f"Created eval run: {run_name} ({eval_run_id})")
        
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
        session_config = params.get("session_config")  # VoiceLive session config for naming
        dataset_name = params.get("dataset_name")  # Dataset name for run naming
        
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
            foundry_dataset_id=foundry_dataset_id,
            session_config=session_config,
            dataset_name=dataset_name
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
        
        # Extract dataset name for run naming
        dataset_name = Path(dataset_path).stem if dataset_path else None
        
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
                # Config-based naming parameters
                "session_config": body.get("session_config"),  # VoiceLive session config for eval group naming
                "dataset_name": dataset_name,  # Dataset name for run naming
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


# =============================================================================
# Container App Proxy Endpoints
# =============================================================================
# These endpoints proxy requests to the VoiceLive Container App.
# Authentication is via Entra ID managed identity (Function App MI → Container App EasyAuth)

# Cache the credential instance for reuse across requests
_container_app_credential = None

def _get_container_app_credential():
    """Get or create a cached DefaultAzureCredential for Container App auth."""
    global _container_app_credential
    if _container_app_credential is None:
        from azure.identity import DefaultAzureCredential
        _container_app_credential = DefaultAzureCredential()
    return _container_app_credential


async def proxy_to_container_app(endpoint: str, body: dict) -> func.HttpResponse:
    """Proxy request to Container App with Entra ID managed identity authentication."""
    import httpx
    
    container_app_url = os.environ.get("CONTAINER_APP_URL")
    if not container_app_url:
        return func.HttpResponse(
            json.dumps({"error": "CONTAINER_APP_URL not configured"}),
            status_code=500,
            mimetype="application/json"
        )
    
    # Build request
    url = f"{container_app_url.rstrip('/')}/{endpoint.lstrip('/')}"
    headers = {"Content-Type": "application/json"}
    
    # Acquire Entra ID token for Container App audience
    entra_client_id = os.environ.get("CONTAINER_APP_ENTRA_CLIENT_ID")
    if entra_client_id:
        try:
            credential = _get_container_app_credential()
            token = credential.get_token(f"api://{entra_client_id}/.default")
            headers["Authorization"] = f"Bearer {token.token}"
        except Exception as e:
            logging.error(f"Failed to acquire token for Container App: {e}")
            return func.HttpResponse(
                json.dumps({"error": f"Container App auth error: {str(e)}"}),
                status_code=500,
                mimetype="application/json"
            )
    
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(url, json=body, headers=headers)
            return func.HttpResponse(
                response.text,
                status_code=response.status_code,
                mimetype="application/json"
            )
    except httpx.TimeoutException:
        return func.HttpResponse(
            json.dumps({"error": "Container App request timed out"}),
            status_code=504,
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"Container App proxy error: {e}")
        return func.HttpResponse(
            json.dumps({"error": f"Container App proxy error: {str(e)}"}),
            status_code=502,
            mimetype="application/json"
        )


@app.route(route="run_voicelive_audio_tests", methods=["POST"])
async def run_voicelive_audio_tests(req: func.HttpRequest) -> func.HttpResponse:
    """
    Proxy to Container App: Start VoiceLive audio processing job.
    
    Starts a job to process audio files through the VoiceLive SDK.
    Returns a job_id to poll with check_voicelive_job_status.
    """
    try:
        body = req.get_json()
        
        # Resolve session_config name to config dict if it's a string
        config_value = body.get("session_config")
        if isinstance(config_value, str):
            try:
                from azure.data.tables import TableServiceClient
                from azure.identity import DefaultAzureCredential
                storage_account = os.environ.get("AZURE_STORAGE_ACCOUNT", "")
                table_url = f"https://{storage_account}.table.core.windows.net"
                table_client = TableServiceClient(
                    endpoint=table_url,
                    credential=DefaultAzureCredential()
                ).get_table_client("sessionconfigs")
                entity = table_client.get_entity(partition_key="config", row_key=config_value)
                # Build session config dict from table entity
                config_dict = {k: v for k, v in entity.items() 
                             if k not in ("PartitionKey", "RowKey", "Timestamp", "odata.etag")}
                body["session_config"] = config_dict
                logging.info(f"Resolved session config '{config_value}' to dict")
            except Exception as e:
                logging.warning(f"Could not resolve session config '{config_value}': {e}, passing as-is")
                body.pop("session_config", None)
        
        return await proxy_to_container_app("/run_voicelive_audio_tests", body)
    except Exception as e:
        logging.error(f"run_voicelive_audio_tests error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="check_voicelive_job_status", methods=["POST"])
async def check_voicelive_job_status(req: func.HttpRequest) -> func.HttpResponse:
    """
    Proxy to Container App: Check VoiceLive audio processing job status.
    
    Returns the status of a VoiceLive audio processing job.
    When status is 'completed', auto-registers output as Foundry dataset
    and includes foundry_dataset_id in the response.
    """
    try:
        body = req.get_json()
        response = await proxy_to_container_app("/check_job_status", body)
        
        # Auto-register completed output as Foundry dataset
        if response.status_code == 200:
            try:
                result = json.loads(response.get_body())
                if result.get("status") == "completed" and result.get("output_path"):
                    foundry_info = _register_voicelive_output_as_foundry_dataset(
                        output_path=result["output_path"],
                        job_id=body.get("job_id", "unknown"),
                    )
                    if foundry_info:
                        result["foundry_dataset"] = foundry_info
                        return func.HttpResponse(
                            json.dumps(result),
                            status_code=200,
                            mimetype="application/json"
                        )
            except Exception as e:
                logging.warning(f"Auto-register to Foundry failed (non-blocking): {e}")
        
        return response
    except Exception as e:
        logging.error(f"check_voicelive_job_status error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


def _register_voicelive_output_as_foundry_dataset(output_path: str, job_id: str) -> dict:
    """Register a VoiceLive output as a Foundry dataset for discovery."""
    from azure.ai.projects import AIProjectClient
    
    project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT") or os.environ.get("PROJECT_ENDPOINT")
    if not project_endpoint:
        return None
    
    try:
        # Download the output file from blob
        local_path, actual_blob = download_results(output_path)
        
        # Generate a dataset name from the output
        short_id = job_id[:8] if len(job_id) > 8 else job_id
        dataset_name = f"voicelive_output_{short_id}"
        
        project_client = AIProjectClient(
            credential=DefaultAzureCredential(),
            endpoint=project_endpoint
        )
        
        dataset = project_client.datasets.upload_file(
            name=dataset_name,
            file_path=local_path,
            description=f"VoiceLive processing output (job: {job_id})",
        )
        
        os.unlink(local_path)
        
        return {
            "foundry_dataset_id": dataset.id,
            "name": dataset.name,
            "version": dataset.version,
        }
    except Exception as e:
        logging.warning(f"Failed to register VoiceLive output as Foundry dataset: {e}")
        return None
