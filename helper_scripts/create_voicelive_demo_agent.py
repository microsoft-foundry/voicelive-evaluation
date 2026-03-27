"""
Create VoiceLive Demo Agent

Creates a simple Foundry agent with VoiceLive session configuration
for testing agent mode evaluations. Based on the VoiceLive Agent
integration quickstart pattern.

Prerequisites:
    - Azure CLI login: az login
    - Environment variables: PROJECT_ENDPOINT, AGENT_NAME (optional)

Usage:
    python helper_scripts/create_voicelive_demo_agent.py
"""

import os
import json
import logging
from typing import Dict

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition

# Setup
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def chunk_config(config_json: str, limit: int = 512) -> Dict[str, str]:
    """Split VoiceLive config into chunked metadata entries (512-char limit)."""
    metadata = {"microsoft.voice-live.configuration": config_json[:limit]}
    remaining = config_json[limit:]
    chunk_num = 1
    while remaining:
        metadata[f"microsoft.voice-live.configuration.{chunk_num}"] = remaining[:limit]
        remaining = remaining[limit:]
        chunk_num += 1
    return metadata


def reassemble_config(metadata: Dict[str, str]) -> str:
    """Reassemble chunked VoiceLive configuration from metadata."""
    config = metadata.get("microsoft.voice-live.configuration", "")
    chunk_num = 1
    while f"microsoft.voice-live.configuration.{chunk_num}" in metadata:
        config += metadata[f"microsoft.voice-live.configuration.{chunk_num}"]
        chunk_num += 1
    return config


def main() -> None:
    project_endpoint = os.environ.get("PROJECT_ENDPOINT")
    if not project_endpoint:
        raise ValueError("PROJECT_ENDPOINT environment variable is required")

    agent_name = os.environ.get("AGENT_NAME", "voicelive-demo-agent")
    model_name = os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")

    logger.info(f"Creating agent '{agent_name}' with model '{model_name}'")

    # VoiceLive session configuration stored in agent metadata
    voice_live_config = {
        "session": {
            "voice": {
                "name": "en-US-Ava:DragonHDLatestNeural",
                "type": "azure-standard",
                "temperature": 0.8,
            },
            "input_audio_transcription": {"model": "azure-speech"},
            "turn_detection": {
                "type": "azure_semantic_vad",
                "end_of_utterance_detection": {
                    "model": "semantic_detection_v1_multilingual"
                },
            },
            "input_audio_noise_reduction": {"type": "azure_deep_noise_suppression"},
            "input_audio_echo_cancellation": {"type": "server_echo_cancellation"},
        }
    }

    # Create agent
    project_client = AIProjectClient(
        endpoint=project_endpoint,
        credential=DefaultAzureCredential(),
    )

    agent = project_client.agents.create_version(
        agent_name=agent_name,
        definition=PromptAgentDefinition(
            model=model_name,
            instructions=(
                "You are a helpful voice assistant for evaluation testing. "
                "Answer questions clearly and concisely. Keep responses brief "
                "and conversational, suitable for voice interaction."
            ),
        ),
        metadata=chunk_config(json.dumps(voice_live_config)),
    )
    logger.info(f"Agent created: {agent.name} (version {agent.version})")

    # Verify
    retrieved = project_client.agents.get(agent_name=agent_name)
    stored_metadata = (retrieved.versions or {}).get("latest", {}).get("metadata", {})
    stored_config = reassemble_config(stored_metadata)

    if stored_config:
        logger.info("VoiceLive configuration stored successfully:")
        print(json.dumps(json.loads(stored_config), indent=2))
    else:
        logger.warning("VoiceLive configuration not found in agent metadata")

    print(f"\n✅ Agent '{agent_name}' ready for VoiceLive agent mode evaluation")
    print(f"   Use: --agent-name {agent_name} --project-name <your-project>")


if __name__ == "__main__":
    main()
