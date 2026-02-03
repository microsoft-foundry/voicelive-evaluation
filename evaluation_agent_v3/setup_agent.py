"""
Foundry Agent Setup Script

Creates or updates the VoiceLive Evaluation Agent in Azure AI Foundry.
This is a one-time setup that registers the agent with its tool definitions.

The agent persists in Foundry and can be accessed via:
- AI Foundry Portal (for testing and monitoring)
- API calls (for programmatic access)
- The runner.py script (for tool execution)

Usage:
    python setup_agent.py                    # Create new agent
    python setup_agent.py --update --agent-id <id>  # Update existing
    python setup_agent.py --list             # List agents
    python setup_agent.py --delete --agent-id <id>  # Delete agent
"""

import os
import sys
import json
import argparse
from pathlib import Path

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.agents.models import FunctionTool

# Load environment
SCRIPT_DIR = Path(__file__).parent
load_dotenv(SCRIPT_DIR / ".env")

# Agent configuration
AGENT_NAME = "voicelive-evaluation-agent"
AGENT_MODEL = os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4o-mini")

# Tool definitions (schemas only - execution handled by runner.py)
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "check_dataset_schema",
            "description": "Analyzes a JSONL dataset to check for required and optional fields. Use BEFORE running full validation to identify missing optional metadata that will use defaults during evaluation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_path": {
                        "type": "string",
                        "description": "Path to JSONL file or folder containing JSONL"
                    }
                },
                "required": ["dataset_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "validate_dataset_consistency",
            "description": "Validates JSONL dataset for structural integrity and completeness. This is a MANDATORY check that must pass before running quality validation or voice agent evaluations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_path": {
                        "type": "string",
                        "description": "Path to JSONL file or dataset folder"
                    },
                    "expected_turns": {
                        "type": "integer",
                        "description": "If specified, validates all conversations have exactly N turns"
                    },
                    "ignore_comments": {
                        "type": "boolean",
                        "description": "Skip lines starting with // or #"
                    }
                },
                "required": ["dataset_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "validate_dataset_quality",
            "description": "Assesses content quality of a validated dataset. This is an ADVISORY check that should run AFTER consistency validation passes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_path": {
                        "type": "string",
                        "description": "Path to JSONL file or dataset folder"
                    },
                    "strict": {
                        "type": "boolean",
                        "description": "Use strict keyword-only alignment matching"
                    },
                    "verbose": {
                        "type": "boolean",
                        "description": "Show detailed per-conversation analysis"
                    }
                },
                "required": ["dataset_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_evaluation_recommendations",
            "description": "Analyzes a dataset and provides recommended settings for evaluation. Call this AFTER validation passes and BEFORE running evaluation on large datasets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_path": {
                        "type": "string",
                        "description": "Path to validated JSONL dataset file or folder"
                    }
                },
                "required": ["dataset_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_voicelive_evaluation",
            "description": "Runs Azure VoiceLive audio evaluation tests. Processes audio through VoiceLive API and captures evaluation metrics. IMPORTANT: Run dataset validation BEFORE using this function.",
            "parameters": {
                "type": "object",
                "properties": {
                    "test_files_path": {
                        "type": "string",
                        "description": "Path to audio test file (.wav) or dataset file (.jsonl)"
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Directory for output files"
                    },
                    "session_mode": {
                        "type": "string",
                        "enum": ["per-conversation", "per-file", "single"],
                        "description": "Session handling mode"
                    },
                    "timeout_minutes": {
                        "type": "integer",
                        "description": "Maximum time to wait for evaluation (default: 30)"
                    },
                    "max_workers": {
                        "type": "integer",
                        "description": "Number of parallel workers (max recommended: 8)"
                    },
                    "parallel": {
                        "type": "boolean",
                        "description": "Enable parallel processing (default: true)"
                    }
                },
                "required": ["test_files_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_datasets",
            "description": "Lists ALL available JSONL datasets for evaluation. Always present the COMPLETE list to users.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder_path": {
                        "type": "string",
                        "description": "Path to search for datasets. Defaults to common dataset locations."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_evaluation_results",
            "description": "Analyzes VoiceLive evaluation output files to extract insights and metrics. Use this for evaluation OUTPUT files, NOT for input datasets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "results_path": {
                        "type": "string",
                        "description": "Path to evaluation results folder or aggregate JSONL file"
                    }
                },
                "required": ["results_path"]
            }
        }
    }
]

# Agent instructions
AGENT_INSTRUCTIONS = """You are an intelligent assistant for automating VoiceLive evaluation workflows.

You help users:
1. Discover and list available datasets
2. Validate datasets before evaluation (consistency + quality checks)
3. Get recommendations for large dataset evaluations
4. Run VoiceLive audio evaluations
5. Analyze evaluation results and provide insights

## Workflow Rules

ALWAYS follow this sequence:
1. check_dataset_schema → Identify missing optional fields
2. validate_dataset_consistency → MANDATORY structural check
3. validate_dataset_quality → ADVISORY content check  
4. get_evaluation_recommendations → For large datasets (>50 entries)
5. run_voicelive_evaluation → Execute the evaluation
6. analyze_evaluation_results → Extract insights

## Large Dataset Handling

For datasets with >50 entries:
1. Run get_evaluation_recommendations after validation
2. Present recommended settings (timeout, workers) to user
3. Ask for confirmation before proceeding
4. Max recommended workers: 8 (higher may cause API rate limits)

## Important Notes

- All Azure API calls use Azure Identity (DefaultAzureCredential)
- Tool execution is handled by the runner process
- Results are stored in the configured output directory
- Tracing is automatic via Foundry Agent Service
"""


def get_client() -> AIProjectClient:
    """Get authenticated AIProjectClient."""
    endpoint = os.environ.get("PROJECT_ENDPOINT")
    if not endpoint:
        print("ERROR: PROJECT_ENDPOINT environment variable required")
        sys.exit(1)
    
    credential = DefaultAzureCredential()
    return AIProjectClient(endpoint=endpoint, credential=credential)


def create_agent(client: AIProjectClient) -> str:
    """Create a new agent in Foundry."""
    print(f"Creating agent '{AGENT_NAME}' with model '{AGENT_MODEL}'...")
    
    agent = client.agents.create_agent(
        model=AGENT_MODEL,
        name=AGENT_NAME,
        instructions=AGENT_INSTRUCTIONS,
        tools=TOOL_DEFINITIONS,
    )
    
    print(f"✓ Agent created successfully!")
    print(f"  Agent ID: {agent.id}")
    print(f"  Name: {agent.name}")
    print(f"  Model: {agent.model}")
    print(f"  Tools: {len(TOOL_DEFINITIONS)}")
    print(f"\nSave this Agent ID for future use:")
    print(f"  AGENT_ID={agent.id}")
    
    # Save to .agent file
    agent_file = SCRIPT_DIR / ".agent"
    with open(agent_file, "w") as f:
        json.dump({"agent_id": agent.id, "name": agent.name}, f, indent=2)
    print(f"\nAgent ID saved to: {agent_file}")
    
    return agent.id


def update_agent(client: AIProjectClient, agent_id: str) -> None:
    """Update an existing agent."""
    print(f"Updating agent '{agent_id}'...")
    
    agent = client.agents.update_agent(
        agent_id=agent_id,
        model=AGENT_MODEL,
        name=AGENT_NAME,
        instructions=AGENT_INSTRUCTIONS,
        tools=TOOL_DEFINITIONS,
    )
    
    print(f"✓ Agent updated successfully!")
    print(f"  Agent ID: {agent.id}")
    print(f"  Tools: {len(TOOL_DEFINITIONS)}")


def list_agents(client: AIProjectClient) -> None:
    """List all agents in the project."""
    print("Listing agents...")
    
    agents = client.agents.list_agents()
    
    agent_list = list(agents)
    print(f"\nFound {len(agent_list)} agent(s):\n")
    for agent in agent_list:
        print(f"  ID: {agent.id}")
        print(f"  Name: {agent.name}")
        print(f"  Model: {agent.model}")
        print(f"  Created: {agent.created_at}")
        print()


def delete_agent(client: AIProjectClient, agent_id: str) -> None:
    """Delete an agent."""
    print(f"Deleting agent '{agent_id}'...")
    
    client.agents.delete_agent(agent_id)
    
    print(f"✓ Agent deleted successfully!")
    
    # Remove .agent file if it matches
    agent_file = SCRIPT_DIR / ".agent"
    if agent_file.exists():
        with open(agent_file) as f:
            data = json.load(f)
        if data.get("agent_id") == agent_id:
            agent_file.unlink()
            print(f"  Removed {agent_file}")


def get_saved_agent_id() -> str | None:
    """Get agent ID from .agent file if it exists."""
    agent_file = SCRIPT_DIR / ".agent"
    if agent_file.exists():
        with open(agent_file) as f:
            data = json.load(f)
        return data.get("agent_id")
    return None


def main():
    parser = argparse.ArgumentParser(description="Manage VoiceLive Evaluation Agent in Foundry")
    parser.add_argument("--create", action="store_true", help="Create a new agent")
    parser.add_argument("--update", action="store_true", help="Update existing agent")
    parser.add_argument("--list", action="store_true", help="List all agents")
    parser.add_argument("--delete", action="store_true", help="Delete an agent")
    parser.add_argument("--agent-id", help="Agent ID for update/delete operations")
    args = parser.parse_args()
    
    client = get_client()
    
    if args.list:
        list_agents(client)
    elif args.delete:
        agent_id = args.agent_id or get_saved_agent_id()
        if not agent_id:
            print("ERROR: --agent-id required for delete")
            sys.exit(1)
        delete_agent(client, agent_id)
    elif args.update:
        agent_id = args.agent_id or get_saved_agent_id()
        if not agent_id:
            print("ERROR: --agent-id required for update (or run --create first)")
            sys.exit(1)
        update_agent(client, agent_id)
    else:
        # Default: create new agent
        create_agent(client)


if __name__ == "__main__":
    main()
