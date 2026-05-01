# VoiceLive Audio Evaluation Skill

Runs Azure VoiceLive audio evaluation tests using test audio files and conversation datasets. This skill processes audio through the VoiceLive API and captures comprehensive evaluation metrics including transcription accuracy, response quality, latency, and conversation flow.

## Overview

This skill wraps the existing `voice_agent_audio_input_evaluation.py` script to enable AI agents to perform VoiceLive API evaluations. It supports both single-file and batch processing modes with customizable system prompts and tool definitions.

**Key Capabilities:**
- Process audio files (.wav) through VoiceLive API
- Execute conversation datasets (.jsonl) with multiple audio interactions
- Capture evaluation metrics (transcription, response quality, latency)
- Support custom system prompts per conversation
- Test with tool definitions (function calling)
- Generate evaluation reports in JSONL format
- Batch processing with aggregate results

## When to Use This Skill

✅ **Use this skill when:**
- Evaluating VoiceLive API performance with audio test files
- Processing conversation datasets with audio inputs
- Capturing runtime evaluation metrics (latency, response quality)
- Testing VoiceLive with custom system prompts
- Running batch evaluations across multiple audio files
- Generating evaluation reports with conversation transcripts

❌ **Don't use this skill for:**
- Validating dataset structure/syntax → Use `validate-dataset-consistency` skill
- Checking dataset quality (prompts, tool definitions) → Use `validate-dataset-quality` skill
- Non-VoiceLive evaluations → Use appropriate evaluation tool

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `test_files_path` | string | Yes | Path to audio file (.wav) or dataset file (.jsonl) |
| `output_dir` | string | No | Directory for audio output files (recorded responses) |
| `evaluation_dir` | string | No | Directory for evaluation result files (.jsonl) |
| `session_timestamp` | string | No | Custom timestamp for this session (YYYYMMDD_HHMMSS) |
| `evaluation_output_file_override` | string | No | Override path for aggregate evaluation output |
| `session_suffix` | string | No | Suffix for session identifiers (tracking multiple runs) |

### Parameter Details

**test_files_path**
- Single audio: `C:\datasets\audio_001.wav`
- Dataset: `C:\datasets\conversations.jsonl`
- Dataset format (JSONL):
  ```json
  {"audio_file": "audio_001.wav", "system_prompt": "You are helpful", "expected_answer": "..."}
  {"audio_file": "audio_002.wav", "system_prompt": "You are concise", "tool_definitions": [...]}
  ```

**evaluation_dir**
- When specified, generates evaluation JSONL files with metrics:
  - `conversation_id`: Unique identifier
  - `audio_file`: Input audio file used
  - `system_prompt`: System instruction used
  - `user_message`: Transcribed user input
  - `assistant_response`: VoiceLive response
  - `latency_ms`: Response latency
  - `timestamp`: Evaluation timestamp

**evaluation_output_file_override**
- Use for batch mode: consolidates all evaluations into one file
- Without this: creates separate evaluation files per dataset

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AZURE_VOICE_LIVE_ENDPOINT` | Yes | Azure VoiceLive service endpoint URL |
| `AZURE_VOICE_LIVE_MODEL` | Yes | VoiceLive model deployment name |
| `AZURE_VOICE_LIVE_API_VERSION` | No | API version (default: 2025-05-01-preview) |
| `AZURE_VOICELIVE_API_KEY` | No | API key (OPTIONAL - Azure Identity preferred) |

**Authentication:**
- **Primary:** Azure DefaultAzureCredential (Managed Identity, Azure CLI, etc.)
- **Fallback:** AZURE_VOICELIVE_API_KEY environment variable
- **Scope:** `https://ai.azure.com/.default`

## Usage Examples

### Command Line (Direct Execution)

```bash
# Single conversation evaluation
python voice_agent_audio_input_evaluation.py \
  --test_files_path "C:\datasets\conversation_001.jsonl" \
  --evaluation_dir "C:\evaluations"

# Batch evaluation with aggregate output
python voice_agent_audio_input_evaluation.py \
  --test_files_path "C:\datasets\wave1_conversations.jsonl" \
  --output_dir "C:\output\wave1" \
  --evaluation_dir "C:\evaluations" \
  --evaluation_output_file_override "C:\evaluations\wave1_aggregate.jsonl" \
  --session_suffix "wave1_run1"

# Single audio file (no dataset)
python voice_agent_audio_input_evaluation.py \
  --test_files_path "C:\datasets\audio_sample.wav" \
  --output_dir "C:\output"
```

### Python Module (Programmatic)

```python
import sys
sys.path.append('C:/Localrepos/voicelive-evaluation/evaluation_harness')
from voice_agent_audio_input_evaluation import main

# Run evaluation
main(
    test_files_path="C:/datasets/conversations.jsonl",
    output_dir="C:/output",
    evaluation_dir="C:/evaluations",
    session_timestamp="20260131_015423",
    session_suffix="wave1_run1"
)
```

### Agent Skills (Natural Language)

When used with GitHub Copilot CLI or Foundry Agent Service:

```plaintext
# Natural language examples
"Run VoiceLive evaluation on dataset C:\datasets\test.jsonl"
"Evaluate VoiceLive performance with conversations from C:\datasets\wave2\sample.jsonl and save to C:\eval"
"Test VoiceLive with audio files in C:\datasets and output results to C:\output"
```

The agent will:
1. Discover this skill via `skill.yaml`
2. Map natural language to parameters
3. Execute the evaluation
4. Report results back to user

## Output Files

### Audio Output (if `output_dir` specified)
```
output_dir/
  └── 20260131_015423/
      ├── conversation_001_response.wav
      ├── conversation_002_response.wav
      └── ...
```

### Evaluation Output (if `evaluation_dir` specified)
```
evaluation_dir/
  └── 20260131_015423/
      └── 20260131_015423_conversations.jsonl
```

**Evaluation JSONL Format:**
```json
{"conversation_id": "conv_001", "audio_file": "audio_001.wav", "user_message": "What's the weather?", "assistant_response": "I don't have access to real-time weather data.", "latency_ms": 1234, "timestamp": "2026-01-31T01:54:23Z"}
{"conversation_id": "conv_002", "audio_file": "audio_002.wav", "user_message": "Tell me a joke", "assistant_response": "Why did the chicken cross the road?", "latency_ms": 987, "timestamp": "2026-01-31T01:54:45Z"}
```

### Aggregate Output (if `evaluation_output_file_override` specified)
All evaluations written to single file for batch processing:
```
C:\evaluations\wave1_aggregate.jsonl
```

## Integration Modes

### 1. Command Line (Direct)
**Use when:** Running manual tests or from shell scripts
```bash
python voice_agent_audio_input_evaluation.py --test_files_path "C:\datasets\test.jsonl"
```

### 2. Python Module Import
**Use when:** Building custom evaluation workflows or automation pipelines
```python
from voice_agent_audio_input_evaluation import main
main(test_files_path="...", evaluation_dir="...")
```

### 3. Agent Skills (Dynamic Discovery)
**Use when:** Using with Foundry Agent Service, GitHub Copilot CLI, or other agent frameworks

Agents discover this skill via `.github/skills/` or `skills/` directory structure and invoke based on natural language intent.

## Dataset Format

### JSONL Conversation Dataset
```json
{"audio_file": "audio_001.wav", "system_prompt": "You are a helpful assistant.", "expected_answer": "Expected response text", "tool_definitions": []}
{"audio_file": "audio_002.wav", "system_prompt": "You are concise.", "expected_answer": "Short response", "tool_definitions": [{"name": "get_weather", "description": "Get weather info"}]}
```

**Required fields:**
- `audio_file`: Path to WAV file (relative to .jsonl location)

**Optional fields:**
- `system_prompt`: Custom system instruction for this conversation
- `expected_answer`: Expected response for evaluation comparison
- `tool_definitions`: Array of tool definitions for function calling tests

## Requirements

- **Python**: 3.8+
- **Azure SDK**: `pip install azure-ai-voicelive azure-identity`
- **Audio**: WAV format files (16-bit PCM recommended)
- **Azure**: VoiceLive service endpoint and appropriate permissions

## Authentication

### Azure Identity (Recommended)
Script uses `DefaultAzureCredential` which tries (in order):
1. Managed Identity (for Azure deployments)
2. Azure CLI credentials (for local dev: `az login`)
3. Environment variables
4. Interactive browser login

### API Key (Fallback)
Set `AZURE_VOICELIVE_API_KEY` environment variable if Azure Identity cannot be used.

## Error Handling

The script handles:
- Missing audio files (skips with warning)
- Invalid JSONL syntax (reports line number)
- Missing system prompts (uses default)
- VoiceLive API errors (logs and continues)
- UTF-8 encoding issues (automatic sanitization)

## Related Skills

- **validate-dataset-consistency**: Validate dataset structure before evaluation
- **validate-dataset-quality**: Check dataset quality (prompts, tool definitions)

## Notes

- Creates timestamped directories to avoid overwriting results
- Supports both legacy WebSocket and new SDK-based VoiceLive connections
- Automatically handles UTF-8 encoding for international characters
- JSONL format allows easy streaming and processing of large result sets
- Each conversation is independent (parallelization possible in future)

## Support

For issues or questions:
1. Check environment variables are set correctly
2. Verify Azure Identity permissions on VoiceLive resource
3. Validate dataset format with `validate-dataset-consistency` skill
4. Review evaluation output files for error messages
