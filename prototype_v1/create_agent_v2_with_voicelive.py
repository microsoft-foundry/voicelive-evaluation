import os
import json
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition

load_dotenv()

project_client = AIProjectClient(
    endpoint=os.environ["PROJECT_ENDPOINT"],
    credential=DefaultAzureCredential(),
)

agent_name=os.environ["AGENT_NAME"]

# Define the Voice Live settings
voice_live_configuration = {
    "session": {
        "voice": {"name": "en-US-Ava:DragonHDLatestNeural", "type": "azure-standard", "temperature": 0.8},
        "input_audio_transcription": {"model": "azure-speech"},
        "turn_detection": {"type": "azure_semantic_vad",
            "end_of_utterance_detection": {
                "model": "semantic_detection_v1_multilingual"
            },
        },
        "input_audio_noise_reduction": {"type": "azure_deep_noise_suppression"},
        "input_audio_echo_cancellation": {"type": "server_echo_cancellation"}
    }
}

# Create agent
agent = project_client.agents.create_version(
    agent_name=agent_name,
    definition=PromptAgentDefinition(
        model=os.environ["MODEL_DEPLOYMENT_NAME"],
        instructions="You are a helpful assistant that answers general questions",
    ),
    metadata={
        "microsoft.voice-live.configuration": json.dumps(voice_live_configuration)
    },
)
print(f"Agent created (id: {agent.id}, name: {agent.name}, version: {agent.version})")

# Retrieve the agent config to verify Voice Live settings
retrieved_agent = project_client.agents.get(agent_name=agent_name)
print(f"\nRetrieved agent: {retrieved_agent.name}")

# Extract Voice Live config from versions.latest.metadata
vl_config_str = (retrieved_agent.versions or {}).get('latest', {}).get('metadata', {}).get('microsoft.voice-live.configuration')
if vl_config_str:
    print("Voice Live configuration:")
    print(json.dumps(json.loads(vl_config_str), indent=2))
else:
    print("Voice Live configuration not found in agent metadata.")
