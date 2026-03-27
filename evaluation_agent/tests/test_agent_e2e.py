"""
Comprehensive E2E test suite for VoiceLive Evaluation Agent.
Tests all 8 categories: discovery, validation, upload, VoiceLive processing,
evaluation, resource management, results, and edge cases.

Usage:
    python test_agent_e2e.py --test all
    python test_agent_e2e.py --test discovery
    python test_agent_e2e.py --category discovery
    python test_agent_e2e.py --list-tests
"""
import argparse
import os
import sys
import time
from typing import Callable
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from dotenv import load_dotenv

load_dotenv()

DEFAULT_AGENT_NAME = "voicelive-evaluation-agent-cloud"
DEFAULT_ENDPOINT = os.environ.get(
    "PROJECT_ENDPOINT",
    "https://ai-vh7j24h6z2pgw.services.ai.azure.com/api/projects/jagoerge-voicelive-eval-sec"
)

# Rate limit delay between tests (seconds)
RATE_LIMIT_DELAY = 3


def ask_agent(openai_client, agent_name: str, prompt: str, label: str) -> tuple[bool, str]:
    """Send a prompt to the agent and return (success, response_text)."""
    print(f"\n{'-' * 60}")
    print(f"  {label}")
    print(f"  Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}")
    print(f"{'-' * 60}")
    try:
        resp = openai_client.responses.create(
            input=[{"role": "user", "content": prompt}],
            extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
        )
        text = resp.output_text
        preview = text[:500]
        print(f"  Response: {preview}{'...' if len(text) > 500 else ''}")
        return True, text
    except Exception as e:
        print(f"  ERROR: {e}")
        return False, str(e)


def check_response(text: str, must_contain: list[str] = None,
                   must_not_contain: list[str] = None,
                   any_of: list[str] = None) -> tuple[bool, str]:
    """Validate response text against expected patterns."""
    t = text.lower()
    reasons = []

    if must_contain:
        for kw in must_contain:
            if kw.lower() not in t:
                reasons.append(f"missing '{kw}'")
    if must_not_contain:
        for kw in must_not_contain:
            if kw.lower() in t:
                reasons.append(f"unexpected '{kw}'")
    if any_of:
        if not any(kw.lower() in t for kw in any_of):
            reasons.append(f"missing any of {any_of}")

    passed = len(reasons) == 0
    detail = "; ".join(reasons) if reasons else "all checks passed"
    return passed, detail


# --- Category 1: Dataset Discovery & Listing ---------------------

def test_list_all_datasets(client, agent_name: str) -> bool:
    """List all datasets -- should show both blob and Foundry datasets."""
    ok, text = ask_agent(client, agent_name, "List all datasets", "1.1 List All Datasets")
    if not ok:
        return False
    passed, detail = check_response(text, must_contain=["eval_ready_test", "raw_audio_test"])
    print(f"  Check: {detail}")
    return passed


def test_list_voicelive_datasets(client, agent_name: str) -> bool:
    """List only VoiceLive blob datasets."""
    ok, text = ask_agent(
        client, agent_name,
        "List only the VoiceLive audio datasets from blob storage",
        "1.2 List VoiceLive Datasets"
    )
    if not ok:
        return False
    passed, detail = check_response(text, must_contain=["raw_audio_test"])
    print(f"  Check: {detail}")
    return passed


def test_list_evaluation_datasets(client, agent_name: str) -> bool:
    """List only Foundry evaluation datasets."""
    ok, text = ask_agent(
        client, agent_name,
        "List only the evaluation-ready datasets from Foundry data store",
        "1.3 List Evaluation Datasets"
    )
    if not ok:
        return False
    # Should mention Foundry datasets
    passed, detail = check_response(text, must_contain=["eval_ready_test"])
    print(f"  Check: {detail}")
    return passed


# --- Category 2: Dataset Validation ------------------------------

def test_validate_voicelive_dataset(client, agent_name: str) -> bool:
    """Validate a VoiceLive audio dataset (has WavPath/Question/Answer)."""
    ok, text = ask_agent(
        client, agent_name,
        "Validate the raw_audio_test dataset for VoiceLive processing",
        "2.1 Validate VoiceLive Dataset"
    )
    if not ok:
        return False
    passed, detail = check_response(text, must_contain=["valid"])
    print(f"  Check: {detail}")
    return passed


def test_validate_eval_dataset(client, agent_name: str) -> bool:
    """Validate an evaluation-ready dataset (has query/response)."""
    ok, text = ask_agent(
        client, agent_name,
        "Validate the eval_ready_test dataset for evaluation",
        "2.2 Validate Eval-Ready Dataset"
    )
    if not ok:
        return False
    passed, detail = check_response(text, must_contain=["valid"])
    print(f"  Check: {detail}")
    return passed


def test_schema_check(client, agent_name: str) -> bool:
    """Check schema of a dataset."""
    ok, text = ask_agent(
        client, agent_name,
        "Check the schema of the eval_ready_test dataset",
        "2.3 Schema Check"
    )
    if not ok:
        return False
    # Should mention fields like query, response
    passed, detail = check_response(text, must_contain=["query", "response"])
    print(f"  Check: {detail}")
    return passed


def test_validate_nonexistent(client, agent_name: str) -> bool:
    """Validate a dataset that doesn't exist -- should get graceful error."""
    ok, text = ask_agent(
        client, agent_name,
        "Validate the dataset called totally_fake_dataset_xyz",
        "2.4 Validate Nonexistent Dataset"
    )
    # Even if the call succeeded (ok=True), the response should indicate not found
    t = text.lower()
    graceful = any(w in t for w in [
        "not found", "could not find", "doesn't exist", "does not exist",
        "no dataset", "couldn't find", "unable to find", "error"
    ])
    no_500 = "500" not in t and "internal server error" not in t
    passed = graceful and no_500
    print(f"  Check: graceful={graceful}, no_500={no_500}")
    return passed


# --- Category 3: Session Configuration ---------------------------

def test_get_session_config(client, agent_name: str) -> bool:
    """Get details of a specific session config."""
    ok, text = ask_agent(
        client, agent_name,
        "Show me details of the 'default' session configuration",
        "3.1 Get Session Config"
    )
    if not ok:
        return False
    passed, detail = check_response(text, must_contain=["gpt-4.1"], any_of=["24000", "24,000", "24kHz", "24 kHz"])
    print(f"  Check: {detail}")
    return passed


def test_list_configs(client, agent_name: str) -> bool:
    """List session configs -- should return available configs including agent-mode."""
    ok, text = ask_agent(
        client, agent_name,
        "List all session configurations",
        "3.2 List Session Configs"
    )
    if not ok:
        return False
    passed, detail = check_response(text, must_contain=["default", "conf1", "agent-mode"])
    print(f"  Check: {detail}")
    return passed


def test_get_agent_mode_config(client, agent_name: str) -> bool:
    """Get details of the agent-mode session config."""
    ok, text = ask_agent(
        client, agent_name,
        "Show me details of the 'agent-mode' session configuration",
        "3.3 Get Agent Mode Config"
    )
    if not ok:
        return False
    passed, detail = check_response(text, must_contain=["agent-mode"], any_of=["voicelive-demo-agent", "agent", "Foundry"])
    print(f"  Check: {detail}")
    return passed


# --- Category 4: Foundry Evaluation ------------------------------

def test_run_evaluation(client, agent_name: str) -> bool:
    """Start an evaluation with a specific evaluator."""
    ok, text = ask_agent(
        client, agent_name,
        "Run evaluation on eval_ready_test dataset with only fluency evaluator",
        "4.1 Run Evaluation (fluency only)"
    )
    if not ok:
        return False
    passed, detail = check_response(text, must_contain=["evaluation"])
    print(f"  Check: {detail}")
    return passed


def test_get_recommendations(client, agent_name: str) -> bool:
    """Get evaluation recommendations for a dataset."""
    ok, text = ask_agent(
        client, agent_name,
        "What evaluation settings do you recommend for the eval_ready_test dataset?",
        "4.2 Get Evaluation Recommendations"
    )
    if not ok:
        return False
    # Should mention evaluators or recommendations
    t = text.lower()
    has_advice = any(w in t for w in ["recommend", "evaluator", "suggest", "setting"])
    print(f"  Check: has_advice={has_advice}")
    return has_advice


# --- Category 5: Resource Management -----------------------------

def test_list_eval_groups(client, agent_name: str) -> bool:
    """List evaluation groups."""
    ok, text = ask_agent(
        client, agent_name,
        "List all evaluation groups",
        "5.1 List Evaluation Groups"
    )
    if not ok:
        return False
    # Should either list groups or say there are none/some
    t = text.lower()
    has_info = any(w in t for w in ["evaluation group", "eval_", "no evaluation", "0 evaluation", "groups"])
    print(f"  Check: has_info={has_info}")
    return has_info


def test_list_foundry_datasets(client, agent_name: str) -> bool:
    """List Foundry datasets specifically."""
    ok, text = ask_agent(
        client, agent_name,
        "List all Foundry datasets with their versions",
        "5.2 List Foundry Datasets"
    )
    if not ok:
        return False
    passed, detail = check_response(text, must_contain=["version"])
    print(f"  Check: {detail}")
    return passed


def test_list_evaluators(client, agent_name: str) -> bool:
    """List available evaluators."""
    ok, text = ask_agent(
        client, agent_name,
        "What evaluators can I use?",
        "5.3 List Evaluators"
    )
    if not ok:
        return False
    passed, detail = check_response(
        text,
        must_contain=["intent_resolution", "fluency", "relevance"]
    )
    print(f"  Check: {detail}")
    return passed


# --- Category 6: Streaming ---------------------------------------

def test_streaming(client, agent_name: str) -> bool:
    """Verify streaming responses work."""
    print(f"\n{'-' * 60}")
    print(f"  6.1 Streaming Response")
    print(f"{'-' * 60}")
    try:
        stream = client.responses.create(
            stream=True,
            input=[{"role": "user", "content": "List datasets briefly"}],
            extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
        )
        chunks = 0
        for event in stream:
            if event.type == "response.output_text.delta":
                chunks += 1
        print(f"  Received {chunks} streaming chunks")
        return chunks > 0
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


# --- Category 7: Multi-turn Conversation -------------------------

def test_conversation(client, agent_name: str) -> bool:
    """Test multi-turn conversation with context retention."""
    print(f"\n{'-' * 60}")
    print(f"  7.1 Multi-turn Conversation")
    print(f"{'-' * 60}")
    try:
        # Turn 1
        print("  Turn 1: List datasets")
        r1 = client.responses.create(
            input=[{"role": "user", "content": "List all datasets"}],
            extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
        )
        print(f"  Got response ({len(r1.output_text)} chars)")

        time.sleep(RATE_LIMIT_DELAY)

        # Turn 2: Follow-up referencing previous context
        print("  Turn 2: Follow-up about schema")
        r2 = client.responses.create(
            input=[
                {"role": "user", "content": "List all datasets"},
                {"role": "assistant", "content": r1.output_text},
                {"role": "user", "content": "Check the schema of the first eval-ready dataset you listed"},
            ],
            extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
        )
        print(f"  Got response ({len(r2.output_text)} chars)")
        # Should reference a specific dataset from the list
        t2 = r2.output_text.lower()
        has_schema_info = any(w in t2 for w in ["query", "response", "field", "schema", "column"])
        print(f"  Check: has_schema_info={has_schema_info}")
        return has_schema_info
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


# --- Category 8: Edge Cases & Off-Track Prompts ------------------

def test_off_topic(client, agent_name: str) -> bool:
    """Ask something completely unrelated -- should decline gracefully."""
    ok, text = ask_agent(
        client, agent_name,
        "What is the capital of France?",
        "8.1 Off-Topic Question"
    )
    if not ok:
        return False
    # Agent should either redirect to its purpose or provide a brief answer
    # Either way, it shouldn't crash
    t = text.lower()
    redirects = any(w in t for w in ["evaluation", "dataset", "voicelive", "i can help"])
    answers = "paris" in t
    print(f"  Check: redirects={redirects}, answers={answers} (either is acceptable)")
    return redirects or answers  # Must either redirect to purpose or answer the question


def test_ambiguous_request(client, agent_name: str) -> bool:
    """Ambiguous request -- should ask for clarification."""
    ok, text = ask_agent(
        client, agent_name,
        "Run a test",
        "8.2 Ambiguous Request"
    )
    if not ok:
        return False
    t = text.lower()
    asks_clarification = any(w in t for w in [
        "which", "what dataset", "specify", "please provide",
        "could you", "would you", "more information", "clarify"
    ])
    print(f"  Check: asks_clarification={asks_clarification}")
    return asks_clarification  # Should ask for clarification on ambiguous requests


def test_capabilities(client, agent_name: str) -> bool:
    """Ask about agent capabilities."""
    ok, text = ask_agent(
        client, agent_name,
        "What can you do? What are your capabilities?",
        "8.3 Capabilities Query"
    )
    if not ok:
        return False
    t = text.lower()
    mentions_features = sum(1 for w in [
        "dataset", "evaluat", "voicelive", "validat", "config"
    ] if w in t)
    print(f"  Check: mentions {mentions_features}/5 feature areas")
    return mentions_features >= 2


def test_no_polling_promise(client, agent_name: str) -> bool:
    """Agent should not promise to continuously track status."""
    ok, text = ask_agent(
        client, agent_name,
        "Run evaluation on eval_ready_test with fluency only. Track the progress for me and let me know when done.",
        "8.4 No Polling Promise"
    )
    if not ok:
        return False
    t = text.lower()
    # Should NOT promise continuous tracking
    promises_tracking = any(phrase in t for phrase in [
        "i will monitor", "i'll keep checking", "i will track",
        "i'll monitor", "i will check back", "i'll let you know when",
        "i'll track", "i will keep", "let me track",
        "i will follow up automatically", "i'll update you when",
    ])
    suggests_manual = any(phrase in t for phrase in [
        "ask me", "check the status", "check_evaluation_status",
        "let me know when you want", "when you'd like"
    ])
    print(f"  Check: promises_tracking={promises_tracking}, suggests_manual={suggests_manual}")
    return not promises_tracking


# --- Test Registry ------------------------------------------------

CATEGORIES: dict[str, dict[str, Callable]] = {
    "discovery": {
        "list_all": test_list_all_datasets,
        "list_voicelive": test_list_voicelive_datasets,
        "list_eval": test_list_evaluation_datasets,
    },
    "validation": {
        "validate_voicelive": test_validate_voicelive_dataset,
        "validate_eval": test_validate_eval_dataset,
        "schema_check": test_schema_check,
        "validate_missing": test_validate_nonexistent,
    },
    "config": {
        "get_config": test_get_session_config,
        "list_configs": test_list_configs,
        "get_agent_config": test_get_agent_mode_config,
    },
    "evaluation": {
        "run_eval": test_run_evaluation,
        "recommendations": test_get_recommendations,
    },
    "resources": {
        "list_groups": test_list_eval_groups,
        "list_foundry_ds": test_list_foundry_datasets,
        "list_evaluators": test_list_evaluators,
    },
    "streaming": {
        "streaming": test_streaming,
    },
    "conversation": {
        "multi_turn": test_conversation,
    },
    "edge_cases": {
        "off_topic": test_off_topic,
        "ambiguous": test_ambiguous_request,
        "capabilities": test_capabilities,
        "no_polling": test_no_polling_promise,
    },
}

# Flatten for --test access
ALL_TESTS: dict[str, Callable] = {}
for cat_tests in CATEGORIES.values():
    ALL_TESTS.update(cat_tests)


def main():
    parser = argparse.ArgumentParser(
        description="Comprehensive E2E tests for VoiceLive Evaluation Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Categories:
  discovery    - Dataset listing and filtering
  validation   - Dataset validation (VoiceLive, eval-ready, missing)
  config       - Session configuration management
  evaluation   - Foundry evaluation execution
  resources    - Resource management (groups, datasets, evaluators)
  streaming    - Streaming response support
  conversation - Multi-turn conversation
  edge_cases   - Off-topic, ambiguous, capabilities, no-polling
""",
    )
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--agent-name", default=DEFAULT_AGENT_NAME)
    parser.add_argument("--test", help="Run a single test by name")
    parser.add_argument("--category", help="Run all tests in a category")
    parser.add_argument("--list-tests", action="store_true")
    parser.add_argument("--delay", type=int, default=RATE_LIMIT_DELAY,
                        help=f"Delay between tests in seconds (default: {RATE_LIMIT_DELAY})")
    args = parser.parse_args()

    if args.list_tests:
        print("Available tests by category:\n")
        for cat_name, cat_tests in CATEGORIES.items():
            print(f"  {cat_name}:")
            for test_name, test_fn in cat_tests.items():
                print(f"    {test_name}: {test_fn.__doc__}")
            print()
        return

    # Determine which tests to run
    if args.test:
        if args.test == "all":
            tests_to_run = ALL_TESTS
        elif args.test in ALL_TESTS:
            tests_to_run = {args.test: ALL_TESTS[args.test]}
        else:
            print(f"Unknown test: {args.test}")
            print(f"Available: {', '.join(ALL_TESTS.keys())}")
            sys.exit(1)
    elif args.category:
        if args.category in CATEGORIES:
            tests_to_run = CATEGORIES[args.category]
        else:
            print(f"Unknown category: {args.category}")
            print(f"Available: {', '.join(CATEGORIES.keys())}")
            sys.exit(1)
    else:
        tests_to_run = ALL_TESTS

    print(f"Connecting to: {args.endpoint}")
    print(f"Agent: {args.agent_name}")
    print(f"Tests: {len(tests_to_run)} | Delay: {args.delay}s")

    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint=args.endpoint, credential=credential) as project_client,
        project_client.get_openai_client() as openai_client,
    ):
        # Verify agent
        try:
            agent = project_client.agents.get(agent_name=args.agent_name)
            print(f"Agent: {agent.name} (versions: {list(agent.versions.keys()) if agent.versions else 'none'})")
        except Exception as e:
            print(f"ERROR: Agent not found: {e}")
            sys.exit(1)

        results: dict[str, bool] = {}
        category_results: dict[str, list[tuple[str, bool]]] = {}

        for cat_name, cat_tests in CATEGORIES.items():
            cat_results = []
            for test_name, test_fn in cat_tests.items():
                if test_name not in tests_to_run:
                    continue
                # The streaming test gets the openai_client directly
                if test_name in ("streaming", "multi_turn"):
                    passed = test_fn(openai_client, args.agent_name)
                else:
                    passed = test_fn(openai_client, args.agent_name)
                results[test_name] = passed
                cat_results.append((test_name, passed))
                time.sleep(args.delay)
            if cat_results:
                category_results[cat_name] = cat_results

        # Summary
        print(f"\n{'=' * 60}")
        print("  E2E TEST SUMMARY")
        print(f"{'=' * 60}")

        total_pass = 0
        total_fail = 0
        for cat_name, cat_results in category_results.items():
            cat_pass = sum(1 for _, p in cat_results if p)
            cat_total = len(cat_results)
            status = "[OK]" if cat_pass == cat_total else "[!]"
            print(f"\n  {status} {cat_name} ({cat_pass}/{cat_total})")
            for test_name, passed in cat_results:
                icon = "[OK]" if passed else "[X]"
                print(f"     {icon} {test_name}")
                if passed:
                    total_pass += 1
                else:
                    total_fail += 1

        print(f"\n{'-' * 60}")
        print(f"  Total: {total_pass}/{total_pass + total_fail} passed")
        if total_fail > 0:
            print(f"  Failed: {total_fail}")
        print(f"{'=' * 60}")

        sys.exit(0 if total_fail == 0 else 1)


if __name__ == "__main__":
    main()
