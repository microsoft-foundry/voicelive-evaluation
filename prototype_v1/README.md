# Voice Agent Audio Input Evaluation

Processes pre-recorded audio files through the Azure VoiceLive SDK for evaluation. This is a modern async Python CLI tool that sends WAV audio to an Azure VoiceLive endpoint, collects transcriptions, assistant responses, and tool-call results, and writes structured JSONL output compatible with the Azure AI Evaluation SDK.

## Features

- **PTT and VAD mode support** — choose between server-side Voice Activity Detection (default) or push-to-talk sequencing
- **SDK-pattern tool call handling** — uses `FunctionCallOutputItem` with `previous_item_id` to return results, matching the container-app pattern
- **Multi-turn conversations** — groups audio files by `conversationID` and processes them sequentially within a persistent session
- **Late event drain** — after audio finishes, continues collecting events to capture complete responses and trailing transcriptions
- **JSONL evaluation output** — each turn produces a record with `query`, `response`, `ground_truth`, `tool_calls`, and latency metrics, ready for Azure AI Evaluation SDK

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
| `--output-dir`, `-o` | `output/` | Output directory for evaluation results |
| `--evaluation-dir`, `-e` | `None` | Evaluation data directory (optional) |
| `--session-mode` | `per-conversation` | Session handling: `single`, `per-file`, `per-conversation` |
| `--push-to-talk` | `False` | Enable push-to-talk mode instead of VAD |
| `--model` | `gpt-realtime` | VoiceLive model name |
| `--voice` | `en-US-Ava:DragonHDLatestNeural` | Azure TTS voice |
| `--sample-rate` | `24000` | Audio sample rate in Hz |
| `--verbose`, `-v` | `False` | Enable DEBUG logging |

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

## Output Format

Output is a JSONL file in the output directory. Each line represents one conversation turn:

```json
{
  "query": "What is the weather in Seattle?",
  "response": "The weather in Seattle is sunny with a high of 75°F.",
  "ground_truth": "It is sunny and 75 degrees in Seattle.",
  "context": "",
  "tool_calls": [{"name": "get_weather", "arguments": {"location": "Seattle"}, "result": "{\"temperature\": 72, \"condition\": \"sunny\"}"}],
  "tool_definitions": [{"type": "function", "name": "get_weather", "description": "Get weather", "parameters": {}}],
  "audio_file": "audio/turn1.wav",
  "conversation_id": "conv-001",
  "turn_number": 1,
  "metrics": {
    "transcription_latency_seconds": 0.82,
    "text_response_latency_seconds": 1.45,
    "audio_response_latency_seconds": 1.51
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

| Variable | Required | Description |
|---|---|---|
| `AZURE_VOICELIVE_ENDPOINT` | Yes | WebSocket endpoint for VoiceLive (e.g. `wss://...azure.com`) |
| `AZURE_VOICELIVE_MODEL` | No | Model override (default: `gpt-realtime`) |
| `AZURE_VOICELIVE_API_VERSION` | No | API version override (default: `2025-05-15-preview`) |

Azure credentials are resolved via `DefaultAzureCredential` — ensure you are logged in with `az login` or have a managed identity configured.

## Known Limitations

1. **PTT mode constrained by VoiceLive VAD requirement** — the platform always requires `turn_detection` to be set, so pure PTT (`turn_detection=None`) is not achievable; PTT results may miss some turns.
2. **Tool definitions auto-normalised** — if `tool_definitions` is a `dict` instead of a `list`, it is automatically wrapped in a list.
3. **No built-in evaluation runner** — this script produces evaluation-ready JSONL; use it with the Azure AI Evaluation SDK (or the `evaluation_agent`) to compute quality metrics.
4. **Audio resampling is linear interpolation** — sufficient for speech evaluation but not audiophile-grade.

## Version History

| Version | Description |
|---|---|
| **v3** (Current) | Full async rewrite with PTT/VAD modes, SDK-pattern `FunctionCallOutputItem` tool calls, late event drain, `asyncio`-native |
| **v2** | VoiceLive SDK integration with threading wrappers |
| **v1** | Original WebSocket-based implementation |
