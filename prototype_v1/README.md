# Voice Agent Audio Input Evaluation (v3)

This prototype provides automated evaluation capabilities for Azure Voice Live API agents, processing audio files and generating comprehensive evaluation data for use with Azure AI Evaluation SDK.

## Version History

| Version | Script | Description |
|---------|--------|-------------|
| **v3 (Current)** | `voice_agent_audio_input_evaluation_v3.py` + `voice_agent_evaluation_v2.py` | Latest version using the new Azure Evaluations implementation leveraging the OpenAI Evals SDK |
| v2 (Legacy) | `voice_agent_audio_input_evaluation_v2.py` + `voice_agent_evaluation_v1.py` | Old version using the legacy Azure Evaluations SDK implementation |
| v1 (Legacy) | `voice_agent_audio_input_evaluation_v1.py` | Old version using the legacy Azure Evaluations SDK implementation |

> **Note:** The v1 and v2 scripts are kept for reference but are considered legacy. New projects should use the v3 implementation which leverages the updated Azure Evaluations code built on the OpenAI Evals SDK for improved evaluator support and reliability.

## Overview

The `voice_agent_audio_input_evaluation_v3.py` script enables you to:
- Send pre-recorded audio files to Azure Voice Live API
- Capture agent responses (text and audio)
- Generate evaluation data in JSONL format compatible with Azure AI Evaluation SDK
- Track operational metrics including latency, tool usage, and VAD behavior
- Support single, per-file, and per-conversation session modes
- Automatically run evaluations after session completion

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

## Prerequisites

### Required Packages
```bash
pip install -r requirements.txt
```

Key dependencies:
- `azure-identity`: Azure authentication
- `azure-ai-projects`: Azure AI Projects SDK
- `websocket-client`: WebSocket communication
- `numpy`: Audio processing
- `sounddevice`: Audio I/O
- `python-dotenv`: Environment variable management

### Azure Resources
- Azure Voice Live API endpoint with appropriate model deployment
- Azure AI Foundry project for evaluation
- Azure credentials (DefaultAzureCredential)

## Configuration

### Environment Variables

Create a `.env` file in the `prototype_v1` directory based on `.sample_env`:

```bash
# Voice Live API Configuration (used by voice_agent_audio_input_evaluation_v3.py)
AZURE_VOICE_LIVE_API_VERSION="2025-05-01-preview"
AZURE_VOICE_LIVE_MODEL="phi4-mini"  # or "gpt-4o-realtime-preview", "gpt-4o-mini-realtime-preview"
AZURE_VOICE_LIVE_ENDPOINT="https://your-endpoint.azure.com/"
AZURE_VOICE_LIVE_API_KEY="your-key-here"  # Only if not using DefaultAzureCredential

# Azure AI Foundry Configuration (used by voice_agent_evaluation_v2.py)
PROJECT_ENDPOINT="https://your-project-endpoint.azure.com/"
AOAI_DEPLOYMENT_NAME="gpt-4o"
AOAI_REASONING_DEPLOYMENT_NAME="o4-mini"
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
python voice_agent_audio_input_evaluation_v3.py \
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
python voice_agent_audio_input_evaluation_v3.py \
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
python voice_agent_audio_input_evaluation_v3.py \
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
python voice_agent_audio_input_evaluation_v3.py \
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
python voice_agent_audio_input_evaluation_v3.py \
  --test-files ./sample_evaluation_input/BingChat_7days_en/BingChat_en_minimal_10.jsonl \
  --output-dir ./output \
  --evaluation ./output \
  --session-mode per-file
```

## Usage

### Basic Usage

```bash
python voice_agent_audio_input_evaluation_v3.py \
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

### Session Modes

#### Single Session Mode (Default)
All audio files processed in one continuous conversation:
```bash
python voice_agent_audio_input_evaluation_v3.py \
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
python voice_agent_audio_input_evaluation_v3.py \
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
python voice_agent_audio_input_evaluation_v3.py \
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

```python
turn_detection = {
    "type": "azure_semantic_vad",  # or "server_vad"
    "threshold": 0.3,              # VAD sensitivity (0.0-1.0)
    "prefix_padding_ms": 200,      # Audio kept before speech
    "silence_duration_ms": 200,    # Silence duration to trigger end
    "remove_filler_words": True,   # Remove "um", "uh", etc.
    "end_of_utterance_detection": {  # Only for non-gpt models
        "model": "semantic_detection_v1",
        "threshold": 0.1,
        "timeout": 4
    }
}
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
| `gpt-4o-realtime-preview` | `gpt-4o-transcribe` |
| `gpt-4o-mini-realtime-preview` | `gpt-4o-mini-transcribe` |
| Other models (phi4-mini, etc.) | `azure-fast-transcription` |

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

1. **Audio Format**: Only WAV files supported (resampled to 24kHz mono)
2. **Modalities**: Tool calling requires audio-only modality (`["audio"]`)
3. **Safety Timeout**: 60-second timeout per file if service fails to respond
4. **Tool Execution**: Tools execute locally via `TOOL_REGISTRY`, not on Azure service
5. **Multi-part Responses**: Script waits for tool follow-up responses but may need tuning for complex tool chains

## Integration with Evaluation

After session completion, the script automatically runs evaluation using `voice_agent_evaluation_v2.py`:

```python
voice_agent_evaluation_v2.main(
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

## License

See repository root for license information.
