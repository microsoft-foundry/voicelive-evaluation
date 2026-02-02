# Voice Agent Audio Input Evaluation

This prototype provides automated evaluation capabilities for Azure Voice Live API agents, processing audio files and generating comprehensive evaluation data for use with Azure AI Evaluation SDK.

## Version History

| Version | Script | Description |
|---------|--------|-------------|
| **Current** | `voice_agent_audio_input_evaluation.py` + `voice_agent_evaluation.py` | Latest version using the new Azure Evaluations implementation leveraging the OpenAI Evals SDK |
| Legacy | `old_prototypes/voice_agent_audio_input_evaluation_v*.py` + `old_prototypes/voice_agent_evaluation_v*.py` | Old versions kept for reference |

> **Note:** Legacy scripts are kept in `old_prototypes/` for reference. New projects should use the current implementation.

## Overview

The `voice_agent_audio_input_evaluation.py` script enables you to:
- Send pre-recorded audio files to Azure Voice Live API using the **Azure VoiceLive SDK** (`azure-ai-voicelive`)
- Capture agent responses (text and audio)
- Generate evaluation data in JSONL format compatible with Azure AI Evaluation SDK
- Track operational metrics including latency, tool usage, and VAD behavior
- Support single, per-file, and per-conversation session modes
- Automatically run evaluations after session completion

> **Note:** As of December 2025, this script uses the official Azure VoiceLive SDK (`azure-ai-voicelive>=1.1.0`) for improved stability and Windows compatibility.

## Features

### Core Capabilities
- **Multi-turn conversations**: Process multiple audio files in sequence, maintaining conversation context
- **Tool calling support**: Track and evaluate tool/function calls made by the agent with automatic tool execution
- **VAD (Voice Activity Detection) handling**: Automatically detects when silence in audio causes turn splitting
- **Metadata alignment**: Ensures ground truth, expected tool calls, and tool definitions align correctly with agent responses via snapshot mechanism
- **Three session modes**: Single session (all files in one conversation), per-file (isolated sessions), or per-conversation (grouped by conversationID)
- **Custom system prompts**: Override default system prompt per-conversation using the `system_prompt` field in JSONL
- **Operational metrics**: Comprehensive tracking of response latencies, turn counts, and audio response rates
- **Automatic evaluation**: Runs Azure AI Evaluation SDK evaluators after session completion

### Evaluation Integration
Generates evaluation data compatible with Azure AI Evaluation SDK evaluators:
- `IntentResolutionEvaluator`: Measures how well the agent identifies correct intent from user query (Scale: 1-5)
- `TaskAdherenceEvaluator`: Measures adherence to task based on system message (Scale: 1-5)
- `TaskCompletionEvaluator`: Measures if the agent completed the task (Scale: 1-5)
- `ResponseCompletenessEvaluator`: Assesses how completely the response addresses the query using ground truth (Scale: 1-5)
- `ToolCallAccuracyEvaluator`: Uses LLM-as-judge to assess if actual tool calls were appropriate (Scale: 1-5)
- `ToolSelectionEvaluator`: Evaluates if the correct tools were selected (Scale: 1-5)
- `ToolInputAccuracyEvaluator`: Evaluates accuracy of tool input parameters (Scale: 1-5)
- `ToolOutputUtilizationEvaluator`: Evaluates how well tool outputs were used (Scale: 1-5)
- `GroundednessEvaluator`: Measures if responses are grounded in provided context
- `RelevanceEvaluator`: Measures response relevance to the query

## Azure VoiceLive SDK

As of December 2025, this prototype uses the official **Azure VoiceLive SDK** (`azure-ai-voicelive`) instead of a custom WebSocket implementation. This provides:

- **Improved stability**: Official SDK handles connection management, reconnection, and error handling
- **Windows compatibility**: Better support for Windows environments (no websocket-client threading issues)
- **Type safety**: Strongly-typed models for audio formats, transcription options, and events
- **Future-proof**: SDK updates automatically bring new features and fixes

### SDK Imports

The script uses these key imports from the SDK:

```python
from azure.ai.voicelive.aio import connect as voicelive_connect
from azure.ai.voicelive.models import (
    ServerEventType,
    RequestSession,
    ServerVad,
    AzureSemanticVadMultilingual,
    AzureStandardVoice,
    Modality,
    InputAudioFormat,
    OutputAudioFormat,
    AudioInputTranscriptionOptions,
    AudioNoiseReduction,
    AudioEchoCancellation,
    EouDetection,
)
```

### Connection Pattern

```python
# SDK-based connection (current implementation)
async with voicelive_connect(
    endpoint=endpoint,
    credential=credential,
    model=model
) as connection:
    # Send session configuration
    await connection.send(session_update)
    # Send audio and receive events
    ...
```

> **Note:** The legacy `websocket-client` package is kept in requirements for backward compatibility but is no longer the primary connection method.

## Session Parameters

The VoiceLive session is configured with several parameters that control audio processing, turn detection, voice output, and transcription. These are set in the `session_config` dictionary.

### Turn Detection

Turn detection determines when the user has finished speaking and the agent should respond. The framework supports two modes:

```python
turn_detection = {
    "type": "azure_semantic_vad_multilingual",  # or "server_vad"
    "threshold": 0.3,              # Voice activity detection threshold (0.0-1.0)
    "prefix_padding_ms": 300,      # Audio to include before detected speech start
    "speech_duration_ms": 80,      # Minimum speech duration to trigger detection
    "silence_duration_ms": 500,    # Silence duration to end turn
    "remove_filler_words": True,   # Remove "um", "uh", etc.
    "interrupt_responses": True,   # Allow user to interrupt agent responses
}
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `type` | string | `azure_semantic_vad_multilingual` | VAD type: `server_vad` (volume-based) or `azure_semantic_vad_multilingual` (semantic-based, multilingual) |
| `threshold` | float | 0.3 | Sensitivity threshold (0.0-1.0). Lower = more sensitive |
| `prefix_padding_ms` | int | 300 | Milliseconds of audio to include before speech detection |
| `speech_duration_ms` | int | 80 | Minimum speech duration (ms) to trigger detection |
| `silence_duration_ms` | int | 500 | Silence duration (ms) to consider turn complete |
| `remove_filler_words` | bool | True | Remove filler words ("um", "uh", etc.) from transcription |
| `interrupt_responses` | bool | True | Allow user speech to interrupt agent responses |

### End-of-Utterance Detection

For non-GPT models (e.g., phi4, gpt-4.1), semantic end-of-utterance detection provides more accurate turn boundaries:

```python
"end_of_utterance_detection": {
    "model": "semantic_detection_v1_multilingual",
    "threshold": 0.1,    # Semantic detection threshold (default: 0.1)
    "timeout": 4,        # Timeout in seconds (default: 4)
}
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | string | `semantic_detection_v1_multilingual` | Semantic detection model to use (multilingual) |
| `threshold` | float | 0.1 | Detection sensitivity (lower = more likely to detect end) |
| `timeout` | int | 4 | Maximum wait time (seconds) for utterance end |

> **Note:** End-of-utterance detection is **not supported** for `gpt-realtime` and `gpt-realtime-mini` models.

### Audio Processing

```python
"input_audio_noise_reduction": {
    "type": "azure_deep_noise_suppression"
},
"input_audio_echo_cancellation": {
    "type": "server_echo_cancellation"
}
```

| Feature | Type | Description |
|---------|------|-------------|
| Noise Reduction | `azure_deep_noise_suppression` | AI-powered noise suppression for cleaner input |
| Echo Cancellation | `server_echo_cancellation` | Server-side echo cancellation for full-duplex audio |

### Input Audio Transcription

```python
"input_audio_transcription": {
    "model": "azure-fast-transcription",  # Transcription model
    # "prompt": "<optional-prompt>",       # For gpt-transcribe or whisper models
    # "phrase_list": ["term1", "term2"],   # Custom vocabulary (not for gpt-4o-realtime)
}
```

| Model | Supported Models | Notes |
|-------|------------------|-------|
| `azure-speech` | phi4, gpt-4.1, phi4-mm-realtime | Default for non-GPT models |
| `gpt-4o-transcribe` | gpt-realtime | Automatically selected |
| `gpt-4o-mini-transcribe` | gpt-realtime-mini | Automatically selected |
| `whisper-1` | All | Fallback option |

### Voice Output

```python
"voice": {
    "name": "en-US-Steffan:DragonHDLatestNeural",
    "type": "azure-standard",  # or "azure-custom"
    # "endpoint_id": "...",    # Required for azure-custom
    "temperature": 0.8,
}
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | string | `en-US-Steffan:DragonHDLatestNeural` | Voice name (Azure Neural Voice) |
| `type` | string | `azure-standard` | Voice type: `azure-standard` or `azure-custom` |
| `endpoint_id` | string | - | Custom Voice endpoint ID (required for `azure-custom`) |
| `temperature` | float | 0.8 | Voice variability (0.0-1.0) |

### Session Modalities

```python
"modalities": ["audio"]  # Options: ["audio"], ["text"], ["text", "audio"]
```

> **Important:** When using tool calling, only `["audio"]` modality is supported.

### Complete Session Configuration Example

The script now uses SDK-native objects for session configuration (as of Jan 2026):

```python
from azure.ai.voicelive.models import (
    RequestSession, AzureSemanticVadMultilingual, AzureStandardVoice,
    AudioInputTranscriptionOptions, AudioNoiseReduction, AudioEchoCancellation,
    EouDetection, Modality, InputAudioFormat, OutputAudioFormat
)

# Configure turn detection with EOU for non-GPT models
sdk_turn_detection = AzureSemanticVadMultilingual(
    end_of_utterance_detection=EouDetection(model="semantic_detection_v1_multilingual"),
)

# Configure audio processing
sdk_noise_reduction = AudioNoiseReduction(type="azure_deep_noise_suppression")
sdk_echo_cancellation = AudioEchoCancellation(type="server_echo_cancellation")
sdk_transcription = AudioInputTranscriptionOptions(model="azure-speech")

# Configure voice output
sdk_voice = AzureStandardVoice(
    name="en-US-Steffan:DragonHDLatestNeural",
    type="azure-standard",
)

# Build the SDK RequestSession object
sdk_session = RequestSession(
    modalities=[Modality.TEXT, Modality.AUDIO],
    instructions="You are a helpful agent assisting users with their questions.",
    voice=sdk_voice,
    turn_detection=sdk_turn_detection,
    input_audio_transcription=sdk_transcription,
    input_audio_noise_reduction=sdk_noise_reduction,
    input_audio_echo_cancellation=sdk_echo_cancellation,
    tools=tools if tools else None,
    input_audio_format=InputAudioFormat.PCM16,
    output_audio_format=OutputAudioFormat.PCM16,
)

# Send session update using SDK-native method
connection.update_session(sdk_session)
```

> **Note:** For `gpt-realtime` and `gpt-realtime-mini` models, omit the `end_of_utterance_detection` parameter as it's not supported.

## Prerequisites

### Required Packages

Install dependencies from the requirements file:

```bash
pip install -r requirements.txt
```

Key dependencies (see `requirements.txt` for versions):
- `azure-ai-voicelive>=1.1.0`: **Azure VoiceLive SDK** for Voice Live API communication
- `azure-identity`: Azure authentication
- `azure-ai-projects`: Azure AI Projects SDK
- `azure-core`: Azure core functionality
- `openai`: OpenAI SDK for evaluation integration
- `websocket-client`: WebSocket communication (kept for backward compatibility)
- `numpy`: Audio processing
- `sounddevice`: Audio I/O
- `python-dotenv`: Environment variable management
- `filelock`: Cross-process file locking for batch processing

### Azure Resources
- Azure Voice Live API endpoint with appropriate model deployment
- Azure AI Foundry project for evaluation
- Azure credentials (DefaultAzureCredential)

## Configuration

### Environment Variables

Create a `.env` file in the `prototype_v1` directory based on `.sample_env`:

```bash
# Voice Live API Configuration (used by voice_agent_audio_input_evaluation.py)
AZURE_VOICE_LIVE_API_VERSION=2025-10-01
AZURE_VOICE_LIVE_MODEL=gpt-4.1  # Options: "phi4-mini", "phi4-mm-realtime", "gpt-realtime", "gpt-realtime-mini", "gpt-4.1"
AZURE_VOICE_LIVE_ENDPOINT=https://your-resource.services.ai.azure.com/
AZURE_VOICE_LIVE_API_KEY=  # Only required if not using DefaultAzureCredential

# Azure AI Foundry Configuration (used by voice_agent_evaluation.py)
PROJECT_ENDPOINT=https://your-resource.services.ai.azure.com/api/projects/your-project
AOAI_DEPLOYMENT_NAME=gpt-4.1-mini
AOAI_REASONING_DEPLOYMENT_NAME=o4-mini
```

### System Instructions

The default system instruction is defined at the top of the script:

```python
SYSTEM_INSTRUCTION = "You are a helpful agent assisting users with their questions."
```

This can be overridden per-conversation using the `system_prompt` field in your JSONL dataset.

### Tool Definitions and Registry

Tools are defined in your JSONL dataset and executed locally via the `TOOL_REGISTRY`:

```python
# Built-in tool implementations
def get_horoscope(sign):
    return f"{sign}: Next Tuesday you will befriend a baby otter."

def fetchWeather(location):
    return f"The weather in {location} is sunny with a high of 75°F."

# Tool registry maps tool names to callable functions
TOOL_REGISTRY = {
    "get_horoscope": get_horoscope,
    "fetchWeather": fetchWeather
}
```

To add custom tools, add the implementation to `TOOL_REGISTRY` and include the tool definition in your JSONL dataset.
]
```

Tool implementations are in the `TOOL_REGISTRY` dictionary:

```python
TOOL_REGISTRY = {
    "get_horoscope": get_horoscope,
    "fetchWeather": fetchWeather,
}
```

## Input Data Formats

### JSONL Format (Recommended)

For evaluation with ground truth and tool definitions:

```jsonl
{"WavPath": "path/to/audio1.wav", "Question": "What is my horoscope?", "Answer": "Expected response", "tool_definitions": [...], "conversationID": "conv1", "system_prompt": "You are a helpful assistant."}
{"WavPath": "path/to/audio2.wav", "Question": "I am an Aquarius.", "Answer": "Your horoscope...", "tool_definitions": [...], "conversationID": "conv1"}
```

#### JSONL Field Requirements

**MANDATORY Fields:**

| Field | Description |
|-------|-------------|
| `WavPath` or `audio` | Path to audio file (absolute or relative to JSONL file). Script skips lines missing this field. |

**OPTIONAL Fields:**

| Field | Description | Default |
|-------|-------------|---------|
| `Question` or `question` | Transcript or description of user query (for logging) | `None` |
| `Answer` or `answer` | Expected ground truth for `ResponseCompletenessEvaluator` | `None` |
| `tool_definitions` | Array of tool schemas available for the session | `[]` (no tools) |
| `conversationID` or `conversation_id` | Groups turns into conversations for `per-conversation` mode | `'default'` |
| `system_prompt` | Custom system prompt for the agent session | Script default |

#### Tool Definitions Format

Tool definitions follow the Azure OpenAI function calling schema:

```json
{
  "type": "function",
  "name": "get_horoscope",
  "description": "Get today's horoscope for an astrological sign.",
  "parameters": {
    "type": "object",
    "properties": {
      "sign": {
        "type": "string",
        "description": "An astrological sign like Taurus or Aquarius"
      }
    },
    "required": ["sign"]
  }
}
```

#### Tool Definition Behavior by Session Mode

| Mode | Behavior |
|------|----------|
| **Single** | Uses `tool_definitions` from first file for entire session |
| **Per-file** | Each file can have its own `tool_definitions` |
| **Per-conversation** | Uses `tool_definitions` from first file of each conversation |

#### Minimal Valid JSONL

```jsonl
{"WavPath": "audio.wav"}
```

#### Complete JSONL Example

```jsonl
{"WavPath": "turn1.wav", "Question": "What's the weather?", "Answer": "It's sunny today.", "tool_definitions": [{"type": "function", "name": "fetchWeather", "description": "Get weather", "parameters": {"type": "object", "properties": {"location": {"type": "string"}}, "required": ["location"]}}], "conversationID": "weather_conv", "system_prompt": "You are a helpful weather assistant."}
```

### Plain Text Format

For simple testing without evaluation metadata:

```
/path/to/audio1.wav
/path/to/audio2.wav
```

One audio file path per line. Lines starting with `#` are treated as comments.

## Sample Datasets

Multiple sample datasets are provided in `sample_evaluation_input/`:

### DataOceanDemoComplexSession1
A creative writing conversation with 3 turns demonstrating context retention:
- Turn 1: Request for atmospheric paragraph about London pub
- Turn 2: Rewrite in detective novel style + convert to poem
- Turn 3: Brief acknowledgment showing conversation continuity

**Use case:** Testing multi-turn creative tasks and conversation coherence.

```bash
python voice_agent_audio_input_evaluation.py \
  --test-files ./sample_evaluation_input/DataOceanDemoComplexSession1/DataOceanDemoComplexSession1.jsonl \
  --output-dir ./output \
  --evaluation ./output \
  --session-mode single
```

### Eiffel_Tower_Visit_1 (6 turns)
A conversation with horoscope query split across separate audio files:
- Turn 1: Greeting
- Turn 2: Horoscope query ("What is my horoscope?")
- Turn 3: Sign provided ("I am an Aquarius.") - triggers tool call
- Turn 4-6: Eiffel Tower visit planning

**Use case:** Testing tool calling behavior, custom system prompts, and conversation context.

```bash
python voice_agent_audio_input_evaluation.py \
  --test-files ./sample_evaluation_input/Eiffel_Tower_Visit_1/Eiffel_Tower_Visit_1.jsonl \
  --output-dir ./output \
  --evaluation ./output \
  --session-mode single
```

### MultiConversationSample
Combined dataset with multiple conversations for `per-conversation` mode:
- **Conversation 1 (Eiffel_Tower_Visit_1)**: 6 turns - travel assistant with horoscope tool call
- **Conversation 2 (DataOceanDemoComplexSession1)**: 3 turns - creative writing assistant

**Use case:** Testing multiple independent conversations with different system prompts.

```bash
python voice_agent_audio_input_evaluation.py \
  --test-files ./sample_evaluation_input/MultiConversationSample/multiConversationSample.jsonl \
  --output-dir ./output \
  --evaluation ./output \
  --session-mode per-conversation
```

### Tool_Call_Test_Sample
Specialized dataset for testing tool calling with contrasting system prompts:
- **Conversation 1**: System prompt instructs agent to use tools when appropriate
- **Conversation 2**: System prompt instructs agent to prefer own knowledge over tools

**Use case:** Testing agent behavior under different tool usage constraints.

```bash
python voice_agent_audio_input_evaluation.py \
  --test-files ./sample_evaluation_input/Tool_Call_Test_Sample/Tool_Call_Test_Sample.jsonl \
  --output-dir ./output \
  --evaluation ./output \
  --session-mode per-conversation
```

### BingChat_7days_en
English dataset from real Bing Chat conversations:
- `BingChat_en_minimal_10.jsonl`: 10 English samples for quick testing

**Use case:** Testing with real-world English query patterns using `per-file` mode.

```bash
python voice_agent_audio_input_evaluation.py \
  --test-files ./sample_evaluation_input/BingChat_7days_en/BingChat_en_minimal_10.jsonl \
  --output-dir ./output \
  --evaluation ./output \
  --session-mode per-file
```

## Usage

### Basic Usage

```bash
python voice_agent_audio_input_evaluation.py \
  --test-files ./sample_evaluation_input/dataset.jsonl \
  --output-dir ./output \
  --evaluation ./output
```

### Command Line Arguments

| Argument | Short | Default | Description |
|----------|-------|---------|-------------|
| `--test-files` | `-f` | `./sample_evaluation_input/Eiffel_Tower_Visit_1/Eiffel_Tower_Visit_1.jsonl` | Path to JSONL or text file with audio file list |
| `--output-dir` | `-o` | `./output` | Directory for response audio and logs |
| `--evaluation` | `-e` | `./output` | Directory for evaluation JSONL output |
| `--session-mode` | - | `single` | Session handling mode: `single`, `per-file`, or `per-conversation` |
| `--eval-object-id` | - | `None` | Optional evaluation object ID to reuse an existing eval group in Azure AI Evaluation SDK |
| `--sample-rate` | - | `16000` | Audio sample rate in Hz for resampling input audio files |
| `--verbose` | `-v` | `False` | Enable verbose logging (DEBUG level instead of INFO) |

### Session Modes

#### Single Session Mode (Default)
All audio files processed in one continuous conversation:
```bash
python voice_agent_audio_input_evaluation.py \
  --test-files dataset.jsonl \
  --session-mode single
```

**Use when:**
- Testing multi-turn conversations
- Agent needs context from previous turns
- Evaluating conversation coherence

**Behavior:**
- Uses `system_prompt` and `tool_definitions` from first file for entire session
- Conversation history maintained across all files
- Single evaluation file generated

#### Per-File Session Mode
Each audio file processed in a fresh, isolated session:
```bash
python voice_agent_audio_input_evaluation.py \
  --test-files dataset.jsonl \
  --session-mode per-file
```

**Use when:**
- Testing single-turn interactions
- Files are independent queries
- Avoiding context contamination between tests

**Behavior:**
- Each file can have its own `system_prompt` and `tool_definitions`
- Session state reset between files
- All results aggregated into single evaluation file with naming: `{timestamp}_aggregate_{dataset_name}.jsonl`
- Session outputs organized in `session-{n}` subfolders

#### Per-Conversation Session Mode
New session created for each unique `conversationID`:
```bash
python voice_agent_audio_input_evaluation.py \
  --test-files dataset.jsonl \
  --session-mode per-conversation
```

**Use when:**
- Testing multiple conversations in one dataset
- Each conversation needs isolated context
- Different system prompts per conversation

**Behavior:**
1. Groups turns by `conversationID` field
2. Creates new session for each unique conversationID
3. Uses `system_prompt` and `tool_definitions` from first file of each conversation
4. Maintains context within each conversation
5. All results aggregated into single evaluation file
6. Session outputs organized in `conv-{conversationID}` subfolders

**Example dataset structure:**
```jsonl
{"WavPath": "conv1_turn1.wav", "conversationID": "Eiffel_Tower_Visit", "system_prompt": "You are a travel assistant."}
{"WavPath": "conv1_turn2.wav", "conversationID": "Eiffel_Tower_Visit"}
{"WavPath": "conv2_turn1.wav", "conversationID": "Weather_Query", "system_prompt": "You are a weather assistant."}
{"WavPath": "conv2_turn2.wav", "conversationID": "Weather_Query"}
```

## Output Files

### Directory Structure

```
output/
├── 2025-12-08_13-10-27/                                      # Timestamp directory
│   ├── 2025-12-08_13-10-27_dataset.jsonl                    # Evaluation data (single mode)
│   ├── 2025-12-08_13-10-27_aggregate_dataset.jsonl          # Aggregated evaluation (per-file/per-conversation)
│   ├── operational_summary_2025-12-08_13-10-27.json         # Metrics summary
│   ├── turn_01_response.wav                                  # Agent audio responses (single mode)
│   ├── session-1/                                            # Per-file session folder
│   │   ├── session-1_turn_01_response.wav
│   │   └── operational_summary_2025-12-08_13-10-27_session-1.json
│   ├── conv-Eiffel_Tower_Visit/                              # Per-conversation session folder
│   │   ├── conv-Eiffel_Tower_Visit_turn_01_response.wav
│   │   └── ...
│   └── ...
```

### Evaluation JSONL

One record per logical turn:

```json
{
  "query": [
    {"role": "system", "content": "System instruction..."},
    {"role": "user", "content": [{"type": "text", "text": "User query"}]}
  ],
  "response": [
    {"role": "assistant", "content": [{"type": "text", "text": "Agent response"}]}
  ],
  "metrics": {
    "turn-audio-resonse-latency-in-seconds": 1.523,
    "turn-audio-transcription-latency-in-seconds": 0.445,
    "logical_turn_number": 1,
    "conversation_topic": "horoscope",
    "inputs_in_turn": 1,
    "responses_in_turn": 1,
    "audio_response_received": true
  },
  "tool_calls": [
    {"type": "tool_call", "tool_call_id": "call_123", "name": "get_horoscope", "arguments": {"sign": "Aquarius"}}
  ],
  "tool_definitions": [
    {"type": "function", "name": "get_horoscope", "description": "...", "parameters": {...}}
  ],
  "ground_truth": "Expected response text for evaluation"
}
```

### Operational Metrics Summary

The `operational_summary_*.json` file provides high-level statistics:

```json
{
  "operational_metrics": {
    "turns_processed": "5/3",
    "expected_turns": 3,
    "actual_turns": 5,
    "vad_splitting_detected": true,
    "turn_expansion_factor": 1.67,
    "turns_with_audio_response": 5,
    "turns_with_text_only_response": 0,
    "audio_response_rate": 1.0
  },
  "session_info": {
    "timestamp": "2025-12-08 13:10:27",
    "evaluation_mode": "enabled",
    "session_id": "2025-12-08_13-10-27",
    "session_suffix": "conv-Eiffel_Tower_Visit"
  }
}
```

## Operational Metrics Explained

### Turn Metrics

| Metric | Description |
|--------|-------------|
| `expected_turns` | Number of audio files in input dataset |
| `actual_turns` | Number of logical turns created (may differ due to VAD) |
| `vad_splitting_detected` | Whether VAD split audio into multiple turns |
| `turn_expansion_factor` | Average turns per audio file |

### Response Type Metrics

| Metric | Description |
|--------|-------------|
| `turns_with_audio_response` | Turns where agent returned audio |
| `turns_with_text_only_response` | Turns with text but no audio |
| `audio_response_rate` | Percentage of turns with audio |

### Latency Metrics (Per Turn)

| Metric | Description |
|--------|-------------|
| `turn-audio-resonse-latency-in-seconds` | Time from audio sent to first audio response |
| `turn-text-resonse-latency-in-seconds` | Time from audio sent to first text response |
| `turn-audio-transcription-latency-in-seconds` | Time from audio sent to transcription complete |

## Metadata Alignment (Snapshot Mechanism)

The script implements a snapshot mechanism to ensure metadata stays aligned with the correct turn, even when VAD causes turn splitting:

1. **Snapshot on File Load**: When each audio file is loaded, metadata is captured:
   - `turn_ground_truth`
   - `turn_tool_definitions`

2. **Persistence Across VAD Splits**: Snapshots persist across ALL turns generated from a single audio file

3. **Sequential File Processing**: Next file waits for previous file's turn finalization before loading new metadata

4. **Evaluation Uses Snapshots**: Evaluation data uses snapshot values, not current class variables

## Tool Calling Flow

The script handles tool calls with the following flow:

1. **Tool Call Detection**: Agent sends `function_call.arguments.delta` events
2. **Arguments Accumulation**: Arguments are streamed and accumulated in `function_call_buffers`
3. **Tool Execution**: On `function_call.arguments.done`, tool is executed via `TOOL_REGISTRY`
4. **Result Sent**: Tool result sent back via `conversation.item.create` (function_call_output)
5. **Response Continuation**: `response.create` sent to prompt agent to incorporate tool result
6. **Evaluation Capture**: Tool calls and results captured in `tool_calls` and `tool_content` for evaluation

## Advanced Configuration

### Turn Detection Settings

Using SDK-native objects:

```python
from azure.ai.voicelive.models import AzureSemanticVadMultilingual, EouDetection

# For non-GPT models (phi4, gpt-4.1, etc.) - with EOU detection
sdk_turn_detection = AzureSemanticVadMultilingual(
    end_of_utterance_detection=EouDetection(model="semantic_detection_v1_multilingual"),
)

# For GPT-realtime models - without EOU detection
sdk_turn_detection = AzureSemanticVadMultilingual()
```

### Voice Settings

```python
"voice": {
    "name": "en-US-Steffan:DragonHDLatestNeural",
    "type": "azure-standard",  # or "azure-custom"
    "temperature": 0.8
}
```

### Transcription Model Selection

| Model | Transcription Model |
|-------|---------------------|
| `gpt-realtime` | `gpt-4o-transcribe` |
| `gpt-realtime-mini` | `gpt-4o-mini-transcribe` |
| Other models (phi4-mini, gpt-4.1, etc.) | `azure-speech` |

## Troubleshooting

### VAD Splitting Issues
**Problem:** More turns created than expected
**Solution:** 
- Trim silence from audio files
- Adjust `silence_duration_ms` and `threshold` in turn_detection
- Review `vad_splitting_detected` metric

### Metadata Misalignment
**Problem:** Wrong ground truth or tool definitions on turns
**Solution:**
- Verify script waits for `response_complete_event` before loading next file
- Check snapshot variables (`turn_ground_truth`, `turn_tool_definitions`)

### Missing Audio Responses
**Problem:** `audio_response_rate < 1.0`
**Solution:**
- Verify `modalities = ["audio"]` in session configuration
- Check model supports audio output
- Review for tool calling interruptions

### Tool Calls Not Detected
**Problem:** `tool_calls` array empty
**Solution:**
- Verify tool definitions in JSONL match expected schema
- Ensure user query explicitly requests tool usage
- Check tool is registered in `TOOL_REGISTRY`

### Tool Execution Errors
**Problem:** Tool returns error instead of result
**Solution:**
- Verify tool implementation in `TOOL_REGISTRY` matches expected signature
- Check tool arguments parsing

## Logs

Execution logs are written to `logs/` with timestamp:
```
logs/2025-12-08_13-10-27_voicelive_file_input.log
```

Log level set to WARN by default. Modify in script:
```python
logging.basicConfig(level=logging.INFO)  # For verbose logging
```

## Known Limitations

1. **Audio Format**: Only WAV files supported (resampled to 16kHz mono)
2. **Modalities**: Tool calling requires audio-only modality (`["audio"]`)
3. **Safety Timeout**: 60-second timeout per file if service fails to respond
4. **Tool Execution**: Tools execute locally via `TOOL_REGISTRY`, not on Azure service
5. **Multi-part Responses**: Script waits for tool follow-up responses but may need tuning for complex tool chains

## Integration with Evaluation

After session completion, the script automatically runs evaluation using `voice_agent_evaluation.py`:

```python
voice_agent_evaluation.main(
    eval_input_path=evaluation_jsonl_file,
    output_folder=timestamp_root,
    eval_group_name=eval_description,
    setupCustomEvaluators=False  # Uses builtin agent evaluators
)
```

The evaluation runs these built-in evaluators:
- Intent Resolution
- Task Adherence
- Task Completion
- Response Completeness
- Groundedness
- Relevance
- Tool Call Accuracy
- Tool Selection
- Tool Input Accuracy
- Tool Output Utilization
- Tool Call Success

## Contributing

When modifying the script:
1. Maintain snapshot mechanism for metadata alignment
2. Update operational metrics calculations if adding new metrics
3. Test with all three session modes
4. Verify VAD splitting handled correctly
5. Test tool calling flow end-to-end

---

## Batch Processor

The `batch_processor.py` script provides multi-threaded/multi-process execution for `voice_agent_audio_input_evaluation.py`. It spawns separate subprocesses for each session to avoid global state conflicts.

### Batch Processor Features

- **Parallel session processing**: Run multiple sessions concurrently with `--max-workers`
- **Multiple session modes**: Supports `single`, `per-file`, and `per-conversation` modes
- **Aggregated evaluation**: All session results are aggregated into a single evaluation file
- **Thread-safe file writing**: Uses file locking to safely write to shared evaluation files
- **Folder processing**: Can process multiple dataset files from a folder

### Batch Processor Usage

#### Basic Usage

Process a single dataset with parallel conversation sessions:
```bash
python batch_processor.py --test-files dataset.jsonl --session-mode per-conversation --max-workers 4
```

#### Session Modes (Batch)

| Mode | Description | Parallelism |
|------|-------------|-------------|
| `single` | All files processed in one WebSocket session | No parallelism (forced to 1 worker) |
| `per-file` | Each audio file gets its own session | Parallel (up to max-workers) |
| `per-conversation` | Files grouped by conversationID, one session per conversation | Parallel (up to max-workers) |

#### Processing Multiple Datasets

Process all JSONL files in a folder:
```bash
python batch_processor.py --test-files-folder ./datasets --session-mode per-file --max-workers 2
```

#### All Batch Processor Options

```
--test-files, -f       Path to a single JSONL file containing audio file records
--test-files-folder    Path to a folder containing multiple JSONL dataset files
--session-mode         Session handling mode: single, per-file, or per-conversation (default: per-conversation)
--max-workers          Maximum number of parallel session processes (default: 1)
--output-dir, -o       Directory to store response audio files and evaluation results
--evaluation, -e       Directory to store JSONL evaluation data
--eval-object-id       Optional evaluation object ID for Azure AI Evaluation SDK
--timeout              Timeout in seconds for each session subprocess (default: 600)
--dry-run              Show sessions that would be processed without running them
--verbose              Show detailed output from session subprocesses
--skip-evaluation      Skip the final evaluation step
```

### Batch Processor Examples

#### Dry Run (Preview)
```bash
python batch_processor.py --test-files dataset.jsonl --session-mode per-conversation --dry-run
```

#### Per-Conversation with 4 Workers
```bash
python batch_processor.py --test-files multi_conversation_dataset.jsonl \
    --session-mode per-conversation \
    --max-workers 4 \
    --output-dir ./output \
    --evaluation ./output
```

#### Per-File with Custom Timeout
```bash
python batch_processor.py --test-files dataset.jsonl \
    --session-mode per-file \
    --max-workers 2 \
    --timeout 900 \
    --verbose
```

### Batch Output Structure

```
output/
└── 2024-12-11_10-30-00/           # Timestamp folder
    ├── temp/                       # Temporary files (cleaned up after processing)
    ├── 2024-12-11_10-30-00_aggregate_dataset.jsonl  # Aggregated evaluation data
    ├── operational_summary_*.json  # Per-session operational summaries
    └── evaluation_results/         # Final evaluation results
```

### How Batch Processing Works

1. **Dataset Parsing**: The batch processor reads the input JSONL dataset file(s)
2. **Session Preparation**: Based on the session mode, files are grouped into sessions
3. **Subprocess Execution**: Each session runs as a separate subprocess of `voice_agent_audio_input_evaluation.py`
4. **Aggregation**: All session evaluation outputs are written to a shared aggregated JSONL file
5. **Final Evaluation**: After all sessions complete, the final evaluation is run on the aggregated data

### Thread Safety

When running with multiple workers, all subprocesses write to the same aggregated evaluation file. The system uses `filelock` to ensure safe concurrent writes without data corruption.

### Comparison: Direct Script vs Batch Processor

| Feature | Direct v3 Script | Batch Processor |
|---------|-----------------|-----------------|
| Parallelism | Sequential only | Configurable workers |
| Session isolation | Shared global state | Isolated subprocesses |
| Multi-dataset | Manual | Automatic folder processing |
| Evaluation | Per-run | Aggregated across all sessions |

---

## Utility Scripts

### deleteEvaluationGroups.py

Cleanup utility for removing Azure AI Foundry Evaluation Groups created during evaluation runs.

**Usage:**

```bash
# List all evaluation groups (dry run - no deletion)
python deleteEvaluationGroups.py

# Delete evaluation groups matching a search string
python deleteEvaluationGroups.py --delete-search-string "Voice Live API: 20251212_"
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `--delete-search-string` | Search string to match evaluation group names. Only groups containing this string will be deleted. If omitted, lists groups without deleting. |

**Example:** After running batch evaluations with timestamp prefixes, clean up old runs:

```bash
# Delete all evaluation groups from December 10th runs
python deleteEvaluationGroups.py --delete-search-string "20251210_"
```

> **Note:** This script uses `DefaultAzureCredential` and requires the `PROJECT_ENDPOINT` environment variable to be set in your `.env` file.

### deleteDatasets.py

Cleanup utility for removing Azure AI Foundry Datasets created during evaluation runs.

**Usage:**

```bash
# List all datasets (dry run - no deletion)
python deleteDatasets.py

# Delete datasets matching a search string
python deleteDatasets.py --delete-search-string "Voice_Live_API_20251212_"
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `--delete-search-string` | Search string to match dataset names. Only datasets containing this string will be deleted (all versions). If omitted, lists datasets without deleting. |

**Example:** After running batch evaluations with timestamp prefixes, clean up old dataset versions:

```bash
# Delete all datasets from December 10th runs
python deleteDatasets.py --delete-search-string "20251210_"
```

> **Note:** This script uses `DefaultAzureCredential` and requires the `PROJECT_ENDPOINT` environment variable to be set in your `.env` file. When a dataset is deleted, all its versions are removed.

### hf_audio_loader.py

HuggingFace Dataset Loader utility for downloading and processing audio datasets from HuggingFace Hub. Extracts audio files and metadata into a format compatible with the Voice Live evaluation pipeline.

**Location:** `hf_audio_loader.py`

**Features:**
- Downloads audio datasets from HuggingFace Hub
- Extracts WAV files to local storage
- Creates individual JSON metadata files per audio item
- Generates combined JSONL file with all dataset elements for batch processing
- Supports multiple dataset formats (llama-questions, speech-web-questions, speech-triavia-qa)

**Usage:**

```bash
# Run from prototype_v1 directory
python hf_audio_loader.py
```

**Configuration:** Edit the `dataset_name` variable in the script to select different datasets:

```python
dataset_name = "TwinkStart/llama-questions"
# dataset_name = "TwinkStart/speech-web-questions"
# dataset_name = "TwinkStart/speech-triavia-qa"
```

**Output Structure:**

```
local_datasets/
└── TwinkStart/
    └── llama-questions/
        ├── wav/
        │   ├── 0.wav
        │   ├── 1.wav
        │   └── ...
        └── TwinkStart-llama-questions.jsonl
```

**Combined JSONL Format:** Each line contains:

| Field | Description |
|-------|-------------|
| `WavPath` | Absolute path to the WAV file |
| `Question` | Question text from original metadata |
| `Answer` | Answer text from original metadata |
| `Wav Filename` | Filename of the WAV file (e.g., `0.wav`) |

**Authentication:** The script will prompt for a HuggingFace token when run. You can leave it empty, but this will apply rate limiting and restrict the amount of data that can be downloaded. For full access, set `HF_TOKEN` environment variable or run `huggingface-cli login`.

---

## Open Topics

The following items are planned or under consideration for future development:

| Item | Description | Priority | Status |
|------|-------------|----------|--------|
| ~~Migrate to Voice Live SDK~~ | ~~Replace custom WebSocket implementation with official Azure Voice Live SDK~~ | ~~High~~ | ✅ **Completed** (Dec 2025) - Now using `azure-ai-voivelive>=1.1.0` |
| ~~SDK-native session configuration~~ | ~~Refactor session configuration to use SDK model objects (`RequestSession`, `AzureSemanticVadMultilingual`, `AudioNoiseReduction`, `AudioEchoCancellation`, `EouDetection`) instead of dict-based config. Added `update_session()` method for type-safe session updates.~~ | ~~High~~ | ✅ **Completed** (Jan 2026) |
| SDK Phase 2: Remove Compatibility Layer | Remove backward-compatibility wrapper and refactor to native SDK patterns. See breakdown below. | Medium | In Progress |
| Retry Logic for Failed Files | Add `--retry-failed` flag to re-process files that failed in a previous run (read from operational summary to identify failures) | Medium | Planned |
| Progress Reporting | Add progress bar (tqdm) for large datasets with estimated time remaining | Low | Planned |

### SDK Phase 2 Breakdown

| Sub-item | Description | Status |
|----------|-------------|--------|
| ~~SDK-native session updates~~ | ~~Use `RequestSession` objects directly via `update_session()` method instead of dict-based `_send_session_update()`~~ | ✅ **Completed** (Jan 2026) |
| Remove `LegacyVoiceLiveConnection` | Remove the legacy WebSocket-based connection class | Planned |
| Remove legacy `create_session()` | Remove the legacy session creation function that uses dict-based config | Planned |
| Native async patterns | Refactor `SDKVoiceLiveConnection` to use native async patterns instead of `recv()`/`send()`/`close()` wrapper methods | Planned |
| Use SDK enums directly | Replace string-based event type matching via `EVENT_TYPE_MAP` with SDK enums (`ServerEventType.*`) | Planned |
| Remove `websocket-client` | Remove `websocket-client` from requirements.txt once legacy code is removed | Planned |

---

## Skills

Skill definitions for AI agent integration are available in `skills`:

| Skill | Description |
|-------|-------------|
| `voicelive-audio-evaluation` | VoiceLive audio evaluation - runs the evaluation script with configurable parameters |
| `batch-processor-py` | Parallel batch processing - wraps the batch processor for multi-threaded execution |

Skills enable AI agents (GitHub Copilot CLI, Azure AI Agents, etc.) to discover and invoke these tools via natural language.

### Usage with Agents

```plaintext
# Natural language examples for AI agents
"Run VoiceLive evaluation on the Eiffel_Tower_Visit dataset"
"Evaluate the dataset at C:\datasets\test.jsonl with per-conversation mode"
"Run batch evaluation with 8 workers on the large_dataset folder"
```

---

## License

See repository root for license information.
