# Voice Live Evaluation Agent

## Overview

An intelligent agent for automating VoiceLive evaluation workflows, including dataset validation, audio testing, and result analysis. Built on Azure AI Agents SDK with Azure Identity for secure API access.

**Key Principle:** All API calls use Azure Identity - NO API KEYS.

**Deployment Options:**
- **Local:** Run directly with `python agent.py`
- **Cloud:** Deploy to Azure AI Foundry Agent Service (see [Cloud Deployment](#cloud-deployment))

**Current Status:** ✅ Implemented
- ✅ 6 function tools (schema check, validation, evaluation, analysis)
- ✅ Smart session mode auto-detection
- ✅ Real-time console status output
- ✅ Progress tracking for long evaluations
- ✅ Dynamic metrics extraction (including custom metrics)
- ✅ Folder and file path handling
- ✅ OpenTelemetry tracing (console + Azure Monitor)
- ✅ AI Foundry Portal URL for cloud evaluation results

---

## Quick Start

### Prerequisites

```bash
# Install dependencies
pip install -r requirements.txt

# For Azure Monitor tracing (optional)
pip install azure-monitor-opentelemetry

# Create .env file in this folder:
PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>
MODEL_DEPLOYMENT_NAME=gpt-4.1-mini

# Optional: Azure Monitor connection string for cloud tracing
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=xxx;IngestionEndpoint=https://xxx.in.applicationinsights.azure.com/
```

### Run the Agent

```bash
# Interactive mode
python agent.py

# Single message mode
python agent.py --message "What datasets are available?"
python agent.py --message "Validate the Eiffel_Tower_Visit dataset"
python agent.py --message "How do I create a correct dataset?"
python agent.py --message "Run evaluation on Eiffel_Tower_Visit"
python agent.py --message "Analyze the evaluation results in output/2026-02-02_10-26-31/"

# With tracing options
python agent.py --verbose              # Enable DEBUG logging
python agent.py --trace-console        # Force console tracing (ignore Azure Monitor)
python agent.py --trace-content        # Include message content in traces (PII warning!)
```

### Example Session

```
You: What datasets are available?

⚙️  Searching for datasets...
✓ Found 6 datasets in 2 locations

Agent: Here are all 6 datasets found:

1. **Eiffel_Tower_Visit** (6 entries) - recommended mode: per-conversation
   Path: prototype_v1/sample_evaluation_input/Eiffel_Tower_Visit

2. **BingChat_en_minimal_10** (10 entries) - recommended mode: per-file
   Path: prototype_v1/sample_evaluation_input/BingChat_7days_en
[...]

You: Run evaluation on Eiffel_Tower_Visit

📁 Folder provided, using: Eiffel_Tower_Visit.jsonl

⚙️  Starting VoiceLive evaluation on Eiffel_Tower_Visit.jsonl...
   Session mode: per-conversation (auto-detected)
   Entries: 6
   Timeout: 30 minutes
✓ Evaluation COMPLETED for Eiffel_Tower_Visit.jsonl (185.3s)

Agent: Evaluation completed!
- Session mode: per-conversation (auto-detected)
- Duration: 3 minutes 5 seconds
- Output: prototype_v1/output/...

You: Analyze the evaluation results

⚙️  Analyzing evaluation results...
✓ Analyzed 4 turns, 14 metrics from 1 conversation(s)

Agent: Here are the evaluation insights:
- ✓ Strong groundedness (5.0/5)
- ✓ Strong intent_resolution (5.0/5)
- ⚠ task_completion is below 70% (50%)
- ✓ Good latency: 1.69s average
```

---

## Agent Tools

| Tool | Purpose |
|------|---------|
| `check_dataset_schema` | Quick check for required vs optional fields (RECOMMENDED first) |
| `list_datasets` | Find all JSONL datasets (shows complete list with metadata) |
| `validate_dataset_consistency` | MANDATORY structural validation before evaluation |
| `validate_dataset_quality` | ADVISORY content quality assessment |
| `run_voicelive_evaluation` | Execute VoiceLive API tests with smart session mode and parallel processing |
| `analyze_evaluation_results` | Analyze evaluation outputs for metrics and insights |

### Tool Parameters

Most parameters are optional - the agent infers sensible defaults from context.

| Tool | Key Parameters |
|------|----------------|
| `check_dataset_schema` | `dataset_path` (auto-resolved from folder) |
| `list_datasets` | `folder_path` (optional, defaults to common locations) |
| `validate_dataset_consistency` | `dataset_path`, `expected_turns` (optional), `ignore_comments` |
| `validate_dataset_quality` | `dataset_path`, `strict`, `verbose`, `json_output`, `ignore_comments` |
| `run_voicelive_evaluation` | `test_files_path`, `output_dir`, `evaluation_dir`, `session_mode`, `session_suffix`, `timeout_minutes`, `max_workers`, `parallel`, `verbose` |
| `analyze_evaluation_results` | `results_path` (folder or file, auto-finds aggregate JSONL) |

### Input vs Output Files

| File Type | Location | Tool to Use |
|-----------|----------|-------------|
| Input datasets | `sample_evaluation_input/` | `validate_dataset_consistency`, `validate_dataset_quality` |
| Evaluation outputs | `output/` folders | `analyze_evaluation_results` |

### Path Handling

The agent accepts both **folder paths** and **file paths**:
- **Folder**: Automatically finds the `.jsonl` file inside
  - For input datasets: Uses first `.jsonl` found
  - For evaluation results: Prioritizes `*aggregate*.jsonl` files
- **File**: Uses the file directly

---

## Features

### Parallel Processing

Evaluations run in parallel by default for faster processing of large datasets:

```
⚙️  Starting VoiceLive evaluation on dataset.jsonl...
   Session mode: per-conversation (auto-detected) | Workers: 4
   Entries: 100
   Timeout: 30 minutes
   Mode: Parallel (batch processor)
✓ Evaluation COMPLETED for dataset.jsonl (45.3s) [parallel: 4 workers]
```

**Worker Configuration:**

| Environment | Default Workers | Recommended |
|-------------|----------------|-------------|
| Local (laptop) | 4 | 2-4 |
| Local (workstation) | 4 | 4-8 |
| Cloud (Azure) | Set via env var | 8-16 |

**User Requests:**
- "Run evaluation with 8 workers" → `max_workers=8`
- "Run faster" / "more parallelism" → Higher worker count
- "Run sequentially" / "no parallelism" → `parallel=False`
- "Run in single mode" → `session_mode="single"` (always sequential)

**Environment Variable:**
```bash
# Set default workers (useful for cloud deployments)
export EVAL_AGENT_MAX_WORKERS=16
```

### Real-Time Console Status

Status prints **immediately** when tools execute:

```
⚙️  Searching for datasets...
✓ Found 6 datasets in 2 locations

⚙️  Running consistency validation on dataset.jsonl...
✓ Consistency validation PASSED

⚙️  Starting VoiceLive evaluation on dataset.jsonl...
   Session mode: per-conversation (auto-detected) | Workers: 4
   Entries: 6
   Timeout: 30 minutes
   Mode: Parallel (batch processor)
✓ Evaluation COMPLETED for dataset.jsonl (185.3s) [parallel: 4 workers]
```

### Status Icons
- ⚙️ Tool executing
- 📁 Folder detected, using file inside
- ✓ Success
- ⚠ Warning
- ✗ Error

### Session Mode Auto-Detection

| Dataset Structure | Auto-Selected Mode | Parallelism |
|-------------------|-------------------|-------------|
| Has `conversationID` field | `per-conversation` | ✅ Parallel |
| No `conversationID` field | `per-file` | ✅ Parallel |
| User explicitly requests | `single` | ❌ Sequential |

### Dynamic Metrics Analysis

The `analyze_evaluation_results` tool automatically discovers ALL metrics from multiple formats:
- **Foundry evaluation format**: Metrics from `results` array (groundedness, relevance, task_completion, etc.)
- **Raw evaluation output**: Metrics directly in entry (latency, turn counts, audio response rates)
- **Custom metrics**: Any numeric metrics added to evaluations
- **Pass/fail rates**: For each metric when available

Supported output formats:
- Foundry evaluator output (with `results` array)
- Raw VoiceLive evaluation output (with `metrics` object)
- Aggregated batch processor output

---

## Tracing and Logging

The agent supports OpenTelemetry-based tracing compatible with both local development and cloud deployment, plus file-based conversation logging for agent evaluation.

### Log Files (Foundry Evaluation Compatible)

Logs are stored in `./logs/` (or `EVAL_AGENT_LOG_DIR`) with three file types:

| File | Format | Purpose |
|------|--------|---------|
| `agent_conversations_{date}.jsonl` | Foundry-compatible JSONL | Agent evaluation with Azure AI Evaluation SDK |
| `agent_traces_{date}.jsonl` | OpenTelemetry spans | Debugging and performance analysis |
| `agent_{date}.log` | Structured JSON | General application logging |

**Conversation log format** (compatible with `AIAgentConverter` and Foundry evaluators):
```json
{
  "id": "uuid",
  "thread_id": "uuid",
  "run_id": "uuid",
  "context": [{"role": "user", "content": "..."}, ...],
  "input": "What datasets are available?",
  "output": "I found 5 datasets...",
  "tool_calls": [{"name": "list_datasets", "arguments": {...}, "result": "..."}],
  "system_message": "You are the Voice Live Evaluation Agent...",
  "timestamp": "2026-02-02T12:00:00Z",
  "metadata": {"model": "gpt-4o-mini", "thread_id": "..."}
}
```

### Evaluating Agent Performance

Use the conversation logs with Azure AI Foundry evaluation SDK:

```python
from azure.ai.evaluation import IntentResolutionEvaluator, TaskAdherenceEvaluator
import json

# Load conversation logs
with open("logs/agent_conversations_2026-02-02.jsonl") as f:
    conversations = [json.loads(line) for line in f]

# Evaluate each turn
evaluator = IntentResolutionEvaluator(model_config=model_config)
for turn in conversations:
    result = evaluator(
        query=turn["input"],
        response=turn["output"],
        context=turn["context"],
    )
    print(f"Intent Resolution: {result}")
```

### Local Development (Console Tracing)

By default, traces are written to files. Enable console output with:

```bash
python agent.py --verbose  # Enable DEBUG level (includes console spans)
```

### Cloud Deployment (Azure Monitor)

Set the Application Insights connection string for production tracing:

```bash
# .env file or environment variable
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=xxx;IngestionEndpoint=https://xxx.in.applicationinsights.azure.com/
```

Traces automatically flow to:
- Azure Monitor Application Insights
- Foundry project "Tracing" tab (if using AIProjectClient)
- Local JSONL files (always, for backup)

### Tracing Options

| Option | Description |
|--------|-------------|
| `--verbose` | Enable DEBUG level logging (console spans) |
| `--trace-console` | Force console tracing even if Azure Monitor configured |
| `--trace-content` | Include message content in traces (⚠️ may contain PII) |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Azure Monitor connection (enables cloud tracing) |
| `EVAL_AGENT_LOG_DIR` | Log directory (default: `./logs`) |
| `EVAL_AGENT_LOG_LEVEL` | Logging level: DEBUG, INFO, WARNING, ERROR |
| `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` | Set `true` to trace message content |

### What Gets Logged

| Category | Details |
|----------|---------|
| Conversations | User input, agent output, tool calls, context, timestamps |
| Traces | Spans with parent/child relationships, attributes, events |
| Tool executions | Name, arguments, result, status, duration |
| Errors | Exception details with stack traces |

---

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `PROJECT_ENDPOINT` | Yes | Azure AI Foundry project endpoint |
| `MODEL_DEPLOYMENT_NAME` | No | Model to use (default: gpt-4o-mini) |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | No | Azure Monitor (enables cloud tracing) |
| `EVAL_AGENT_MAX_WORKERS` | No | Default parallel workers (default: 4) |
| `EVAL_AGENT_OUTPUT_DIR` | No | Evaluation output directory (default: ./output) |
| `EVAL_AGENT_LOG_DIR` | No | Log directory (default: ./logs) |
| `EVAL_AGENT_LOG_LEVEL` | No | Logging level (default: INFO) |

### Storage Directories

| Directory | Purpose | Environment Variable |
|-----------|---------|---------------------|
| `./output/` | Evaluation results and audio files | `EVAL_AGENT_OUTPUT_DIR` |
| `./logs/` | Conversation logs and traces | `EVAL_AGENT_LOG_DIR` |

For cloud deployment, set these environment variables to cloud storage paths (e.g., Azure Blob mounted paths).

### Timeout Settings

Default evaluation timeout is **30 minutes**. For longer evaluations:
```
"Run evaluation on large_dataset with timeout 60 minutes"
```

---

## Dependencies

See `requirements.txt`:
- `azure-ai-agents>=1.1.0` - Azure AI Agents SDK
- `azure-ai-projects>=2.0.0b2` - Azure AI Projects SDK (Foundry evaluation)
- `azure-identity>=1.25.1` - Azure authentication
- `azure-ai-voicelive>=1.2.0b2` - VoiceLive SDK
- `python-dotenv>=1.0.0` - Environment configuration
- `opentelemetry-sdk>=1.20.0` - Tracing (required)
- `azure-monitor-opentelemetry>=1.6.0` - Cloud tracing (optional)

---

## Related Projects

| Project | Path | Purpose |
|---------|------|---------|
| Dataset Validators | `../dataset_validator/` | Validation scripts |
| VoiceLive Evaluation | `../prototype_v1/` | Audio evaluation script |
| Skills | `./skills/` | Skill definitions for agent integration |

### Skills

Skill definitions in `./skills/` enable AI agent integration:

| Skill | Description |
|-------|-------------|
| `voicelive-audio-evaluation` | VoiceLive audio evaluation execution |
| `batch-processor-py` | Parallel batch processing for large datasets |
| `validate-dataset-consistency` | Structural validation of JSONL datasets |
| `validate-dataset-quality` | Content quality assessment for datasets |

Skills allow AI agents (GitHub Copilot CLI, Azure AI Agents) to discover and invoke tools via natural language.

---

## Cloud Deployment

The agent can be deployed to Azure AI Foundry Agent Service for cloud execution.

### Architecture

| Component | Service |
|-----------|---------|
| Agent hosting | Azure AI Foundry Agent Service (hosted container) |
| Storage | Azure Blob Storage (datasets, outputs) |
| LLM | Azure OpenAI (gpt-4o-mini) via Foundry |
| Tracing | Foundry native tracing |
| Auth | Managed Identity (no secrets) |

### Why This Architecture

| Decision | Rationale |
|----------|-----------|
| **Containers** | Agent uses subprocess calls - needs full Python runtime |
| **Foundry Agent Service** | Native integration, simpler than Container Apps |
| **No Key Vault** | Pure Entra ID auth - no secrets to store |
| **No Container Registry** | Foundry manages containers internally |
| **No App Insights** | Foundry has native tracing |

### Deployment with azd

```bash
# Deploy everything
azd up

# Tear down
azd down
```

### Required Azure Services

- Azure AI Foundry (hosting + LLM)
- Azure Blob Storage

**Estimated cost:** $55-220/month

See [ARCHITECTURE.md](ARCHITECTURE.md#cloud-deployment-architecture) for detailed design decisions and the full deployment plan.

---

## Roadmap & Future Features

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed design discussions.

### Planned Enhancements

| Feature | Description | Priority |
|---------|-------------|----------|
| **Create Dataset** | Generate evaluation datasets from audio folders via natural language | High |
| **Flexible VoiceLive Config** | Runtime configuration of VoiceLive API parameters | High |
| **VoiceLive SDK Migration** | Replace subprocess calls with native SDK integration | Medium |
| **Comparative Reports** | Compare results across evaluation runs | Medium |
| **CI/CD Integration** | GitHub Actions and Azure DevOps pipeline support | Medium |
| **Dataset Augmentation** | Auto-generate dataset variations for testing | Low |

### Contributing Ideas

Have a feature idea? See the "Feature Ideas" section in [ARCHITECTURE.md](ARCHITECTURE.md) for the current roadmap and add your suggestions there.

---

## Troubleshooting

### Common Issues

**"Permission denied" on folder path**
- The evaluation script needs a `.jsonl` file, not a folder
- Fixed: Agent now auto-detects folders and finds the `.jsonl` inside

**Evaluation timeout**
- Default is 30 minutes
- Increase with `timeout_minutes` parameter or ask for longer timeout

**ImportError for VoiceLive SDK**
- Ensure `azure-ai-voicelive>=1.2.0b2` is installed
- Run: `pip install --upgrade --pre azure-ai-voicelive`

**Quality validation fails on evaluation output**
- Use `analyze_evaluation_results` for output files
- Use `validate_dataset_quality` only for input datasets
