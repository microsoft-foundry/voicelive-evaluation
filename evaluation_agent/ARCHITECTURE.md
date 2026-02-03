# Voice Live Evaluation Agent - Architecture & Design

This document captures architecture decisions, design considerations, implementation approaches evaluated, and open topics for future development.

---

## Table of Contents

1. [Current Architecture](#current-architecture)
2. [Design Decisions](#design-decisions)
3. [Implementation Approaches Evaluated](#implementation-approaches-evaluated)
4. [Component Details](#component-details)
5. [Authentication & Security](#authentication--security)
6. [Open Topics & Future Work](#open-topics--future-work)

---

## Current Architecture

### Implemented Approach: Azure AI Agents SDK with Function Tools

We implemented a **Python-based agent using Azure AI Agents SDK** with local function tools. This is a variation of the "Pure Foundry" approach, optimized for rapid iteration.

```
┌─────────────────────────────────────────────────────────┐
│                  User (Natural Language)                │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│              Azure AI Foundry Project                    │
│  ┌────────────────────────────────────────────────────┐ │
│  │         Voice Live Evaluation Agent                │ │
│  │         (Azure AI Agents SDK)                      │ │
│  │                                                    │ │
│  │  ┌──────────────────────────────────────────────┐  │ │
│  │  │            6 Function Tools                  │  │ │
│  │  │  • check_dataset_schema                      │  │ │
│  │  │  • list_datasets                             │  │ │
│  │  │  • validate_dataset_consistency              │  │ │
│  │  │  • validate_dataset_quality                  │  │ │
│  │  │  • run_voicelive_evaluation                  │  │ │
│  │  │  • analyze_evaluation_results                │  │ │
│  │  └──────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────┘ │
└────────────────────────┬────────────────────────────────┘
                         │ Azure Identity (DefaultAzureCredential)
         ┌───────────────┼───────────────┐
         │               │               │
         ▼               ▼               ▼
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  Dataset    │  │  VoiceLive  │  │  Foundry    │
│ Validators  │  │    SDK      │  │ Evaluation  │
│ (subprocess)│  │ (subprocess)│  │   Output    │
└─────────────┘  └─────────────┘  └─────────────┘
```

### Key Design Choices

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Framework | Azure AI Agents SDK | Native Azure integration, function tools, minimal code |
| Tool execution | Subprocess calls | Isolation, existing scripts work unchanged |
| Authentication | DefaultAzureCredential | Works locally (CLI) and in production (Managed Identity) |
| Session management | Auto-detection | Reduces user friction, intelligent defaults |
| Progress feedback | Console print + return values | Immediate visibility during long operations |
| Tracing | OpenTelemetry + Azure Monitor | Standard protocol, dual local/cloud support |
| Parallel processing | Conditional batch processor | Uses batch_processor.py when workers > 1, single script otherwise |

---

## Design Decisions

### 1. Function Tools over Skills

**Decision:** Use `FunctionTool` with Python functions rather than external skill definitions.

**Rationale:**
- Simpler development and debugging
- No separate skill deployment needed
- Functions can directly call subprocess
- Auto-execution via `enable_auto_function_calls()`

**Trade-off:** Less portable than standalone skills, but faster iteration.

### 2. Subprocess for Script Execution

**Decision:** Call existing validation/evaluation scripts via subprocess rather than importing.

**Rationale:**
- Scripts work unchanged (no refactoring needed)
- Process isolation (encoding, environment)
- Can capture and parse stdout/stderr
- Timeout handling per-operation

**Trade-off:** Slight overhead vs direct import, but better isolation.

### 3. Smart Path Handling

**Decision:** Accept both folder paths and file paths, auto-resolve to `.jsonl` files.

**Rationale:**
- Users often reference datasets by folder name
- Reduces friction and errors
- Agent instructions mention datasets by name, not full path

**Implementation:**
- Input datasets: Uses first `.jsonl` file found in folder
- Evaluation results: Prioritizes `*aggregate*.jsonl` files (batch processor output)

### 4. Dynamic Metrics Extraction

**Decision:** Discover ALL metrics dynamically from multiple output formats.

**Rationale:**
- Foundry evaluations can have custom metrics
- Raw evaluation output has different structure than Foundry format
- Future-proof against metric additions
- No code changes needed for new metrics

**Supported formats:**
- Foundry evaluator output: `entry.results[].score`
- Raw evaluation output: `entry.metrics.*`
- Nested format: `entry.datasource_item.metrics.*`

### 5. Real-Time Console Status

**Decision:** Print status immediately during function execution.

**Rationale:**
- Long operations (evaluations) need visibility
- Agent response comes after function completes
- Users see progress without waiting

### 6. OpenTelemetry-Based Tracing

**Decision:** Use OpenTelemetry as the tracing standard with automatic exporter selection.

**Rationale:**
- Industry standard protocol (vendor-neutral)
- Native integration with Azure Monitor / Application Insights
- Azure AI Agents SDK has built-in OpenTelemetry instrumentation
- Same code works locally (console) and in production (cloud)

**Implementation:**
```
┌─────────────────────────────────────────────────────────────┐
│                     tracing.py Module                        │
├─────────────────────────────────────────────────────────────┤
│  setup_tracing()                                            │
│    ├── Check APPLICATIONINSIGHTS_CONNECTION_STRING          │
│    │     ├── Set? → Azure Monitor exporter                  │
│    │     └── Not set? → Console exporter                    │
│    ├── Configure OpenTelemetry TracerProvider               │
│    ├── Instrument Azure AI Agents SDK (AIAgentsInstrumentor)│
│    └── Configure structured logging                         │
├─────────────────────────────────────────────────────────────┤
│  get_tracer(name) → OpenTelemetry Tracer                    │
│  get_logger(name) → Python Logger                           │
│  log_tool_execution(tool, status, details)                  │
│  trace_tool_function(func) → Decorator                      │
└─────────────────────────────────────────────────────────────┘
```

**What Gets Traced:**
| Span/Event | Attributes |
|------------|------------|
| `agent.main` | model, mode (single/interactive), cloud_tracing |
| `agent.session` | session_id |
| `tool.*` | tool.name, tool.args, tool.status, tool.error |
| Tool events | dataset, entries, elapsed_seconds |

**Trade-offs:**
- Adds ~15 dependencies (OpenTelemetry stack)
- Console tracing can be verbose in DEBUG mode
- Azure Monitor requires connection string configuration

### 7. Conditional Parallel Processing

**Decision:** Use batch_processor.py for parallel execution, single script for sequential.

**Rationale:**
- Batch processor already tested and handles subprocess isolation
- ThreadPoolExecutor provides clean parallel execution
- Filelock ensures thread-safe result aggregation
- No need to duplicate parallel logic in agent

**Implementation:**
```python
# Decision logic in run_voicelive_evaluation()
use_batch_processor = effective_workers > 1 and batch_processor_path.exists()

if use_batch_processor:
    # Uses: batch_processor.py --max-workers N
else:
    # Uses: voice_agent_audio_input_evaluation.py (sequential)
```

**Conditions for sequential mode:**
- `parallel=False` explicitly set
- `max_workers=1`
- `session_mode="single"` (continuous conversation)
- Very small datasets (workers auto-limited to entry count)

**Trade-offs:**
- Two code paths to maintain
- Batch processor adds subprocess overhead
- But: subprocess isolation prevents state conflicts in parallel sessions

### 8. Agent-Owned Storage Directories

**Decision:** Agent uses its own output/log directories rather than downstream script defaults.

**Rationale:**
- Agent should control where its artifacts are stored
- Enables consistent configuration for local vs cloud deployment
- Single environment variable configures storage location
- Easier to find agent outputs (in `./output/` not `prototype_v1/output/`)

**Implementation:**
```python
def get_agent_output_directory() -> Path:
    env_path = os.environ.get("EVAL_AGENT_OUTPUT_DIR")
    if env_path:
        return Path(env_path)
    return SCRIPT_DIR / "output"  # Agent's local directory
```

**Cloud deployment:** Set `EVAL_AGENT_OUTPUT_DIR` to mounted cloud storage path.

---

## Implementation Approaches Evaluated

We evaluated 4 approaches before implementation:

### Approach 1: Pure Foundry Agent Service ✅ SELECTED (Modified)

**Description:** Native Foundry Agent Service with minimal custom code.

**Pros:**
- ✅ Minimal code (~500 lines YAML)
- ✅ Built-in skill discovery
- ✅ Native Azure Identity
- ✅ Production-ready

**Cons:**
- ⚠️ Learning curve for Foundry patterns
- ⚠️ Constrained to Foundry capabilities

**What we implemented:** A Python variation using Azure AI Agents SDK with function tools, which gives us Foundry hosting benefits with Python flexibility.

### Approach 2: Semantic Kernel + Foundry

**Description:** SK agent with plugins, deployed to Foundry.

**Pros:**
- ✅ Powerful auto-planning
- ✅ Rich plugin ecosystem
- ✅ Flexible

**Cons:**
- ⚠️ ~2000 lines of code
- ⚠️ Packaging complexity
- ⚠️ Steeper learning curve

**Status:** Not selected for initial implementation, but viable for future if complex planning needed.

### Approach 3: LangChain + Foundry

**Description:** LangChain agent with tools, deployed to Foundry.

**Pros:**
- ✅ Rich tooling ecosystem
- ✅ LLM-first design
- ✅ Strong community

**Cons:**
- ⚠️ ~2500 lines of code
- ⚠️ Azure Identity integration less native
- ⚠️ Tool wrapping overhead

**Status:** Not selected. Similar benefits to SK with more code.

### Approach 4: Hybrid (Foundry + Python Extensions)

**Description:** Foundry core + Python extensions for complex logic.

**Pros:**
- ✅ Best of both worlds
- ✅ Gradual migration path
- ✅ Flexibility

**Cons:**
- ⚠️ Two systems to understand
- ⚠️ Extension deployment complexity

**Status:** Partially adopted. We use Python functions but within Azure AI Agents SDK rather than as separate extensions.

### Comparison Matrix

| Feature | Pure Foundry | Semantic Kernel | LangChain | Hybrid | **Implemented** |
|---------|--------------|-----------------|-----------|--------|-----------------|
| Code to Maintain | ~500 lines | ~2000 lines | ~2500 lines | ~2200 lines | **~800 lines** |
| Azure Identity | Native | Good | Moderate | Good | **Native** |
| Skill Discovery | Built-in | Manual | Manual | Built-in | **Function Tools** |
| Learning Curve | Moderate | Steep | Moderate | Steep | **Low** |
| Flexibility | Moderate | High | High | High | **High** |
| Timeline to MVP | 3-4 weeks | 5-6 weeks | 5-6 weeks | 5 weeks | **1 week** |

---

## Component Details

### Agent Core (`agent.py`)

```
agent.py (~1200 lines)
├── Function Tools (6)
│   ├── check_dataset_schema()
│   ├── list_datasets()
│   ├── validate_dataset_consistency()
│   ├── validate_dataset_quality()
│   ├── run_voicelive_evaluation()
│   └── analyze_evaluation_results()
├── Helper Functions
│   ├── _detect_session_mode()
│   ├── _count_dataset_entries()
│   └── _run_subprocess_with_progress()
├── Agent Setup
│   ├── AGENT_INSTRUCTIONS (system prompt)
│   ├── create_agent()
│   └── StreamingEventHandler
└── Entry Points
    ├── interactive_mode()
    ├── run_conversation()
    └── main()
```

### Dependencies

| Package | Purpose | Version |
|---------|---------|---------|
| `azure-ai-agents` | Agent SDK | >=1.1.0 |
| `azure-identity` | Authentication | >=1.25.1 |
| `azure-ai-voicelive` | VoiceLive SDK | >=1.2.0b2 |
| `python-dotenv` | Environment config | >=1.0.0 |

### External Scripts Called

| Script | Location | Purpose |
|--------|----------|---------|
| `validate_dataset_consistency.py` | `dataset_validator/` | Structural validation |
| `validate_dataset_quality.py` | `dataset_validator/` | Content quality |
| `voice_agent_audio_input_evaluation.py` | `prototype_v1/` | VoiceLive evaluation |

---

## Authentication & Security

### Azure Identity Patterns Used

**1. DefaultAzureCredential (Dev & Production)**
```python
from azure.identity import DefaultAzureCredential
credential = DefaultAzureCredential()
```

Tries authentication methods in order:
1. Environment variables
2. Managed Identity (in Azure)
3. Azure CLI (local dev)
4. Visual Studio Code
5. Interactive browser

**2. No API Keys**
- All Azure services use Azure AD tokens
- No secrets in code or config
- Key Vault only if certificates needed

### RBAC Permissions Required

| Permission | Resource | Purpose |
|------------|----------|---------|
| `Cognitive Services User` | Azure OpenAI | LLM access |
| `Storage Blob Data Reader` | Storage Account | Read datasets |
| `Storage Blob Data Contributor` | Storage Account | Write results |

---

## Open Topics & Future Work

### Completed ✅

| Item | Description | Status |
|------|-------------|--------|
| Parallel batch processing | Integrated batch_processor.py for parallel evaluations | ✅ Done |
| Folder path resolution | Auto-find JSONL files in folders for all tools | ✅ Done |
| Multi-format metrics extraction | Support Foundry, raw, and nested metric formats | ✅ Done |
| OpenTelemetry tracing | Console + Azure Monitor with file logging | ✅ Done |
| Conversation logging | Foundry-compatible JSONL for agent evaluation | ✅ Done |
| Foundry portal URL | Extract and display report_url from cloud evaluations | ✅ Done |
| Azure AI Projects SDK | Added as required dependency for Foundry evaluation | ✅ Done |

### High Priority

#### 1. Streaming Progress for Long Evaluations
**Problem:** Evaluations can take 5-30 minutes. Users see console status but agent response comes only at the end.

**Potential Solutions:**
- Implement async evaluation with polling
- WebSocket-based progress updates
- Split into start/status/results functions

#### 2. Error Recovery & Retry
**Problem:** Network failures or transient errors abort the entire operation.

**Potential Solutions:**
- Exponential backoff retry logic
- Checkpoint/resume for long evaluations
- Partial results preservation

### Medium Priority

#### 3. Result Caching
**Problem:** Re-running validations on unchanged datasets wastes time.

**Potential Solutions:**
- Hash-based cache invalidation
- Store validation results with timestamps
- Skip if dataset unchanged

#### 4. Custom Evaluator Integration
**Problem:** Currently uses Foundry's built-in evaluators only.

**Potential Solutions:**
- Parameter to specify custom evaluator
- Support for evaluator configuration files
- Plugin architecture for evaluators

#### 5. Conversation History Persistence
**Problem:** Agent forgets context when restarted.

**Potential Solutions:**
- Thread ID persistence to file
- Resume previous conversation option
- Context summary on restart

### Low Priority / Future Exploration

#### 7. Multi-Agent Orchestration
**Idea:** Separate agents for validation, evaluation, and analysis that coordinate.

**Benefits:**
- Specialized agents with focused prompts
- Parallel execution
- Better scaling

#### 8. Web UI
**Idea:** Browser-based interface instead of CLI.

**Considerations:**
- Would need FastAPI/Flask backend
- WebSocket for real-time updates
- Authentication flow changes

#### 9. Scheduled Evaluations
**Idea:** Cron-like scheduling for recurring evaluations.

**Considerations:**
- Azure Functions integration
- Result storage and notification
- Drift detection

### Feature Ideas & Future Enhancements

Ideas for new capabilities to extend the agent's functionality:

#### 1. Create Dataset Feature 🆕
**Description:** Enable users to create properly formatted evaluation datasets through natural language.

**Capabilities:**
- Generate JSONL dataset from audio files in a folder
- Auto-detect conversation structure from filenames
- Add/edit metadata (system prompts, ground truth, tool definitions)
- Validate generated dataset before saving

**User Experience:**
```
User: "Create a dataset from the audio files in /path/to/audio/"
Agent: Scans folder, detects 10 audio files, generates dataset.jsonl
```

#### 2. Enable Flexible VoiceLive Configuration 🆕
**Description:** Allow users to customize VoiceLive API parameters at runtime.

**Configuration Options:**
- Model selection (voice model, language model)
- Voice settings (speed, pitch, voice ID)
- Timeout and retry policies
- Custom system prompts per evaluation
- Tool definitions injection

**Implementation Approach:**
- Configuration file support (YAML/JSON)
- Command-line parameter passthrough
- Environment variable overrides

#### 3. Finalize Full VoiceLive SDK Migration 🆕
**Description:** Complete migration from subprocess-based execution to native SDK integration.

**Benefits:**
- Eliminate subprocess overhead
- Better error handling and recovery
- Direct access to streaming responses
- Simplified dependency management

**Migration Steps:**
1. Replace subprocess calls with direct SDK imports
2. Implement async/await for concurrent processing
3. Add proper connection pooling
4. Unified error handling across all tools

#### 4. Comparative Evaluation Reports 🆕
**Description:** Compare results across multiple evaluation runs to track improvements or regressions.

**Features:**
- Side-by-side metrics comparison
- Trend analysis over time
- Automatic regression detection
- Visual diff of transcription quality

#### 5. Dataset Augmentation 🆕
**Description:** Automatically generate variations of existing datasets for more comprehensive testing.

**Techniques:**
- Audio speed/pitch variations
- Background noise injection
- Accent simulation
- Multi-speaker scenarios

#### 6. Integration with CI/CD Pipelines 🆕
**Description:** Enable automated evaluation as part of continuous integration workflows.

**Features:**
- GitHub Actions integration
- Azure DevOps pipeline support
- Threshold-based pass/fail gates
- Automated regression alerts

### Technical Debt

| Item | Description | Priority |
|------|-------------|----------|
| Streaming fallback | Falls back to non-streaming silently | Low |
| Error message parsing | Agent sometimes misinterprets errors | Medium |
| Test coverage | No automated tests yet | High |
| Type hints | Incomplete type annotations | Low |
| ~~Folder path handling~~ | ~~analyze_evaluation_results didn't support folders~~ | ~~Medium~~ ✅ Fixed |
| ~~Multi-format metrics~~ | ~~Only supported Foundry format, not raw eval output~~ | ~~Medium~~ ✅ Fixed |

---

## Migration Paths

### If More Complex Planning Needed → Semantic Kernel

1. Create SK plugins wrapping existing functions
2. Add planners for multi-step workflows
3. Keep Azure Identity authentication
4. Deploy to Foundry as container

### If Performance Issues → Direct Integration

1. Import validation modules directly (no subprocess)
2. Use async/await throughout
3. Implement connection pooling for APIs
4. Consider caching layer

### If Multi-Tenant Needed → Foundry Native

1. Define skills as standalone packages
2. Deploy to Foundry Agent Service
3. Use per-tenant configuration
4. Leverage Foundry's scaling

---

## References

### Azure Documentation
- [Azure AI Agents SDK](https://learn.microsoft.com/azure/ai-services/agents/)
- [Azure Identity](https://learn.microsoft.com/azure/developer/python/sdk/authentication-overview)
- [DefaultAzureCredential](https://learn.microsoft.com/python/api/azure-identity/azure.identity.defaultazurecredential)

### Related Projects
- Dataset Validators: `../dataset_validator/`
- VoiceLive Evaluation: `../prototype_v1/`
- Skills Definitions: `./skills/` (4 skills: voicelive-audio-evaluation, batch-processor-py, validate-dataset-consistency, validate-dataset-quality)

---

*Last updated: February 3, 2026*
