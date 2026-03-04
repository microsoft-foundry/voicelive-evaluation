# Batch Processor Skill

Multi-threaded batch processor for VoiceLive audio evaluations.

## Overview

The batch processor wraps `voice_agent_audio_input_evaluation.py` with parallel execution capabilities using Python's `ThreadPoolExecutor`. Each session runs as a separate subprocess to ensure isolation and avoid global state conflicts.

## When to Use

- **Large datasets** (50+ entries) that benefit from parallel processing
- **per-file or per-conversation modes** with multiple sessions
- When evaluation speed is critical

## Quick Start

```bash
# Parallel evaluation with 4 workers
python batch_processor.py \
  --test-files dataset.jsonl \
  --session-mode per-conversation \
  --max-workers 4

# Process all datasets in a folder
python batch_processor.py \
  --test-files-folder ./datasets \
  --session-mode per-file \
  --max-workers 8
```

## Worker Configuration

| Environment | Recommended Workers | Rationale |
|-------------|-------------------|-----------|
| Local (laptop) | 2-4 | Avoid overloading CPU/memory |
| Local (workstation) | 4-8 | More resources available |
| Cloud (Azure VM) | 8-16 | Scale with available vCPUs |

### Setting Defaults

```bash
# Environment variable for default worker count
export EVAL_AGENT_MAX_WORKERS=8
```

## Session Modes

| Mode | Parallelism | Use Case |
|------|-------------|----------|
| `per-conversation` | ✅ Parallel | Multi-turn conversations with conversationID |
| `per-file` | ✅ Parallel | Independent audio files |
| `single` | ❌ Sequential | All files in one continuous session |

## How It Works

1. **Parse dataset** - Read JSONL and extract entries
2. **Prepare sessions** - Group by conversationID or create per-file sessions
3. **Execute parallel** - Run N concurrent subprocess workers
4. **Aggregate results** - Thread-safe write to shared JSONL (using filelock)
5. **Final evaluation** - Run evaluators on aggregated output

## Agent Integration

The evaluation agent automatically uses batch_processor.py when appropriate:

```python
# Agent auto-selects batch processor when max_workers > 1
run_voicelive_evaluation(
    test_files_path="dataset.jsonl",
    max_workers=4  # Enables batch processor
)

# Force sequential execution
run_voicelive_evaluation(
    test_files_path="dataset.jsonl",
    parallel=False  # Uses single script
)
```

## Output Structure

```
output/
└── 2024-12-11_10-30-00/
    ├── temp/                          # Cleaned after processing
    ├── aggregate_dataset.jsonl        # Combined evaluation data
    ├── operational_summary_*.json     # Processing metrics
    └── evaluation_results/            # Final evaluation output
```

## Error Handling

- **Timeout**: Each subprocess has configurable timeout (default: 600s)
- **Failures**: Failed sessions are logged; processing continues
- **Cleanup**: Temp files removed even on partial failure

## See Also

- `voice_agent_audio_input_evaluation.py` - Single session evaluation
- `voice_agent_evaluation.py` - Evaluation metrics
