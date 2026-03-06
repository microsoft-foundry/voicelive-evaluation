# Voice Agent Audio Input Evaluation

Processes pre-recorded audio files through the Azure VoiceLive SDK for evaluation. This is a modern async Python CLI tool that sends WAV audio to an Azure VoiceLive endpoint, collects transcriptions, assistant responses, and tool-call results, and writes structured JSONL output compatible with the Azure AI Evaluation SDK.

## Features

- **Full evaluation pipeline** — VoiceLive audio processing → evaluation JSONL → Azure AI Foundry evaluation run, all in one command
- **PTT and VAD mode support** — choose between server-side Voice Activity Detection (default) or push-to-talk sequencing
- **SDK-pattern tool call handling** — uses `FunctionCallOutputItem` with `previous_item_id` to return results, matching the container-app pattern
- **Multi-turn conversations** — groups audio files by `conversationID` and processes them sequentially within a persistent session
- **Batch processor integration** — compatible with `batch_processor.py` for parallel multi-dataset processing with aggregated evaluation
- **Response audio saving** — saves assistant response audio as WAV files per turn for audio quality review
- **Operational summaries** — generates JSON metrics per run: turns processed, VAD splitting detection, audio response rate
- **Late event drain** — after audio finishes, continues collecting events to capture complete responses and trailing transcriptions
- **Conversation history tracking** — builds full conversation context (system + user + assistant + tool messages) for multi-turn evaluation
- **JSONL evaluation output** — each turn produces a record with `query` (as conversation history list), `response`, `ground_truth`, `tool_calls`, and latency metrics

## Quick Start

### Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | `async`/`await` and `asyncio.TaskGroup` |
| Azure VoiceLive endpoint | Set via `AZURE_VOICELIVE_ENDPOINT` |
| Azure credentials | `DefaultAzureCredential` — Azure CLI login or managed identity |
| Audio files | 16-bit PCM WAV (any sample rate; resampled automatically) |

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

## CLI Arguments

| Argument | Default | Description |
|---|---|---|
| `--test-files`, `-f` | *(required)* | JSONL file listing audio files and metadata |
| `--output-dir`, `-o` | `output/` | Output directory for results and response audio |
| `--evaluation-dir`, `-e` | `None` | Evaluation data directory (defaults to output-dir) |
| `--session-mode` | `per-conversation` | Session handling: `single`, `per-file`, `per-conversation` |
| `--push-to-talk` | `False` | Enable push-to-talk mode instead of VAD |
| `--skip-evaluation` | `False` | Skip running Foundry evaluation after processing |
| `--session-suffix` | `None` | Session suffix for output naming (used by batch_processor) |
| `--aggregate-eval-file` | `None` | Shared JSONL file for batch aggregation |
| `--eval-object-id` | `None` | Existing Foundry eval group ID to reuse |
| `--model` | `gpt-realtime` | VoiceLive model name |
| `--voice` | `en-US-Ava:DragonHDLatestNeural` | Azure TTS voice |
| `--sample-rate` | `24000` | Audio sample rate in Hz |
| `--verbose`, `-v` | `False` | Enable DEBUG logging |
| `--enable-barge-in` | `True` | Enable auto-truncation for barge-in (default) |
| `--disable-barge-in` | | Disable auto-truncation for barge-in |

## Dataset Format

Input is a JSONL file where each line is a JSON object:

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

Azure credentials are resolved via `DefaultAzureCredential` — ensure you are logged in with `az login` or have a managed identity configured.

## Evaluation Integration

When `--skip-evaluation` is **not** set, the script automatically runs Azure AI Foundry evaluation after processing:

1. Writes evaluation-ready JSONL with conversation history context
2. Calls `voice_agent_evaluation.main()` which creates an eval group, uploads dataset, and runs 11 built-in evaluators
3. Polls for completion and outputs per-item scores + aggregate summary

```bash
# Full pipeline: VoiceLive processing + Foundry evaluation
python voice_agent_audio_input_evaluation.py -f dataset.jsonl -o output -e output

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
10. **Batch processor shared file writes** — parallel subprocess workers append to a shared aggregate JSONL file without inter-process locking; unlikely but possible write contention under high parallelism.

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

## Version History

| Version | Description |
|---|---|
| **v3.3** (Current) | Code quality fixes — content_index barge-in fix, empty response placeholder, batch race condition fix (per-process files), path traversal validation, async lock safety, SAS token redaction, float32 WAV support, list-type Answer OR-join |
| **v3.2** | SDK format alignment — tool message flat format (`name`/`tool_call_id`/`arguments` at top level), azure-ai-evaluation 1.15.3, azure-ai-voicelive 1.2.0b4, Foundry UX content validation fixes |
| **v3.1** | Full evaluation pipeline integration, batch processor compatibility, response audio saving, operational summaries, conversation history tracking, .env/CWD fixes |
| **v3** | Full async rewrite with PTT/VAD modes, SDK-pattern `FunctionCallOutputItem` tool calls, late event drain, `asyncio`-native |
| **v2** | VoiceLive SDK integration with threading wrappers |
| **v1** | Original WebSocket-based implementation |
