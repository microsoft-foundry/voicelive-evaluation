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
from azure.ai.projects.models import PromptAgentDefinition
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
            "description": "Analyzes a JSONL dataset to detect its type and check fields. Returns dataset_type: 'voicelive' (WavPath/audio fields), 'evaluation' (query/response fields), 'hybrid', or 'unknown'. MUST be called first before any validation or evaluation to determine the correct workflow.",
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
            "description": "Runs VoiceLive AUDIO evaluation pipeline: processes .wav audio files through VoiceLive SDK, then runs Foundry evaluators on the output. REQUIRES a VoiceLive audio dataset (WavPath/audio fields). Do NOT use for evaluation-ready datasets (query/response format). Always call check_dataset_schema first to verify dataset_type is 'voicelive'.",
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
    },
    {
        "type": "function",
        "function": {
            "name": "list_session_configs",
            "description": "Lists all available VoiceLive session configurations. Each config defines model, voice, VAD settings, and audio processing options for evaluation runs.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_session_config",
            "description": "Gets detailed information about a specific VoiceLive session configuration by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the configuration to retrieve (e.g., 'default', 'conf1', 'conf2')"
                    }
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_session_config",
            "description": "Creates a new VoiceLive session configuration with custom settings. Use for setting up different evaluation scenarios.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Unique name for the configuration"
                    },
                    "description": {
                        "type": "string",
                        "description": "Human-readable description of this config's purpose"
                    },
                    "model": {
                        "type": "string",
                        "enum": ["gpt-realtime", "gpt-realtime-mini", "gpt-4.1"],
                        "description": "VoiceLive model to use"
                    },
                    "sample_rate": {
                        "type": "integer",
                        "enum": [16000, 24000],
                        "description": "Audio sample rate in Hz (16000 or 24000)"
                    },
                    "voice_name": {
                        "type": "string",
                        "description": "Voice preset name (e.g., 'alloy', 'echo', 'shimmer')"
                    },
                    "vad_type": {
                        "type": "string",
                        "enum": ["server_vad", "azure_semantic_vad_multilingual"],
                        "description": "Voice Activity Detection type"
                    },
                    "vad_threshold": {
                        "type": "number",
                        "description": "VAD sensitivity threshold (0.0-1.0). Omit to use SDK default."
                    },
                    "silence_duration_ms": {
                        "type": "integer",
                        "description": "Silence duration in ms to detect end of speech. Omit to use SDK default."
                    },
                    "eou_detection": {
                        "type": "boolean",
                        "description": "Enable End-of-Utterance detection (only for gpt-4.1 model)"
                    },
                    "eou_model": {
                        "type": "string",
                        "description": "EOU model to use (default: azure_semantic_v1_multilingual)"
                    },
                    "transcription_model": {
                        "type": "string",
                        "description": "Transcription model (auto-selected based on main model if not specified)"
                    },
                    "noise_reduction": {
                        "type": "string",
                        "description": "Noise reduction type (default: azure_deep_noise_suppression)"
                    },
                    "echo_cancellation": {
                        "type": "string",
                        "description": "Echo cancellation type (default: server_echo_cancellation)"
                    },
                    "is_default": {
                        "type": "boolean",
                        "description": "Set as the default configuration"
                    }
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_session_config",
            "description": "Updates an existing VoiceLive session configuration. Only provided fields are updated.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the configuration to update"
                    },
                    "description": {"type": "string"},
                    "model": {"type": "string", "enum": ["gpt-realtime", "gpt-realtime-mini", "gpt-4.1"]},
                    "sample_rate": {"type": "integer", "enum": [16000, 24000]},
                    "voice_name": {"type": "string"},
                    "vad_type": {"type": "string", "enum": ["server_vad", "azure_semantic_vad_multilingual"]},
                    "vad_threshold": {"type": "number"},
                    "silence_duration_ms": {"type": "integer"},
                    "eou_detection": {"type": "boolean"},
                    "eou_model": {"type": "string"},
                    "transcription_model": {"type": "string"},
                    "noise_reduction": {"type": "string"},
                    "echo_cancellation": {"type": "string"},
                    "is_default": {"type": "boolean"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_session_config",
            "description": "Deletes a VoiceLive session configuration. Cannot delete the 'default' config.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the configuration to delete"
                    }
                },
                "required": ["name"]
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
4. Run VoiceLive audio evaluations with configurable settings
5. Analyze evaluation results and provide insights
6. Manage VoiceLive session configurations

## CRITICAL: Dataset Type Routing (MANDATORY FIRST STEP)

BEFORE any validation or evaluation, ALWAYS run check_dataset_schema first.
It returns a dataset_type field that determines the correct workflow.

### If dataset_type is "voicelive" (has WavPath/audio fields):
1. check_dataset_schema → Verify dataset_type is "voicelive"
2. validate_dataset_consistency → MANDATORY structural check
3. validate_dataset_quality → ADVISORY content check
4. get_evaluation_recommendations → For large datasets (>50 entries)
5. run_voicelive_evaluation → Processes audio + runs evaluation
6. analyze_evaluation_results → Extract insights

### If dataset_type is "evaluation" (has query/response fields):
This local agent processes VoiceLive AUDIO datasets only.
Evaluation-ready datasets (query/response format) do NOT need VoiceLive audio processing.
Tell the user: "This dataset is already in evaluation-ready format (query/response).
It does not contain audio files to process through VoiceLive. To run Foundry evaluators
on it, use the cloud-deployed agent or the Foundry Portal directly."

### If dataset_type is "unknown":
Do NOT proceed. Ask the user to verify the dataset format.
A valid VoiceLive dataset needs WavPath or audio fields pointing to .wav files.

## COMMON MISTAKE
Do NOT call run_voicelive_evaluation on a dataset with query/response fields.
That tool processes audio files through the VoiceLive SDK and will fail or produce
wrong results if the dataset has no audio to process.

## Session Configuration

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
- EOU detection only works with gpt-4.1 model (ignored for realtime models)
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
    
    # Build the agent definition
    definition = PromptAgentDefinition(
        model=AGENT_MODEL,
        instructions=AGENT_INSTRUCTIONS,
        tools=TOOL_DEFINITIONS,
    )
    
    agent = client.agents.create(
        name=AGENT_NAME,
        definition=definition,
        description="VoiceLive Evaluation Agent for automating evaluation workflows"
    )
    
    print(f"✓ Agent created successfully!")
    print(f"  Agent ID: {agent.id}")
    print(f"  Name: {agent.name}")
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
    """Update an existing agent by creating a new version."""
    print(f"Creating new version of agent '{agent_id}'...")
    
    # Build the agent definition
    definition = PromptAgentDefinition(
        model=AGENT_MODEL,
        instructions=AGENT_INSTRUCTIONS,
        tools=TOOL_DEFINITIONS,
    )
    
    # Create a new version of the agent
    agent = client.agents.create_version(
        agent_name=agent_id,
        definition=definition,
        description="VoiceLive Evaluation Agent with config management tools"
    )
    
    print(f"✓ Agent version created successfully!")
    print(f"  Agent ID: {agent.id}")
    print(f"  Name: {agent.name}")
    print(f"  Version: {agent.version}")
    print(f"  Tools: {len(TOOL_DEFINITIONS)}")


def list_agents(client: AIProjectClient) -> None:
    """List all agents in the project."""
    print("Listing agents...")
    
    agents = client.agents.list()
    
    agent_list = list(agents)
    print(f"\nFound {len(agent_list)} agent(s):\n")
    for agent in agent_list:
        print(f"  ID: {agent.id}")
        print(f"  Name: {agent.name}")
        print(f"  Created: {getattr(agent, 'created_at', 'N/A')}")
        print()


def delete_agent(client: AIProjectClient, agent_id: str) -> None:
    """Delete an agent."""
    print(f"Deleting agent '{agent_id}'...")
    
    client.agents.delete(agent_id)
    
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
