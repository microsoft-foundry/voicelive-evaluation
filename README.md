# VoiceLive Evaluation

Evaluation tools and frameworks for Azure VoiceLive (Speech-to-Speech-to-Text) voice agents. Combines VoiceLive API testing with Azure AI Foundry evaluators to assess voice assistant performance across quality dimensions like intent resolution, task adherence, and response completeness.

## Repository Structure

| Directory | Status | Description |
|-----------|--------|-------------|
| [`evaluation_agent/`](evaluation_agent/) | **Active** | Cloud-native AI agent for automating VoiceLive evaluation workflows. Backed by Azure Functions (23 endpoints), a Container App for long-running audio processing, and an AI Foundry Agent with OpenAPI tools. Supports dataset management, session configuration, VoiceLive audio testing (PTT/VAD), Foundry evaluation, and results analysis. |
| [`evaluation_harness/`](evaluation_harness/) | **Active** | Local standalone evaluation harness for processing pre-recorded audio through the VoiceLive SDK. Supports Push-to-Talk and Voice Activity Detection modes with batch processing and Azure AI Foundry evaluation integration. The local counterpart to `evaluation_agent`. |
| [`dataset_validator/`](dataset_validator/) | **Active** | CLI tools for validating JSONL evaluation datasets. Includes consistency validation (syntax, required fields, audio file presence) and quality validation (content metrics, alignment checks). |
| [`helper_scripts/`](helper_scripts/) | **Active** | Utility scripts for dataset preparation, agent creation, and Foundry resource cleanup. Includes HuggingFace dataset downloader. |
| [`UltraEval-Audio/`](UltraEval-Audio/) | Archived | Based on an external open-source audio evaluation framework. Used in early stages of VoiceLive evaluation experimentation but is not up to date and currently unused. |

## Getting Started

The primary solution is the **evaluation agent** — see [`evaluation_agent/README.md`](evaluation_agent/README.md) for full setup and usage instructions.

For local development and testing with pre-recorded audio, see [`evaluation_harness/README.md`](evaluation_harness/README.md).

## Setup

```pwsh
python -m venv .venv
.venv\Scripts\Activate.ps1
python.exe -m pip install --upgrade pip
pip install -r .\requirements.txt
```

> **Note:** Each subdirectory has its own `requirements.txt` — install from the directory you are working in.

## Contributing

This project welcomes contributions and suggestions.  Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit [Contributor License Agreements](https://cla.opensource.microsoft.com).

When you submit a pull request, a CLA bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., status check, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft
trademarks or logos is subject to and must follow
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.
Any use of third-party trademarks or logos are subject to those third-party's policies.
