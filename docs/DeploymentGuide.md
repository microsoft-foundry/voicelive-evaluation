# Deployment Guide — VoiceLive Evaluation

This guide covers deploying the VoiceLive Evaluation solution template to Azure using the Azure Developer CLI (`azd`).

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| Azure CLI | 2.50+ | [Install](https://learn.microsoft.com/cli/azure/install-azure-cli) |
| Azure Developer CLI (azd) | 1.18+ | [Install](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd) |
| Python | 3.11+ | [Download](https://www.python.org/downloads/) |
| Docker Desktop | Latest | [Download](https://www.docker.com/products/docker-desktop/) |

### Azure Permissions Required

| Permission | Scope | Purpose |
|---|---|---|
| **Contributor** | Subscription | Create resource groups and resources |
| **User Access Administrator** | Subscription | Assign RBAC roles to managed identities |
| **Cognitive Services User** | VoiceLive resource | API access for voice agent testing |

## Deployment Steps

### 1. Authenticate

```bash
# Log into Azure CLI
az login

# Log into Azure Developer CLI
azd auth login
```

### 2. Initialize Environment

```bash
# From the repo root
azd init
```

You'll be prompted for:
- **Environment name** — used as a prefix for Azure resources (e.g., `voicelive-eval-dev`)
- **Azure subscription** — select the subscription to deploy to
- **Azure region** — select a supported region (Sweden Central or East US 2 recommended)

### 3. Configure Parameters (Optional)

Set optional parameters before deployment:

```bash
# Use an existing Foundry project instead of creating one
azd env set CREATE_FOUNDRY false
azd env set PROJECT_ENDPOINT "https://your-foundry-project.cognitiveservices.azure.com"

# Set Voice Live endpoint (if not using auto-provisioned)
azd env set AZURE_VOICE_LIVE_ENDPOINT "https://your-voicelive-endpoint.cognitiveservices.azure.com"

# Skip Container App deployment (Functions-only mode)
azd env set DEPLOY_CONTAINER_APP false
```

### 4. Deploy

```bash
azd up
```

This command:
1. **Provisions infrastructure** — Creates resource group, AI Foundry project, Storage, Functions, Container App
2. **Deploys code** — Packages and deploys the evaluation agent to Azure Functions and Container App
3. **Runs post-provision hooks** — Assigns RBAC roles, seeds configuration tables
4. **Runs post-deploy hooks** — Displays deployment summary with URLs

Typical deployment time: **10–15 minutes**.

### 5. Verify Deployment

After `azd up` completes, verify:

```bash
# Check Function App is responding
curl $AZURE_FUNCTION_APP_URL/api/health

# Check Container App is responding
curl $AZURE_CONTAINER_APP_URL/health
```

## Troubleshooting

### Common Issues

| Issue | Cause | Fix |
|---|---|---|
| `azd up` fails with quota error | Insufficient Azure OpenAI quota | Check quota in Azure Portal → AI Services → Quotas |
| 403 errors during evaluation | Missing RBAC roles | Run `evaluation_agent/scripts/azd/postprovision.ps1` manually |
| Container App not starting | Docker not running | Start Docker Desktop before deploying |
| VoiceLive connection timeout | Wrong region | Use Sweden Central or East US 2 |

### Re-deploying

```bash
# Re-deploy code only (skip infrastructure)
azd deploy

# Re-provision infrastructure only
azd provision

# Full re-deploy
azd up
```

### Cleanup

```bash
# Delete all Azure resources
azd down

# Delete environment configuration
azd env delete <env-name>
```

## Infrastructure Details

The Bicep templates provision:

| Resource | Module | Purpose |
|---|---|---|
| Resource Group | `main.bicep` | Container for all resources |
| AI Foundry Account + Project | `modules/foundry.bicep` | Evaluation platform with model deployments |
| Storage Account | `modules/storage.bicep` | Dataset and results storage (Blob + Table) |
| Azure Functions | `modules/function-app.bicep` | 23 evaluation tool endpoints |
| Container App + ACR | `modules/container-app.bicep` | Long-running VoiceLive audio processing |
| RBAC Assignments | `modules/foundry-rbac.bicep`, `modules/service-rbac.bicep` | Keyless access between services |

All resources use **managed identities** and **RBAC** for service-to-service authentication where supported. Some platform-required connections (e.g., Functions storage, ACR pull) may use keys.
