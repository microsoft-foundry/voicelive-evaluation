# Voice Agent Audio Input Evaluation (v2)

This prototype provides automated evaluation capabilities for Azure Voice Live API agents, processing audio files and generating comprehensive evaluation data for use with Azure AI Evaluation SDK.

## Overview

The `voice_agent_audio_input_evaluation_v2.py` script enables you to:
- Send pre-recorded audio files to Azure Voice Live API
- Capture agent responses (text and audio)
- Generate evaluation data in JSONL format compatible with Azure AI Evaluation SDK
- Track operational metrics including latency, tool usage, and VAD behavior
- Support both single-session and per-file session modes

## Features

### Core Capabilities
- **Multi-turn conversations**: Process multiple audio files in sequence, maintaining conversation context
- **Tool calling support**: Track and evaluate tool/function calls made by the agent
- **VAD (Voice Activity Detection) handling**: Automatically detects when silence in audio causes turn splitting
- **Metadata alignment**: Ensures ground truth, expected tool calls, and tool definitions align correctly with agent responses
- **Dual session modes**: Run all files in one conversation or each file in isolated sessions
- **Operational metrics**: Comprehensive tracking of response latencies, turn counts, and audio response rates

### Evaluation Integration
- Generates evaluation data compatible with Azure AI Evaluation SDK evaluators:
  - `IntentResolutionEvaluator`: Measures how well the agent identifies correct intent from user query (Scale: 1-5)
  - `TaskAdherenceEvaluator`: Measures adherence to task based on system message (Scale: 1-5)
  - `ResponseCompletenessEvaluator`: Assesses how completely the response addresses the query using ground truth (Scale: 1-5)
  - `ToolCallAccuracyEvaluator`: Validates tool calling behavior (Scale: 0-1)
  - `OperationalMetricsEvaluator`: Collects runtime execution metrics

## Prerequisites

### Required Packages
```bash
pip install -r requirements.txt
```

Key dependencies:
- `azure-identity`: Azure authentication
- `websocket-client`: WebSocket communication
- `numpy`: Audio processing
- `sounddevice`: Audio I/O
- `python-dotenv`: Environment variable management

### Azure Resources
- Azure Voice Live API endpoint with appropriate model deployment
- Azure credentials (DefaultAzureCredential or API key)

## Configuration

### Environment Variables

Create a `.env` file in the `prototype_v1` directory based on `.sample_env`:

```bash
# Required - Voice Live API Configuration
AZURE_VOICE_LIVE_API_VERSION="2025-05-01-preview"
AZURE_VOICE_LIVE_MODEL="phi4-mini"  # or "gpt-4o-realtime-preview"
AZURE_VOICE_LIVE_ENDPOINT="https://your-endpoint.azure.com/"

# Optional - for API key authentication (otherwise DefaultAzureCredential is used)
AZURE_VOICE_LIVE_API_KEY="your-key-here"

# Optional - for evaluation SDK
PROJECT_CONNECTION_STRING="your-project-connection"
```

### System Instructions

The agent's system instruction is defined at the top of the script:

```python
SYSTEM_INSTRUCTION = "You are a helpful agent assisting users with their questions."
```

Modify this to customize agent behavior.

### Tool Definitions

Tools are defined in the `main()` function:

```python
tools = [
    {
        "type": "function",
        "name": "get_horoscope",
        "description": "Get today's horoscope for an astrological sign.",
        "parameters": {
            "type": "object",
            "properties": {
                "sign": {
                    "type": "string",
                    "description": "An astrological sign like Taurus or Aquarius",
                },
            },
            "required": ["sign"],
        },
    },
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

For evaluation with ground truth and tool expectations:

```jsonl
{"WavPath": "path/to/audio1.wav", "Question": "What is my horoscope? I am an Aquarius.", "Answer": "Expected response text", "expected_tool_calls": [{"type": "tool_call", "tool_call_id": "expected_call_1", "name": "get_horoscope", "arguments": {"sign": "Aquarius"}}], "tool_definitions": [{"type": "function", "name": "get_horoscope", "description": "Get today's horoscope...", "parameters": {...}}], "conversationID": "horoscope_query"}
{"WavPath": "path/to/audio2.wav", "Question": "Tell me a joke.", "Answer": "Expected joke response", "expected_tool_calls": [], "tool_definitions": [], "conversationID": "joke_request"}
```

#### JSONL Field Requirements

**MANDATORY Fields:**

- **`WavPath`** or **`audio`** (required): Path to audio file (absolute or relative to JSONL file)
  - The script will skip lines missing this field with a warning
  - Can use either field name; `WavPath` takes precedence

**OPTIONAL Fields:**

- **`Question`** or **`question`**: Transcript or description of the user's query
  - Used for documentation and logging
  - Defaults to `None` if missing

- **`Answer`** or **`answer`**: Expected ground truth response for evaluation
  - Used by `ResponseCompletenessEvaluator` and other quality metrics
  - Defaults to `None` if missing; evaluation can still run without it

- **`expected_tool_calls`**: Array of expected tool calls for validation
  - Used by `ToolCallAccuracyEvaluator`
  - Defaults to `[]` (empty array) if missing
  - Format: `[{"type": "tool_call", "tool_call_id": "id", "name": "function_name", "arguments": {...}}]`

- **`tool_definitions`**: Array of tool/function definitions available for the turn
  - Used for evaluation context
  - Defaults to `[]` (empty array) if missing
  - Format matches Azure OpenAI function calling schema

- **`conversationID`** or **`conversation_id`**: Identifier for grouping turns into conversations
  - **Required for `--session-mode per-conversation`**
  - Defaults to `'default'` if missing (all turns treated as same conversation)
  - Used to determine when to reset session state

#### Minimal Valid JSONL

```jsonl
{"WavPath": "audio.wav"}
```

This is the minimum required to run the script. All other fields enhance evaluation capabilities but aren't required for basic operation.

#### Complete JSONL Example

```jsonl
{"WavPath": "turn1.wav", "Question": "What's the weather?", "Answer": "It's sunny today.", "expected_tool_calls": [{"type": "tool_call", "name": "get_weather", "arguments": {"location": "Seattle"}}], "tool_definitions": [{"type": "function", "name": "get_weather", "parameters": {...}}], "conversationID": "weather_conv"}
```

### Plain Text Format

For simple testing without evaluation:

```
/path/to/audio1.wav
/path/to/audio2.wav
/path/to/audio3.wav
```

One audio file path per line. Lines starting with `#` are treated as comments.

## Sample Datasets

Two multi-turn conversation datasets are provided in `sample_evaluation_input/`:

### DataOceanDemoComplexSession1
A creative writing conversation with 3 turns demonstrating context retention:
- Turn 1: Request for atmospheric paragraph about London pub
- Turn 2: Rewrite in detective novel style + convert to poem
- Turn 3: Brief acknowledgment showing conversation continuity

A sample result can be found in `sample_evaluation_input/2025-11-25_16-31-15_DataOceanDemoComplexSession1`.

```bash
python voice_agent_audio_input_evaluation_v2.py \
  --test-files ./prototype_v1/sample_evaluation_input/DataOceanDemoComplexSession1/DataOceanDemoComplexSession1.jsonl \
  --output-dir ./output \
  --evaluation ./output \
  --session-mode single
```

### Eiffel_Tower_Visit_1
A 6-turn conversation demonstrating tool calling and context building:
- Turn 1: Greeting
- Turn 2-3: Horoscope query with tool call (Aquarius sign)
- Turn 4-6: Eiffel Tower visit planning (hours, Sunday programs, restaurants)

A sample result can be found in `sample_evaluation_input/2025-11-25_16-23-13_Eiffel_Tower_Visit_1`.

```bash
python voice_agent_audio_input_evaluation_v2.py \
  --test-files ./prototype_v1/sample_evaluation_input/Eiffel_Tower_Visit_1/Eiffel_Tower_Visit_1.jsonl \
  --output-dir ./output \
  --evaluation ./output \
  --session-mode single
```

## Usage

### Basic Usage

```bash
python voice_agent_audio_input_evaluation_v2.py \
  --test-files ./sample_evaluation_input/dataset.jsonl \
  --output-dir ./output \
  --evaluation ./output
```

### Command Line Arguments

| Argument | Short | Default | Description |
|----------|-------|---------|-------------|
| `--test-files` | `-f` | `./test_files.txt` | Path to JSONL or text file with audio file list |
| `--output-dir` | `-o` | `./output` | Directory for response audio and logs |
| `--evaluation` | `-e` | `./output` | Directory for evaluation JSONL output |
| `--session-mode` | - | `single` | Session handling mode: `single`, `per-file`, or `per-conversation` |

### Session Modes

#### Single Session Mode (Default)
All audio files processed in one continuous conversation:
```bash
python voice_agent_audio_input_evaluation_v2.py \
  --test-files dataset.jsonl \
  --session-mode single
```

**Use when:**
- Testing multi-turn conversations
- Agent needs context from previous turns
- Evaluating conversation coherence

#### Per-File Session Mode
Each audio file processed in a fresh, isolated session:
```bash
python voice_agent_audio_input_evaluation_v2.py \
  --test-files dataset.jsonl \
  --session-mode per-file
```

**Use when:**
- Testing single-turn interactions
- Files are independent queries
- Avoiding context contamination between tests

#### Per-Conversation Session Mode
New session created for each unique `conversationID`:
```bash
python voice_agent_audio_input_evaluation_v2.py \
  --test-files dataset.jsonl \
  --session-mode per-conversation
```

**Use when:**
- Testing multiple conversations in one dataset
- Each conversation needs isolated context
- Evaluating conversation-level metrics across different scenarios

**How it works:**
1. Script groups turns by `conversationID` field in JSONL
2. Creates new session for each unique conversationID
3. Maintains context within each conversation
4. Resets session when conversationID changes
5. Aggregates all results for single evaluation run

**Example dataset structure:**
```jsonl
{"WavPath": "conv1_turn1.wav", "conversationID": "Eiffel_Tower_Visit"}
{"WavPath": "conv1_turn2.wav", "conversationID": "Eiffel_Tower_Visit"}
{"WavPath": "conv2_turn1.wav", "conversationID": "Weather_Query"}
{"WavPath": "conv2_turn2.wav", "conversationID": "Weather_Query"}
```
This creates 2 sessions: one for Eiffel_Tower_Visit (2 turns) and one for Weather_Query (2 turns)

## Output Files

The script generates timestamped output in the specified directories:

### Directory Structure

```
output/
├── 2025-11-25_15-30-45/                          # Timestamp directory
│   ├── 2025-11-25_15-30-45_dataset.jsonl        # Evaluation data
│   ├── operational_summary_2025-11-25_15-30-45.json  # Metrics summary
│   ├── turn_01_response.wav                      # Agent audio responses
│   ├── turn_02_response.wav
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
  "expected_tool_calls": [
    {"type": "tool_call", "tool_call_id": "expected_call_1", "name": "get_horoscope", "arguments": {"sign": "Aquarius"}}
  ],
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
    "timestamp": "2025-11-25 15:30:45",
    "evaluation_mode": "enabled",
    "session_id": "2025-11-25_15-30-45",
    "session_suffix": null
  }
}
```

## Operational Metrics Explained

### Turn Metrics

| Metric | Description | How It's Measured |
|--------|-------------|-------------------|
| `expected_turns` | Number of audio files in input dataset | Count of files in test-files list |
| `actual_turns` | Number of logical turns created | Incremented when `finalize_turn_and_get_evaluation_data()` is called |
| `turns_processed` | Display format showing actual/expected | String: `"{actual_turns}/{expected_turns}"` |

### VAD (Voice Activity Detection) Metrics

| Metric | Description | How It's Measured |
|--------|-------------|-------------------|
| `vad_splitting_detected` | Whether VAD split audio into multiple turns | Boolean: `actual_turns > expected_turns` |
| `turn_expansion_factor` | Average turns per audio file | Calculated: `actual_turns / expected_turns` |

**VAD Splitting Explained:**
When audio files contain silence at the beginning or pauses during speech, Azure's Voice Activity Detection may interpret this as multiple distinct user inputs, creating more turns than audio files. A factor of 1.67 means each audio file generated an average of 1.67 turns.

### Response Type Metrics

| Metric | Description | How It's Measured |
|--------|-------------|-------------------|
| `turns_with_audio_response` | Turns where agent returned audio | Incremented when `audio_response_received = true` in turn metrics |
| `turns_with_text_only_response` | Turns with text but no audio | Incremented when `audio_response_received = false` in turn metrics |
| `audio_response_rate` | Percentage of turns with audio | Calculated: `turns_with_audio_response / actual_turns` |

**Note:** A low audio response rate may indicate:
- Agent configuration issues (modalities not set correctly)
- API service issues
- Tool calling interrupting audio generation

### Latency Metrics (Per Turn)

Captured in each turn's metrics object:

| Metric | Description | How It's Measured |
|--------|-------------|-------------------|
| `turn-audio-resonse-latency-in-seconds` | Time from audio sent to first audio response | `first_audio_response_time - audio_send_end_time` |
| `turn-text-resonse-latency-in-seconds` | Time from audio sent to first text response | `first_text_response_time - audio_send_end_time` |
| `turn-audio-transcription-latency-in-seconds` | Time from audio sent to transcription complete | `transcription_complete_time - audio_send_end_time` |

**Timestamps Captured:**
- `audio_send_end_time`: Set when `input_audio_buffer.speech_stopped` event received
- `first_text_response_time`: Set on first `response.output_text.delta` event
- `first_audio_response_time`: Set on first `response.audio.delta` event
- `transcription_complete_time`: Set on `conversation.item.input_audio_transcription.completed` event

### Turn Context Metrics

| Metric | Description | How It's Measured |
|--------|-------------|-------------------|
| `logical_turn_number` | Sequential turn counter | Incremented in `finalize_turn_and_get_evaluation_data()` |
| `inputs_in_turn` | Number of user inputs in this turn | Count of `user_content` entries (excluding placeholders) |
| `responses_in_turn` | Number of assistant responses | Count of `assistant_content` entries |
| `conversation_topic` | Detected topic from user query | Extracted via keyword detection in user transcript |

**Multiple Inputs per Turn:**
VAD splitting can cause multiple user inputs within a single logical turn. For example, silence at the start of audio creates an empty user input, followed by the actual speech - both counted as one turn with 2 inputs.

## Metadata Alignment

The script implements a snapshot mechanism to ensure metadata (ground truth, expected tool calls, tool definitions) stays aligned with the correct turn, even when VAD causes turn splitting:

1. **Snapshot on File Load**: When each audio file is loaded, metadata is captured in snapshot variables:
   - `turn_ground_truth`
   - `turn_expected_tool_calls`
   - `turn_tool_definitions`

2. **Persistence Across VAD Splits**: Snapshots persist across ALL turns generated from a single audio file

3. **Sequential File Processing**: The next file waits for the previous file's turn finalization to complete before loading new metadata

4. **Evaluation Uses Snapshots**: When writing evaluation data, the script uses snapshot values, not current class variables

This ensures that if File 1 generates 2 turns due to VAD, both turns receive File 1's metadata, not File 2's.

## Troubleshooting

### VAD Splitting Issues
**Problem:** More turns created than expected
**Solution:** 
- Add padding/trim silence from audio files
- Check audio quality and background noise
- Review `vad_splitting_detected` metric

### Metadata Misalignment
**Problem:** Wrong ground truth or expected tool calls on turns
**Solution:**
- Verify script waits for `response_complete_event` (not `audio_transcript_complete_event`)
- Check snapshot variables are not cleared prematurely
- Use `--session-mode single` for debugging

### Missing Audio Responses
**Problem:** `audio_response_rate < 1.0`
**Solution:**
- Verify `modalities = ["audio"]` in session configuration
- Check model supports audio output (e.g., gpt-4o-realtime-preview)
- Review agent logs for tool calling interruptions

### Tool Calls Not Detected
**Problem:** `tool_calls` array empty when tools should be used
**Solution:**
- Verify tool definitions in input JSONL match agent configuration
- Check user query explicitly requests tool usage
- Review agent system instructions encourage tool usage

## Integration with Azure AI Evaluation SDK

Use the generated JSONL file with `voice_agent_evaluation_v1.py`:

```bash
python voice_agent_evaluation_v1.py \
  --input ./output/2025-11-25_15-30-45/2025-11-25_15-30-45_dataset.jsonl \
  --output ./evaluation_results
```

This will run configured evaluators (ToolCallAccuracyEvaluator, GroundednessEvaluator, etc.) and generate results.

## Advanced Configuration

### Custom Turn Detection Settings

Modify in `main()` function:

```python
turn_detection = {
    "type": "azure_semantic_vad",  # or "server_vad"
    "threshold": 0.3,              # VAD sensitivity (0.0-1.0)
    "prefix_padding_ms": 200,      # Audio kept before speech
    "silence_duration_ms": 200,    # Silence duration to trigger end
    "remove_filler_words": True,   # Remove "um", "uh", etc.
}
```

### Audio Processing Settings

```python
AUDIO_SAMPLE_RATE = 24000  # Hz - required by Voice Live API
AUDIO_CHUNK_MS = 20        # Milliseconds per chunk
```

### Transcription Model Selection

```python
# For gpt-realtime models
transcription_model = "gpt-4o-transcribe"

# For other models  
transcription_model = "azure-speech"
```

## Logs

Execution logs are written to `logs/` with timestamp:
```
logs/2025-11-25_15-30-45_voicelive_file_input.log
```

Log level set to WARN by default. Modify in script:
```python
logging.basicConfig(level=logging.INFO)  # For verbose logging
```

## Known Limitations

1. **Audio Format**: Only WAV files supported (resampling to 24kHz mono)
2. **Modalities**: Tool calling requires audio-only modality
3. **Timeout**: 60-second safety timeout per file (configurable)
4. **Tool Execution**: Tools execute locally, not on Azure service

## Contributing

When modifying the script:
1. Maintain snapshot mechanism for metadata alignment
2. Update operational metrics calculations if adding new metrics
3. Test with both session modes
4. Verify VAD splitting handled correctly

## License

See repository root for license information.
