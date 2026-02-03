# VoiceLive Evaluation Agent v3 - Azure AI Projects SDK

Cloud-native implementation using **Azure AI Projects SDK** (`azure-ai-projects`) for integration with the new Azure AI Foundry Portal, built-in tracing, and agent management.

## Key Differences from v2

| Feature | v2 (Container Apps) | v3 (Azure AI Projects) |
|---------|---------------------|---------------------------|
| SDK | azure-ai-agents | **azure-ai-projects** |
| Hosting | Azure Container Apps | Foundry Agent Service |
| Tracing | Application Insights (optional) | **Built-in Foundry tracing** |
| Portal | Azure Portal | **New AI Foundry Portal** |
| Agent Lifecycle | Ephemeral (per-session) | **Persistent & versioned** |
| Observability | Manual setup | **Native Foundry UI** |

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Azure AI Foundry Project                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │              Foundry Agent Service (Built-in)                      │  │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐   │  │
│  │  │ Agent Registry  │  │ Tracing & Logs  │  │ Version Control │   │  │
│  │  │ (persistent)    │  │ (automatic)     │  │ (built-in)      │   │  │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────┘   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                    │                                     │
│                                    ▼                                     │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │              Tool Execution (Function Calling)                     │  │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ │  │
│  │  │ validate    │ │ evaluate    │ │ analyze     │ │ list        │ │  │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘ │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
          ┌─────────────────┐             ┌─────────────────┐
          │  Tool Runner    │             │  Azure Blob     │
          │  (local/cloud)  │             │  Storage        │
          │                 │             │  datasets/      │
          │  Executes       │             │  outputs/       │
          │  evaluation     │             │                 │
          │  scripts        │             │                 │
          └─────────────────┘             └─────────────────┘
```

## How It Works

1. **Agent Definition**: Agent is created/registered in Foundry with tool definitions
2. **Persistent Agent**: Agent persists in Foundry (not recreated each session)
3. **Tool Runner**: A runner process handles tool execution (locally or in cloud)
4. **Built-in Tracing**: All conversations and tool calls visible in Foundry Portal

## Quick Start

### 1. Create the Foundry Agent (one-time setup)

```bash
cd evaluation_agent_v3
python setup_agent.py
```

This registers the agent in your Foundry project. You'll get an Agent ID.

### 2. Run the Tool Runner

```bash
# Interactive mode - handles tool calls locally
python runner.py

# Or in cloud mode (uses blob storage)
python runner.py --cloud
```

### 3. Access via Foundry Portal

1. Go to [AI Foundry Portal](https://ai.azure.com)
2. Select your project
3. Go to **Agents** → Find your agent
4. Click **Test** to interact
5. View **Tracing** for observability

## Files

| File | Purpose |
|------|---------|
| `setup_agent.py` | Creates/updates agent in Foundry (run once) |
| `runner.py` | Handles tool execution (run when using agent) |
| `tools.py` | Tool function implementations |
| `cloud_storage.py` | Azure Blob Storage integration |
| `tracing.py` | OpenTelemetry tracing setup |

## Environment Variables

```env
# Required
PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>
MODEL_DEPLOYMENT_NAME=gpt-4o-mini

# Voice Live API (for evaluations)
AZURE_VOICE_LIVE_ENDPOINT=https://<resource>.services.ai.azure.com/
AZURE_VOICE_LIVE_MODEL=gpt-realtime
AZURE_VOICE_LIVE_API_VERSION=2025-10-01

# Metrics evaluation
AOAI_DEPLOYMENT_NAME=gpt-4o-mini
AOAI_REASONING_DEPLOYMENT_NAME=o4-mini

# Optional - Cloud storage (enables cloud mode)
AZURE_STORAGE_ACCOUNT=<storage-account>
AZURE_STORAGE_DATASETS_CONTAINER=datasets   # default
AZURE_STORAGE_OUTPUTS_CONTAINER=outputs     # default
```

## Cloud Storage (Optional)

Cloud storage is **optional** but recommended for production:

| Mode | Storage | When to Use |
|------|---------|-------------|
| **Local** | Filesystem | Development, small datasets |
| **Cloud** | Azure Blob Storage | Production, shared/large datasets |

### Enabling Cloud Mode

Set `AZURE_STORAGE_ACCOUNT` to enable cloud mode:

```bash
export AZURE_STORAGE_ACCOUNT=mystorageaccount
python runner.py --cloud
```

### Blob Container Structure

```
<storage-account>
├── datasets/              # Input datasets
│   ├── project-a/
│   │   └── test.jsonl
│   └── project-b/
│       └── eval.jsonl
└── outputs/               # Evaluation results
    └── results/
        └── 2026-02-03_10-30-00/
            ├── aggregate.jsonl
            └── metrics.json
```

### Creating Containers

The containers are **not automatically created**. Create them manually:

```bash
# Using Azure CLI
az storage container create --account-name $AZURE_STORAGE_ACCOUNT --name datasets
az storage container create --account-name $AZURE_STORAGE_ACCOUNT --name outputs

# Or via Azure Portal: Storage Account → Containers → + Container
```

### Upload Datasets

```bash
# Upload a dataset
az storage blob upload \
  --account-name $AZURE_STORAGE_ACCOUNT \
  --container-name datasets \
  --file my-dataset.jsonl \
  --name project/my-dataset.jsonl
```

## Viewing Traces in Foundry

1. Open AI Foundry Portal
2. Navigate to your project
3. Go to **Tracing** section
4. Filter by agent name or time range
5. Click on any trace to see:
   - Full conversation history
   - Tool calls and responses
   - Latency metrics
   - Token usage

## Deployment Options

### Option A: Local Runner (Development)
- Run `runner.py` on your machine
- Tools execute locally
- Good for development/testing

### Option B: Azure Functions (Production)
- Deploy tool functions to Azure Functions
- Fully serverless
- See `deploy/` folder for templates (TODO)

### Option C: Container + Foundry (Hybrid)
- Tools run in Container App
- Agent managed by Foundry
- Best of both worlds

## Agent Management

```bash
# Create new agent
python setup_agent.py --create

# Update existing agent
python setup_agent.py --update --agent-id <id>

# List agents
python setup_agent.py --list

# Delete agent
python setup_agent.py --delete --agent-id <id>
```

## Comparison with v1/v2

| Aspect | v1 | v2 | v3 |
|--------|----|----|-----|
| SDK | azure-ai-agents | azure-ai-agents | **azure-ai-projects** |
| Deployment | Local only | Container Apps | Foundry Agent Service |
| Agent lifecycle | Per-session | Per-session | **Persistent** |
| Tracing | Console/AppInsights | AppInsights | **Foundry native** |
| Portal | None | Azure Portal | **AI Foundry Portal** |
| Tool execution | Local subprocess | Container subprocess | Runner process |

## See Also

- [AI Foundry Agent Service Docs](https://learn.microsoft.com/azure/ai-services/agents/)
- [evaluation_agent/](../evaluation_agent/) - v1 (local only)
- [evaluation_agent_v2/](../evaluation_agent_v2/) - v2 (Container Apps)
