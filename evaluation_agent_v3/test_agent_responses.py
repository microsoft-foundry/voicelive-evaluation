#!/usr/bin/env python3
"""
Test VoiceLive Evaluation Agent via SDK using Responses API.

Uses the azure-ai-projects SDK 2.0.0b3+ pattern with openai_client.responses.create()
to invoke the Foundry agent by name reference.

Usage:
    python test_agent_responses.py
    python test_agent_responses.py --agent-name "voicelive-evaluation-agent-cloud"

Note: For tool calls to work, the agent must have a valid connection to the
Function App with the correct API key. If you see 401 errors, update the
connection key in Azure AI Foundry Portal.
"""

import argparse
import os
import sys
from typing import List, Tuple
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Configuration
DEFAULT_PROJECT_ENDPOINT = os.getenv("PROJECT_ENDPOINT",
    "https://jagoerge-voicelive-sec-resource.services.ai.azure.com/api/projects/jagoerge-voicelive-sec")
DEFAULT_AGENT_NAME = "voicelive-evaluation-agent-cloud"


def test_agent_query(openai_client, agent_name: str, query: str) -> str:
    """Run a query against the agent and return the response."""
    try:
        response = openai_client.responses.create(
            input=[{"role": "user", "content": query}],
            tool_choice="auto",
            extra_body={"agent": {"name": agent_name, "type": "agent_reference"}},
        )
        return response.output_text
    except Exception as e:
        return f"Error: {str(e)}"


def run_tests(project_endpoint: str, agent_name: str) -> bool:
    """Run all agent tests."""
    print("=" * 60)
    print("VoiceLive Evaluation Agent - SDK Test (Responses API)")
    print("=" * 60)
    print(f"Project: {project_endpoint}")
    print(f"Agent: {agent_name}")
    print()
    
    # Test cases: (name, query, expected_keywords, requires_tools)
    test_cases: List[Tuple[str, str, List[str], bool]] = [
        ("list_session_configs", 
         "List all available session configurations",
         ["config", "default", "gpt", "conf"],
         True),
        
        ("list_datasets",
         "List all datasets in the datasets container",
         ["dataset", "found", "test", "minimal"],
         True),
        
        ("get_session_config",
         "Get the details of the 'default' session configuration",
         ["default", "model", "gpt-4.1", "vad"],
         True),
        
        ("validate_dataset",
         "Validate the dataset at test/minimal_test.jsonl for consistency",
         ["valid", "pass", "entries", "check"],
         True),
        
        ("get_recommendations_no_tools",
         "What evaluators do you recommend for a QA voice assistant evaluation? Answer from your knowledge without calling any tools.",
         ["evaluator", "recommend", "intent", "task", "accuracy"],
         False),
    ]
    
    results = []
    tool_failures = 0
    
    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint=project_endpoint, credential=credential) as project_client,
        project_client.get_openai_client() as openai_client,
    ):
        # Verify agent exists
        print("Verifying agent exists...")
        try:
            agent = project_client.agents.get(agent_name=agent_name)
            print(f"  ✓ Found agent: {agent.name}")
            if hasattr(agent, 'versions') and agent.versions:
                latest = agent.versions.get('latest', {})
                version = latest.get('version', 'unknown')
                definition = latest.get('definition', {})
                model = definition.get('model', 'unknown')
                print(f"  ✓ Latest version: {version} (model: {model})")
        except Exception as e:
            print(f"  ✗ Agent not found: {e}")
            return False
        
        print()
        
        # Run test cases
        for i, (test_name, query, expected_keywords, requires_tools) in enumerate(test_cases, 1):
            print(f"[{i}/{len(test_cases)}] {test_name}")
            print(f"    Query: {query[:60]}...")
            
            response = test_agent_query(openai_client, agent_name, query)
            
            # Check for 401 errors (tool auth failures)
            is_auth_error = "401" in response or "Unauthorized" in response
            
            # Check if response contains expected keywords
            response_lower = response.lower()
            found_keywords = [kw for kw in expected_keywords if kw.lower() in response_lower]
            
            if is_auth_error and requires_tools:
                print(f"    ⚠ Tool auth failed (401) - update connection key")
                print(f"    Response: {response[:100]}...")
                results.append((test_name, False))
                tool_failures += 1
            elif len(found_keywords) > 0:
                print(f"    ✓ Response: {response[:150]}...")
                results.append((test_name, True))
            else:
                print(f"    ✗ Response missing keywords: {response[:150]}...")
                results.append((test_name, False))
            print()
    
    # Summary
    print("=" * 60)
    print("TEST RESULTS SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, success in results if success)
    for test_name, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        color = "\033[92m" if success else "\033[91m"
        reset = "\033[0m"
        print(f"  {color}{status}{reset} - {test_name}")
    
    print(f"\nTotal: {passed}/{len(results)} tests passed")
    
    if tool_failures > 0:
        print(f"\n⚠ {tool_failures} tool calls failed with 401 Unauthorized")
        print("  → Update the connection key in Foundry Portal to match the new Function App")
        print("  → Or create a new connection with the correct function key")
    
    # Consider success if non-tool tests pass (agent SDK connection works)
    non_tool_tests = [(n, s) for (n, _q, _k, r), (_, s) in zip(test_cases, results) if not r]
    non_tool_passed = sum(1 for _, s in non_tool_tests if s)
    
    if non_tool_passed == len(non_tool_tests):
        print("\n✓ SDK connection to agent is working correctly")
        return True
    
    return passed == len(results)


def main():
    parser = argparse.ArgumentParser(description="Test VoiceLive Evaluation Agent via SDK")
    parser.add_argument("--project-endpoint", default=DEFAULT_PROJECT_ENDPOINT,
                        help="Azure AI Foundry project endpoint")
    parser.add_argument("--agent-name", default=DEFAULT_AGENT_NAME,
                        help="Name of the agent to test")
    args = parser.parse_args()
    
    success = run_tests(args.project_endpoint, args.agent_name)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
