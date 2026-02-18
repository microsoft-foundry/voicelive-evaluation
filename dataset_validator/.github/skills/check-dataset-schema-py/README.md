# check-dataset-schema Skill

Quick pre-validation check to analyze dataset fields and identify what's required vs optional.

## Purpose

Use this skill BEFORE full validation to understand what defaults will be applied during evaluation. Unlike consistency validation (which may fail on missing fields), this tool clearly distinguishes:

- **REQUIRED fields** - Evaluation cannot proceed without these
- **OPTIONAL fields** - Evaluation uses defaults if missing

## Field Requirements

### Required (evaluation fails without)
| Field | Description |
|-------|-------------|
| `WavPath` or `audio` | Path to audio file |

### Optional (uses defaults if missing)
| Field | Default | Description |
|-------|---------|-------------|
| `Question`/`question` | None | User query transcript |
| `Answer`/`answer` | None (skips ResponseCompleteness) | Expected response |
| `tool_definitions` | [] (no tools) | Tool/function definitions |
| `conversationID`/`conversation_id` | 'default' | Conversation grouping |
| `system_prompt` | Script default | Agent instructions |

## Usage

```bash
# Basic schema check
python check_dataset_schema.py dataset.jsonl

# Check folder
python check_dataset_schema.py ./datasets/wave1/

# JSON output for programmatic use
python check_dataset_schema.py dataset.jsonl --json
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All fields present |
| 1 | Error or missing required fields |
| 2 | Can proceed but optional fields missing |

## Workflow Guidance

**When optional fields are missing:**
Ask the user if they want to proceed with defaults. Explain what defaults will be used.

**When required fields are missing:**
Stop and explain which fields need to be added.

## Example Output

```
============================================================
DATASET SCHEMA CHECK
============================================================
File: dataset.jsonl
Entries: 10

REQUIRED FIELDS (evaluation fails without these):
----------------------------------------
  ✅ All required fields present

OPTIONAL FIELDS (uses defaults if missing):
----------------------------------------
  ⚠  system_prompt: 0/10 present
     → Custom agent instructions
     → Default: Script default system prompt
  ⚠  conversation_id: 0/10 present
     → Conversation grouping identifier
     → Default: 'default' (all entries treated as one conversation)

============================================================
⚠  CAN PROCEED WITH DEFAULTS
   Optional fields missing - evaluation will use default values.
```
