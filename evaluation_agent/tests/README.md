# Evaluation Agent Tests

Integration and E2E test suites for the VoiceLive Evaluation Agent. These are **standalone test scripts** (not pytest-based) that test the deployed agent and its Azure Functions backend against live Azure services.

## Prerequisites

- Azure CLI login (`az login`)
- Active `.env` file in `evaluation_agent/` with `PROJECT_ENDPOINT` and `AGENT_ID`
- Deployed Azure Functions and Container App
- Python virtual environment with `evaluation_agent/requirements.txt` installed

## Test Suites

| Script | Description | What it Tests |
|--------|-------------|---------------|
| `test_agent_cloud.py` | Cloud integration tests | 9 tests — Agent connectivity, tool invocation via Foundry Agent SDK, response format validation |
| `test_agent_behavior.py` | Behavioral decision tests | 6 tests — Agent decision-making with different dataset types, error handling, multi-step workflows |
| `test_agent_e2e.py` | End-to-end pipeline tests | 20 tests across 8 categories — Discovery, validation, upload, VoiceLive processing, evaluation, resource management, results, edge cases |
| `test_agent_responses.py` | Responses API tests | Tests agent via Azure AI Projects Responses API (SDK 2.0+), validates streaming and non-streaming responses |
| `test_agent_sdk.py` | Direct SDK/endpoint tests | Tests Azure Functions endpoints directly via HTTP requests (bypasses agent), validates tool API contracts |
| `test_media_integration.py` | Media + Foundry integration | 8 tests — Function App and Container App endpoints for media dataset schema detection, validation, and `foundry_dataset` passthrough |

## Running Tests

All scripts accept `--help` for full options. Common patterns:

```bash
# Run from the evaluation_agent directory
cd evaluation_agent

# Cloud integration tests (quick — agent connectivity)
python tests/test_agent_cloud.py

# Behavioral tests (medium — agent decision-making)
python tests/test_agent_behavior.py

# Full E2E suite (long — entire pipeline)
python tests/test_agent_e2e.py

# Direct endpoint tests (no agent needed)
python tests/test_agent_sdk.py --base-url https://func-vh7j24h6z2pgw.azurewebsites.net/api

# Media + Foundry integration tests
python tests/test_media_integration.py
python tests/test_media_integration.py --function-url https://func-xxx.azurewebsites.net/api
python tests/test_media_integration.py --container-url https://ca-xxx.azurecontainerapps.io
```

## Manual Test Guide

`e2e_test_conversation.md` documents 20 manual E2E test cases with expected agent behavior. Use it as a reference when testing the agent interactively through the Foundry UX.

## Test Results Summary (Last Run)

| Suite | Result |
|-------|--------|
| Cloud | 9/9 passed |
| Behavioral | 6/6 passed |
| E2E | 20/20 passed |
| Responses | 4/5 passed |
