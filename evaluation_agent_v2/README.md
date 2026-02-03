# VoiceLive Evaluation Agent v2

Cloud-deployable version of the VoiceLive Evaluation Agent with Azure Container Apps and Blob Storage support.

## Overview

This is an enhanced version of the evaluation agent designed for both **local development** and **cloud deployment**. It includes:

- **Dual-mode operation**: Works locally (filesystem) or in cloud (Azure Blob Storage)
- **Containerized deployment**: Docker-based for consistent environments
- **Infrastructure as Code**: Bicep templates for Azure deployment via `azd`
- **Managed Identity auth**: No secrets required - uses DefaultAzureCredential

## Quick Start

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
$env:PROJECT_ENDPOINT = "https://<resource>.services.ai.azure.com/api/projects/<project>"

# Run interactively (local mode)
python agent.py

# Or with explicit local mode
python agent.py --verbose
```

### Cloud Deployment

**Prerequisites:**
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) must be installed and **running**
- Azure CLI logged in (`az login`)
- Azure Developer CLI installed (`azd`)

```bash
# Start Docker Desktop first (required for container build)
# On Windows: Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"

# Login to Azure
azd auth login

# Initialize environment (first time only)
azd init

# Deploy everything
azd up

# Or deploy separately
azd provision  # Infrastructure only
azd deploy     # Code only

# Tear down
azd down
```

> **Note:** If you get "Docker service is not running" error, start Docker Desktop and wait for it to fully initialize before running `azd up`.

## Deployment Modes

| Mode | Storage | Use Case |
|------|---------|----------|
| **Local** | Filesystem (`./output/`) | Development, testing |
| **Cloud** | Azure Blob Storage | Production, team use |

### Mode Detection

The agent auto-detects cloud mode when:
- `AZURE_STORAGE_ACCOUNT` environment variable is set, OR
- `EVAL_AGENT_MODE=cloud` is set, OR
- `--cloud` flag is passed

```bash
# Force cloud mode
python agent.py --cloud

# Force local mode (default)
python agent.py
```

## Project Structure

```
evaluation_agent_v2/
├── agent.py              # Main agent (dual-mode)
├── tracing.py            # OpenTelemetry tracing
├── cloud_storage.py      # Azure Blob Storage client
├── requirements.txt      # Python dependencies
├── Dockerfile            # Container image
├── .dockerignore         # Docker build exclusions
├── .env.sample           # Environment template
├── azure.yaml            # azd configuration
├── infra/                # Bicep infrastructure
│   ├── main.bicep        # Main orchestration
│   ├── main.parameters.json
│   └── modules/          # Individual resources
│       ├── ai-services.bicep
│       ├── storage.bicep
│       ├── container-app.bicep
│       └── ...
└── scripts/              # Evaluation scripts (cloud copy)
    ├── batch_processor.py
    ├── voice_agent_audio_input_evaluation.py
    └── validators/
```

## Environment Variables

### Required

| Variable | Description |
|----------|-------------|
| `PROJECT_ENDPOINT` | Azure AI Foundry project endpoint |

### Cloud Mode (required when deployed)

| Variable | Description |
|----------|-------------|
| `AZURE_STORAGE_ACCOUNT` | Storage account name |
| `AZURE_STORAGE_DATASETS_CONTAINER` | Datasets container (default: `datasets`) |
| `AZURE_STORAGE_OUTPUTS_CONTAINER` | Outputs container (default: `outputs`) |

### Optional

| Variable | Description |
|----------|-------------|
| `MODEL_DEPLOYMENT_NAME` | Model to use (default: `gpt-4o-mini`) |
| `EVAL_AGENT_MODE` | Force `cloud` or `local` mode |
| `EVAL_AGENT_LOG_LEVEL` | Logging level (default: `INFO`) |
| `EVAL_AGENT_MAX_WORKERS` | Parallel workers (default: `4`) |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Azure Monitor tracing |

## Azure Resources (Cloud Deployment)

When deployed with `azd up`, the following resources are created:

| Resource | Purpose |
|----------|---------|
| **Azure AI Services** | LLM inference (GPT-4o-mini) |
| **Azure Blob Storage** | Dataset and output storage |
| **Azure Container Apps** | Hosts the containerized agent |
| **Azure Container Registry** | Stores container images |
| **Log Analytics** | Container Apps logging |

### Estimated Cost

- **Development**: ~$85/month (minimal usage)
- **Production**: ~$200-345/month (depends on evaluation volume)

## Local vs Cloud Differences

| Feature | Local | Cloud |
|---------|-------|-------|
| Dataset source | Filesystem | Blob Storage |
| Output location | `./output/` | Blob Storage |
| Script paths | `../../prototype_v1/` | `./scripts/` |
| Auth | Azure CLI / env vars | Managed Identity |
| Tracing | Console | Azure Monitor |

## Usage Examples

### List Available Datasets

```
> List datasets
```

In local mode, searches `prototype_v1/local_datasets/`.
In cloud mode, lists from Blob Storage `datasets/` container.

### Run Evaluation

```
> Run voicelive evaluation on datasets/project-a/test.jsonl
```

### Validate Dataset

```
> Validate dataset C:\path\to\dataset.jsonl
```

## Development

### Building the Docker Image

```bash
docker build -t voicelive-eval-agent .
```

### Running Locally in Docker

```bash
docker run -it \
  -e PROJECT_ENDPOINT="..." \
  -e AZURE_STORAGE_ACCOUNT="..." \
  voicelive-eval-agent
```

### Testing Cloud Storage

```python
from cloud_storage import CloudStorageClient, is_cloud_mode

if is_cloud_mode():
    client = CloudStorageClient()
    datasets = client.list_datasets()
    print(datasets)
```

## Relationship to evaluation_agent (v1)

This v2 version is a **cloud-deployable fork** of the original `evaluation_agent/`:

- **v1** (`evaluation_agent/`): Local-only, simpler setup, references repo scripts
- **v2** (`evaluation_agent_v2/`): Cloud-ready, containerized, self-contained scripts

Both versions share the same core functionality and tool definitions. v2 adds:
- Cloud storage integration
- Container deployment
- Infrastructure as Code
- Self-contained script copies

## Troubleshooting

### "Storage account name required"
Set `AZURE_STORAGE_ACCOUNT` or run without `--cloud` flag for local mode.

### "Dataset not found"
- Local: Check file path exists
- Cloud: Verify blob exists in `datasets/` container

### "Module not found: tracing"
Ensure you're running from the `evaluation_agent_v2/` directory.

## See Also

- [evaluation_agent/README.md](../evaluation_agent/README.md) - Original v1 agent
- [evaluation_agent/ARCHITECTURE.md](../evaluation_agent/ARCHITECTURE.md) - Architecture details
