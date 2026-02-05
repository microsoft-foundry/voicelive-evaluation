# VoiceLive Evaluation Agent v3 - Architecture

## Overview

The VoiceLive Evaluation Agent v3 is a cloud-native AI agent deployed on Azure AI Foundry Agent Service. It automates the validation and execution of VoiceLive audio evaluation workflows through natural language interaction.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Azure Cloud                                     │
│                                                                              │
│   User ──► Foundry Portal ──► Agent ──► HTTP ──► Azure Functions            │
│              (ai.azure.com)    │              (OpenAPI Tools)                │
│                                │                     │                       │
│                                │              ┌──────┴──────┐                │
│                                │              │  Durable    │                │
│                                │              │  Functions  │                │
│                                │              │  (async)    │                │
│                                │              └──────┬──────┘                │
│                                │                     ▼                       │
│                                │              Blob Storage                   │
│                                │              ├── datasets/                  │
│                                │              └── outputs/                   │
│                                │                                             │
│                                └──► Tracing & Observability                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Design Decisions

### 1. Why Azure AI Foundry Agent Service?

**Decision**: Use Foundry Agent Service instead of standalone agent deployment.

**Alternatives Considered**:
- Standalone agent with local runner (v1)
- Container Apps with custom agent loop (v2)
- Foundry Agent Service with OpenAPI tools (v3) ✅

**Reasoning**:
- **Built-in observability**: All conversations and tool calls visible in Foundry Portal tracing
- **Managed infrastructure**: No need to manage agent orchestration
- **Portal integration**: Users can interact via Foundry Portal UI
- **Version management**: Agent versions tracked automatically
- **Simpler deployment**: Agent definition is declarative, tools are HTTP endpoints

**Trade-offs**:
- Less control over agent loop behavior
- Dependent on Foundry service availability
- OpenAPI tool limitations (no streaming, specific auth patterns)

---

### 2. Why Azure Functions + Durable Functions?

**Decision**: Implement tools as Azure Functions with Durable Functions for long-running operations.

**Alternatives Considered**:
- Azure Container Apps (always-on container)
- Azure Container Instances (per-job containers)
- Standard Functions only (with 10-min timeout)

**Reasoning**:
- **Serverless cost model**: Pay only for execution time
- **Auto-scaling**: Handles variable load automatically
- **Durable Functions**: Overcomes 10-minute timeout for evaluations
- **Async pattern**: Natural fit for AI agent workflows (start job → poll status)
- **Same codebase**: No need for separate container image

**How Durable Functions Work**:
```
run_voicelive_evaluation (HTTP) 
    → evaluation_orchestrator (Durable)
        → prepare_evaluation (Activity)
        → execute_evaluation (Activity) 
        → finalize_evaluation (Activity)

check_evaluation_status (HTTP)
    → queries orchestrator status
```

**Trade-offs**:
- More complex than simple HTTP functions
- Durable Functions have their own learning curve
- Activity functions have 10-min timeout (orchestrator doesn't)

---

### 3. Why Function Keys over Entra ID?

**Decision**: Use Azure Function Keys with Foundry Custom Key Connection.

**Alternatives Considered**:
- Anonymous auth (no security)
- Entra ID Easy Auth (App Registration required)
- Managed Identity with custom token validation
- API Management gateway

**Reasoning**:
- **No App Registration needed**: Enterprise tenants often require ServiceTree GUID for App Registration creation, which blocked our Entra ID approach
- **Built-in to Functions**: Function Keys are native, no additional setup
- **Foundry Connection support**: Custom Key Connections work well with OpenAPI tools
- **Simple rotation**: Keys can be rotated in Azure Portal

**Implementation**:
```python
# Function App uses FUNCTION auth level
app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# Foundry Connection stores the key
# Connection has both 'code' and 'x-functions-key' keys

# Agent uses connection-based auth
auth = OpenApiProjectConnectionAuthDetails(
    security_scheme=OpenApiProjectConnectionSecurityScheme(
        project_connection_id="<full-connection-resource-id>"
    )
)
```

**Trade-offs**:
- Function keys are shared secrets (less secure than identity-based)
- Must manage key rotation manually
- Connection requires full resource ID (not just name)

---

### 4. Why Flexible Path Handling?

**Decision**: Make `download_dataset()` accept any path format the agent might send.

**Problem**: The agent sends paths in various formats:
- `"Eiffel_Tower_Visit_1"` (just name)
- `"Eiffel_Tower_Visit_1/Eiffel_Tower_Visit_1.jsonl"` (relative)
- `"datasets/Eiffel_Tower_Visit_1/Eiffel_Tower_Visit_1.jsonl"` (with container)

**Solution**:
```python
def normalize_dataset_path(dataset_path: str) -> str:
    # Strip whitespace, quotes, leading slashes
    # Strip container prefix if present
    # Search for matching blob if not exact match
```

**Reasoning**:
- Agent behavior is non-deterministic; can't guarantee path format
- Better UX to be flexible than fail on formatting
- Reduces need for complex agent instructions

**Trade-offs**:
- Slightly slower (may search blobs)
- Could match wrong dataset if names are similar

---

### 5. Why Schema Validation Changes?

**Decision**: Update validation to match actual dataset schema, not assumed schema.

**Original (Wrong)**:
```python
required_fields = {"ConversationId", "Turns"}  # Wrong!
```

**Corrected**:
```python
required_field_aliases = {
    "audio_path": ["WavPath", "audio"],  # Actual required field
}
optional_field_aliases = {
    "question": ["Question", "question"],
    "answer": ["Answer", "answer"],
    "conversation_id": ["conversationID", "conversation_id"],
    # ...
}
```

**Reasoning**:
- Actual datasets use `WavPath`, `Question`, `Answer` fields
- Field names have multiple aliases (camelCase vs snake_case)
- Only `audio_path` is truly required; others have defaults

**Lesson Learned**: Always verify schema against actual data, not assumptions.

---

### 6. Why OpenAPI Tools over Function Tools?

**Decision**: Use OpenAPI tools instead of local function tools.

**Comparison**:

| Aspect | Function Tools (v1/v2) | OpenAPI Tools (v3) |
|--------|------------------------|-------------------|
| Execution | Local runner process | HTTP calls to Functions |
| Deployment | Runner must be running | Serverless, always available |
| Debugging | Local logs | App Insights + Foundry tracing |
| Auth | Implicit (same process) | Explicit (keys/tokens) |
| Scalability | Limited by runner | Auto-scales |

**Reasoning**:
- No dependency on local runner process
- Works from any client (Portal, SDK, API)
- Built-in monitoring and tracing
- Scales automatically with load

---

## Component Details

### Azure Functions (12 total)

| Function | Type | Purpose |
|----------|------|---------|
| `list_datasets` | HTTP | List available datasets in blob storage |
| `check_dataset_schema` | HTTP | Validate dataset has required fields |
| `validate_dataset_consistency` | HTTP | Check for data consistency issues |
| `validate_dataset_quality` | HTTP | Assess data quality metrics |
| `get_evaluation_recommendations` | HTTP | Suggest evaluation settings |
| `run_voicelive_evaluation` | HTTP | Start async evaluation job |
| `check_evaluation_status` | HTTP | Poll evaluation job status |
| `analyze_evaluation_results` | HTTP | Analyze completed evaluation results |
| `evaluation_orchestrator` | Durable | Orchestrate evaluation workflow |
| `prepare_evaluation` | Activity | Download and prepare dataset |
| `execute_evaluation` | Activity | Run actual evaluation |
| `finalize_evaluation` | Activity | Upload results, cleanup |

### Blob Storage Structure

```
stv3g7ywvldzjeo/
├── datasets/
│   ├── Eiffel_Tower_Visit_1/
│   │   └── Eiffel_Tower_Visit_1.jsonl
│   ├── MultiConversationSample/
│   │   └── multiConversationSample.jsonl
│   └── ...
└── outputs/
    └── evaluations/
        └── {instance_id}/
            └── results.json
```

### Foundry Connection

- **Type**: CustomKeys
- **Keys**: `code`, `x-functions-key` (same value)
- **Usage**: Agent includes key in HTTP requests to Functions

---

## Security Considerations

1. **Function Keys**: Stored in Foundry Connection, not in code
2. **Blob Storage**: Functions use managed identity to access blobs
3. **No secrets in OpenAPI spec**: Auth handled via connection reference
4. **HTTPS only**: All endpoints require HTTPS

---

## Future Improvements

1. **Full azd automation**: Create Foundry resources + agent via Bicep/scripts
2. **Webhook notifications**: Notify when long evaluations complete
3. **Progress streaming**: Report evaluation progress in real-time
4. **Multi-region**: Deploy Functions closer to data sources
5. **Cost optimization**: Use Premium plan for faster cold starts

---

*Document created: February 4, 2026*
