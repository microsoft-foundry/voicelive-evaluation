# Multi-Conversation Sample Dataset

This dataset demonstrates how to combine multiple conversations into a single JSONL file for evaluation with the `per-conversation` session mode.

## Dataset Structure

The dataset contains 9 turns from 2 different conversations:
- **Eiffel_Tower_Visit_1**: 6 turns about horoscopes and Eiffel Tower visit planning
- **DataOceanDemoComplexSession1**: 3 turns about creative writing

## Files

- `multiConversationSample.jsonl` - Combined JSONL dataset with conversationID field
- Audio files from both conversations (`.wav` files)

## Usage

### Per-Conversation Session Mode

Run the evaluation script with `--session-mode per-conversation` to process each conversation in its own session:

```powershell
python voice_agent_audio_input_evaluation_v2.py `
  --test-files sample_evaluation_input/MultiConversationSample/multiConversationSample.jsonl `
  --output-dir output `
  --evaluation output `
  --session-mode per-conversation
```

**How it works:**
1. The script reads the JSONL file and groups turns by `conversationID`
2. For each unique conversationID:
   - A new Voice Live session is created
   - All turns with that conversationID are processed in sequence
   - Session state is maintained across turns within the same conversation
3. When a new conversationID is encountered:
   - The previous session is closed
   - A new session is started for the new conversation
4. All evaluation data is aggregated into a single JSONL file
5. One evaluation run is performed on the aggregated results

### Session Mode Comparison

| Mode | Description | Use Case |
|------|-------------|----------|
| `single` | All files in one continuous session | Testing conversation continuity across all inputs |
| `per-file` | Each file in its own fresh session | Testing individual responses without context |
| `per-conversation` | New session per conversationID | Testing multiple conversations independently |

## JSONL Format

Each line in the JSONL file must include:

```json
{
  "WavPath": "audio_file.wav",
  "Question": "User question/transcript",
  "Answer": "Expected response",
  "expected_tool_calls": [],
  "tool_definitions": [],
  "conversationID": "unique_conversation_identifier"
}
```

**Important**: 
- Files with the same `conversationID` are processed in the same session
- Files should be sorted by conversationID and turn order
- The `conversationID` field is required when using `--session-mode per-conversation`
