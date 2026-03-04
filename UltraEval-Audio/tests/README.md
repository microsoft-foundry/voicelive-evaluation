# UltraEval-Audio Tests

Test suites for the UltraEval-Audio evaluation framework. These are standalone test scripts that validate evaluator registration, dataset loading, and Azure AI Foundry integration.

## Prerequisites

- Python virtual environment with `UltraEval-Audio/requirments.txt` installed
- For Foundry tests: Azure CLI login and `.env` with `AOAI_ENDPOINT`, `AOAI_DEPLOYMENT_NAME`

## Test Suites

| Script | Description |
|--------|-------------|
| `test_audio_evals_registry.py` | Validates evaluator and model registry — checks all evaluators/models are discoverable and instantiable |
| `test_dataset.py` | Validates dataset loading and format — checks JSONL parsing, field validation, audio path resolution |
| `test_azure_ai_foundry.py` | Tests Azure AI Foundry evaluator integration — batch evaluation, QA scoring, result format validation |

## Running Tests

```bash
# Run from UltraEval-Audio directory
cd UltraEval-Audio

# Registry tests (no Azure credentials needed)
python tests/test_audio_evals_registry.py

# Dataset tests (no Azure credentials needed)
python tests/test_dataset.py

# Foundry evaluator tests (requires Azure credentials)
python tests/test_azure_ai_foundry.py
```
