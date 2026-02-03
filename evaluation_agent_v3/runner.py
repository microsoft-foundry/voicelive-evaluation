"""
Runner for VoiceLive Evaluation Agent v3

This script connects to a Foundry Agent and handles tool execution.
The agent orchestration happens in Foundry, while tool execution happens here.

Usage:
    python runner.py                    # Interactive mode
    python runner.py --cloud            # Cloud mode (blob storage)
    python runner.py --message "..."    # Single message mode
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import (
    MessageRole,
    ThreadRun,
    RunStatus,
    SubmitToolOutputsAction,
    RequiredFunctionToolCall,
)

# Load environment
SCRIPT_DIR = Path(__file__).parent
load_dotenv(SCRIPT_DIR / ".env")

# Import tool implementations
from tools import execute_tool, TOOLS


def get_agent_id() -> str:
    """Get agent ID from .agent file or environment."""
    # Check environment first
    agent_id = os.environ.get("AGENT_ID")
    if agent_id:
        return agent_id
    
    # Check .agent file
    agent_file = SCRIPT_DIR / ".agent"
    if agent_file.exists():
        with open(agent_file) as f:
            data = json.load(f)
        return data.get("agent_id")
    
    return None


def handle_tool_calls(client: AgentsClient, thread_id: str, run: ThreadRun) -> None:
    """Handle tool calls from the agent."""
    if not isinstance(run.required_action, SubmitToolOutputsAction):
        return
    
    tool_outputs = []
    
    for tool_call in run.required_action.submit_tool_outputs.tool_calls:
        if isinstance(tool_call, RequiredFunctionToolCall):
            tool_name = tool_call.function.name
            try:
                arguments = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                arguments = {}
            
            print(f"\n📞 Tool call: {tool_name}")
            print(f"   Arguments: {json.dumps(arguments, indent=2)[:200]}...")
            
            # Execute the tool
            result = execute_tool(tool_name, arguments)
            
            tool_outputs.append({
                "tool_call_id": tool_call.id,
                "output": json.dumps(result)
            })
    
    # Submit tool outputs
    if tool_outputs:
        client.submit_tool_outputs_to_run(
            thread_id=thread_id,
            run_id=run.id,
            tool_outputs=tool_outputs
        )


def run_conversation(client: AgentsClient, agent_id: str, user_message: str) -> str:
    """Run a single conversation turn."""
    # Create thread
    thread = client.threads.create()
    
    # Add user message
    client.messages.create(
        thread_id=thread.id,
        role=MessageRole.USER,
        content=user_message
    )
    
    # Create run
    run = client.runs.create(
        thread_id=thread.id,
        agent_id=agent_id
    )
    
    # Poll for completion
    while True:
        run = client.runs.get(thread_id=thread.id, run_id=run.id)
        
        if run.status == RunStatus.COMPLETED:
            break
        elif run.status == RunStatus.REQUIRES_ACTION:
            handle_tool_calls(client, thread.id, run)
        elif run.status in [RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.EXPIRED]:
            return f"Run failed with status: {run.status}"
        else:
            # Still running, wait a bit
            import time
            time.sleep(1)
    
    # Get messages
    messages = client.messages.list(thread_id=thread.id)
    
    # Find assistant response
    for msg in messages.data:
        if msg.role == MessageRole.ASSISTANT:
            # Extract text content
            for content in msg.content:
                if hasattr(content, 'text'):
                    return content.text.value
    
    return "No response from agent"


def interactive_mode(client: AgentsClient, agent_id: str) -> None:
    """Run in interactive mode."""
    print("\n" + "=" * 60)
    print("VoiceLive Evaluation Agent v3 (Foundry Agent Service)")
    print("=" * 60)
    print(f"Agent ID: {agent_id}")
    print(f"Tools: {', '.join(TOOLS.keys())}")
    print("\nType your requests in natural language.")
    print("Type 'quit' or 'exit' to end the session.")
    print("=" * 60 + "\n")
    
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break
        
        if not user_input:
            continue
        
        if user_input.lower() in ['quit', 'exit', 'q']:
            print("Goodbye!")
            break
        
        print("\nAgent: ", end="", flush=True)
        response = run_conversation(client, agent_id, user_input)
        print(response)
        print()


def main():
    parser = argparse.ArgumentParser(description="VoiceLive Evaluation Agent Runner")
    parser.add_argument("--message", "-m", help="Single message to process")
    parser.add_argument("--agent-id", help="Agent ID (or set AGENT_ID env var)")
    parser.add_argument("--cloud", action="store_true", help="Run in cloud mode")
    parser.add_argument("--endpoint", help="Project endpoint (or set PROJECT_ENDPOINT env var)")
    args = parser.parse_args()
    
    # Set cloud mode
    if args.cloud:
        os.environ["EVAL_AGENT_MODE"] = "cloud"
    
    # Get endpoint
    endpoint = args.endpoint or os.environ.get("PROJECT_ENDPOINT")
    if not endpoint:
        print("ERROR: PROJECT_ENDPOINT required")
        print("Set via --endpoint or PROJECT_ENDPOINT environment variable")
        sys.exit(1)
    
    # Get agent ID
    agent_id = args.agent_id or get_agent_id()
    if not agent_id:
        print("ERROR: Agent ID required")
        print("Run 'python setup_agent.py' first to create an agent")
        print("Or set AGENT_ID environment variable")
        sys.exit(1)
    
    # Create client
    print("Connecting to Azure AI Foundry...")
    credential = DefaultAzureCredential()
    client = AgentsClient(endpoint=endpoint, credential=credential)
    
    # Verify agent exists
    try:
        agent = client.get_agent(agent_id)
        print(f"Connected to agent: {agent.name} ({agent.id})")
    except Exception as e:
        print(f"ERROR: Could not find agent '{agent_id}': {e}")
        print("Run 'python setup_agent.py' to create the agent")
        sys.exit(1)
    
    # Run mode
    if args.message:
        response = run_conversation(client, agent_id, args.message)
        print(response)
    else:
        interactive_mode(client, agent_id)


if __name__ == "__main__":
    main()
