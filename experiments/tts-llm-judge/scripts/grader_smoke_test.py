"""
Smoke test: AzureOpenAIScoreModelGrader in the VoiceLive eval harness env.

Tier 1 (text plumbing): prove the score_model grader runs end-to-end via
azure.ai.evaluation.evaluate() using the harness's existing judge deployment.
A correct grader should score a right answer ~1.0 and a wrong answer ~0.0.

Mirrors the auth/config wiring in
evaluation_harness/variability_test_output/run_variability.py
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

# Load the harness .env (same file run_variability.py uses)
HARNESS = Path(__file__).resolve().parents[3] / "evaluation_harness"
load_dotenv(HARNESS / ".env", override=True)

JUDGE_DEPLOYMENT = os.environ["AOAI_DEPLOYMENT_NAME"]
PROJECT_ENDPOINT = os.environ["PROJECT_ENDPOINT"]
RESOURCE_HOST = PROJECT_ENDPOINT.split("/api/")[0].rstrip("/")
AOAI_ENDPOINT = RESOURCE_HOST  # AzureOpenAI evaluators accept the AI Services base URL

# Auth: prefer api key if present, else AAD token (matches run_variability.py)
api_key = os.environ.get("AZURE_OPENAI_KEY")
MODEL_CONFIG: dict = {
    "azure_endpoint": AOAI_ENDPOINT,
    "azure_deployment": JUDGE_DEPLOYMENT,
    "api_version": "2024-12-01-preview",
}
grader_credential = None
if api_key:
    MODEL_CONFIG["api_key"] = api_key
    print("[setup] auth=api_key")
else:
    from azure.identity import DefaultAzureCredential

    # The score_model grader requires an explicit TokenCredential (not the
    # AZURE_OPENAI_AD_TOKEN env var that the standard evaluators rely on).
    grader_credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    print("[setup] auth=aad_credential")

print(f"[setup] judge_deployment={JUDGE_DEPLOYMENT}  endpoint={AOAI_ENDPOINT}")

from azure.ai.evaluation import AzureOpenAIScoreModelGrader, evaluate

# Tiny text dataset: row1 correct, row2 wrong
rows = [
    {"question": "What is 2+2?", "response": "The answer is 4.", "expected": "4"},
    {"question": "What is the capital of France?", "response": "It is Berlin.", "expected": "Paris"},
]

tmpdir = Path(tempfile.mkdtemp(prefix="grader_smoke_"))
data_path = tmpdir / "smoke.jsonl"
with data_path.open("w", encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps(r) + "\n")
print(f"[setup] dataset={data_path}")

grader = AzureOpenAIScoreModelGrader(
    model_config=MODEL_CONFIG,
    model=JUDGE_DEPLOYMENT,
    name="answer_correctness",
    input=[
        {
            "role": "system",
            "content": (
                "You grade whether a response correctly answers the question. "
                "Return a float in [0,1]: 1.0 if the response matches the expected "
                "answer, 0.0 if it is wrong."
            ),
        },
        {
            "role": "user",
            "content": (
                "Question: {{item.question}}\n"
                "Response: {{item.response}}\n"
                "Expected: {{item.expected}}"
            ),
        },
    ],
    range=[0.0, 1.0],
    pass_threshold=0.5,
    credential=grader_credential,
)

print("[run] calling evaluate() with the score_model grader ...")
result = evaluate(
    data=str(data_path),
    evaluators={"answer_correctness": grader},
    output_path=str(tmpdir / "result.json"),
)

print("\n===== METRICS =====")
print(json.dumps(result.get("metrics", {}), indent=2))
print("\n===== PER-ROW =====")
for i, row in enumerate(result.get("rows", [])):
    keys = {k: v for k, v in row.items() if "answer_correctness" in k}
    print(f"row {i}: {json.dumps(keys)}")

print(f"\n[done] full result at {tmpdir / 'result.json'}")
