from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    PromptAgentDefinition, MCPTool, Tool, BingGroundingAgentTool, BingGroundingSearchToolParameters, BingGroundingSearchConfiguration
)
from dotenv import load_dotenv
import os
load_dotenv()

project_client = AIProjectClient(
    endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
    credential=DefaultAzureCredential(),
)

# Define the MCP tool for accessing speech capabilities
mcp_tool = MCPTool(
    server_label="AzureSpeechMCPServer",
    server_url="https://jagoerge-voicelive-sec-resource.cognitiveservices.azure.com/speech/mcp?api-version=2025-11-07-preview",
    require_approval="never",
    project_connection_id="AzureSpeechMCPServer"
)

# Define the Bing grounding tool
bing_tool = BingGroundingAgentTool(
    bing_grounding=BingGroundingSearchToolParameters(
        search_configurations=[BingGroundingSearchConfiguration(
            project_connection_id="/subscriptions/2c2e6d10-4e48-40fd-8f4d-d9fb770d0c6d/resourceGroups/rg-jagoerge-voicelive-sec/providers/Microsoft.CognitiveServices/accounts/jagoerge-voicelive-sec-resource/projects/jagoerge-voicelive-sec/connections/BingSearchGroundingqw45j5",
            market="en-us",
            set_lang="en",
            count=5
        )]
    )
)

instructions = """You are Tobi the agent, assisting users with their travel questions.

Introduce yourself when you greet the user. Keep responses concise.
When making recommendations always start with your top 3.
"""

# """You are a support agent that answers custom questions about our products.

# Always use the knowledge MCP tool to answer user questions about products.
# Always speak in a professional tone. 
# Always refer to the user by name if provided."""

# Create tools list with proper typing for the agent definition
tools: list[Tool] = [mcp_tool, bing_tool]

try:
    with project_client:
        # Create an agent with MCP tool and Bing grounding capabilities
        agent = project_client.agents.create_version(
            agent_name="MyVoiceLiveAgentwSpeechMCPwBing",
            definition=PromptAgentDefinition(
                model="gpt-5-chat",
                instructions=instructions,
                tools=tools,
            ),
        )
        print(f"Agent created (id: {agent.id}, name: {agent.name}, version: {agent.version})")
except Exception as e:
    print(f"Error creating agent: {e}")
