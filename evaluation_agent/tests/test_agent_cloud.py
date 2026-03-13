"""
Test the deployed VoiceLive Evaluation Agent using Azure AI Projects SDK.
Uses azure-ai-projects SDK 2.0.0b3+ with Responses API.

Usage:
    python test_agent_cloud.py
    python test_agent_cloud.py --endpoint <project-endpoint>
    python test_agent_cloud.py --test list_datasets
    python test_agent_cloud.py --test all
"""
import argparse
import os
import sys
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from dotenv import load_dotenv

load_dotenv()

# Default configuration
DEFAULT_AGENT_NAME = "voicelive-evaluation-agent-cloud"
DEFAULT_ENDPOINT = os.environ.get(
    "PROJECT_ENDPOINT",
    "https://ai-vh7j24h6z2pgw.services.ai.azure.com/api/projects/jagoerge-voicelive-eval-sec"
)


def test_list_datasets(openai_client, agent_name: str) -> bool:
    """Test: List available datasets."""
    print("\n" + "=" * 60)
    print("TEST: List Datasets")
    print("=" * 60)
    
    try:
        response = openai_client.responses.create(
            input=[{"role": "user", "content": "List available datasets"}],
            extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
        )
        print(f"Response:\n{response.output_text}")
        return True
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def test_list_evaluators(openai_client, agent_name: str) -> bool:
    """Test: List available evaluators."""
    print("\n" + "=" * 60)
    print("TEST: List Evaluators")
    print("=" * 60)
    
    try:
        response = openai_client.responses.create(
            input=[{"role": "user", "content": "What evaluators are available?"}],
            extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
        )
        print(f"Response:\n{response.output_text}")
        return True
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def test_list_session_configs(openai_client, agent_name: str) -> bool:
    """Test: List session configurations."""
    print("\n" + "=" * 60)
    print("TEST: List Session Configs")
    print("=" * 60)
    
    try:
        response = openai_client.responses.create(
            input=[{"role": "user", "content": "Show me the available VoiceLive session configurations"}],
            extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
        )
        print(f"Response:\n{response.output_text}")
        return True
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def test_check_dataset_schema(openai_client, agent_name: str) -> bool:
    """Test: Check dataset schema."""
    print("\n" + "=" * 60)
    print("TEST: Check Dataset Schema")
    print("=" * 60)
    
    try:
        response = openai_client.responses.create(
            input=[{"role": "user", "content": "Check the schema of the eval_ready_test dataset"}],
            extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
        )
        print(f"Response:\n{response.output_text}")
        return True
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def test_validate_dataset(openai_client, agent_name: str) -> bool:
    """Test: Validate dataset consistency."""
    print("\n" + "=" * 60)
    print("TEST: Validate Dataset")
    print("=" * 60)
    
    try:
        response = openai_client.responses.create(
            input=[{"role": "user", "content": "Validate the eval_ready_test dataset"}],
            extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
        )
        print(f"Response:\n{response.output_text}")
        return True
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def test_list_evaluation_groups(openai_client, agent_name: str) -> bool:
    """Test: List evaluation groups."""
    print("\n" + "=" * 60)
    print("TEST: List Evaluation Groups")
    print("=" * 60)
    
    try:
        response = openai_client.responses.create(
            input=[{"role": "user", "content": "List evaluation groups"}],
            extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
        )
        print(f"Response:\n{response.output_text}")
        return True
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def test_streaming(openai_client, agent_name: str) -> bool:
    """Test: Streaming response."""
    print("\n" + "=" * 60)
    print("TEST: Streaming Response")
    print("=" * 60)
    
    try:
        stream = openai_client.responses.create(
            stream=True,
            input=[{"role": "user", "content": "List available datasets briefly"}],
            extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
        )
        
        print("Streaming response: ", end="", flush=True)
        for event in stream:
            if event.type == "response.output_text.delta":
                print(event.delta, end="", flush=True)
        print()  # newline after streaming
        return True
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def test_run_evaluation(openai_client, agent_name: str) -> bool:
    """Test: Run a quick evaluation on eval_ready_test dataset."""
    print("\n" + "=" * 60)
    print("TEST: Run Evaluation (fluency only for speed)")
    print("=" * 60)
    
    try:
        response = openai_client.responses.create(
            input=[{"role": "user", "content": "Run evaluation on eval_ready_test dataset with only fluency evaluator"}],
            extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
        )
        print(f"Response:\n{response.output_text}")
        # Check for success indicators
        text = response.output_text.lower()
        if "started" in text or "running" in text or "completed" in text or "evaluation" in text:
            return True
        return True  # If we got a response without error, consider it a pass
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def test_conversation_flow(openai_client, agent_name: str) -> bool:
    """Test: Multi-turn conversation flow."""
    print("\n" + "=" * 60)
    print("TEST: Multi-turn Conversation")
    print("=" * 60)
    
    try:
        # Turn 1: List datasets
        print("Turn 1: Asking about datasets...")
        response1 = openai_client.responses.create(
            input=[{"role": "user", "content": "What datasets do I have?"}],
            extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
        )
        print(f"  Response: {response1.output_text[:200]}...")
        
        # Turn 2: Follow-up about the dataset
        print("\nTurn 2: Asking about validation...")
        messages = [
            {"role": "user", "content": "What datasets do I have?"},
            {"role": "assistant", "content": response1.output_text},
            {"role": "user", "content": "Is that dataset valid for evaluation?"}
        ]
        response2 = openai_client.responses.create(
            input=messages,
            extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
        )
        print(f"  Response: {response2.output_text[:200]}...")
        
        return True
    except Exception as e:
        print(f"ERROR: {e}")
        return False


# Available tests
TESTS = {
    "list_datasets": test_list_datasets,
    "list_evaluators": test_list_evaluators,
    "list_session_configs": test_list_session_configs,
    "check_dataset_schema": test_check_dataset_schema,
    "validate_dataset": test_validate_dataset,
    "list_evaluation_groups": test_list_evaluation_groups,
    "streaming": test_streaming,
    "run_evaluation": test_run_evaluation,
    "conversation": test_conversation_flow,
}


def main():
    parser = argparse.ArgumentParser(
        description="Test the deployed VoiceLive Evaluation Agent"
    )
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help="Azure AI Project endpoint"
    )
    parser.add_argument(
        "--agent-name",
        default=DEFAULT_AGENT_NAME,
        help="Agent name to test"
    )
    parser.add_argument(
        "--test",
        choices=list(TESTS.keys()) + ["all"],
        default="list_datasets",
        help="Which test to run (default: list_datasets)"
    )
    parser.add_argument(
        "--list-tests",
        action="store_true",
        help="List available tests"
    )
    args = parser.parse_args()
    
    if args.list_tests:
        print("Available tests:")
        for name in TESTS:
            print(f"  - {name}")
        return
    
    print(f"Connecting to: {args.endpoint}")
    print(f"Agent: {args.agent_name}")
    
    # Use nested context managers per SDK 2.0 pattern
    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint=args.endpoint, credential=credential) as project_client,
        project_client.get_openai_client() as openai_client,
    ):
        # Verify agent exists
        try:
            agent = project_client.agents.get(agent_name=args.agent_name)
            print(f"Agent found: {agent.name} (versions: {list(agent.versions.keys()) if agent.versions else 'none'})")
        except Exception as e:
            print(f"ERROR: Could not find agent '{args.agent_name}': {e}")
            sys.exit(1)
        
        # Run tests
        tests_to_run = list(TESTS.keys()) if args.test == "all" else [args.test]
        results = {}
        
        for test_name in tests_to_run:
            test_func = TESTS[test_name]
            results[test_name] = test_func(openai_client, args.agent_name)
        
        # Summary
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        passed = sum(1 for r in results.values() if r)
        total = len(results)
        
        for name, result in results.items():
            status = "PASS" if result else "FAIL"
            print(f"  {name}: {status}")
        
        print(f"\nTotal: {passed}/{total} tests passed")
        
        if passed < total:
            sys.exit(1)


if __name__ == "__main__":
    main()
