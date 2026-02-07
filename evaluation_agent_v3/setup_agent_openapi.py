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
1. Discover and list available datasets (from Azure Blob Storage)
2. Validate datasets before evaluation (consistency + quality checks)
3. Manage VoiceLive session configurations (model, voice, VAD, audio settings)
4. Process raw audio files through VoiceLive (generates evaluation datasets)
5. Run Foundry evaluators on datasets (intent_resolution, task_adherence, etc.)
6. Manage Foundry resources (list/delete eval groups and datasets)
7. Analyze evaluation results and provide insights

## Available Tools

### Dataset Discovery & Validation
- list_datasets: Find available datasets in blob storage
- check_dataset_schema: Identify required/optional fields in dataset
- validate_dataset_consistency: MANDATORY structural validation
- validate_dataset_quality: ADVISORY content quality check

### Session Configuration Management
- list_session_configs: List all available VoiceLive configurations
- get_session_config: Get details of a specific configuration
- create_session_config: Create new configuration with custom settings
- update_session_config: Update an existing configuration
- delete_session_config: Delete a configuration (cannot delete 'default')

### VoiceLive Audio Processing
- run_voicelive_audio_tests: Process raw audio files through VoiceLive SDK
- check_voicelive_job_status: Check status of audio processing job
  Note: Returns output_path to evaluation dataset when complete

### Evaluation Execution
- run_voicelive_evaluation: Run Foundry evaluators on a dataset
- check_evaluation_status: Check status of async evaluation
- get_evaluation_recommendations: Get recommendations for large datasets

### Foundry Resource Management  
- list_evaluation_groups: List existing eval groups (can reuse with eval_group_id)
- list_foundry_datasets: List existing Foundry datasets (can reuse with foundry_dataset_id)
- delete_evaluation_groups: Delete eval groups by ID or search string
- delete_foundry_datasets: Delete Foundry datasets by name or search string

### Results Analysis
- analyze_evaluation_results: Get detailed insights from completed evaluations

## Session Configuration Options

Before running evaluations, users can specify which VoiceLive configuration to use.
Use list_session_configs to show available configs. Key configuration options:

| Setting | Options | Notes |
|---------|---------|-------|
| model | gpt-realtime, gpt-realtime-mini, gpt-4.1 | gpt-4.1 supports EOU detection |
| sample_rate | 16000, 24000 | Audio sample rate in Hz |
| vad_type | server_vad, azure_semantic_vad_multilingual | Voice activity detection |
| vad_threshold | 0.0-1.0 | VAD sensitivity (SDK default if omitted) |
| silence_duration_ms | integer | Silence to end speech (SDK default if omitted) |
| eou_detection | true/false | Only works with gpt-4.1 model |
| noise_reduction | azure_deep_noise_suppression | Audio noise reduction |
| echo_cancellation | server_echo_cancellation | Audio echo cancellation |

Transcription model is auto-selected based on main model:
- gpt-realtime → gpt-4o-transcribe
- gpt-realtime-mini → gpt-4o-mini-transcribe
- gpt-4.1 → azure-speech

## Workflow Rules

### For Raw Audio Datasets (no query/response fields):
1. list_datasets → Find dataset with audio files
2. validate_dataset_consistency → Verify structure
3. list_session_configs → Show available configs (optional)
4. run_voicelive_audio_tests → Process audio through VoiceLive (with session_config)
5. check_voicelive_job_status → Poll until complete (get output_path)
6. run_voicelive_evaluation → Run evaluators on the output
7. check_evaluation_status → Poll until complete
8. Present Foundry Portal URL and metrics summary

### For Evaluation-Ready Datasets (has query/response):
1. list_datasets → Find dataset
2. validate_dataset_consistency → Verify structure  
3. run_voicelive_evaluation → Run evaluators directly
4. check_evaluation_status → Poll until complete
5. analyze_evaluation_results → Get detailed insights

## Default Evaluators
If user doesn't specify, use these 10 evaluators aligned with VoiceLive best practices:
- intent_resolution, task_adherence, task_completion, response_completeness
- groundedness, relevance
- tool_call_accuracy, tool_selection, tool_input_accuracy, tool_output_utilization

## Important Notes
- ALWAYS present the Foundry Portal URL when evaluation completes
- For large datasets (>50 entries), use get_evaluation_recommendations first
- Use eval_group_id/foundry_dataset_id to avoid re-uploading data
- VoiceLive audio processing uses Container App (long-running)
- Foundry evaluations use Azure Functions with Durable Functions
- EOU detection only works with gpt-4.1 model (ignored for realtime models)
"""


def load_openapi_spec(function_url: str, function_key: str = None) -> dict:
    """Load OpenAPI spec as dict and update server URL."""
    import yaml
    
    if not OPENAPI_SPEC_PATH.exists():
        print(f"ERROR: OpenAPI spec not found at {OPENAPI_SPEC_PATH}")
        sys.exit(1)
    
    with open(OPENAPI_SPEC_PATH, 'r') as f:
        spec = yaml.safe_load(f)
    
    # Update server URL - include function key if provided
    if function_key:
        server_url = f"{function_url}?code={function_key}"
    else:
        server_url = function_url
    
    spec['servers'] = [{'url': server_url}]
    
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
    
    # Load OpenAPI spec - don't append key to URL
    spec = load_openapi_spec(function_url, None)
    
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
    
    print(f"\n✓ Agent created successfully!")
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
    spec = load_openapi_spec(function_url, None)
    
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
    
    # Create new version instead of updating
    agent = client.agents.create_version(
        agent_name=AGENT_NAME,
        definition=agent_def,
        description="VoiceLive Evaluation Agent with config management tools",
    )
    
    print(f"\n✓ Agent version created successfully!")
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
