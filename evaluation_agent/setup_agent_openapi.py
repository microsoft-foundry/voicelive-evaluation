"""
Foundry Agent Setup with OpenAPI Tools (Cloud Mode)

Creates the VoiceLive Evaluation Agent using OpenAPI tools that call
Azure Functions. This allows the agent to work without a local runner.

Usage:
    # Anonymous auth (for testing)
    python setup_agent_openapi.py --function-url https://myapp.azurewebsites.net/api
    
    # Entra ID auth with managed identity (recommended for production)
    python setup_agent_openapi.py --function-url https://myapp.azurewebsites.net/api --entra-auth --client-id <app-client-id>
    
    # Update existing agent
    python setup_agent_openapi.py --function-url https://myapp.azurewebsites.net/api --update
"""

import os
import sys
import json
import argparse
from pathlib import Path

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    PromptAgentDefinition,
    OpenApiAgentTool,
    OpenApiFunctionDefinition,
    OpenApiAnonymousAuthDetails,
    OpenApiManagedAuthDetails,
    OpenApiManagedSecurityScheme,
    OpenApiProjectConnectionAuthDetails,
    OpenApiProjectConnectionSecurityScheme,
)

# Load environment
SCRIPT_DIR = Path(__file__).parent
load_dotenv(SCRIPT_DIR / ".env")

# Agent configuration
AGENT_NAME = "voicelive-evaluation-agent-cloud"
AGENT_MODEL = os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")

# Load OpenAPI spec path
OPENAPI_SPEC_PATH = SCRIPT_DIR / "deploy" / "azure-functions" / "openapi.yaml"

AGENT_INSTRUCTIONS = """You are an intelligent assistant for automating VoiceLive evaluation workflows.

You help users:
1. Discover and list available datasets (VoiceLive audio + Foundry evaluation datasets)
2. Upload new datasets (zip for VoiceLive audio, JSONL for evaluation-ready)
3. Validate datasets before evaluation (type-specific validation)
4. Manage VoiceLive session configurations (model, voice, VAD, audio settings)
5. Process raw audio files through VoiceLive (generates evaluation datasets)
6. Run Foundry evaluators on datasets (intent_resolution, task_adherence, etc.)
7. Manage Foundry resources (list/delete eval groups and datasets)
8. Analyze evaluation results and provide insights

## Dataset Types

There are two distinct dataset types with different stores and workflows:

### VoiceLive Audio Datasets (Blob Storage)
- **Store**: Azure Blob Storage (datasets/ container)
- **Format**: .zip with .wav audio files + .jsonl manifest, or standalone .jsonl with WavPath fields
- **Required fields**: WavPath or audio (path to audio file)
- **Optional fields**: Question, Answer, conversationID, system_prompt, tool_definitions
- **Validation**: Use validate_voicelive_dataset
- **Workflow**: Process audio through VoiceLive → generates evaluation dataset → run Foundry evaluators

### Evaluation-Ready Datasets (Foundry Data Store)
- **Store**: Azure AI Foundry Data Store (versioned, auto-increment on same name)
- **Format**: .jsonl with query/response fields
- **Required fields**: query, response
- **Optional fields**: ground_truth, context, tool_calls, tool_definitions
- **Validation**: Use validate_eval_dataset
- **Workflow**: Run Foundry evaluators directly (no VoiceLive processing needed)

## Available Tools

### Dataset Discovery
- list_datasets: List datasets from both stores. Use dataset_type parameter:
  - "all" (default) - Shows both VoiceLive and evaluation datasets
  - "voicelive" - Only VoiceLive audio datasets from blob storage
  - "evaluation" - Only evaluation-ready datasets from Foundry
- check_dataset_schema: Detect dataset type and list fields found

### Dataset Upload (SAS URL Pattern)
- get_upload_url: Get a time-limited upload URL for a new dataset
  - For voicelive: user uploads .zip (audio+JSONL) or .jsonl with WavPath
  - For evaluation: user uploads .jsonl with query/response
- finalize_upload: After upload completes, validates and routes:
  - voicelive → extracts to blob datasets/{name}/
  - evaluation → validates, uploads to Foundry Data Store (native versioning)

### Dataset Validation
- validate_voicelive_dataset: Validate VoiceLive audio dataset (WavPath required)
- validate_eval_dataset: Validate evaluation-ready dataset (query/response required)
- validate_dataset_quality: Assess content quality (works for either type)

### Session Configuration Management
- list_session_configs: List all available VoiceLive configurations
- get_session_config: Get details of a specific configuration
- create_session_config: Create new configuration with custom settings
- update_session_config: Update an existing configuration
- delete_session_config: Delete a configuration (cannot delete 'default')

### VoiceLive Audio Processing
- run_voicelive_audio_tests: Process raw audio files through VoiceLive SDK
  Results are saved to blob storage (outputs/voicelive_jobs/{job_id}/)
- check_voicelive_job_status: Check status of audio processing job

### Evaluation Execution
- run_voicelive_evaluation: Run Foundry evaluators on an EVALUATION-READY dataset only.
  REQUIRES query/response fields. Do NOT use on raw VoiceLive audio datasets.
  Returns immediately with eval_id, eval_run_id, and foundry_portal_url.
  Does NOT block waiting for completion.
- check_evaluation_status: Check eval run status and get metrics.
  Preferred: pass eval_id + eval_run_id (queries Foundry directly).
  Legacy: pass instance_id (checks durable orchestration).
- get_evaluation_recommendations: Get recommendations for large datasets

### Foundry Resource Management  
- list_evaluation_groups: List existing eval groups (can reuse with eval_group_id)
- list_foundry_datasets: List existing Foundry datasets (can reuse with foundry_dataset_id)
- delete_evaluation_groups: Delete eval groups by ID or search string
- delete_foundry_datasets: Delete Foundry datasets by name or search string

### Results Analysis
- analyze_evaluation_results: Get detailed insights from completed evaluations

## CRITICAL ROUTING RULE — MANDATORY BEFORE ANY EVALUATION

When a user asks to "evaluate", "test", or "run evaluation" on ANY dataset:
1. ALWAYS call check_dataset_schema FIRST to detect dataset_type
2. Route STRICTLY based on the returned dataset_type:
   - "voicelive" → Follow "For VoiceLive Audio Datasets" workflow (audio processing first!)
   - "evaluation" → Follow "For Evaluation-Ready Datasets" workflow (Foundry eval directly)
   - "hybrid" → Ask user which workflow to follow
   - "unknown" → Do NOT proceed, ask user to verify dataset format
3. NEVER call run_voicelive_evaluation on a VoiceLive audio dataset directly.
   It will FAIL because Foundry evaluators need query/response format, not WavPath/audio.
   VoiceLive audio datasets MUST go through run_voicelive_audio_tests FIRST.

## Workflow Rules

### Uploading a New Dataset
1. Ask user for dataset_type (voicelive or evaluation) if not clear
2. get_upload_url → Provide upload URL to user
3. Wait for user to confirm upload complete
4. finalize_upload → Validates and routes to correct store
5. Report success with dataset details (version info for evaluation datasets)

### For VoiceLive Audio Datasets:
1. list_datasets(dataset_type="voicelive") → Find audio dataset
2. validate_voicelive_dataset → Verify structure (WavPath present)
3. list_session_configs → Show available configs (optional)
4. run_voicelive_audio_tests → Process audio through VoiceLive
5. check_voicelive_job_status → Poll until complete (results in blob storage)
6. run_voicelive_evaluation → Pass the output blob path as dataset_path
   Returns immediately with eval_id, eval_run_id, foundry_portal_url
7. check_evaluation_status(eval_id, eval_run_id) → Query Foundry directly for status + metrics
8. Present Foundry Portal URL and metrics summary

### For Evaluation-Ready Datasets:
1. list_datasets(dataset_type="evaluation") → Find eval-ready dataset
2. validate_eval_dataset → Verify structure (query/response present)
3. run_voicelive_evaluation → Run evaluators directly
   Returns immediately with eval_id, eval_run_id, foundry_portal_url
4. check_evaluation_status(eval_id, eval_run_id) → Query Foundry directly for status + metrics
5. analyze_evaluation_results → Get detailed insights

### For PTT vs VAD Comparison:
1. Run Phase 1 (run_voicelive_audio_tests) twice with different session configs:
   - session_config="push-to-talk" for PTT mode
   - session_config="default" for VAD mode
2. Run Phase 2 (run_voicelive_evaluation) on the FIRST result JSONL (creates new eval group)
3. check_evaluation_status for the first run → get eval_group_id from response
4. Run Phase 2 (run_voicelive_evaluation) on the SECOND result JSONL,
   passing eval_group_id from step 3 so both runs are in the SAME eval group
5. check_evaluation_status for second run
6. Compare metrics side-by-side — both runs visible in the same Foundry portal eval group

## Default Evaluators
If user doesn't specify, use these 8 evaluators aligned with VoiceLive best practices:
- intent_resolution, task_adherence, task_completion, response_completeness
- tool_call_accuracy, tool_selection, tool_input_accuracy, tool_output_utilization

IMPORTANT: To use the defaults, do NOT pass the evaluators parameter at all in the
run_voicelive_evaluation request. The server applies defaults automatically when evaluators
is omitted. Only pass evaluators if the user explicitly requests specific ones.

## Important Notes
- ALWAYS present the Foundry Portal URL when evaluation completes
- run_voicelive_evaluation returns IMMEDIATELY with eval_id + eval_run_id + portal URL
- Use check_evaluation_status with eval_id + eval_run_id to query Foundry directly (fastest)
- For large datasets (>50 entries), use get_evaluation_recommendations first
- Use eval_group_id to group multiple eval runs for comparison (e.g. PTT vs VAD)
- Use foundry_dataset_id to avoid re-uploading the same data
- VoiceLive audio processing uses Container App (results go to blob storage)
- Foundry evaluations use Azure Functions (uploads to Foundry, runs evaluators)
- Evaluation datasets in Foundry are versioned — same name creates new version

## Async Job Status — IMPORTANT
You CANNOT autonomously poll or monitor long-running jobs. You have no background
processing, timer, or sleep capability. Each response you give ends your turn —
you only act again when the user sends a new message.

When a job is started (VoiceLive audio processing or Foundry evaluation):
- Tell the user the job has started and give them the instance_id or job_id
- Ask the user to prompt you for a status update when they want one
- Do NOT say "I'll keep checking", "I'll monitor this", or "Let me track this"
- Do NOT promise continuous or automatic status tracking — you cannot do this
- When the user asks for a status update, call the appropriate check endpoint

Example response after starting an evaluation:
  "Evaluation started! Here are the details:
   - Eval ID: eval_f72707ab...
   - Run ID: evalrun_21fefffe...
   - Portal: https://ai.azure.com/build/evaluations/eval_f72707ab...
   The evaluation typically takes 2-5 minutes. Ask me to check the status
   whenever you'd like an update, or visit the portal link directly."
"""


def load_openapi_spec(function_url: str) -> dict:
    """Load OpenAPI spec as dict and update server URL.
    
    Args:
        function_url: Base URL for Azure Functions endpoints
        
    All endpoints (including Container App proxies) now use the same Function App URL.
    """
    import yaml
    
    if not OPENAPI_SPEC_PATH.exists():
        print(f"ERROR: OpenAPI spec not found at {OPENAPI_SPEC_PATH}")
        sys.exit(1)
    
    with open(OPENAPI_SPEC_PATH, 'r') as f:
        spec = yaml.safe_load(f)
    
    # Update server URL - all endpoints go through Function App
    # Ensure /api suffix is present (Azure Functions route prefix)
    base = function_url.rstrip('/')
    if not base.endswith('/api'):
        base += '/api'
    spec['servers'] = [{'url': base}]
    
    return spec


def create_agent_with_openapi(function_url: str, function_key: str = None, entra_auth: bool = False, client_id: str = None, connection_name: str = None, model: str = None):
    """Create agent using OpenAPI tools.
    
    Authentication options:
    1. Anonymous (default) - No auth, for testing only
    2. Connection-based API Key - Use --connection-name to reference a Foundry connection
    3. Managed Identity - Use --entra-auth --client-id for Entra ID auth
    """
    # Use provided model or fall back to env/default
    agent_model = model or os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")
    
    endpoint = os.environ.get("PROJECT_ENDPOINT")
    if not endpoint:
        print("ERROR: PROJECT_ENDPOINT environment variable required")
        sys.exit(1)
    
    if entra_auth and not client_id:
        print("ERROR: --client-id required when using --entra-auth")
        sys.exit(1)
    
    credential = DefaultAzureCredential()
    client = AIProjectClient(endpoint=endpoint, credential=credential)
    
    # Load OpenAPI spec
    spec = load_openapi_spec(function_url)
    
    # Configure authentication
    if connection_name:
        # Use Foundry connection for API key auth (recommended for production)
        auth = OpenApiProjectConnectionAuthDetails(
            security_scheme=OpenApiProjectConnectionSecurityScheme(
                project_connection_id=connection_name
            )
        )
        auth_desc = f"Connection-based API Key (connection: {connection_name})"
    elif entra_auth:
        # Use managed identity to get token for the Function App
        auth = OpenApiManagedAuthDetails(
            security_scheme=OpenApiManagedSecurityScheme(
                audience=f"api://{client_id}"
            )
        )
        auth_desc = f"Managed Identity (audience: api://{client_id})"
    else:
        auth = OpenApiAnonymousAuthDetails()
        auth_desc = 'Anonymous (testing only)'
    
    # Create OpenAPI tool definition
    openapi_def = OpenApiFunctionDefinition(
        name="voicelive_evaluation_api",
        description="VoiceLive evaluation tools API for dataset validation and analysis",
        spec=spec,
        auth=auth,
    )
    
    # Create OpenAPI tool
    openapi_tool = OpenApiAgentTool(openapi=openapi_def)
    
    # Create agent definition
    agent_def = PromptAgentDefinition(
        model=agent_model,
        instructions=AGENT_INSTRUCTIONS,
        tools=[openapi_tool],
    )
    
    print(f"Creating agent '{AGENT_NAME}' with OpenAPI tools...")
    print(f"  Function URL: {function_url}")
    print(f"  Model: {agent_model}")
    print(f"  Auth: {auth_desc}")
    
    agent = client.agents.create(
        name=AGENT_NAME,
        definition=agent_def,
        description="VoiceLive Evaluation Agent with OpenAPI tools calling Azure Functions",
    )
    
    print(f"\n[OK] Agent created successfully!")
    print(f"  Agent Name: {agent.name}")
    print(f"  Agent ID: {agent.id}")
    print(f"\nThis agent calls Azure Functions directly - no local runner needed!")
    print(f"\nUse in Foundry Portal:")
    print(f"  1. Go to https://ai.azure.com")
    print(f"  2. Select your project")
    print(f"  3. Go to Agents → Find '{AGENT_NAME}'")
    print(f"  4. Click Test to interact")
    
    # Save to .agent-cloud file
    agent_file = SCRIPT_DIR / ".agent-cloud"
    with open(agent_file, "w") as f:
        json.dump({
            "agent_id": agent.id,
            "name": agent.name,
            "function_url": function_url,
            "mode": "openapi",
            "auth": "connection" if connection_name else ("entra" if entra_auth else "anonymous")
        }, f, indent=2)
    print(f"\nAgent info saved to: {agent_file}")
    
    return agent.id


def update_agent_with_openapi(function_url: str, function_key: str = None, entra_auth: bool = False, client_id: str = None, connection_name: str = None, model: str = None):
    """Update existing agent with OpenAPI tools by creating a new version."""
    # Use provided model or fall back to env/default
    agent_model = model or os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")
    
    endpoint = os.environ.get("PROJECT_ENDPOINT")
    if not endpoint:
        print("ERROR: PROJECT_ENDPOINT environment variable required")
        sys.exit(1)
    
    if entra_auth and not client_id:
        print("ERROR: --client-id required when using --entra-auth")
        sys.exit(1)
    
    credential = DefaultAzureCredential()
    client = AIProjectClient(endpoint=endpoint, credential=credential)
    
    # Load OpenAPI spec
    spec = load_openapi_spec(function_url)
    
    # Configure authentication
    if connection_name:
        auth = OpenApiProjectConnectionAuthDetails(
            security_scheme=OpenApiProjectConnectionSecurityScheme(
                project_connection_id=connection_name
            )
        )
        auth_desc = f"Connection-based API Key (connection: {connection_name})"
    elif entra_auth:
        auth = OpenApiManagedAuthDetails(
            security_scheme=OpenApiManagedSecurityScheme(
                audience=f"api://{client_id}"
            )
        )
        auth_desc = f"Managed Identity (audience: api://{client_id})"
    else:
        auth = OpenApiAnonymousAuthDetails()
        auth_desc = 'Anonymous (testing only)'
    
    # Create OpenAPI tool definition
    openapi_def = OpenApiFunctionDefinition(
        name="voicelive_evaluation_api",
        description="VoiceLive evaluation tools API for dataset validation and analysis",
        spec=spec,
        auth=auth,
    )
    
    # Create OpenAPI tool
    openapi_tool = OpenApiAgentTool(openapi=openapi_def)
    
    # Create agent definition
    agent_def = PromptAgentDefinition(
        model=agent_model,
        instructions=AGENT_INSTRUCTIONS,
        tools=[openapi_tool],
    )
    
    print(f"Creating new version of agent '{AGENT_NAME}' with OpenAPI tools...")
    print(f"  Function URL: {function_url}")
    print(f"  Model: {agent_model}")
    print(f"  Auth: {auth_desc}")
    
    # Create new version with 'latest' label so Responses API can find it.
    # The SDK's create_version() doesn't expose version_label as a kwarg,
    # so we serialize the definition to a dict and add version_label.
    def_dict = agent_def.as_dict()
    body = {
        "definition": def_dict,
        "description": "VoiceLive Evaluation Agent with config management tools",
        "version_label": "latest",
    }
    agent = client.agents.create_version(
        agent_name=AGENT_NAME,
        body=body,
    )
    
    print(f"\n[OK] Agent version created successfully!")
    print(f"  Agent Name: {agent.name}")
    print(f"  Version: {agent.version}")
    
    return agent.id


def main():
    parser = argparse.ArgumentParser(
        description="Create/Update VoiceLive Evaluation Agent with OpenAPI tools",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Authentication Options:
  Anonymous (default):     No auth - for testing only
  Connection-based:        --connection-name <name>  (recommended for production)
  Managed Identity:        --entra-auth --client-id <id>  (requires App Registration)

Examples:
  # Create with anonymous auth (testing)
  python setup_agent_openapi.py --function-url https://func-xxx.azurewebsites.net/api

  # Create with Foundry connection auth (production)
  python setup_agent_openapi.py --function-url https://func-xxx.azurewebsites.net/api \\
      --connection-name voicelive-eval-api-key

  # Update existing agent
  python setup_agent_openapi.py --function-url https://func-xxx.azurewebsites.net/api --update
        """
    )
    parser.add_argument("--function-url", required=True, 
                        help="Azure Functions base URL (e.g., https://myapp.azurewebsites.net/api)")
    parser.add_argument("--connection-name",
                        help="Foundry connection name for API key auth (create in Foundry portal first)")
    parser.add_argument("--entra-auth", action="store_true",
                        help="Use Entra ID managed identity authentication")
    parser.add_argument("--client-id",
                        help="App Registration Client ID (required with --entra-auth)")
    parser.add_argument("--update", action="store_true",
                        help="Update existing agent instead of creating new one")
    parser.add_argument("--model",
                        help="Model deployment name (default from env or gpt-4.1-mini)")
    args = parser.parse_args()
    
    # Use provided model or fall back to env/default
    model = args.model or os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")
    
    if args.update:
        update_agent_with_openapi(
            args.function_url, 
            entra_auth=args.entra_auth, 
            client_id=args.client_id,
            connection_name=args.connection_name,
            model=model
        )
    else:
        create_agent_with_openapi(
            args.function_url, 
            entra_auth=args.entra_auth, 
            client_id=args.client_id,
            connection_name=args.connection_name,
            model=model
        )


if __name__ == "__main__":
    main()
