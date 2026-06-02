# Voice Agent Audio Input Evaluation

Processes pre-recorded audio files through the Azure VoiceLive SDK for evaluation. This is a modern async Python CLI tool that sends WAV audio to an Azure VoiceLive endpoint, collects transcriptions, assistant responses, and tool-call results, and writes structured JSONL output compatible with the Azure AI Evaluation SDK.

## Features

- **Full evaluation pipeline** — VoiceLive audio processing → evaluation JSONL → Azure AI Foundry evaluation run, all in one command
- **PTT and VAD mode support** — choose between server-side Voice Activity Detection (default) or push-to-talk sequencing
- **Configurable session parameters** — all VoiceLive parameters (model, voice, VAD, EOU, noise reduction, echo cancellation) via CLI args or JSON config file
- **Evaluator selection** — 8 default evaluators aligned with Container App, or select from 13 available with `--evaluators`
- **Config file support** — load session config from JSON with `--config`, CLI args override file values
- **SDK-pattern tool call handling** — uses `FunctionCallOutputItem` with `previous_item_id` to return results, matching the container-app pattern
- **Multi-turn conversations** — groups audio files by `conversationID` and processes them sequentially within a persistent session
- **Batch processor integration** — compatible with `batch_processor.py` for parallel multi-dataset processing with aggregated evaluation
- **Response audio saving** — saves assistant response audio as WAV files per turn for audio quality review
- **Operational summaries** — generates JSON metrics per run: turns processed, VAD splitting detection, audio response rate
- **Late event drain** — after audio finishes, continues collecting events to capture complete responses and trailing transcriptions
- **Conversation history tracking** — builds full conversation context (system + user + assistant + tool messages) for multi-turn evaluation
- **JSONL evaluation output** — each turn produces a record with `query` (as conversation history list), `response`, `ground_truth`, `tool_calls`, and latency metrics
- **Float32 WAV support** — handles IEEE float32 WAV files from HuggingFace datasets alongside standard PCM16
- **List-type Answer handling** — automatically joins list answers with OR for multi-answer datasets

## Quick Start

### Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11+ | `async`/`await`, `asyncio.TaskGroup`, and `numpy>=2.4.6` |
| Azure VoiceLive endpoint | Set via `AZURE_VOICELIVE_ENDPOINT` |
| Azure credentials | `DefaultAzureCredential` — Azure CLI login or managed identity |
| Audio files | 16-bit PCM WAV (any sample rate; resampled automatically) |

> ⚠️ **Before you start — common blockers:**
> - **RBAC roles required:** Your identity needs **Cognitive Services User** on the VoiceLive resource (for API access) AND **Azure AI User** on the Foundry project (for evaluation + agent mode). Missing roles cause silent `403` errors that aren't always obvious.
> - **Region availability:** VoiceLive and the Foundry Evaluations API are only available in select regions. Confirmed working: **Sweden Central**, **East US 2**. Other regions (e.g., `southcentralus`) may fail with no clear error message.
> - **`.env` file location:** The `.env` file must be in the `evaluation_harness/` directory (next to the script), NOT the repo root.

### Install

```bash
pip install -r requirements.txt
```

### Set environment

```bash
export AZURE_VOICELIVE_ENDPOINT="wss://<your-endpoint>.azure.com"
# Optional
export AZURE_VOICELIVE_MODEL="gpt-realtime"
export AZURE_VOICELIVE_API_VERSION="2025-05-15-preview"
```

### Basic run

```bash
python voice_agent_audio_input_evaluation.py -f dataset.jsonl
```

## Audio Processing Modes

### VAD Mode (default)

Server-side Voice Activity Detection automatically detects speech boundaries.

- Audio send and event collection run **concurrently** (`asyncio` tasks)
- Silence keepalive packets maintain the VAD session between utterances
- Late-drain phase captures trailing events after the last audio chunk
- **Best results**: 6/6 queries, 6/6 responses in multi-turn tests

```bash
python voice_agent_audio_input_evaluation.py -f dataset.jsonl
```

### PTT Mode (`--push-to-talk`)

Client sends all audio, then explicitly commits the buffer and requests a response.

- Processing is **sequential**: send audio → commit → `response.create` → collect events
- Prevents race conditions by waiting for each phase to complete
- **Results**: 4/6 queries, 4/6 responses (VoiceLive platform limitation)
- **Known limitation**: `turn_detection=None` is not supported by VoiceLive; the SDK always sets a VAD configuration

```bash
python voice_agent_audio_input_evaluation.py -f dataset.jsonl --push-to-talk
```

### PTT vs VAD Guidance

**VAD mode is recommended for all production evaluations.** PTT mode is experimental and has known platform limitations.

| Aspect | VAD Mode | PTT Mode |
|---|---|---|
| **Audio response rate** | ~100% | ~83% (platform limitation) |
| **Turn detection** | Automatic (semantic VAD) | Client-controlled (commit + response.create) |
| **EOU detection** | Enabled (recommended) | Disabled (prevents premature cutoff) |
| **Barge-in** | Enabled (natural conversation) | Disabled (no concurrent playback) |
| **Best for** | Production evaluation, customer demos | Testing client-controlled scenarios |

#### Why PTT has lower response rates

Voice Live requires a `turn_detection` configuration — `turn_detection=None` is not supported. In PTT mode, the background VAD can interfere with the client's explicit commit/response flow, causing:
- Premature turn finalization before the client commits
- `conversation_already_has_active_response` errors when VAD and PTT both trigger
- Dropped audio responses (~17% of turns affected)

#### PTT configuration strategy

The PTT sample configs use these mitigations:
1. **`server_vad`** instead of semantic VAD — simpler, less aggressive (200ms speech threshold vs 80ms)
2. **`silence_duration_ms: 2000`** — extended silence timeout reduces premature end-of-speech detection
3. **`use_eou_detection: false`** — prevents semantic end-of-utterance from finalizing the turn early
4. **`enable_barge_in: false`** — prevents auto-truncation interference

#### Transcription and punctuation

Voice Live transcription handles punctuation automatically:
- **Cascaded models** (gpt-5, gpt-4.1): Azure Speech STT adds punctuation (periods, commas, question marks) based on speech patterns
- **Real-time models** (gpt-realtime): The model's built-in transcription (e.g., `gpt-4o-transcribe`) handles punctuation
- Evaluation JSONL output includes the transcribed text as-is; the evaluation SDK's GPT-judge evaluators compare semantically, so minor punctuation differences do not affect scores

## CLI Arguments

### Core

| Argument | Default | Description |
|---|---|---|
| `--test-files`, `-f` | — | JSONL file listing audio files and metadata (local path) |
| `--foundry-dataset` | — | Read dataset from Foundry Data Store: `NAME[:VERSION]` |
| `--upload-dataset` | `False` | Upload evaluation results to Foundry after processing |
| `--output-dir`, `-o` | `output/` | Output directory for results and response audio |
| `--evaluation-dir`, `-e` | `None` | Evaluation data directory (defaults to output-dir) |
| `--session-mode` | `per-conversation` | Session handling: `single`, `per-file`, `per-conversation` |
| `--skip-evaluation` | `False` | Skip running Foundry evaluation after processing |
| `--verbose`, `-v` | `False` | Enable DEBUG logging |

> **Note:** One of `--test-files` or `--foundry-dataset` is required. `--foundry-dataset` requires `PROJECT_ENDPOINT` env var.

### VoiceLive Session

| Argument | Default | Description |
|---|---|---|
| `--model` | `gpt-realtime` | VoiceLive model name |
| `--voice` | `en-US-Ava:DragonHDLatestNeural` | Azure TTS voice |
| `--voice-type` | `azure-standard` | Voice type: `azure-standard` or `preset` |
| `--sample-rate` | `24000` | Audio sample rate in Hz |
| `--push-to-talk` | `False` | Enable push-to-talk mode instead of VAD |
| `--enable-barge-in` | `True` | Enable auto-truncation for barge-in (default) |
| `--disable-barge-in` | | Disable auto-truncation for barge-in |
| `--noise-reduction` | `azure_deep_noise_suppression` | Noise reduction type |
| `--echo-cancellation` | `server_echo_cancellation` | Echo cancellation type |
| `--transcription-model` | *(auto)* | Transcription model override (auto: gpt-4o-transcribe for gpt-realtime, azure-speech for gpt-4.1) |

### Turn Detection (VAD)

| Argument | Default | Description |
|---|---|---|
| `--vad-type` | `azure_semantic_vad_multilingual` | VAD type |
| `--vad-threshold` | *(SDK default)* | VAD sensitivity threshold |
| `--silence-duration-ms` | *(SDK default)* | Silence duration for end-of-speech detection |
| `--enable-eou-detection` | `True` | Enable end-of-utterance detection (default) |
| `--disable-eou-detection` | | Disable end-of-utterance detection |
| `--eou-model` | `semantic_detection_v1_multilingual` | EOU detection model |

### Evaluation

| Argument | Default | Description |
|---|---|---|
| `--evaluators` | `default` | Evaluator selection: `default` (8 evaluators), `all` (13), or comma-separated list |
| `--eval-group-by` | `dataset` | Eval group naming strategy: `dataset` (group by dataset name) or `settings` (group by model/voice/VAD config) |
| `--eval-object-id` | `None` | Existing Foundry eval group ID to reuse |

> **Eval group naming:** By default, evaluation runs are grouped by dataset name (e.g., `harness_Eiffel_Tower_Visit_1`), making it easy to compare different VoiceLive configurations on the same dataset within a single Foundry eval group. Use `--eval-group-by settings` for the legacy behavior that groups by model/voice/VAD settings instead.

### Config File

| Argument | Default | Description |
|---|---|---|
| `--config` | `None` | Load session config from a JSON file (CLI args override file values) |
| `--api-key` | `None` | Azure VoiceLive API key (overrides `DefaultAzureCredential`; fallback: `AZURE_VOICELIVE_API_KEY` env var) |

### Batch Processing

| Argument | Default | Description |
|---|---|---|
| `--session-suffix` | `None` | Session suffix for output naming (used by batch_processor) |
| `--aggregate-eval-file` | `None` | Per-process JSONL file for batch aggregation |

### Default Evaluators

> **Note:** Some of the metrics listed below are in **preview** or **experimental**. Score ranges, thresholds, and evaluator behavior may change before general availability.

When `--evaluators default` or unspecified, these 8 evaluators run (aligned with the Container App):

| Evaluator | Category |
|-----------|----------|
| `intent_resolution` | System |
| `task_adherence` | System |
| `task_completion` | System |
| `response_completeness` | System |
| `tool_call_accuracy` | Tool calling |
| `tool_selection` | Tool calling |
| `tool_input_accuracy` | Tool calling |
| `tool_output_utilization` | Tool calling |

Additional evaluators available with `--evaluators all`: `groundedness`, `relevance`, `tool_call_success`, `fluency`, `coherence`.

### Config File Format

Load session configuration from a JSON file with `--config`. CLI args override file values.

```json
{
    "model": "gpt-realtime",
    "voice": "en-US-Andrew:DragonHDLatestNeural",
    "voice_type": "azure-standard",
    "sample_rate": 24000,
    "noise_reduction": "azure_deep_noise_suppression",
    "echo_cancellation": "server_echo_cancellation",
    "vad_type": "azure_semantic_vad_multilingual",
    "use_eou_detection": true,
    "eou_model": "semantic_detection_v1_multilingual",
    "push_to_talk": false,
    "enable_barge_in": true
}
```

The config file uses a flat key format for simplicity. It is conceptually aligned with the Container App's `SessionConfig` options but uses flat keys (e.g., `voice`, `voice_type`) rather than the nested structure from `SessionConfig.to_dict()`. Both flat and nested formats are supported when loading.

### Sample Configs

Pre-built sample configs are available in the `configs/` directory. Use them as starting points for your evaluations:

#### Production-Ready (VAD Mode — Recommended)

| Config File | Model | VAD | EOU | Use Case |
|---|---|---|---|---|
| [`sample_vad_realtime.json`](configs/sample_vad_realtime.json) | `gpt-realtime` | `azure_semantic_vad_multilingual` | ✅ Enabled | Real-time native audio model. Lowest latency, recommended for most evaluations. |
| [`sample_vad_cascaded.json`](configs/sample_vad_cascaded.json) | `gpt-5` | `azure_semantic_vad_multilingual` | ✅ Enabled | Cascaded mode (Azure STT → LLM → Azure TTS). Broader model selection (GPT-5, GPT-4.1, Phi). |

#### Experimental (PTT Mode)

| Config File | Model | VAD | EOU | Use Case |
|---|---|---|---|---|
| [`sample_ptt_realtime.json`](configs/sample_ptt_realtime.json) | `gpt-realtime` | `server_vad` (2000ms silence) | ❌ Disabled | Push-to-talk with real-time model. Client controls speech boundaries. |
| [`sample_ptt_cascaded.json`](configs/sample_ptt_cascaded.json) | `gpt-5` | `server_vad` (2000ms silence) | ❌ Disabled | Push-to-talk with cascaded model. |

> ⚠️ **PTT configs are experimental.** Voice Live does not support `turn_detection=None`, so a VAD configuration is always required even in PTT mode. This causes VAD/PTT interference that can reduce audio response rates (~83% vs 100% for VAD). PTT configs use `server_vad` with an extended 2000ms silence timeout to minimize interference, and disable both EOU detection and barge-in. See [PTT vs VAD Guidance](#ptt-vs-vad-guidance) for details.

#### Other Configs

| Config File | Description |
|---|---|
| `sample_config.json` | Basic model-mode config (gpt-realtime, VAD, EOU) |
| `sample_agent_config.json` | Agent mode config (Foundry Agent integration) |
| `sample_agent_cross_resource_config.json` | Cross-resource agent mode config |
| `canonical_vad_config.json` | Canonical VAD config used for internal eval campaigns |
| `canonical_agent_config.json` | Canonical agent config used for internal eval campaigns |

#### Config Parameter Reference

| Parameter | Type | Default | Description |
|---|---|---|---|
| `model` | string | `gpt-realtime` | VoiceLive model. Options: `gpt-realtime`, `gpt-realtime-mini`, `gpt-5`, `gpt-5-mini`, `gpt-4.1`, `gpt-4.1-mini`, `phi4-mini`, etc. |
| `voice` | string | `en-US-Ava:DragonHDLatestNeural` | Azure TTS voice name. HD voices use the `:DragonHDLatestNeural` suffix. |
| `voice_type` | string | `azure-standard` | Voice type: `azure-standard` (Azure TTS) or `preset` (OpenAI native voices like `alloy`, `echo`). |
| `sample_rate` | int | `24000` | Audio sample rate in Hz. Supported: `16000`, `24000`. |
| `noise_reduction` | string | `azure_deep_noise_suppression` | Noise reduction type. Set to `none` to disable. |
| `echo_cancellation` | string | `server_echo_cancellation` | Echo cancellation type. Set to `none` to disable. |
| `vad_type` | string | `azure_semantic_vad_multilingual` | Turn detection type: `server_vad`, `azure_semantic_vad`, `azure_semantic_vad_multilingual`. |
| `silence_duration_ms` | int | `500` (API default) | Silence duration in ms to detect end of speech. Higher values = less aggressive turn detection. |
| `use_eou_detection` | bool | `true` | Enable semantic end-of-utterance detection. Only supported with non-realtime models (cascaded). |
| `eou_model` | string | `semantic_detection_v1_multilingual` | EOU model: `semantic_detection_v1` (English) or `semantic_detection_v1_multilingual` (10+ languages). |
| `push_to_talk` | bool | `false` | Enable push-to-talk mode (client controls speech boundaries). |
| `enable_barge_in` | bool | `true` | Enable barge-in interruption and auto-truncation. |

## Dataset Format

The harness supports two input dataset formats:

### Legacy Format (WavPath)

JSONL where each line references a local audio file:

```jsonl
{"WavPath": "audio/turn1.wav", "Answer": "expected response", "Question": "What is the weather?", "conversationID": "conv-001", "system_prompt": "You are a helpful assistant.", "tool_definitions": [{"type": "function", "name": "get_weather", "description": "Get weather", "parameters": {"type": "object", "properties": {"location": {"type": "string"}}}}]}
```

| Field | Required | Description |
|---|---|---|
| `WavPath` | Yes | Path to the WAV audio file (absolute or relative to the JSONL file) |
| `Answer` | No | Ground truth answer for evaluation |
| `Question` | No | Text of the question (for logging/output) |
| `conversationID` | No | Groups files into multi-turn conversations (default: `"default"`) |
| `system_prompt` | No | Per-conversation system instruction |
| `tool_definitions` | No | Tool/function definitions to register with the session |
| `barge_in` | No | Mark turns designed to interrupt prior agent response (enables truncation tracking) |

### Foundry Media Format (input_audio)

JSONL using Foundry's `messages` / `expected_output` schema with inline audio. Audio can be provided as **base64 data-URI** (Foundry Portal compatible, supports playback) or **blob storage URL** (smaller JSONL files).

```jsonl
{"messages": [{"role": "system", "content": "You are a helpful assistant."}, {"role": "user", "content": [{"type": "text", "text": "What is the weather?"}, {"type": "input_audio", "input_audio": {"data": "data:audio/wav;base64,UklGR...", "format": "wav"}}]}], "expected_output": "The weather is sunny.", "conversationID": "conv-001"}
```

| Content type | `data` field | Description |
|---|---|---|
| Base64 data-URI | `data:audio/wav;base64,UklGR...` | Inline audio, Foundry Portal playback ✅ |
| Blob storage URL | `https://account.blob.core.windows.net/container/file.wav` | Downloaded via `BlobClient` with `DefaultAzureCredential` |

### Foundry Data Store Integration

Datasets can be read directly from Foundry Data Store and results uploaded back:

```bash
# Read from Foundry (auto-resolves latest version)
python voice_agent_audio_input_evaluation.py --foundry-dataset my_dataset -o output/

# Read specific version + upload results
python voice_agent_audio_input_evaluation.py --foundry-dataset my_dataset:2 -o output/ --upload-dataset
```

## Output Format

### Evaluation JSONL

The evaluation data file uses conversation-history-based `query` format, compatible with Azure AI Foundry evaluators:

```json
{
  "query": [
    {"role": "system", "content": "You are a helpful travel assistant named Tobi."},
    {"role": "user", "content": [{"type": "input_text", "text": "What is the weather?"}]}
  ],
  "response": [{"role": "assistant", "content": "The weather in Seattle is sunny."}],
  "ground_truth": "It is sunny and 75 degrees in Seattle.",
  "tool_calls": [{"type": "tool_call", "tool_call_id": "call_xxx", "name": "get_weather", "arguments": {"location": "Seattle"}}],
  "tool_definitions": [{"type": "function", "name": "get_weather", "description": "Get weather", "parameters": {}}],
  "conversation_id": "conv-001",
  "source_file": "audio/turn1.wav",
  "turn_number": 1,
  "metrics": {
    "logical_turn_number": 1,
    "audio_response_received": true,
    "transcription_latency_seconds": 0.82,
    "text_response_latency_seconds": 1.45,
    "audio_response_latency_seconds": 1.51,
    "tool_call_count": 1
  },
  "barge_in": false,
  "was_truncated": false,
  "response_full": ""
}
```

For multi-turn conversations, subsequent turns include the full conversation history in `query` (system + prior user/assistant/tool messages + current user message).

### Response Audio

Per-turn response audio is saved as WAV files:

```
output_dir/
├── conversation_id/
│   ├── turn_01_response.wav
│   ├── turn_02_response.wav
│   └── turn_03_response.wav
```

### Operational Summary

A JSON summary is written per run with metrics:

```json
{
  "operational_metrics": {
    "turns_processed": "6/6",
    "expected_turns": 6,
    "actual_turns": 6,
    "vad_splitting_detected": false,
    "turn_expansion_factor": 1.0,
    "turns_with_audio_response": 6,
    "turns_with_text_only_response": 0,
    "audio_response_rate": 1.0
  },
  "session_info": {
    "timestamp": "2026-02-19 16:30:20",
    "evaluation_mode": "enabled",
    "session_id": "2026-02-19_16-30-20",
    "session_suffix": "direct-eiffel"
  }
}
```

## Tool Call Handling

Tool calls follow the SDK pattern used by the container-app implementation:

1. The VoiceLive server emits a `function_call` event with a tool name and JSON arguments.
2. The script executes the tool locally via the **tool registry** after `RESPONSE_DONE`.
3. The result is sent back using `FunctionCallOutputItem` with the `previous_item_id` linking it to the original call.

### Built-in tools

| Tool | Description |
|---|---|
| `get_horoscope` | Returns a horoscope for a zodiac sign |
| `fetchWeather` | Returns a fake weather report for a location |
| `get_weather` | Generic weather stub (JSON) |
| `search` | Generic search stub (JSON) |
| `get_time` | Returns current time for a timezone |

Custom tool definitions from the dataset are registered with the session; if the tool name matches a built-in, the built-in implementation is used.

## Session Modes

| Mode | Behaviour |
|---|---|
| `per-conversation` *(default)* | Groups dataset entries by `conversationID`; each conversation runs in its own VoiceLive session with turns processed sequentially |
| `per-file` | Each audio file gets its own independent session |
| `single` | All audio files are processed in a single VoiceLive session |

## Environment Variables

The script loads `.env` from its own directory (next to the script) regardless of where you invoke it from.

| Variable | Required | Description |
|---|---|---|
| `AZURE_VOICELIVE_ENDPOINT` | Yes | WebSocket endpoint for VoiceLive (fallback: `AZURE_VOICE_LIVE_ENDPOINT`) |
| `AZURE_VOICELIVE_MODEL` | No | Model override (default: `gpt-realtime`; fallback: `AZURE_VOICE_LIVE_MODEL`) |
| `AZURE_VOICELIVE_API_VERSION` | No | API version override (fallback: `AZURE_VOICE_LIVE_API_VERSION`) |
| `PROJECT_ENDPOINT` | For eval | Azure AI Foundry project endpoint (required for evaluation runs) |
| `AOAI_DEPLOYMENT_NAME` | For eval | Azure OpenAI deployment for evaluators |
| `AOAI_REASONING_DEPLOYMENT_NAME` | For eval | Reasoning model deployment for evaluators |

### Credential Setup

Authentication uses `DefaultAzureCredential`, which tries credentials in this order:
1. **CLI `--api-key` argument** — highest priority, for quick testing
2. **Environment variables** (`AZURE_VOICELIVE_API_KEY`, or `AZURE_CLIENT_ID`/`AZURE_TENANT_ID`/`AZURE_CLIENT_SECRET`)
3. **Azure CLI** (`az login`) — **recommended for local development**
4. **Managed Identity** — recommended for cloud/CI environments

#### Quick setup (local development)

```bash
# 1. Install Azure CLI (if not already installed)
# Windows: winget install Microsoft.AzureCLI
# macOS: brew install azure-cli

# 2. Sign in
az login

# 3. Ensure your account has the required roles on the Foundry resource:
#    - "Cognitive Services User" (for VoiceLive API access)
#    - "Azure AI User" (for agent mode and Foundry features)

# 4. Create .env file in the evaluation_harness directory
cat > .env << 'EOF'
AZURE_VOICELIVE_ENDPOINT=wss://<your-resource-name>.services.ai.azure.com
AZURE_VOICELIVE_MODEL=gpt-realtime
AZURE_VOICELIVE_API_VERSION=2026-04-10
PROJECT_ENDPOINT=https://<your-resource-name>.services.ai.azure.com/api/projects/<your-project-name>
EOF
```

> 💡 **Finding your endpoint:** In the Azure Portal, navigate to your Foundry resource → **Keys and Endpoint**. The VoiceLive WebSocket endpoint uses `wss://` (not `https://`). The `PROJECT_ENDPOINT` is found in the Foundry Portal under your project's welcome page.

Azure credentials are resolved via `DefaultAzureCredential` — ensure you are logged in with `az login` or have a managed identity configured.

## Evaluation Integration

When `--skip-evaluation` is **not** set, the script automatically runs Azure AI Foundry evaluation after processing:

1. Writes evaluation-ready JSONL with conversation history context
2. Calls `voice_agent_evaluation.main()` which creates an eval group, uploads dataset, and runs evaluators
3. Polls for completion and outputs per-item scores + aggregate summary

Eval groups are named by **dataset** by default (e.g., `harness_Eiffel_Tower_Visit_1`). Run names complement the group — in dataset mode, runs show settings (e.g., `gptrealtime_Ava`); in settings mode, runs show dataset name.

```bash
# Full pipeline: VoiceLive processing + Foundry evaluation (grouped by dataset)
python voice_agent_audio_input_evaluation.py -f dataset.jsonl -o output -e output

# Same dataset, different config — runs land in the same eval group for comparison
python voice_agent_audio_input_evaluation.py -f dataset.jsonl -o output --config configs/sample_ptt_cascaded.json

# Group by settings instead (legacy behavior)
python voice_agent_audio_input_evaluation.py -f dataset.jsonl -o output --eval-group-by settings

# Processing only (skip evaluation)
python voice_agent_audio_input_evaluation.py -f dataset.jsonl --skip-evaluation
```

### Batch Processor Integration

Use `batch_processor.py` for parallel multi-dataset/multi-conversation processing:

```bash
# Process all conversations in parallel, then run one final evaluation
python batch_processor.py -f dataset.jsonl --session-mode per-conversation -o output -e output

# Process multiple datasets from a folder
python batch_processor.py --test-files-folder datasets/ --max-workers 4
```

The batch processor spawns subprocesses that write to a shared aggregated eval JSONL file, then runs a single evaluation on the combined results.

### Interpreting Evaluation Scores

Evaluation scores range from **1-5** (GPT-judge evaluators) or **0/1** (binary evaluators). Here's how to read them:

| Score Range | Interpretation |
|---|---|
| **4.0–5.0** | Strong — response matches ground truth and task requirements |
| **3.0–3.9** | Acceptable — mostly correct with minor gaps |
| **2.0–2.9** | Weak — partial or incomplete response |
| **1.0–1.9** | Poor — incorrect or off-topic response |

**Key factors that affect scores:**
- **Dataset quality matters most.** Datasets with well-written ground truth, specific questions, and matching system prompts score highest. Datasets without ground truth (e.g., open-ended chat) will naturally score lower on factual evaluators.
- **Evaluator variance is expected.** GPT-judge evaluators (task_adherence, task_completion, response_quality) show natural run-to-run variance of ±0.3–0.5 points due to LLM non-determinism. Always run multiple evaluations and average results before drawing conclusions.
- **Distinguish Voice Live issues from evaluator issues.** If transcription is accurate but scores are low, the issue is likely in the evaluator prompt or ground truth — not in Voice Live itself. Check the `response` field in the evaluation JSONL to see what Voice Live actually produced.

### Known Evaluator Issues

> ⚠️ **Some built-in evaluators have known issues that can produce misleading results.** These are being tracked with the Azure AI Evaluation team.

| Evaluator | Issue | Impact | Status |
|---|---|---|---|
| **fluency** / **coherence** | Consistently score 5.0 regardless of actual response quality | Provide no discriminative signal; effectively useless | Consider removing from default set |
| **response_completeness** | Known bug caused misleading completeness scores — VoiceLive.Realtime and GPT-realtime showed unexpected differences despite using the same underlying model | Led to introduction of **Containment Accuracy** as a non-AI validation metric to cross-check results; early Round 1 completeness scores should be treated with caution | Mitigated — use Containment Accuracy alongside response_completeness |
| **All GPT-judge evaluators** | Scores vary across environments (local vs CI vs platform) and drift 1–2% over time due to evaluator LLM non-determinism, graph optimization differences, and upstream Foundry evaluator updates | Run-to-run and environment-to-environment comparisons are unreliable without multiple runs averaged; longitudinal trends may reflect evaluator changes rather than model changes | Known — always average multiple runs and pin evaluator model versions when possible |

**Recommendation:** Focus on **response_quality**, **groundedness**, and **relevance** as primary evaluation metrics. Fluency and coherence can be safely excluded from analysis.

## Known Limitations

1. **PTT mode constrained by VoiceLive VAD requirement** — the platform always requires `turn_detection` to be set, so pure PTT (`turn_detection=None`) is not achievable; PTT results may miss some turns due to `conversation_already_has_active_response` errors.
2. **PTT response rate lower than VAD** — PTT achieves ~50-60% response rate vs VAD's ~90-100% in multi-turn tests. This is a known race condition in the VoiceLive SDK where committing audio can trigger a response before the commit event fully processes.
3. **Tool definitions auto-normalised** — if `tool_definitions` is a `dict` instead of a `list`, it is automatically wrapped in a list.
4. **Audio resampling is linear interpolation** — sufficient for speech evaluation but not audiophile-grade.
5. **Response audio is partial** — `RESPONSE_AUDIO_DELTA` events may not contain the complete response audio; saved WAVs may be smaller than expected compared to real-time playback.
6. **Evaluations API regional availability** — the Foundry Evaluations API is not available in all regions (e.g. `southcentralus`). Ensure `PROJECT_ENDPOINT` points to a supported region (e.g. Sweden Central, East US 2).
7. ~~**No barge-in / interruption handling**~~ — **Implemented** (v1.2.0b4+): auto-truncation enabled by default (`--enable-barge-in`). Tracks `was_truncated`, `response_full`, and `barge_in` in evaluation output.
8. **Evaluation polling has no timeout** — `voice_agent_evaluation.py` polls indefinitely for eval run completion with no maximum attempt cap; a stuck run will block the process.
9. **Evaluation output is pretty-printed JSON** — the `*_eval_output.jsonl` files use `indent=4` formatting, so each record spans multiple lines (not strict one-record-per-line JSONL).
10. ~~**Batch processor shared file writes**~~ — **Fixed**: each subprocess worker writes its own per-process eval JSONL file (no shared file); results are concatenated post-completion via `aggregate_evaluation_files()` in `batch_processor.py`. No inter-process write contention.

## Preparing Test Datasets

Use the helper script to download HuggingFace audio datasets as evaluation-ready JSONL:

```bash
# Download all 3 default TwinkStart datasets
python helper_scripts/hf_dataset_to_jsonl.py

# Download with a sample limit
python helper_scripts/hf_dataset_to_jsonl.py TwinkStart/llama-questions --limit 50

# Then run evaluation
python evaluation_harness/voice_agent_audio_input_evaluation.py -f datasets/TwinkStart-llama-questions/TwinkStart-llama-questions.jsonl
```

### Dataset Requirements

For reliable evaluation results, your dataset should include:

| Field | Required? | Why It Matters |
|---|---|---|
| `WavPath` / `input_audio` | **Yes** | The audio to evaluate — must be clear speech, minimal background noise |
| `Answer` / `expected_output` | **Strongly recommended** | Without ground truth, factual evaluators (groundedness, relevance) have nothing to compare against |
| `Question` | Recommended | Used for logging and output context |
| `system_prompt` | Recommended | Ensures the model's behavior matches your ground truth expectations |
| `conversationID` | For multi-turn | Required to group turns into conversations |
| `tool_definitions` | For tool tests | Required if your scenario involves function calling |

> 💡 **Dataset quality correlates strongly with evaluation scores.** In testing, datasets with specific questions + matching ground truth + aligned system prompts scored 4.0+ on average, while datasets with open-ended questions and no ground truth scored 2.0–3.0 — even with identical Voice Live configurations.

**Always validate datasets before running evaluations:**

```bash
# Step 1: Structural validation (must pass)
python dataset_validator/validate_dataset_consistency.py datasets/TwinkStart-llama-questions/TwinkStart-llama-questions.jsonl

# Step 2: Quality validation (advisory)
python dataset_validator/validate_dataset_quality.py datasets/TwinkStart-llama-questions/TwinkStart-llama-questions.jsonl --strict
```

See [`helper_scripts/README.md`](../helper_scripts/README.md) for full CLI options, default datasets, and troubleshooting (FFmpeg, HF auth, dataset discovery). See [`dataset_validator/README.md`](../dataset_validator/README.md) for validation details.

## Troubleshooting

### FFmpeg Required for Audio Decoding

Some HuggingFace datasets store audio in formats that require FFmpeg:
```bash
choco install ffmpeg   # Windows
brew install ffmpeg    # macOS
```

### Debug Mode

Enable verbose logging to diagnose audio processing or evaluation issues:
```bash
python voice_agent_audio_input_evaluation.py -f dataset.jsonl --verbose
```

## Agent Mode (Foundry Agent Integration)

VoiceLive supports connecting to a Foundry Agent instead of a direct model deployment. In agent mode, the agent manages its own instructions, tools, and voice settings — the evaluation pipeline sends minimal session configuration.

### Quick Start

```bash
# Using CLI arguments
python evaluation_harness/voice_agent_audio_input_evaluation.py \
  -f datasets/sample.jsonl -o output \
  --agent-name voicelive-demo-agent \
  --project-name your-project-name

# Using config file
python evaluation_harness/voice_agent_audio_input_evaluation.py \
  -f datasets/sample.jsonl -o output \
  --config sample_agent_config.json

# Using environment variables
export AGENT_NAME=voicelive-demo-agent
export PROJECT_NAME=your-project-name
python evaluation_harness/voice_agent_audio_input_evaluation.py \
  -f datasets/sample.jsonl -o output
```

### Agent Mode CLI Arguments

| Argument | Env Variable | Description |
|----------|-------------|-------------|
| `--agent-name` | `AGENT_NAME` | Foundry agent name (enables agent mode) |
| `--project-name` | `PROJECT_NAME` | Foundry project name (required for agent mode) |
| `--agent-version` | `AGENT_VERSION` | Pin to specific agent version (default: latest) |
| `--foundry-resource-override` | `FOUNDRY_RESOURCE_OVERRIDE` | Cross-resource agent connection |
| `--agent-auth-identity-client-id` | `AGENT_AUTHENTICATION_IDENTITY_CLIENT_ID` | Managed identity for cross-resource auth |

### Agent Mode Config File

See `sample_agent_config.json` for a complete example. The `"agent"` section enables agent mode:

```json
{
  "agent": {
    "agent_name": "voicelive-demo-agent",
    "project_name": "your-project-name"
  }
}
```

Voice, VAD, and audio settings are optional overrides — if omitted, the agent's built-in settings apply.

### Agent Testing Best Practices

> 💡 **Use prompt-matched agents for accurate evaluation.** When testing with an agent, ensure the agent's system prompt matches the expected behavior in your dataset. A generic agent (e.g., "You are a helpful assistant") will score lower on task-specific evaluators — not because of Voice Live quality issues, but because the agent's instructions don't align with the ground truth.

**Recommended approach:**
1. Create a **dedicated test agent** in the Foundry portal with a system prompt that matches your dataset's expected behavior
2. Include relevant `tool_definitions` in the agent if your dataset expects tool calls
3. Pin the agent version with `--agent-version` for reproducible results
4. Compare agent mode scores against a baseline direct-model run with the same dataset to isolate agent routing overhead (~1s additional latency expected)

### Config Transparency

> ℹ️ **Agent Mode Config Transparency**: In agent mode, the evaluation pipeline captures the **effective session configuration** returned by VoiceLive in the `SESSION_UPDATED` event. This includes the agent name, description, agent ID, voice settings (name, type, temperature), and thread ID. These are logged and included in evaluation output for traceability. However, some internal agent settings (e.g., full system prompt text, tool definitions, model parameters) may not be fully surfaced in this event. For complete configuration visibility, also review your agent's settings in the [Foundry portal](https://ai.azure.com).

### Authentication

Agent mode requires Microsoft Entra ID authentication (`DefaultAzureCredential`). API key authentication is not supported for agent invocation. Ensure your identity has the `Azure AI User` role on the Foundry project.

#### Cross-Resource Agent Connections

When the Foundry agent is hosted on a **different resource** than the VoiceLive endpoint, use cross-resource configuration:

```bash
# Cross-resource via CLI
python evaluation_harness/voice_agent_audio_input_evaluation.py \
  -f datasets/sample.jsonl -o output \
  --agent-name VoiceAgentwBingWebSearch \
  --project-name jagoerge-voicelive-sec \
  --agent-version 14 \
  --foundry-resource-override jagoerge-voicelive-sec-resource

# Cross-resource via config file
python evaluation_harness/voice_agent_audio_input_evaluation.py \
  -f datasets/sample.jsonl -o output \
  --config sample_agent_cross_resource_config.json
```

**Cross-resource prerequisites:**
1. The VoiceLive resource's managed identity must have the `Azure AI User` role on the target agent's Foundry resource
2. Set `--foundry-resource-override` to the Foundry resource name (not the full URL)
3. Set `--agent-auth-identity-client-id` to the VoiceLive resource's managed identity client ID (required for cross-resource auth)

See `sample_agent_cross_resource_config.json` for a complete example.

## Version History

| Version | Description |
|---|---|
| **v3.6** (Current) | Dataset-based eval grouping — `--eval-group-by {dataset,settings}` flag (default: `dataset`), complementary run names (settings when grouped by dataset, dataset when grouped by settings), `_short_voice_name()` for readable Azure voice identifiers, agent naming unit tests |
| **v3.5** | Sample configs + documentation — PTT/VAD sample configs (4 configs: VAD realtime, VAD cascaded, PTT realtime, PTT cascaded), config parameter reference table, PTT vs VAD guidance section, credential setup guide, punctuation handling notes |
| **v3.4** | Feature parity with Container App — 12 new CLI args for session config (noise reduction, echo cancellation, VAD, EOU, transcription model, voice type), `--evaluators` arg (default/all/custom), `--config` JSON file support, 8 default evaluators aligned with Container App, sample_config.json |
| **v3.3** | Code quality fixes — content_index barge-in fix, empty response placeholder, batch race condition fix (per-process files), path traversal validation, async lock safety, SAS token redaction, float32 WAV support, list-type Answer OR-join |
| **v3.2** | SDK format alignment — tool message flat format (`name`/`tool_call_id`/`arguments` at top level), azure-ai-evaluation 1.15.3, azure-ai-voicelive 1.2.0b4, Foundry UX content validation fixes |
| **v3.1** | Full evaluation pipeline integration, batch processor compatibility, response audio saving, operational summaries, conversation history tracking, .env/CWD fixes |
| **v3** | Full async rewrite with PTT/VAD modes, SDK-pattern `FunctionCallOutputItem` tool calls, late event drain, `asyncio`-native |
| **v2** | VoiceLive SDK integration with threading wrappers |
| **v1** | Original WebSocket-based implementation |
