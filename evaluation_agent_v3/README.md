# VoiceLive Evaluation Agent v3

Cloud-native AI agent for automating VoiceLive audio evaluation workflows on Azure AI Foundry.

## Overview

The v3 agent combines:
- **Azure AI Foundry Agent Service** - Natural language orchestration with built-in tracing
- **VoiceLive Container App** - Long-running audio processing through VoiceLive SDK
- **Azure Functions** - Serverless dataset validation and Foundry evaluations
- **Azure Blob Storage** - Dataset and results storage
- **Azure Table Storage** - Session configuration management

```mermaid
graph LR
    User -->|Natural Language| Agent[Foundry Agent]
    Agent -->|HTTP| Functions[Azure Functions]
    Agent -->|HTTP| CA[Container App]
    Functions -->|Blob| Storage[(Blob Storage)]
    Functions -->|Table| Tables[(Table Storage)]
    CA -->|VoiceLive SDK| VL[VoiceLive API]
    CA -->|Blob| Storage
    Functions -->|Evaluators| Foundry[Foundry Evaluators]
```

## Quick Start

### Prerequisites

- Azure subscription with Cognitive Services access
- **Azure AI Foundry account and project (must exist before deployment)**
  - The azd/Bicep deployment does NOT create the Foundry account or project
  - Create via [Azure AI Foundry Portal](https://ai.azure.com) or Azure Portal
  - Note the PROJECT_ENDPOINT from Project Settings
- Azure CLI + azd CLI installed
- Python 3.11+
- Docker Desktop (for Container App deployment)

### Deploy Infrastructure

```bash
cd evaluation_agent_v3

# Login and set subscription
az login
azd auth login

# Create environment and configure
azd env new my-voicelive-eval --location eastus2
azd env set PROJECT_ENDPOINT "https://<resource>.services.ai.azure.com/api/projects/<project>"
azd env set AZURE_VOICE_LIVE_ENDPOINT "https://<resource>.services.ai.azure.com/"
azd env set DEPLOY_CONTAINER_APP true  # Include Container App

# Deploy everything (Functions + Container App + Storage)
azd up

# Get deployed resources
azd env get-values
```

### Seed Session Configurations

```bash
# After deployment, seed the default VoiceLive configurations
./scripts/azd/seed-session-configs.ps1 -StorageAccountName <storage-account-name>
```

### Create Foundry Agent

```bash
# Get function URL from azd output
FUNC_URL=$(azd env get-value AZURE_FUNCTION_APP_URL)

# Create agent with OpenAPI tools
python setup_agent_openapi.py --function-url $FUNC_URL

# Or update existing agent
python setup_agent_openapi.py --function-url $FUNC_URL --update
```

### Configure Agent Authentication (Production)

1. **Create Function Key Connection in Foundry Portal**:
   - Go to ai.azure.com → Your Project → Management → Connections
   - Add Custom Keys connection named `voicelive-eval-api-key`
   - Add keys: `code` and `x-functions-key` (same value from Function App)

2. **Update Agent with Connection**:
```bash
CONNECTION_ID="/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<account>/projects/<project>/connections/voicelive-eval-api-key"

python setup_agent_openapi.py \
  --function-url $FUNC_URL \
  --connection-name $CONNECTION_ID \
  --update
```

### Enable Agent Tracing (RBAC)

For agent tracing to work in Application Insights, the Foundry project's managed identity needs the Azure AI User role:

```powershell
# Option 1: Via azd environment (if Foundry account in same RG)
azd env set FOUNDRY_PROJECT_PRINCIPAL_ID "<project-managed-identity-object-id>"
azd env set FOUNDRY_ACCOUNT_NAME "<cognitive-services-account-name>"
azd up

# Option 2: Cross-resource-group (most common)
./scripts/azd/configure-foundry-rbac.ps1 `
  -FoundryAccountResourceId "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<account>" `
  -FoundryProjectPrincipalId "<project-managed-identity-object-id>"
```

**Finding the Principal ID**: Foundry Portal → Project Settings → Identity → Object (Principal) ID

**Note**: Recently granted permissions may take several minutes to propagate.

## Usage

### Via Foundry Portal

1. Go to https://ai.azure.com
2. Select your project → Agents → `voicelive-evaluation-agent-cloud`
3. Click **Test** to interact

**Example prompts**:
- "List available datasets"
- "Validate the Eiffel_Tower_Visit_1 dataset"
- "Run evaluation with intent_resolution and task_adherence evaluators"
- "Process audio files from MultiConversationSample through VoiceLive"

### Via Python SDK

```python
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

client = AIProjectClient(
    endpoint="https://<resource>.services.ai.azure.com/api/projects/<project>",
    credential=DefaultAzureCredential()
)

# Get agent
agent = client.agents.get(name="voicelive-evaluation-agent-cloud")

# Create thread and run
thread = client.agents.threads.create()
client.agents.messages.create(thread_id=thread.id, role="user", 
    content="List available datasets")
run = client.agents.runs.create_and_process(thread_id=thread.id, agent_id=agent.id)

# Get response
messages = client.agents.messages.list(thread_id=thread.id)
print(messages[-1].content[0].text.value)
```

## Available Tools

### Session Configuration Management

| Tool | Description |
|------|-------------|
| `list_session_configs` | List all VoiceLive session configurations |
| `get_session_config` | Get details of a specific config |
| `create_session_config` | Create new VoiceLive config |
| `update_session_config` | Update existing config |
| `delete_session_config` | Delete a config |

### Dataset Discovery & Validation

| Tool | Description |
|------|-------------|
| `list_datasets` | List all JSONL datasets in blob storage |
| `check_dataset_schema` | Check required/optional fields |
| `validate_dataset_consistency` | MANDATORY structural validation |
| `validate_dataset_quality` | ADVISORY content quality check |

### VoiceLive Audio Processing (Container App)

| Tool | Description |
|------|-------------|
| `run_voicelive_audio_tests` | Process audio files through VoiceLive SDK |
| `check_voicelive_job_status` | Poll audio processing job status |

### Foundry Evaluation (Azure Functions)

| Tool | Description |
|------|-------------|
| `run_voicelive_evaluation` | Run Foundry evaluators on dataset |
| `check_evaluation_status` | Poll evaluation job status |
| `get_evaluation_recommendations` | Get settings for large datasets |
| `analyze_evaluation_results` | Analyze completed evaluation |

### Foundry Resource Management

| Tool | Description |
|------|-------------|
| `list_evaluation_groups` | List existing eval groups |
| `list_foundry_datasets` | List Foundry-uploaded datasets |
| `delete_evaluation_groups` | Delete eval groups by ID or search |
| `delete_foundry_datasets` | Delete datasets by name or search |

## Default Evaluators

The agent uses 10 evaluators aligned with VoiceLive best practices:

| Evaluator | Model | Purpose |
|-----------|-------|---------|
| intent_resolution | Reasoning | Did agent understand intent? |
| task_adherence | Reasoning | Did agent follow instructions? |
| task_completion | Reasoning | Did agent complete the task? |
| response_completeness | Reasoning | Was response complete? |
| groundedness | Standard | Is response grounded? |
| relevance | Reasoning | Is response relevant? |
| tool_call_accuracy | Reasoning | Were tool calls correct? |
| tool_selection | Reasoning | Did agent pick right tools? |
| tool_input_accuracy | Reasoning | Were tool inputs correct? |
| tool_output_utilization | Reasoning | Did agent use tool outputs? |

Specify custom subset via `evaluators` parameter:
```json
{"evaluators": ["intent_resolution", "task_adherence"]}
```

## Environment Variables

### Function App (deploy/azure-functions/.env)

```env
# Required
PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>
AZURE_STORAGE_CONNECTION_STRING=<connection-string>
AZURE_STORAGE_DATASETS_CONTAINER=datasets
AZURE_STORAGE_OUTPUTS_CONTAINER=outputs

# Evaluator models
AOAI_DEPLOYMENT_NAME=gpt-4.1-mini
AOAI_REASONING_DEPLOYMENT_NAME=o4-mini
```

### Container App (deploy/container-app/.env)

```env
# VoiceLive API
AZURE_VOICELIVE_ENDPOINT=https://<resource>.services.ai.azure.com/
AZURE_VOICELIVE_MODEL=gpt-realtime
AZURE_VOICELIVE_API_VERSION=2025-10-01

# Blob Storage
AZURE_STORAGE_ACCOUNT_URL=https://<account>.blob.core.windows.net
AZURE_STORAGE_DATASETS_CONTAINER=datasets
AZURE_STORAGE_OUTPUTS_CONTAINER=outputs
```

## Dataset Format

Datasets are JSONL files with one entry per line:

```json
{"WavPath": "file1.wav", "Question": "User query", "Answer": "Expected response", "conversationID": "conv1", "system_prompt": "...", "tool_definitions": [...]}
{"WavPath": "file2.wav", "Question": "Another query", "Answer": "Another response", "conversationID": "conv1"}
```

| Field | Required | Description |
|-------|----------|-------------|
| WavPath / audio_path | Yes* | Path to audio file (for raw audio datasets) |
| query / Question | Yes** | User query text |
| response / Answer | Yes** | Agent response text |
| conversationID | No | Group files by conversation |
| system_prompt | No | Agent instructions |
| tool_definitions | No | Available tools for agent |

*Required for VoiceLive audio processing
**Required for Foundry evaluation

## File Structure

```
evaluation_agent_v3/
├── deploy/
│   ├── azure-functions/           # Azure Functions code
│   │   ├── function_app.py        # 20+ function endpoints
│   │   ├── openapi.yaml           # OpenAPI spec for agent
│   │   ├── requirements.txt
│   │   └── host.json
│   └── container-app/             # VoiceLive Container App
│       ├── app/
│       │   ├── main.py            # FastAPI endpoints
│       │   ├── processor.py       # Audio processing logic
│       │   ├── voicelive_client.py # VoiceLive SDK client
│       │   └── storage.py         # Blob storage operations
│       ├── Dockerfile
│       └── requirements.txt
├── infra/                         # Bicep infrastructure
│   ├── main.bicep                 # Main deployment template
│   ├── main.parameters.json       # Parameters with defaults
│   └── modules/                   # Reusable modules
│       ├── storage.bicep          # Storage + Tables
│       ├── function-app.bicep     # Functions + App Insights
│       └── container-app.bicep    # Container App + ACR
├── scripts/
│   └── azd/                       # Deployment scripts
│       ├── seed-session-configs.ps1  # Seed default configs
│       ├── deploy-container-app.ps1  # Build & deploy container
│       └── setup-agent.ps1           # Create Foundry agent
├── setup_agent.py                 # Local runner setup
├── setup_agent_openapi.py         # Cloud agent setup
├── runner.py                      # Local tool executor
├── tools.py                       # Tool implementations
├── test_agent_sdk.py              # Integration tests
├── azure.yaml                     # azd configuration
├── ARCHITECTURE.md                # Design decisions
└── README.md                      # This file
```

## Testing

### Integration Tests

Run the integration tests to verify all endpoints:

```bash
# Set function key (get from Azure Portal or CLI)
export AZURE_FUNCTION_KEY=$(az functionapp keys list --name <func-name> --resource-group <rg> --query "functionKeys.default" -o tsv)

# Run tests
python test_agent_sdk.py --function-url https://<func-name>.azurewebsites.net/api
```

Expected output:
```
============================================================
VoiceLive Evaluation Agent v3 - Integration Tests
============================================================
[1/10] list_session_configs
   ✓ Found 7 configs
[2/10] get_session_config
   ✓ Got config: default (Model: gpt-4.1)
...
Total: 10/10 tests passed
```

## Session Configurations

The agent supports 7 pre-configured VoiceLive settings:

| Config | Model | Sample Rate | VAD Type | EOU |
|--------|-------|-------------|----------|-----|
| default | gpt-4.1 | 24000 | azure_semantic_vad_multilingual | ✓ |
| conf1 | gpt-realtime | 16000 | server_vad | ✗ |
| conf2 | gpt-realtime-mini | 16000 | server_vad | ✗ |
| conf3 | gpt-4.1 | 16000 | server_vad | ✓ |
| conf4 | gpt-realtime | 24000 | azure_semantic_vad_multilingual | ✗ |
| conf5 | gpt-realtime-mini | 24000 | azure_semantic_vad_multilingual | ✗ |
| conf6 | gpt-4.1 | 24000 | azure_semantic_vad_multilingual | ✓ |

Create custom configurations via the agent:
```
"Create a new session config named 'low-latency' with model gpt-realtime-mini, sample_rate 16000, and vad_type server_vad"
```

## Deployed Resources

After `azd up`, the following resources are created:

| Resource | Purpose |
|----------|---------|
| Resource Group | `rg-<env-name>` |
| Storage Account | `st<token>` - datasets/, outputs/, tables |
| Function App | `func-<token>` - 20+ HTTP endpoints |
| Container App | `ca-voicelive-<token>` - VoiceLive processor |
| Container Registry | `acr<token>` - Docker images |
| App Insights | `func-<token>-insights` - Telemetry |
| Table: sessionconfigs | VoiceLive session configurations |
| Table: configjournal | Evaluation group → config mapping |

## Troubleshooting

### "Blob not found" errors
- Check path format - agent may send various formats
- Verify file exists in correct container (datasets/ vs outputs/)
- Check for `.jsonl` extension

### Evaluation status "failed"
- Check App Insights logs for detailed error
- Verify AOAI_DEPLOYMENT_NAME is valid
- Ensure Azure AI User role assigned to Function's managed identity

### Container App job fails
- Check logs: `az containerapp logs show --name ca-voicelive-processor`
- Verify VoiceLive endpoint and model configured
- Ensure managed identity has Storage Blob Data Contributor

### Agent not finding tools
- Redeploy OpenAPI spec: `python setup_agent_openapi.py --update`
- Verify connection ID is the full resource path
- Check Function App is running and healthy

### Agent tool calls return 401
- The Foundry connection has an old/invalid function key
- Get the current function key: `az functionapp keys list --name <func-name> --resource-group <rg> --query "functionKeys.default" -o tsv`
- Update the connection in Foundry Portal → Management → Connections → Edit

## SDK Limitations

The following operations require **manual configuration** in the Foundry Portal or via Terraform/ARM - they cannot be done via the Python SDK:

| Operation | SDK Support | Alternative |
|-----------|-------------|-------------|
| Create/update connections | ❌ No | Foundry Portal, Terraform (azapi_resource), ARM |
| Configure agent App Insights | ❌ No | Foundry Portal → Tracing → Connect App Insights |
| Delete connections | ❌ No | Foundry Portal, Terraform, ARM |

**Client-side tracing** (your code calling the agent) is fully supported via SDK:
```python
from azure.monitor.opentelemetry import configure_azure_monitor
configure_azure_monitor(connection_string="InstrumentationKey=...")
```

For **agent-side tracing** (traces appearing in Foundry portal):
1. Go to ai.azure.com → Your Project → Tracing
2. Click "Connect Application Insights"
3. Select or create App Insights resource
4. This is a one-time setup per project

## See Also

- [ARCHITECTURE.md](ARCHITECTURE.md) - Design decisions and diagrams
- [prototype_v1/](../prototype_v1/) - Original local evaluation scripts
- [Azure AI Foundry Docs](https://learn.microsoft.com/azure/ai-services/agents/)

---

*Last updated: February 7, 2026*
