# Helper Scripts

Utility scripts for preparing datasets and data conversion for the VoiceLive evaluation pipeline.

## Scripts

### hf_dataset_to_jsonl.py

Downloads HuggingFace audio datasets and creates evaluation-ready JSONL files compatible with `prototype_v1` and `UltraEval-Audio`.

```bash
# Download all 3 default TwinkStart datasets
python helper_scripts/hf_dataset_to_jsonl.py

# Download a specific dataset with a sample limit
python helper_scripts/hf_dataset_to_jsonl.py TwinkStart/llama-questions --limit 50

# Multiple datasets with custom output directory
python helper_scripts/hf_dataset_to_jsonl.py TwinkStart/llama-questions TwinkStart/speech-web-questions --output-dir ./my_datasets

# Gated dataset with HF token
python helper_scripts/hf_dataset_to_jsonl.py my-org/private-dataset --token hf_xxxxx
```

**Default datasets** (when no dataset argument is provided):
- `TwinkStart/llama-questions` (300 samples)
- `TwinkStart/speech-web-questions` (2032 samples)
- `TwinkStart/speech-triavia-qa` (1024 samples)

**CLI arguments:**

| Argument | Default | Description |
|---|---|---|
| `dataset` | All 3 TwinkStart datasets | HuggingFace dataset name(s) |
| `--split` | `test` | Dataset split to download |
| `--limit` | None (all) | Max samples per dataset |
| `--output-dir` | `./datasets` | Output directory |
| `--system-prompt` | None | System prompt for every JSONL row |
| `--token` | None | HuggingFace token (or set `HF_TOKEN` env var) |
| `--cache-dir` | `./hf_data_cache` | HF download cache directory |
| `--verbose` | False | Enable debug logging |

**Output structure:**
```
local_datasets/
├── TwinkStart-llama-questions/
│   ├── TwinkStart-llama-questions.jsonl
│   └── wav/
│       ├── 0.wav
│       ├── 1.wav
│       └── ...
```

The generated JSONL matches the evaluation pipeline schema:
```json
{"WavPath": "/abs/path/to/0.wav", "Question": "...", "Answer": "...", "conversationID": "TwinkStart-llama-questions-0", "system_prompt": null, "tool_definitions": null}
```

### huggingface_datasets.py

Exploratory script for inspecting HuggingFace dataset structure (columns, splits, sample data). Useful for adding support for new datasets.

### convert_bingchat_dataset.py

Converts Bing Chat evaluation datasets to the JSONL format used by the evaluation pipeline.

## Troubleshooting

### FFmpeg Errors

Some HuggingFace datasets require FFmpeg for audio decoding:
```bash
choco install ffmpeg   # Windows
brew install ffmpeg    # macOS
sudo apt install ffmpeg  # Linux
```

### Authentication Errors (Gated Datasets)

For gated/private datasets, provide a HuggingFace token:
```bash
# Option 1: CLI flag
python helper_scripts/hf_dataset_to_jsonl.py my-org/dataset --token hf_xxxxx

# Option 2: Environment variable
export HF_TOKEN=hf_xxxxx
python helper_scripts/hf_dataset_to_jsonl.py my-org/dataset
```

### Dataset Not Found

Verify the dataset name and available splits:
```python
from datasets import get_dataset_infos
infos = get_dataset_infos("TwinkStart/llama-questions")
print(infos)
```
