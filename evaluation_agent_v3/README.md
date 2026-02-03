# VoiceLive Evaluation Agent v3 - Foundry Agent Service

Cloud-native implementation using **Azure AI Foundry Agent Service** for built-in tracing, observability, and agent management.

## Key Differences from v2

| Feature | v2 (Container Apps) | v3 (Foundry Agent Service) |
|---------|---------------------|---------------------------|
| Hosting | Azure Container Apps | Foundry Agent Service |
| Tracing | Application Insights (optional) | **Built-in Foundry tracing** |
| Portal | Azure Portal | **AI Foundry Portal** |
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

# Voice Live API (for evaluations)
AZURE_VOICE_LIVE_ENDPOINT=https://<resource>.services.ai.azure.com/
AZURE_VOICE_LIVE_MODEL=gpt-realtime
AZURE_VOICE_LIVE_API_VERSION=2025-10-01

# Metrics evaluation
AOAI_DEPLOYMENT_NAME=gpt-4o-mini
AOAI_REASONING_DEPLOYMENT_NAME=o4-mini

# Optional - Cloud storage
AZURE_STORAGE_ACCOUNT=<storage-account>
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
| Deployment | Local only | Container Apps | Foundry Agent Service |
| Agent lifecycle | Per-session | Per-session | **Persistent** |
| Tracing | Console/AppInsights | AppInsights | **Foundry native** |
| Portal | None | Azure Portal | **AI Foundry Portal** |
| Tool execution | Local subprocess | Container subprocess | Runner process |

## See Also

- [AI Foundry Agent Service Docs](https://learn.microsoft.com/azure/ai-services/agents/)
- [evaluation_agent/](../evaluation_agent/) - v1 (local only)
- [evaluation_agent_v2/](../evaluation_agent_v2/) - v2 (Container Apps)
