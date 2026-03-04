# Evaluation Harness Tests

Smoke tests for the local evaluation harness — audio loading, dataset parsing, and format validation.

## Test Suites

| Script | Description |
|--------|-------------|
| `test_audio_loading.py` | Tests audio file loading (PCM16 + float32 WAV) and dataset parsing for Eiffel Tower and speech-trivia-qa datasets |

## Running Tests

```bash
cd evaluation_harness
python tests/test_audio_loading.py
```

## Prerequisites

- Python virtual environment with `evaluation_harness/requirements.txt` installed
- Sample datasets in `sample_evaluation_input/` and `local_datasets/`
