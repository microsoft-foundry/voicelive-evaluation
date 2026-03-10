# VoiceLive Evaluation Framework

## Project Overview

This repository provides evaluation tools for Azure VoiceLive (Speech-to-Speech-to-Text) voice agents. It combines VoiceLive API testing with Azure AI Foundry evaluators to assess voice assistant performance.

**Key Principle:** All Azure API calls use **Azure Identity** (DefaultAzureCredential, Managed Identity) - NO API KEYS unless explicitly required for fallback.

## Setup

```powershell
# From repository root
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

For UltraEval-Audio framework:
```powershell
pip install -r UltraEval-Audio/requirments.txt
```

## Repository Structure

| Directory | Purpose |
|-----------|---------|
| `dataset_validator/` | JSONL dataset validation scripts (consistency + quality checks) |
| `evaluation_agent/` | AI agent for automating evaluation workflows via natural language |
| `evaluation_agent/skills/` | Skill definitions for Copilot CLI and Foundry Agent discovery |
| `evaluation_harness/` | Local standalone evaluation harness — VoiceLive audio processing, batch execution, Foundry evaluation |
| `helper_scripts/` | Utility scripts for dataset preparation, agent creation, and Foundry resource cleanup |
| `UltraEval-Audio/` | **Archived** — External audio evaluation framework, not actively maintained |

## Dataset Validation

**Always validate datasets before running evaluations.** Two-step process:

```bash
# Step 1: Consistency validation (MANDATORY - must pass)
python dataset_validator/validate_dataset_consistency.py dataset.jsonl

# Step 2: Quality validation (ADVISORY - guides improvements)
python dataset_validator/validate_dataset_quality.py dataset.jsonl --strict
```

### Key flags:
- `--strict`: Conservative keyword-only alignment matching
- `--verbose`: Detailed per-conversation breakdown
- `--expected-turns N`: Enforce specific turn count
- `--json output.json`: Export results programmatically

### Dataset JSONL format:
```json
{
  "WavPath": "conversation1-turn1.wav",
  "Question": "User question text",
  "Answer": "Expected answer/ground truth",
  "conversationID": "conversation1",
  "system_prompt": "Agent behavior instructions",
  "tool_definitions": null
}
```

## Running Evaluations

### VoiceLive Audio Evaluation (evaluation_harness)
```bash
python evaluation_harness/voice_agent_audio_input_evaluation.py \
  --test_files_path "datasets/sample.jsonl" \
  --evaluation_dir "output/evaluations"
```

### UltraEval-Audio Framework
```powershell
cd UltraEval-Audio

# Basic evaluation
python audio_evals/main.py \
  --dataset llama-questions \
  --model VoiceLiveS2T \
  --evaluator azure-ai-batch-qaevaluator \
  --post_process passthrough \
  --limit 10

# Using test runner
.\runtest.ps1 -Workers 4 -Limit 10 -TestSuite azure-ai-only
```

### Post-processor selection:
- `passthrough` - Azure AI Foundry evaluators (full JSON access)
- `extract_response` - Text-based evaluators (QA, NLG)
- `extract_transcription` - ASR evaluators (WER, CER)

## Required Environment Variables

```bash
# VoiceLive API
AZURE_VOICELIVE_ENDPOINT="https://your-endpoint.services.ai.azure.com/"
AZURE_VOICELIVE_MODEL="gpt-realtime"

# Azure OpenAI (for evaluators)
AOAI_ENDPOINT="https://your-resource.openai.azure.com/"
AOAI_API_KEY="your-api-key"  # Only if Azure Identity unavailable
AOAI_DEPLOYMENT_NAME="gpt-4.1-mini"

# Azure AI Foundry (optional)
AZURE_AI_PROJECT="https://your-project.services.ai.azure.com/api/projects/your-project"
AZURE_AI_FOUNDRY_UPLOAD="true"
```

## Skills System

The `evaluation_agent/skills/` directory contains skill definitions discoverable by Copilot CLI and Azure Foundry Agent Service:

- `validate-dataset-consistency` - Structural validation (MANDATORY pre-evaluation)
- `validate-dataset-quality` - Content quality checks (ADVISORY)
- `voicelive-audio-evaluation` - VoiceLive API runtime testing

Skills include `when_to_use` metadata for intelligent agent decision-making.

## Cross-Solution Sync Rules

This repo contains two VoiceLive audio processing implementations that must stay aligned:

| Solution | Path | Description |
|----------|------|-------------|
| **evaluation_agent** | `evaluation_agent/` | Cloud-deployed agent with Azure Functions backend |
| **evaluation_harness** | `evaluation_harness/` | Local standalone evaluation harness |

### New Features & Changes
When implementing new features or behavior changes to VoiceLive audio processing in **either** solution:
- **Always ask the user** whether the change should also be applied to the partner solution.
- Do not silently skip the partner — prompt explicitly (e.g., "Should this also be applied to evaluation_harness?").

### Bug Fixes
When fixing a bug in VoiceLive audio processing in **either** solution:
- **Automatically check** whether the same bug exists in the partner solution.
- If it does, **propose a fix** for the partner in the same PR/commit.
- If the partner code is structured differently and the bug doesn't apply, note that explicitly.

### What Counts as VoiceLive Audio Processing
Any change touching: audio sending, silence handling, VAD/PTT mode logic, session lifecycle, conversation turn management, response collection, timeout behavior, or VoiceLive SDK usage.

## Conventions

### Authentication
- Prefer `DefaultAzureCredential` for all Azure service calls
- API keys only as fallback when explicitly documented
- No secrets in code - use environment variables

### File Formats
- Datasets: JSONL (one JSON object per line, NOT JSON array)
- Audio: WAV format (16-bit PCM recommended)
- Results: JSONL with timestamps in filenames

### Error Handling
- Dataset validators return exit code 0 (pass) or 1 (fail)
- Use exit codes in CI/CD: `python validate_*.py dataset.jsonl || exit 1`

### Output Organization
```
res/VoiceLiveS2T/
├── {dataset}/
│   └── {evaluator}/
│       ├── YYYY-MM-DD_HH-MM-SS_{evaluator}.jsonl
│       └── YYYY-MM-DD_HH-MM-SS_{evaluator}-overall.json
```
