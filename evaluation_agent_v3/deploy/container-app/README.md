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
- **Dynamic Session Config**: Configurable via API or environment
- **Extensible Design**: Prepared for future Voice Live Agent mode

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/run_voicelive_audio_tests` | POST | Start audio processing job |
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

# Optional
VOICELIVE_DEFAULT_VOICE=en-US-Ava:DragonHDLatestNeural
AUDIO_SAMPLE_RATE=24000
```

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
