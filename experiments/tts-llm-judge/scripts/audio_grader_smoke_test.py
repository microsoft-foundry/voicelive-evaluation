"""
Audio grader smoke test (raw openai.evals path) in the VL harness env.

Goal: prove an Azure score_model grader can LISTEN to a real WAV (via
input_audio) and score it, not just grade a transcript.

Design (discrimination test, no sampling step):
  - The grader model is `gpt-audio` (audio-completions, just deployed).
  - Each dataset row carries base64 WAV + an `expected` phrase.
  - The grader hears the clip and returns 1.0 if it matches `expected`, else 0.0.

Rows:
  A) Eiffel_Tower_Visit-0001.wav  (spoken: "Good morning.")   expected="a morning greeting"  -> expect HIGH
  B) Eiffel_Tower_Visit-0003.wav  (spoken: "I am an Aquarius") expected="a morning greeting"  -> expect LOW

If A scores ~1.0 and B scores ~0.0, the grader genuinely heard the audio.
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import AzureOpenAI

HARNESS = Path(__file__).resolve().parents[3] / "evaluation_harness"
load_dotenv(HARNESS / ".env", override=True)

PROJECT_ENDPOINT = os.environ["PROJECT_ENDPOINT"]
RESOURCE_HOST = PROJECT_ENDPOINT.split("/api/")[0].rstrip("/")
GRADER_MODEL = "gpt-audio"  # deployment name just created
API_VERSION = "2025-04-01-preview"

api_key = os.environ["AZURE_OPENAI_KEY"]  # passed via env at runtime
client = AzureOpenAI(azure_endpoint=RESOURCE_HOST, api_key=api_key, api_version=API_VERSION)
print(f"[setup] endpoint={RESOURCE_HOST}  grader_model={GRADER_MODEL}  api={API_VERSION}")

SAMPLES = HARNESS / "sample_evaluation_input" / "Eiffel_Tower_Visit_1"


def b64(wav_name: str) -> str:
    return base64.b64encode((SAMPLES / wav_name).read_bytes()).decode("ascii")


rows = [
    {"audio_base64": b64("Eiffel_Tower_Visit-0001.wav"), "expected": "a morning greeting"},
    {"audio_base64": b64("Eiffel_Tower_Visit-0003.wav"), "expected": "a morning greeting"},
]
print(f"[setup] {len(rows)} audio rows encoded")

# 1) Eval: schema + audio score_model grader that LISTENS to item audio
data_source_config = {
    "type": "custom",
    "item_schema": {
        "type": "object",
        "properties": {
            "audio_base64": {"type": "string"},
            "expected": {"type": "string"},
        },
        "required": ["audio_base64", "expected"],
    },
    "include_sample_schema": False,  # no generation step; grade item audio directly
}

grader = {
    "type": "score_model",
    "name": "audio_content_fidelity",
    "model": GRADER_MODEL,
    "input": [
        {
            "role": "system",
            "content": (
                'You listen to an audio clip and judge whether what is spoken '
                'matches the expected description. Respond ONLY with JSON '
                '{"result": <float 0..1>} where 1.0 = clearly matches, 0.0 = clearly does not.'
            ),
        },
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Expected: {{item.expected}}. Listen and score the match."},
                {"type": "input_audio", "input_audio": {"data": "{{item.audio_base64}}", "format": "wav"}},
            ],
        },
    ],
    "range": [0, 1],
    "pass_threshold": 0.5,
}

print("[run] creating eval ...")
eval_obj = client.evals.create(
    name="VL audio grader smoke",
    data_source_config=data_source_config,
    testing_criteria=[grader],
)
print(f"[run] eval id={eval_obj.id}")

# 2) Run over the in-line audio rows (jsonl/file_content, no sampling)
run = client.evals.runs.create(
    eval_id=eval_obj.id,
    name="audio-smoke-run",
    data_source={
        "type": "jsonl",
        "source": {"type": "file_content", "content": [{"item": r} for r in rows]},
    },
)
print(f"[run] run id={run.id}  status={run.status}")

# 3) Poll
for _ in range(60):
    run = client.evals.runs.retrieve(run_id=run.id, eval_id=eval_obj.id)
    if run.status in {"completed", "failed"}:
        break
    time.sleep(5)
    print(f"   ... {run.status}")

print(f"\n[run] final status={run.status}")
print(f"[run] result counts: {getattr(run, 'result_counts', None)}")
print(f"[run] report_url: {getattr(run, 'report_url', None)}")

print("\n===== PER-ROW =====")
items = list(client.evals.runs.output_items.list(run_id=run.id, eval_id=eval_obj.id))
for i, it in enumerate(items):
    results = getattr(it, "results", None)
    print(f"row {i}: {json.dumps(results, default=str)}")

client.evals.delete(eval_id=eval_obj.id)
print("\n[done] eval cleaned up")
