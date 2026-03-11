# Evaluation Harness Tests

Test suites for the local evaluation harness — unit tests, integration tests, and E2E pipeline validation.

## Test Suites

| Script | Type | Azure Creds | Description |
|--------|------|:-----------:|-------------|
| `test_audio_loading.py` | Unit | No | Audio file loading (PCM16 + float32 WAV), dataset parsing |
| `test_e2e_pipeline.py` | Integration | No | Dataset loading, eval data assembly, tool message format, path traversal |
| `test_config_and_evaluators.py` | Unit | No | Config file loading, CLI override precedence, evaluator parsing, VAD selection, model override, SessionConfig helpers |
| `test_e2e_full_pipeline.py` | E2E | **Yes** | Full pipeline: dataset → VoiceLive API → Foundry evaluation with realtime + cascaded modes |

## Running Tests

```bash
# Unit tests (no credentials needed)
python evaluation_harness/tests/test_audio_loading.py
python evaluation_harness/tests/test_e2e_pipeline.py --dataset eiffel
python evaluation_harness/tests/test_config_and_evaluators.py

# E2E pipeline (requires Azure credentials + VoiceLive endpoint)
python evaluation_harness/tests/test_e2e_full_pipeline.py --mode realtime --skip-evaluation
python evaluation_harness/tests/test_e2e_full_pipeline.py --mode both
python evaluation_harness/tests/test_e2e_full_pipeline.py --mode cascaded --evaluators all
```

## Test Coverage (40 unit tests + E2E)

| Category | Tests | What's Covered |
|----------|:-----:|----------------|
| SessionConfig defaults | 11 | Default values, transcription model auto-detect, EOU support, tools hint, dataclass replace |
| Evaluator constants | 4 | Count (8 default / 13 all), no duplicates, required names present |
| Evaluator parsing | 8 | "default", "all", None, custom list, spaces, empty string, commas-only |
| Config file loading | 7 | Flat keys, nested keys, CLI override, JSON roundtrip, sample_config.json, unknown keys, empty |
| VAD type selection | 6 | server_vad vs semantic_vad, threshold, EOU for realtime/cascaded, explicit disable |
| Model override | 4 | Env var priority, CLI overrides env, no-env default, CLI can set gpt-realtime |
| E2E pipeline | 2 | Realtime + cascaded modes, output validation, cross-mode field comparison |

## Prerequisites

- Python virtual environment with `requirements.txt` installed
- Sample datasets in `sample_evaluation_input/` (unit tests)
- `AZURE_VOICELIVE_ENDPOINT` env var (E2E tests only)
- Active `az login` session (E2E tests only)
