"""
Foundry Agent Setup with OpenAPI Tools (Cloud Mode)

Creates the VoiceLive Evaluation Agent using OpenAPI tools that call
Azure Functions. This allows the agent to work without a local runner.

Usage:
    python setup_agent_openapi.py --function-url https://myapp.azurewebsites.net/api
    python setup_agent_openapi.py --function-url https://myapp.azurewebsites.net/api --function-key <key>
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
)

# Load environment
SCRIPT_DIR = Path(__file__).parent
load_dotenv(SCRIPT_DIR / ".env")

# Agent configuration
AGENT_NAME = "voicelive-evaluation-agent-cloud"
AGENT_MODEL = os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4o-mini")

# Load OpenAPI spec path
OPENAPI_SPEC_PATH = SCRIPT_DIR / "deploy" / "azure-functions" / "openapi.yaml"

AGENT_INSTRUCTIONS = """You are an intelligent assistant for automating VoiceLive evaluation workflows.

You help users:
1. Discover and list available datasets (from Azure Blob Storage)
2. Validate datasets before evaluation (consistency + quality checks)
3. Get recommendations for large dataset evaluations
4. Run VoiceLive audio evaluations (requires Container Apps deployment)
5. Analyze evaluation results and provide insights

## Workflow Rules

ALWAYS follow this sequence:
1. list_datasets → Find available datasets
2. check_dataset_schema → Identify missing optional fields
3. validate_dataset_consistency → MANDATORY structural check
4. validate_dataset_quality → ADVISORY content check  
5. get_evaluation_recommendations → For large datasets (>50 entries)
6. run_voicelive_evaluation → Execute the evaluation
7. analyze_evaluation_results → Extract insights

## Large Dataset Handling

For datasets with >50 entries:
1. Run get_evaluation_recommendations after validation
2. Present recommended settings (timeout, workers) to user
3. Ask for confirmation before proceeding

## Important Notes

- All tools call Azure Functions via HTTP API
- Datasets are stored in Azure Blob Storage
- Authentication uses Azure Managed Identity
- Full evaluations require Container Apps (Functions have timeout limits)
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


def create_agent_with_openapi(function_url: str, function_key: str = None):
    """Create agent using OpenAPI tools."""
    
    endpoint = os.environ.get("PROJECT_ENDPOINT")
    if not endpoint:
        print("ERROR: PROJECT_ENDPOINT environment variable required")
        sys.exit(1)
    
    credential = DefaultAzureCredential()
    client = AIProjectClient(endpoint=endpoint, credential=credential)
    
    # Load OpenAPI spec with function key embedded in URL if provided
    spec = load_openapi_spec(function_url, function_key)
    
    # Create OpenAPI tool definition
    openapi_def = OpenApiFunctionDefinition(
        name="voicelive_evaluation_api",
        description="VoiceLive evaluation tools API for dataset validation and analysis",
        spec=spec,
        auth=OpenApiAnonymousAuthDetails(),
    )
    
    # Create OpenAPI tool
    openapi_tool = OpenApiAgentTool(openapi=openapi_def)
    
    # Create agent definition
    agent_def = PromptAgentDefinition(
        model=AGENT_MODEL,
        instructions=AGENT_INSTRUCTIONS,
        tools=[openapi_tool],
    )
    
    print(f"Creating agent '{AGENT_NAME}' with OpenAPI tools...")
    print(f"  Function URL: {function_url}")
    print(f"  Auth: {'Function Key (in URL)' if function_key else 'Anonymous'}")
    
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
            "mode": "openapi"
        }, f, indent=2)
    print(f"\nAgent info saved to: {agent_file}")
    
    return agent.id


def main():
    parser = argparse.ArgumentParser(description="Create VoiceLive Evaluation Agent with OpenAPI tools")
    parser.add_argument("--function-url", required=True, 
                        help="Azure Functions base URL (e.g., https://myapp.azurewebsites.net/api)")
    parser.add_argument("--function-key", 
                        help="Function key for authentication (optional if using Managed Identity)")
    args = parser.parse_args()
    
    create_agent_with_openapi(args.function_url, args.function_key)


if __name__ == "__main__":
    main()
