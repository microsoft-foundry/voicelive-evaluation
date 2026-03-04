# Voice Metrics Evaluators

This module provides **four separate custom code-based evaluators** for evaluating voice agent performance in Azure AI Foundry. Each evaluator provides its own pass rate, enabling granular visibility into different aspects of voice quality.

## Overview

| Evaluator | Metric | Pass Threshold | Excellent Threshold |
|-----------|--------|----------------|---------------------|
| `transcriptionLatencyEvaluator` | ASR transcription speed | ≤500ms | ≤300ms |
| `responseLatencyEvaluator` | TTS/response generation speed | ≤2s | ≤1s |
| `audioDeliveryEvaluator` | Audio response delivery success | Delivered = true | N/A |
| `turnAlignmentEvaluator` | Expected vs actual turn matching | Aligned or Shifted | N/A |

## Files

### 1. `voice_metrics_evaluator.py` (Core Module)

The main module containing:
- Four individual evaluator code blocks
- Creation functions for Foundry deployment
- Testing criteria generators
- Local analysis utilities

**Key Functions:**
```python
from voice_metrics_evaluator import (
    # Create individual evaluators in Foundry
    create_transcription_latency_evaluator,
    create_response_latency_evaluator,
    create_audio_delivery_evaluator,
    create_turn_alignment_evaluator,
    
    # Create all at once
    create_all_voice_metrics_evaluators,
    
    # Get testing criteria for eval groups
    get_all_voice_metrics_testing_criteria,
    
    # Local analysis (no Foundry required)
    analyze_voice_metrics_locally,
    print_voice_metrics_summary,
)
```

---

### 2. `voice_metrics_evaluator_local.py` (Local Testing Script)

A standalone command-line tool for running voice metrics evaluation locally without Azure AI Foundry. Useful for:
- Quick local analysis during development
- Testing evaluation logic before Foundry deployment
- Debugging and validating aggregate data files
- CI/CD pipeline integration

**Usage:**
```bash
# Basic usage
python voice_metrics_evaluator_local.py path/to/aggregate.jsonl

# Verbose output (per-record details)
python voice_metrics_evaluator_local.py aggregate.jsonl --verbose

# Simulate Foundry grades
python voice_metrics_evaluator_local.py aggregate.jsonl --simulate-grades

# Save detailed results to JSON
python voice_metrics_evaluator_local.py aggregate.jsonl --output results.json

# All options
python voice_metrics_evaluator_local.py aggregate.jsonl -v -s -o results.json
```

**Command-Line Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--verbose` | `-v` | Print detailed per-record analysis |
| `--simulate-grades` | `-s` | Show grades as they would appear in Foundry |
| `--output FILE` | `-o` | Save detailed results to JSON file |

**Exit Codes:**
- `0`: All evaluators have ≥90% pass rate
- `1`: Some evaluators have <90% pass rate
- `2`: File not found
- `3`: Other error

**Example Output:**
```
======================================================================
VOICE METRICS SUMMARY (Individual Evaluator Preview)
======================================================================

Total Records: 15

----------------------------------------------------------------------
INDIVIDUAL EVALUATOR PASS RATES
----------------------------------------------------------------------

1. TRANSCRIPTION LATENCY EVALUATOR
   Range: 0.191s - 0.459s (avg: 0.321s)
   Excellent (<=300ms): 6/15
   Pass (<=500ms):      15/15
   PASS RATE: 100.0%

2. RESPONSE LATENCY EVALUATOR
   Range: 0.830s - 1.353s (avg: 1.087s)
   Excellent (<=1s): 6/15
   Pass (<=2s):      15/15
   PASS RATE: 100.0%

3. AUDIO DELIVERY EVALUATOR
   Delivered: 15/15
   PASS RATE: 100.0%

4. TURN ALIGNMENT EVALUATOR
   Aligned:  15/15
   Shifted:  0/15 (multi-input, considered pass)
   Extra:    0/15
   Missing:  0/15
   PASS RATE: 100.0%
```

---

### 3. `voice_agent_evaluation_with_metrics.py` (Foundry Integration)

Extended version of `voice_agent_evaluation.py` that integrates voice metrics evaluators with the full Azure AI Foundry evaluation pipeline.

**Features:**
- Combines agent evaluators (task completion, tool calls, etc.) with voice metrics
- Configurable evaluation scenarios
- Local preview before Foundry submission
- Automatic evaluator creation in Foundry

**Configuration Options:**
```python
main(
    eval_input_path="path/to/aggregate.jsonl",
    include_voice_metrics=True,      # Enable voice metrics evaluators
    include_agent_evaluators=True,   # Enable standard agent evaluators
    setup_evaluators=True,           # Create evaluators in Foundry
    run_local_preview=True,          # Run local analysis first
)
```

**Predefined Scenarios:**
| Scenario | Voice Metrics | Agent Evaluators | Description |
|----------|---------------|------------------|-------------|
| `VoiceMetricsDemo` | ✓ | ✓ | Full evaluation with all evaluators |
| `VoiceMetricsOnly` | ✓ | ✗ | Quick voice quality check |
| `AgentOnly` | ✗ | ✓ | Standard agent evaluation |

**Usage:**
```python
# Edit the __main__ section to set your scenario
evaluation_scenario = 'VoiceMetricsDemo'

# Or programmatically:
from voice_agent_evaluation_with_metrics import main

status, report_url = main(
    eval_input_path="./aggregate.jsonl",
    eval_group_name="My Evaluation",
    include_voice_metrics=True,
    include_agent_evaluators=True,
    setup_evaluators=True,
)
```

---

## Data Format

The evaluators expect aggregate JSONL files with the following structure:

```json
{
  "query": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": [{"type": "text", "text": "User message"}]}
  ],
  "response": [...],
  "metrics": {
    "turn-audio-transcription-latency-in-seconds": 0.321,
    "turn-audio-resonse-latency-in-seconds": 1.087,
    "audio_response_received": true,
    "logical_turn_number": 1,
    "inputs_in_turn": 1,
    "responses_in_turn": 1
  }
}
```

**Required Metrics Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `turn-audio-transcription-latency-in-seconds` | float | ASR transcription latency |
| `turn-audio-resonse-latency-in-seconds` | float | TTS/response generation latency |
| `audio_response_received` | boolean | Whether audio was delivered |
| `logical_turn_number` | integer | Actual turn number from the agent |

**Turn Alignment:**
The expected turn number is automatically derived by counting user messages in the `query` array. No source dataset file is required.

---

## Quick Start

### Local Testing (No Foundry Required)

```bash
# 1. Navigate to the evaluation_harness directory
cd evaluation_harness

# 2. Run local evaluation
python voice_metrics_evaluator_local.py your_aggregate.jsonl

# 3. View detailed output
python voice_metrics_evaluator_local.py your_aggregate.jsonl --verbose --simulate-grades
```

### Foundry Integration

```python
# 1. Import the functions
from voice_metrics_evaluator import (
    create_all_voice_metrics_evaluators,
    get_all_voice_metrics_testing_criteria,
)

# 2. Create evaluators in Foundry (one-time setup)
create_all_voice_metrics_evaluators(project_client)

# 3. Add to your testing criteria
testing_criteria = [
    # ... your other evaluators ...
]
testing_criteria.extend(get_all_voice_metrics_testing_criteria())

# 4. Create eval group with all evaluators
eval_object = client.evals.create(
    name="Voice Agent Evaluation",
    data_source_config=data_source_config,
    testing_criteria=testing_criteria,
)
```

### Full Pipeline Example

```bash
# Run the integrated evaluation script
python voice_agent_evaluation_with_metrics.py
```

---

## Evaluator Details

### Transcription Latency Evaluator
Measures how quickly speech is transcribed to text (ASR speed).

| Score | Label | Threshold |
|-------|-------|-----------|
| 1.0 | excellent | ≤300ms |
| 0.8 | good | ≤500ms |
| 0.5 | acceptable | ≤1000ms |
| 0.2 | slow | >1000ms |

### Response Latency Evaluator
Measures how quickly the agent generates and delivers a response (TTS speed).

| Score | Label | Threshold |
|-------|-------|-----------|
| 1.0 | excellent | ≤1s |
| 0.8 | good | ≤2s |
| 0.5 | acceptable | ≤3s |
| 0.2 | slow | >3s |

### Audio Delivery Evaluator
Binary check for whether the audio response was successfully delivered.

| Score | Label | Condition |
|-------|-------|-----------|
| 1.0 | delivered | `audio_response_received == true` |
| 0.0 | not_delivered | `audio_response_received == false` |

### Turn Alignment Evaluator
Compares expected turn number (derived from query) with actual turn number.

| Score | Label | Condition |
|-------|-------|-----------|
| 1.0 | aligned | Expected == Actual |
| 0.8 | shifted | Actual == Expected + 1 (multi-input turn) |
| 0.3-0.8 | extra_turns | Actual > Expected |
| 0.3-0.8 | missing_turns | Actual < Expected |

---

## Environment Setup

Ensure your `.env` file contains:
```
PROJECT_ENDPOINT=https://your-project.azure.com
AOAI_DEPLOYMENT_NAME=your-gpt-deployment
AOAI_REASONING_DEPLOYMENT_NAME=your-o1-deployment
```

---

## Author

Voice Live Evaluation Team  
January 2026
