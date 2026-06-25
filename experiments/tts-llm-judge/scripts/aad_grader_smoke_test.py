"""
AAD-auth grader smoke test (NO API KEY) on solar-agent-optimizer
(Speech Services - DEV - Speech Analytics), where the signed-in principal
holds the 'Azure AI Developer' role (includes Microsoft.CognitiveServices/
accounts/OpenAI/* -> evals/write).

Proves the RBAC resolution: with the right role, DefaultAzureCredential runs
the score_model grader end-to-end via the Azure Evals API, no key needed.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.ai.evaluation import AzureOpenAIScoreModelGrader, evaluate

ENDPOINT = "https://solar-agent-optimizer.cognitiveservices.azure.com"
DEPLOYMENT = "gpt-4o"
API_VERSION = "2024-12-01-preview"

cred = DefaultAzureCredential(exclude_interactive_browser_credential=True)
MODEL_CONFIG = {
    "azure_endpoint": ENDPOINT,
    "azure_deployment": DEPLOYMENT,
    "api_version": API_VERSION,
}
print(f"[setup] AAD auth (no key)  endpoint={ENDPOINT}  deployment={DEPLOYMENT}")

rows = [
    {"question": "What is 2+2?", "response": "The answer is 4.", "expected": "4"},
    {"question": "What is the capital of France?", "response": "It is Berlin.", "expected": "Paris"},
]
tmp = Path(tempfile.mkdtemp(prefix="aad_grader_"))
data_path = tmp / "smoke.jsonl"
data_path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")

grader = AzureOpenAIScoreModelGrader(
    model_config=MODEL_CONFIG,
    model=DEPLOYMENT,
    name="answer_correctness",
    input=[
        {"role": "system", "content": "Return 1.0 if the response matches the expected answer, else 0.0."},
        {"role": "user", "content": "Question: {{item.question}}\nResponse: {{item.response}}\nExpected: {{item.expected}}"},
    ],
    range=[0.0, 1.0],
    pass_threshold=0.5,
    credential=cred,  # AAD, no api_key in model_config
)

print("[run] evaluate() via AAD ...")
result = evaluate(data=str(data_path), evaluators={"answer_correctness": grader},
                  output_path=str(tmp / "result.json"))

print("\n===== METRICS =====")
print(json.dumps(result.get("metrics", {}), indent=2))
print("\n===== PER-ROW =====")
for i, row in enumerate(result.get("rows", [])):
    print(f"row {i}: score={row.get('outputs.answer_correctness.score')} "
          f"passed={row.get('outputs.answer_correctness.passed')}")
print("\n[done] AAD grader ran end-to-end with no key")
