# experiments/tts-llm-judge

Investigation into using a Speech LLM (audio-native `gpt-audio` / GPT-4o-audio) as
the TTS quality judge for voice-agent evaluation, and how it compares to a
purpose-built MOS predictor (DNSMOS / UTMOS).

**Read [`FINDINGS.md`](./FINDINGS.md) first** — it has the full results and the
recommendation.

## Layout

| Path | What |
|------|------|
| `FINDINGS.md` | Write-up: results tables, conclusions, recommendation |
| `clips/` | 9 TTS clips (3 lines x HD / Standard / Degraded) used in the tests |
| `results/tts_sensitivity_results.jsonl` | Raw gpt-audio scores + per-clip reasons |
| `scripts/` | The exact scripts used to produce every number |

## Scripts

| Script | Purpose |
|--------|---------|
| `grader_smoke_test.py` | Text `score_model` grader plumbing via `evaluate()` |
| `audio_grader_smoke_test.py` | Proves the grader LISTENS to a WAV (raw `openai.evals`) |
| `aad_grader_smoke_test.py` | Same grader via `DefaultAzureCredential` (no API key) |
| `tts_sensitivity_demo.py` | Synthesize HD/Standard/Degraded + grade on 3-dim rubric |
| `tts_grade_strict.py` | Re-grade with a strict anchored rubric |
| `tts_pairwise.py` | A/B naturalness test (HD vs Degraded) |
| `tts_dnsmos.py` | DNSMOS P.835/P.808 on the same clips (corroboration) |

## How to run

These are demonstration scripts (not wired into the harness CLI). They use the
harness `.venv` (`azure-ai-evaluation`, `openai`, `requests`) and a `gpt-audio`
deployment.

```powershell
# from repo root, with the harness venv
$env:AZURE_OPENAI_KEY = "<resource key>"   # never commit this
.\.venv\Scripts\python.exe experiments\tts-llm-judge\scripts\tts_dnsmos.py
```

**Auth note:** scripts read the key from the `AZURE_OPENAI_KEY` environment
variable only — no secret is hardcoded or committed. The keyless path
(`aad_grader_smoke_test.py`) uses `DefaultAzureCredential` and requires the
`Azure AI Developer` or `Cognitive Services OpenAI Contributor` role on the
resource (see FINDINGS.md > Auth/RBAC).
