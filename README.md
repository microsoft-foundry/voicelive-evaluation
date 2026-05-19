# VoiceLive Evaluation

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/microsoft-foundry/voicelive-evaluation?quickstart=1)
[![Open in Dev Containers](https://img.shields.io/static/v1?style=for-the-badge&label=Dev%20Containers&message=Open&color=blue&logo=visualstudiocode)](https://vscode.dev/redirect?url=vscode://ms-vscode-remote.remote-containers/cloneInVolume?url=https://github.com/microsoft-foundry/voicelive-evaluation)

End-to-end quality evaluation for voice agents built on **Azure AI Voice Live**. Deploy evaluation infrastructure to Azure with one command, then run pre-recorded audio through your voice agent and get scored results in Azure AI Foundry.

> **Use case**: You've built a customer-service voice agent with Voice Live — an appointment scheduler, a tech-support bot, a healthcare intake agent. Now you need to know: *Is the agent staying on task? Does it resolve customer intents? Are conversations completing successfully?* This solution template gives you a fully automated evaluation pipeline to answer those questions.

> [!IMPORTANT]
> This template uses Azure AI services that may incur costs. Review the [Cost and cleanup](#cost-and-cleanup) section before deploying.

---

## Features

| Capability | Description |
|---|---|
| **Automated voice agent testing** | Process pre-recorded audio datasets through Voice Live in PTT, VAD, or Agent modes |
| **Multi-turn conversation evaluation** | Evaluate complex multi-turn conversations including tool calls and grounding |
| **13 built-in quality evaluators** | Score responses on intent resolution, task adherence, task completion, response completeness, and more |
| **Batch processing** | Run evaluations across multiple conversations and datasets in parallel |
| **Foundry portal integration** | View per-turn and aggregate scores directly in the Azure AI Foundry portal |
| **Cloud + local execution** | Deploy the evaluation agent to Azure, or run the CLI harness locally |

---

## Architecture

```
┌─────────────────┐     config      ┌──────────────────────┐     per turn     ┌─────────────────┐
│  Audio Dataset   │ ──────────────► │  Evaluation Harness  │ ───────────────► │  Voice Live API  │
│  (multi-turn     │                 │  (Python CLI)        │                  │  (your agent)    │
│   scripts+audio) │                 │                      │                  │                  │
└─────────────────┘                 └──────────┬───────────┘                  └─────────────────┘
                                               │ responses
                                               ▼
                                    ┌──────────────────────┐      scores      ┌─────────────────┐
                                    │  Azure AI Foundry     │ ───────────────► │  Scored Results  │
                                    │  Evaluation           │                  │  (per-turn +     │
                                    │  (13 evaluators)      │                  │   aggregate)     │
                                    └──────────────────────┘                  └─────────────────┘
```

The solution deploys:
- **Azure AI Foundry** project with evaluator model deployments (GPT-4.1-mini, o4-mini)
- **Azure Functions** app with 23 evaluation tool endpoints
- **Container App** for long-running VoiceLive audio processing
- **Azure Blob Storage** for datasets and results
- **RBAC** assignments for secure, keyless access

---

## Quick Deploy

### Prerequisites

| Requirement | Details |
|---|---|
| **Azure subscription** | With Cognitive Services and Contributor access |
| **Azure CLI** | [Install](https://learn.microsoft.com/cli/azure/install-azure-cli) |
| **Azure Developer CLI (azd)** | [Install](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd) |
| **Python 3.11+** | For running the evaluation harness locally |
| **Docker Desktop** | For Container App deployment |

### Supported Regions

Voice Live and Azure AI Foundry evaluators are available in select regions:

| Region | Voice Live | Foundry Evaluators |
|---|---|---|
| **Sweden Central** | ✅ | ✅ |
| **East US 2** | ✅ | ✅ |

### Option 1: Deploy with GitHub Codespaces (Recommended)

1. Click **Open in GitHub Codespaces** above
2. Wait for the dev container to build (~2 min)
3. In the terminal:
   ```bash
   azd auth login
   azd up
   ```
4. Follow the prompts to select your subscription and region

### Option 2: Deploy locally

```bash
git clone https://github.com/microsoft-foundry/voicelive-evaluation.git
cd voicelive-evaluation
azd auth login
azd up
```

`azd up` provisions all Azure resources, deploys the evaluation agent, and wires credentials automatically.

---

## Run an Evaluation

After deployment, run evaluations using the local CLI harness:

```bash
# Install harness dependencies
cd evaluation_harness
pip install -r requirements.txt

# Copy and configure environment
cp .sample_env .env
# Edit .env with your Voice Live endpoint

# Run evaluation with a sample dataset
python voice_agent_evaluation.py --config configs/sample_vad_realtime.json

# Or run in batch mode across multiple datasets
python batch_processor.py --config configs/sample_vad_realtime.json
```

### Configuration Modes

| Mode | Config | Use When |
|---|---|---|
| **Server VAD** | `sample_vad_realtime.json` | Agent uses voice activity detection for turn-taking |
| **Push-to-Talk** | `sample_ptt_realtime.json` | Agent uses explicit push-to-talk signals |
| **Agent Mode** | `sample_agent_config.json` | Testing a Foundry Agent with tool calls |

### View Results

After an evaluation run:
1. Open the [Azure AI Foundry portal](https://ai.azure.com)
2. Navigate to your project → **Evaluation**
3. View per-turn scores and aggregate metrics across:
   - Intent Resolution
   - Task Adherence
   - Task Completion
   - Response Completeness
   - *(+ 9 additional evaluators)*

---

## Repository Structure

```
voicelive-evaluation/
├── azure.yaml                    # Azure Developer CLI config (solution template entry point)
├── .devcontainer/                # Codespaces / Dev Container configuration
├── evaluation_harness/           # Local CLI — run evaluations locally
│   ├── configs/                  # Sample evaluation configurations
│   ├── sample_evaluation_input/  # Sample audio datasets
│   └── voice_agent_evaluation.py # Main entry point
├── evaluation_agent/             # Cloud agent — deployed via azd up
│   ├── infra/                    # Bicep infrastructure-as-code
│   ├── deploy/                   # Azure Functions + Container App
│   └── scripts/                  # Post-provision and post-deploy automation
├── dataset_validator/            # CLI tools for validating evaluation datasets
├── helper_scripts/               # Dataset preparation and utility scripts
└── docs/                         # Documentation and transparency FAQ
```

| Component | Purpose | How to Use |
|---|---|---|
| [`evaluation_harness/`](evaluation_harness/) | Local standalone evaluation CLI. Sends audio → Voice Live → evaluators. Supports PTT/VAD/Agent modes, JSON configs, batch processing. | `python voice_agent_evaluation.py --config configs/sample_vad_realtime.json` |
| [`evaluation_agent/`](evaluation_agent/) | Cloud-native agent (Azure Functions + Container App + Foundry Agent). Deployed by `azd up`. | Deployed automatically; interact via Foundry Agent or API |
| [`dataset_validator/`](dataset_validator/) | Validates JSONL evaluation datasets before running evaluations. | `python validator.py --dataset path/to/dataset.jsonl` |
| [`helper_scripts/`](helper_scripts/) | Dataset downloaders, agent creation scripts, Foundry resource cleanup. | See individual script help |

---

## Sample Datasets

The template includes sample evaluation datasets to get started:

| Dataset | Scenario | Turns | Description |
|---|---|---|---|
| `Eiffel_Tower_Visit` | Travel planning | Multi-turn | Customer asks about visiting the Eiffel Tower |
| `DataOceanDemoComplexSession1` | Data analytics | Multi-turn | Complex multi-step data query conversation |
| `Tool_Call_Test_Sample` | Tool integration | Multi-turn | Conversation with tool calls and grounding |
| `MultiConversationSample` | Batch evaluation | Multiple | Multiple conversations for batch processing |

---

## Cost and Cleanup

### Estimated Costs

| Resource | SKU | Estimated Monthly Cost |
|---|---|---|
| Azure AI Foundry (AI Services) | Standard | Usage-based (evaluator model calls) |
| Azure Functions | Consumption | Usage-based (~$0 for evaluation workloads) |
| Container App | Consumption | Usage-based (scales to zero when idle) |
| Azure Blob Storage | Standard LRS | ~$1/month |

> **Tip**: The Container App and Functions scale to zero when not in use, so idle costs are minimal.

### Cleanup

To remove all deployed Azure resources:

```bash
azd down
```

This deletes the resource group and all resources created by the template.

---

## Testing

```bash
# Unit tests (no Azure credentials needed)
python evaluation_harness/tests/test_config_and_evaluators.py   # 40 tests
python evaluation_harness/tests/test_e2e_pipeline.py            # Format + structure tests
python evaluation_harness/tests/test_media_dataset.py           # 24 tests

# E2E pipeline (requires Azure credentials + VoiceLive endpoint)
python evaluation_harness/tests/test_e2e_full_pipeline.py --mode both --skip-evaluation

# Integration tests (requires deployed infrastructure)
python evaluation_agent/tests/test_media_integration.py         # 8 tests
```

---

## Contributing

This project welcomes contributions and suggestions. Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit [Contributor License Agreements](https://cla.opensource.microsoft.com).

When you submit a pull request, a CLA bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., status check, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

## Responsible AI

This solution template uses Azure AI services. Please review our [Transparency FAQ](docs/TRANSPARENCY_FAQ.md) for details on capabilities, limitations, and responsible use.

For Azure AI Voice Live specific transparency documentation, see the [Azure AI Services transparency notes](https://learn.microsoft.com/azure/ai-services/speech-service/voice-live-overview).

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft
trademarks or logos is subject to and must follow
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.
Any use of third-party trademarks or logos are subject to those third-party's policies.
