# VoiceLive Evaluation Agent v2 - Architecture

Cloud-deployable architecture supporting both local development and Azure deployment.

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         VoiceLive Evaluation Agent v2                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐         │
│  │   Agent Core    │───▶│  Tool Functions │───▶│   Subprocess    │         │
│  │   (agent.py)    │    │  (validation,   │    │   Execution     │         │
│  │                 │    │   evaluation)   │    │                 │         │
│  └────────┬────────┘    └─────────────────┘    └────────┬────────┘         │
│           │                                             │                   │
│           ▼                                             ▼                   │
│  ┌─────────────────┐                          ┌─────────────────┐          │
│  │  Azure AI       │                          │  scripts/       │          │
│  │  Agents SDK     │                          │  (evaluation    │          │
│  │                 │                          │   scripts)      │          │
│  └────────┬────────┘                          └─────────────────┘          │
│           │                                                                 │
└───────────┼─────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Azure Services                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐         │
│  │  Azure AI       │    │  Azure Blob     │    │  Azure Monitor  │         │
│  │  Foundry        │    │  Storage        │    │  (App Insights) │         │
│  │  (GPT-4o-mini)  │    │  (datasets/     │    │                 │         │
│  │                 │    │   outputs/)     │    │                 │         │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Dual-Mode Architecture

The agent supports two deployment modes with automatic detection:

### Local Mode (Default)

```
evaluation_agent_v2/
├── agent.py              ──────────▶ Python subprocess calls
│                                            │
│                                            ▼
│                         ../../prototype_v1/batch_processor.py
│                         ../../dataset_validator/*.py
│
├── output/               ◀────────── Results saved locally
└── logs/                 ◀────────── Logs saved locally
```

### Cloud Mode (Container Apps)

```
Container (evaluation_agent_v2/)
├── agent.py              ──────────▶ Python subprocess calls
│                                            │
│                                            ▼
│                         ./scripts/batch_processor.py
│                         ./scripts/validators/*.py
│
│                         ┌──────────────────────────────────┐
│                         │    Azure Blob Storage            │
├── cloud_storage.py ────▶│    ├── datasets/  (input)       │
│                         │    └── outputs/   (results)     │
│                         └──────────────────────────────────┘
```

## Mode Detection Logic

```python
def is_cloud_mode() -> bool:
    return bool(
        os.environ.get("AZURE_STORAGE_ACCOUNT") or 
        os.environ.get("EVAL_AGENT_MODE", "").lower() == "cloud" or
        "--cloud" in sys.argv
    )
```

| Condition | Mode |
|-----------|------|
| `AZURE_STORAGE_ACCOUNT` set | Cloud |
| `EVAL_AGENT_MODE=cloud` | Cloud |
| `--cloud` flag | Cloud |
| None of above | Local |

## Path Resolution

Scripts are located differently based on mode:

```python
if is_cloud_mode():
    # Cloud: scripts bundled in container
    SCRIPTS_DIR = SCRIPT_DIR / "scripts"
    VALIDATORS_DIR = SCRIPTS_DIR / "validators"
else:
    # Local: scripts in repo sibling directories
    SCRIPTS_DIR = REPO_ROOT / "prototype_v1"
    VALIDATORS_DIR = REPO_ROOT / "dataset_validator"
```

## Cloud Infrastructure

### Azure Resources

```
┌──────────────────────────────────────────────────────────────────┐
│                     Resource Group (rg-{env})                     │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────────────┐     ┌─────────────────────┐             │
│  │   AI Services       │     │   Blob Storage      │             │
│  │   (ai-{token})      │     │   (st{token})       │             │
│  │                     │     │                     │             │
│  │   - GPT-4o-mini     │     │   - datasets/       │             │
│  │   - Embeddings      │     │   - outputs/        │             │
│  └─────────┬───────────┘     └──────────┬──────────┘             │
│            │                            │                         │
│            │    RBAC (Managed Identity) │                         │
│            │         ┌──────────────────┘                         │
│            ▼         ▼                                            │
│  ┌─────────────────────────────────────────┐                     │
│  │   Container Apps Environment            │                     │
│  │   (cae-{token})                         │                     │
│  │                                         │                     │
│  │   ┌─────────────────────────────────┐   │                     │
│  │   │   Container App (ca-{token})    │   │                     │
│  │   │                                 │   │                     │
│  │   │   - System Managed Identity     │   │                     │
│  │   │   - Auto-scaling (0-10)         │   │                     │
│  │   │   - Health checks               │   │                     │
│  │   └─────────────────────────────────┘   │                     │
│  └─────────────────────────────────────────┘                     │
│                                                                   │
│  ┌─────────────────────┐     ┌─────────────────────┐             │
│  │   Container         │     │   Log Analytics     │             │
│  │   Registry          │     │   (log-{token})     │             │
│  │   (cr{token})       │     │                     │             │
│  └─────────────────────┘     └─────────────────────┘             │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

### RBAC Assignments

| Role | Scope | Purpose |
|------|-------|---------|
| Cognitive Services User | AI Services | LLM inference |
| Storage Blob Data Contributor | Storage Account | Read/write datasets & outputs |
| AcrPull | Container Registry | Pull container images |

### Security Model

- **No secrets stored**: All auth via Managed Identity
- **DefaultAzureCredential**: Works in both local (CLI) and cloud (MI)
- **Network isolation**: Container Apps can be VNet-integrated (optional)

## Bicep Module Structure

```
infra/
├── main.bicep                    # Orchestration
├── main.parameters.json          # Parameter defaults
└── modules/
    ├── ai-services.bicep         # Azure AI Services + GPT deployment
    ├── storage.bicep             # Blob Storage + containers
    ├── container-registry.bicep  # ACR for images
    ├── container-apps-environment.bicep  # CA environment
    ├── container-app.bicep       # The agent container
    ├── log-analytics.bicep       # Logging workspace
    ├── ai-services-rbac.bicep    # Cognitive Services User role
    └── storage-rbac.bicep        # Storage Blob Data Contributor role
```

## Container Architecture

### Dockerfile Strategy

```dockerfile
# Multi-stage build for smaller image
FROM python:3.11-slim as builder
# Install build deps, pip packages

FROM python:3.11-slim
# Runtime deps: ffmpeg (audio), libsndfile1
# Non-root user for security
# Copy only necessary files
```

### Image Contents

```
/app/
├── agent.py
├── tracing.py
├── cloud_storage.py
├── requirements.txt (installed)
└── scripts/
    ├── batch_processor.py
    ├── voice_agent_audio_input_evaluation.py
    ├── voice_agent_evaluation.py
    ├── voice_metrics_evaluator.py
    └── validators/
        ├── validate_dataset_consistency.py
        ├── validate_dataset_quality.py
        └── check_dataset_schema.py
```

## Data Flow

### Cloud Evaluation Flow

```
1. User Request
   │
   ▼
2. Agent receives "Run evaluation on datasets/project-a/test.jsonl"
   │
   ▼
3. cloud_storage.download_dataset()
   │  - Downloads from Blob: datasets/project-a/test.jsonl
   │  - Downloads audio files: datasets/project-a/audio/*.wav
   │  - Saves to /tmp/voicelive_eval_xxx/
   │
   ▼
4. Subprocess: batch_processor.py
   │  - Processes each entry
   │  - Calls Voice Live API
   │  - Generates results
   │
   ▼
5. cloud_storage.upload_results()
   │  - Uploads to Blob: outputs/2026-02-03_10-30-00/
   │  - Includes aggregate_results.jsonl
   │
   ▼
6. Return results to user with Foundry portal link
```

### Local Evaluation Flow

```
1. User Request
   │
   ▼
2. Agent receives "Run evaluation on C:\datasets\test.jsonl"
   │
   ▼
3. Direct filesystem access
   │  - Reads from local path
   │
   ▼
4. Subprocess: ../../prototype_v1/batch_processor.py
   │  - Processes each entry
   │  - Generates results
   │
   ▼
5. Saves to ./output/
   │
   ▼
6. Return results to user
```

## Environment Configuration

### Container App Environment Variables

Set automatically by Bicep:

```bash
PROJECT_ENDPOINT         # AI Foundry endpoint
MODEL_DEPLOYMENT_NAME    # gpt-4o-mini
AZURE_STORAGE_ACCOUNT    # Storage account name
AZURE_STORAGE_DATASETS_CONTAINER   # datasets
AZURE_STORAGE_OUTPUTS_CONTAINER    # outputs
EVAL_AGENT_MODE          # cloud
EVAL_AGENT_LOG_LEVEL     # INFO
APPLICATIONINSIGHTS_CONNECTION_STRING  # (if enabled)
```

## Scaling Considerations

### Container Apps Scaling

```bicep
scale: {
  minReplicas: 0    // Scale to zero when idle
  maxReplicas: 10   // Handle burst workloads
  rules: [{
    name: 'http-rule'
    http: {
      metadata: {
        concurrentRequests: '10'
      }
    }
  }]
}
```

### Parallel Processing

- **Max workers**: Controlled by `EVAL_AGENT_MAX_WORKERS` (default: 4)
- **Batch processor**: Handles parallel evaluation entries
- **Container memory**: 2Gi recommended for parallel workloads

## Comparison: v1 vs v2

| Aspect | v1 (evaluation_agent) | v2 (evaluation_agent_v2) |
|--------|----------------------|--------------------------|
| Deployment | Local only | Local + Cloud |
| Storage | Filesystem | Filesystem / Blob Storage |
| Scripts | External (../../) | Bundled (./scripts/) |
| Container | Not supported | Docker + Bicep |
| Auth | Azure CLI | CLI + Managed Identity |
| Infra | Manual | Infrastructure as Code |
| Cost | Free (local) | ~$85-345/month (cloud) |

## Future Enhancements

- [ ] VNet integration for private endpoints
- [ ] Azure Key Vault integration (if secrets needed)
- [ ] GitHub Actions CI/CD pipeline
- [ ] Multi-region deployment
- [ ] Kubernetes (AKS) alternative deployment
