"""
Create and test an Azure AI Foundry Agent with Bing Web Search tool.
Uses azure-ai-projects SDK 2.0.0b3+ with Responses API
"""
import argparse
import os
import json
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    PromptAgentDefinition, 
    Tool, 
    BingGroundingAgentTool, 
    BingGroundingSearchToolParameters, 
    BingGroundingSearchConfiguration
)
from dotenv import load_dotenv

def agent_responses_api_non_streaming_test(agent_name: str, tool_choice: str) -> None:
    """Test the agent by sending a query and printing the response along with any citations."""
    print("\n--- Testing agent with 'What is the capital of France?' ---")
    print(f"(tool_choice={tool_choice})")
    
    response = openai_client.responses.create(
        input=[{"role": "user", "content": "What is the capital of France?"}],
        tool_choice=tool_choice,
        extra_body={"agent": {"name": agent_name, "type": "agent_reference"}},
    )
    print(f"Agent response: {response.output_text}")
    
    # Extract citations from the response
    for item in response.output:
        if item.type == "message":
            for content in item.content:
                if hasattr(content, 'annotations') and content.annotations:
                    for annotation in content.annotations:
                        if annotation.type == "url_citation":
                            print(f"  [Citation: {annotation.url}]")

def agent_responses_api_streaming_test(agent_name: str, tool_choice: str) -> None:
    """Test the agent with a streaming response to demonstrate real-time output and citations."""
    print("\n--- Testing agent with streaming response ---")
    print(f"(tool_choice={tool_choice})")
    
    stream_response = openai_client.responses.create(
        stream=True,
        tool_choice=tool_choice,
        input="What is the current date and weather in Seattle?",
        extra_body={"agent": {"name": agent_name, "type": "agent_reference"}},
    )

    for event in stream_response:
        if event.type == "response.created":
            print(f"Response created with ID: {event.response.id}")
        elif event.type == "response.output_text.delta":
            print(event.delta, end="", flush=True)
        elif event.type == "response.output_item.done":
            if event.item.type == "message":
                item = event.item
                if item.content[-1].type == "output_text":
                    text_content = item.content[-1]
                    for annotation in text_content.annotations:
                        if annotation.type == "url_citation":
                            print(f"\n  [Citation: {annotation.url}]")
        elif event.type == "response.completed":
            print(f"\n\nFull response: {event.response.output_text}")

if __name__ == "__main__":

    load_dotenv()

    agent_name="VoiceAgentwBingWebSearch"

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Create and test an Azure AI Foundry Voice Agent with Bing Web Search tool.")
    parser.add_argument(
        "--agent-name",
        type=str,
        default=agent_name,
        help="Name of the agent to create and test"
    )
    parser.add_argument(
        "--force-tool-use", 
        action="store_true", 
        help="Force the agent to use Bing search tool even for simple queries (produces citations)"
    )
    parser.add_argument(
        "--clean-up-agent", 
        action="store_true", 
        help="Delete the agent version after testing"
    )
    args = parser.parse_args()

    # Set tool_choice based on flag
    tool_choice = "required" if args.force_tool_use else "auto"

    project_endpoint = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
    # Use nested context managers per SDK 2.0 pattern
    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint=project_endpoint, credential=credential) as project_client,
        project_client.get_openai_client() as openai_client,
    ):
        # Get connection ID from connection name (recommended approach)
        try:
            bing_connection = project_client.connections.get(
                os.environ.get("BING_PROJECT_CONNECTION_NAME", "BingSearchGroundingqw45j5"),
            )
            print(f"Bing Search connection ID: {bing_connection.id}")
        except Exception as e:
            print(f"Error retrieving Bing Search connection: {e}. Please check the connection name and ensure it exists.")
            exit(1)

        # Define the Voice Live settings
        voice_live_configuration = {
            "session": {
                "voice": {"name": "en-US-Ava:DragonHDLatestNeural"}, #en-US-AvaNeural
                "input_audio_transcription": {"model": "azure-speech", "language": "en"},
                "turn_detection": {"type": "azure_semantic_vad", "prefix_padding_ms": 500},
                "input_audio_echo_cancellation": {"type": "server_echo_cancellation"},
            }
        }
        # Define the Bing grounding tool
        bing_tool = BingGroundingAgentTool(
            bing_grounding=BingGroundingSearchToolParameters(
                search_configurations=[BingGroundingSearchConfiguration(
                    project_connection_id=bing_connection.id,
                    market="en-us",
                    set_lang="en",
                    count=5
                )]
            )
        )

        instructions = """You are a helpful assistant with access to Bing Web Search.
    Use the search tool when you need to look up factual information. Be polite, concise, and helpful.

    You are used to generate ground truth data used for evaluations. A simple example for a ground truth can be a very concise factual answer.

    Example: “What is the capital of France?” => Answer: “Paris.”

    Given most conversational Ais / LLMs will not reply with short answers like this, a full sentence response will constitute a more proper representation for the ground truth. However, we want to avoid adding additional information an agent system might generate that could be misinterpreted or obfuscate the evaluation result.

    Negative example: “The capital of France is Paris. It is located in the north-central part of the country along the Seine River and is widely regarded as one of the world’s major centers of art, culture, fashion, and gastronomy.”

    Positive examples:
    -	“The capital of France is Paris.”
    -	“The tallest mountain in the world is Mount Everest.”

    Acceptable example:
    -	The capital of France is Paris in the Seine valley.
    -	“The tallest mountain in the world is Mount Everest, standing at 8,849 meters (29,032 feet) above sea level.”

    Requirement summary:
    -	Full concise sentence answers.
    -	Ground truth only answers question without additional information added.
    -	Acceptable is information directly related to the question; e.g. height, if asked for tallest or smallest, directional locations, aliases, etc.

    """

        # Create tools list
        tools: list[Tool] = [bing_tool]

        # Step 1: Create the agent
        agent = project_client.agents.create_version(
            agent_name=agent_name,
            definition=PromptAgentDefinition(
                model=os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-5-chat"),
                instructions=instructions,
                tools=tools,
            ),
            description="Agent with Bing Web Search for factual queries.",
            metadata={
                "microsoft.voice-live.configuration": json.dumps(voice_live_configuration),
                "created_by": "create_agent_with_bing_web_search_with_VL.py script"
            },
        )
        print(f"Agent created (id: {agent.id}, name: {agent.name}, version: {agent.version})")

        # Step 2: Retrieve the agent to verify it was created
        retrieved_agent = project_client.agents.get(agent_name=agent_name)
        print(f"Retrieved agent (name: {retrieved_agent.name}, versions: {retrieved_agent.versions})")

        # Step 3: Test the agent using the Responses API (SDK 2.0+ pattern)
        agent_responses_api_non_streaming_test(agent_name=agent.name, tool_choice=tool_choice)

        # Step 4: Test with streaming response
        agent_responses_api_streaming_test(agent_name=agent.name, tool_choice=tool_choice)

        # Optional: Clean up by deleting the agent version
        if args.clean_up_agent:
            project_client.agents.delete_version(agent_name=agent.name, agent_version=agent.version)
            print("\nAgent version deleted")
