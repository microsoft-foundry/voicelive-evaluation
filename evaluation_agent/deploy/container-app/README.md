# VoiceLive Audio Processor - Container App

Azure Container App for processing raw audio files through Azure VoiceLive SDK.

## Purpose

This Container App runs VoiceLive audio tests on datasets and generates evaluation-ready JSONL files that can be processed by the Azure Functions evaluation pipeline.

## Architecture

```
┌─────────────────┐     ┌─────────────────────┐     ┌─────────────────┐
│   Blob Storage  │◄───►│   Container App     │────►│ Azure Functions │
│   (datasets/)   │     │   (VoiceLive)       │     │  (Evaluation)   │
│   (outputs/)    │     │                     │     │                 │
└─────────────────┘     └─────────────────────┘     └─────────────────┘
```

## Features

- **Full VoiceLive SDK Integration**: Uses `azure-ai-voicelive` SDK natively
- **Async Job Processing**: Long-running jobs with status polling
- **Blob Storage Integration**: Reads datasets, writes outputs and logs
- **Foundry Dataset Integration**: Downloads datasets directly from Foundry Data Store via `foundry_dataset` parameter (independent of Function App — no blob staging required)
- **Media Dataset Support**: Accepts Foundry media format (`input_audio` via base64 data-URI or blob URL) alongside legacy `WavPath`
- **Dynamic Session Config**: Configurable via API or environment
- **Voice Live Agent Mode**: Connects to a Foundry Agent (`agent` section in `session_config` / `AGENT_NAME`+`PROJECT_NAME`) instead of a bare model deployment; the agent owns its instructions, tools, and voice settings (Entra ID auth required)

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/run_voicelive_audio_tests` | POST | Start audio processing job (accepts `dataset_path` or `foundry_dataset`) |
| `/check_job_status` | POST | Check job status |
| `/jobs/{job_id}` | GET | Get job details |

## Environment Variables

```bash
# Azure VoiceLive
AZURE_VOICELIVE_ENDPOINT=https://your-resource.services.ai.azure.com/
AZURE_VOICELIVE_MODEL=gpt-realtime

# Blob Storage
AZURE_STORAGE_ACCOUNT=stv3g7ywvldzjeo
AZURE_STORAGE_DATASETS_CONTAINER=datasets
AZURE_STORAGE_OUTPUTS_CONTAINER=outputs

# Foundry Integration (required for foundry_dataset support)
PROJECT_ENDPOINT=https://your-project.services.ai.azure.com/  # or AZURE_AI_PROJECT_ENDPOINT

# Optional
VOICELIVE_DEFAULT_VOICE=en-US-Ava:DragonHDLatestNeural
AUDIO_SAMPLE_RATE=24000
```

## Foundry Dataset Support

The Container App can download datasets directly from Foundry Data Store, bypassing blob staging entirely. Pass `foundry_dataset` instead of `dataset_path` in the request body:

```json
{
  "foundry_dataset": "my_dataset:v1",
  "session_mode": "per-conversation"
}
```

- Format: `NAME` (latest version) or `NAME:VERSION`
- Requires `PROJECT_ENDPOINT` (or `AZURE_AI_PROJECT_ENDPOINT`) env var
- Supports both legacy `WavPath` entries and media format (`input_audio` with base64 data-URI or blob URL)
- The Container App downloads the dataset independently — it does **not** go through the Function App for Foundry access

## Local Development

```bash
cd container-app
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Deployment

```bash
# Build and push image
az acr build --registry <registry> --image voicelive-processor:latest .

# Deploy via azd
azd deploy voicelive-processor
```
