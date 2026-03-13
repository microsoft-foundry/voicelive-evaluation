"""
Behavioral tests for VoiceLive Evaluation Agent.
Tests agent decision-making for different dataset types and error scenarios.

Usage:
    python test_agent_behavior.py
    python test_agent_behavior.py --test eval_routing
"""
import argparse
import os
import sys
import time
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from dotenv import load_dotenv

load_dotenv()

DEFAULT_AGENT_NAME = "voicelive-evaluation-agent-cloud"
DEFAULT_ENDPOINT = os.environ.get(
    "PROJECT_ENDPOINT",
    "https://ai-vh7j24h6z2pgw.services.ai.azure.com/api/projects/jagoerge-voicelive-eval-sec"
)


def ask_agent(openai_client, agent_name: str, prompt: str, label: str) -> tuple:
    """Ask the agent a question and return (success, response_text)."""
    print(f"\n{'=' * 60}")
    print(f"TEST: {label}")
    print(f"PROMPT: {prompt}")
    print("=" * 60)
    try:
        resp = openai_client.responses.create(
            input=[{"role": "user", "content": prompt}],
            extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
        )
        text = resp.output_text
        print(f"RESPONSE:\n{text[:600]}")
        if len(text) > 600:
            print(f"  ... ({len(text)} chars total)")
        return True, text
    except Exception as e:
        print(f"ERROR: {e}")
        return False, str(e)


def test_eval_ready_routing(client, agent_name: str) -> tuple:
    """Eval-ready dataset should suggest Foundry-only evaluation (no VoiceLive)."""
    ok, text = ask_agent(
        client, agent_name,
        "I want to evaluate the eval_ready_test dataset. What steps should I take?",
        "Eval-Ready Routing: Should suggest Foundry evaluators directly"
    )
    t = text.lower()
    # Should mention running evaluators directly, not VoiceLive processing
    suggests_foundry = any(w in t for w in ["evaluator", "foundry", "run_voicelive_evaluation", "run evaluation"])
    suggests_voicelive_audio = "run_voicelive_audio_tests" in t or "process audio" in t
    behavior_ok = suggests_foundry and not suggests_voicelive_audio
    print(f"\n  Analysis: suggests_foundry={suggests_foundry}, suggests_audio_processing={suggests_voicelive_audio}")
    print(f"  Behavior: {'CORRECT - Foundry-only path' if behavior_ok else 'NEEDS TUNING - should not suggest audio processing'}")
    return ok, behavior_ok


def test_raw_audio_routing(client, agent_name: str) -> tuple:
    """Raw audio dataset should suggest VoiceLive processing first."""
    ok, text = ask_agent(
        client, agent_name,
        "I want to evaluate the raw_audio_test dataset. What steps should I take?",
        "Raw Audio Routing: Should suggest VoiceLive processing first"
    )
    t = text.lower()
    suggests_voicelive = any(w in t for w in ["voicelive", "audio", "process", "run_voicelive_audio"])
    suggests_pipeline = any(w in t for w in ["then", "after", "followed by", "next", "step"])
    behavior_ok = suggests_voicelive
    print(f"\n  Analysis: suggests_voicelive={suggests_voicelive}, suggests_pipeline={suggests_pipeline}")
    print(f"  Behavior: {'CORRECT - VoiceLive+Foundry pipeline' if behavior_ok else 'NEEDS TUNING - should suggest audio processing'}")
    return ok, behavior_ok


def test_foundry_only_eval(client, agent_name: str) -> tuple:
    """Running evaluation on eval-ready dataset should invoke run_voicelive_evaluation directly."""
    ok, text = ask_agent(
        client, agent_name,
        "Run a fluency evaluation on the eval_ready_test dataset",
        "Foundry-Only Eval: Should start evaluation directly"
    )
    t = text.lower()
    # Should either start the evaluation or describe starting it
    started = any(w in t for w in ["started", "running", "instance_id", "evaluation", "check_evaluation_status"])
    print(f"\n  Analysis: evaluation_started={started}")
    print(f"  Behavior: {'CORRECT - Started Foundry evaluation' if started else 'CHECK - May need review'}")
    return ok, started


def test_results_access(client, agent_name: str) -> tuple:
    """Agent should be able to list evaluation groups and guide to results."""
    ok, text = ask_agent(
        client, agent_name,
        "Show me all evaluation results and groups. Are there any completed evaluations I can analyze?",
        "Results Access: List groups and offer analysis"
    )
    t = text.lower()
    # Should report on groups (even if empty) and mention how to analyze
    acknowledges_state = any(w in t for w in ["no evaluation", "no groups", "empty", "none", "0 evaluation", "groups"])
    print(f"\n  Analysis: acknowledges_state={acknowledges_state}")
    print(f"  Behavior: {'CORRECT' if acknowledges_state else 'CHECK'}")
    return ok, acknowledges_state


def test_missing_dataset_404(client, agent_name: str) -> tuple:
    """Non-existent dataset should get a clear 'not found' error, not a 500."""
    ok, text = ask_agent(
        client, agent_name,
        "Check the schema of the nonexistent_dataset dataset",
        "404 Handling: Should report dataset not found gracefully"
    )
    t = text.lower()
    # Should mention not found, doesn't exist, etc. - not a raw 500 error
    graceful = any(w in t for w in ["not found", "could not find", "doesn't exist", "does not exist", "no dataset", "couldn't find", "unable to find"])
    raw_error = "500" in t or "internal server error" in t
    behavior_ok = graceful or (ok and not raw_error)
    print(f"\n  Analysis: graceful_msg={graceful}, raw_500={raw_error}")
    print(f"  Behavior: {'CORRECT - Graceful 404' if behavior_ok else 'NEEDS FIX - Getting 500 errors'}")
    return ok, behavior_ok


def test_run_raw_audio_eval(client, agent_name: str) -> tuple:
    """Asking to evaluate raw audio dataset should trigger VoiceLive processing."""
    ok, text = ask_agent(
        client, agent_name,
        "Run evaluation on the raw_audio_test dataset with fluency evaluator",
        "Raw Audio Eval: Should process through VoiceLive first or explain why"
    )
    t = text.lower()
    # Should either start VoiceLive processing, ask about config, or explain the audio pipeline
    handles_audio = any(w in t for w in ["voicelive", "audio", "process", "wav", "container app"])
    started_eval = any(w in t for w in ["started", "instance_id", "running"])
    print(f"\n  Analysis: handles_audio={handles_audio}, started_eval={started_eval}")
    if handles_audio:
        print("  Behavior: CORRECT - Recognized audio dataset and mentioned VoiceLive")
    elif started_eval:
        print("  Behavior: PARTIAL - Started eval directly (may work if dataset has query/response)")
    else:
        print("  Behavior: CHECK - Unexpected response")
    return ok, handles_audio or started_eval


# Test registry
TESTS = {
    "eval_routing": test_eval_ready_routing,
    "audio_routing": test_raw_audio_routing,
    "foundry_eval": test_foundry_only_eval,
    "results_access": test_results_access,
    "missing_dataset": test_missing_dataset_404,
    "raw_audio_eval": test_run_raw_audio_eval,
}


def main():
    parser = argparse.ArgumentParser(description="Behavioral tests for VoiceLive Evaluation Agent")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--agent-name", default=DEFAULT_AGENT_NAME)
    parser.add_argument("--test", choices=list(TESTS.keys()) + ["all"], default="all")
    parser.add_argument("--list-tests", action="store_true")
    args = parser.parse_args()

    if args.list_tests:
        print("Available behavioral tests:")
        for name, fn in TESTS.items():
            print(f"  {name}: {fn.__doc__}")
        return

    print(f"Connecting to: {args.endpoint}")
    print(f"Agent: {args.agent_name}")

    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint=args.endpoint, credential=credential) as project_client,
        project_client.get_openai_client() as openai_client,
    ):
        tests_to_run = TESTS if args.test == "all" else {args.test: TESTS[args.test]}
        results = []

        for name, test_fn in tests_to_run.items():
            ok, behavior_ok = test_fn(openai_client, args.agent_name)
            results.append((name, ok, behavior_ok))
            time.sleep(1)  # Rate limit buffer

        # Summary
        print(f"\n{'=' * 60}")
        print("BEHAVIORAL TEST SUMMARY")
        print("=" * 60)
        pass_count = 0
        behavior_count = 0
        for name, ok, behavior_ok in results:
            status = "PASS" if ok else "FAIL"
            behavior = "CORRECT" if behavior_ok else "NEEDS TUNING"
            if ok:
                pass_count += 1
            if behavior_ok:
                behavior_count += 1
            print(f"  {name}: {status} | Behavior: {behavior}")

        print(f"\nTotal: {pass_count}/{len(results)} calls succeeded, {behavior_count}/{len(results)} correct behavior")
        sys.exit(0 if pass_count == len(results) else 1)


if __name__ == "__main__":
    main()
