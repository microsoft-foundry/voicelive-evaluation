# Deploying the Runner Process

The Foundry Agent Service handles orchestration, but **tool execution requires deployment**.

## Two Deployment Approaches

| Approach | Tools Run In | Runner Needed? | Best For |
|----------|--------------|----------------|----------|
| **A. OpenAPI + Functions** | Azure Functions | No | Validation, analysis |
| **B. Local Runner** | Your machine | Yes | Development, full evals |

### Approach A: OpenAPI Tools (Recommended for Cloud)

Deploy tools as Azure Functions, agent calls them directly via HTTP.

```
User → Foundry Portal → Agent → HTTP Call → Azure Functions → Blob Storage
                                                    ↓
                                            Tool execution
```

**Deployment Steps:**

```bash
# 1. Deploy Azure Functions
cd evaluation_agent_v3/deploy/azure-functions
func azure functionapp publish <your-function-app-name>

# 2. Configure Function App settings (Azure Portal or CLI)
az functionapp config appsettings set \
  --name <your-function-app-name> \
  --resource-group <rg> \
  --settings \
    AZURE_STORAGE_ACCOUNT=<storage-account> \
    AZURE_STORAGE_DATASETS_CONTAINER=datasets \
    AZURE_STORAGE_OUTPUTS_CONTAINER=outputs

# 3. Create agent with OpenAPI tools
cd evaluation_agent_v3
python setup_agent_openapi.py \
  --function-url https://<your-function-app-name>.azurewebsites.net/api \
  --function-key <your-function-key>
```

**Note:** `run_voicelive_evaluation` returns a 501 - full evaluations need Container Apps due to Function timeout limits.

### Approach B: Local Runner (Development)

Simply run the runner on your machine:

```bash
cd evaluation_agent_v3
cp .env.sample .env
# Edit .env with your values
python runner.py
```

**Pros:** Easy setup, good for development
**Cons:** Must keep terminal open, not production-ready

---

### Option B: Azure Functions (Recommended for Production)

Deploy as serverless HTTP-triggered function.

See `azure-functions/` folder for templates.

**Environment Variables:** Set in Azure Portal → Function App → Configuration → Application Settings

```bash
# Deploy via Azure Functions Core Tools
cd deploy/azure-functions
func azure functionapp publish <function-app-name>
```

**Pros:** Serverless, auto-scaling, pay-per-use
**Cons:** Cold start latency, 10-minute timeout limit

---

### Option C: Azure Container Apps

Deploy runner as a container with HTTP endpoint.

**Environment Variables:** Set via Bicep, ARM, or Azure Portal

```bicep
resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  properties: {
    template: {
      containers: [
        {
          env: [
            { name: 'AZURE_STORAGE_ACCOUNT', value: storageAccountName }
            { name: 'PROJECT_ENDPOINT', value: projectEndpoint }
            // ... other env vars
          ]
        }
      ]
    }
  }
}
```

**Pros:** Full control, longer timeouts, persistent connections
**Cons:** Requires container management

---

### Option D: Always-On Process (VM/ACI)

Run the runner as a persistent process.

**For Azure VM:**
```bash
# Set environment variables in /etc/environment or ~/.bashrc
export AZURE_STORAGE_ACCOUNT=mystorageaccount
export PROJECT_ENDPOINT=https://...

# Run with systemd or screen/tmux
python runner.py
```

**For Azure Container Instance:**
```bash
az container create \
  --name voicelive-runner \
  --image myregistry.azurecr.io/voicelive-runner:latest \
  --environment-variables \
    AZURE_STORAGE_ACCOUNT=mystorageaccount \
    PROJECT_ENDPOINT=https://...
```

---

## Environment Variables Reference

All deployment options need these environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `PROJECT_ENDPOINT` | Yes | Foundry project endpoint |
| `MODEL_DEPLOYMENT_NAME` | Yes | LLM deployment name |
| `AGENT_ID` | Yes | Agent ID from setup_agent.py |
| `AZURE_VOICE_LIVE_ENDPOINT` | Yes | Voice Live API endpoint |
| `AZURE_VOICE_LIVE_MODEL` | Yes | Voice Live model name |
| `AZURE_VOICE_LIVE_API_VERSION` | Yes | API version |
| `AOAI_DEPLOYMENT_NAME` | Yes | AOAI deployment for metrics |
| `AOAI_REASONING_DEPLOYMENT_NAME` | Yes | Reasoning model deployment |
| `AZURE_STORAGE_ACCOUNT` | No* | Storage account (enables cloud mode) |

*Required if using cloud storage for datasets/results

## Connecting Foundry to Your Runner

Currently, the runner uses **polling** - it connects to Foundry and waits for tool calls.
This means:

1. **Runner initiates connection** to Foundry (not the other way around)
2. **No inbound networking required** - runner polls for work
3. **Runner must be running** when you use the agent

### Future: Webhook-based Integration

For true serverless (Azure Functions), you'd need Foundry to call your function via webhook.
This requires:
1. Public HTTPS endpoint for your function
2. Configuring Foundry to call your endpoint for tool execution
3. (This is not yet implemented in this project)
