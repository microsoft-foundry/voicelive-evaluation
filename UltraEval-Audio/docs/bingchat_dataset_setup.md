# BingChat Agent Test Set Setup Guide

## Overview
This guide documents the setup of the BingChat Agent Test Set (FY26) for evaluation in the UltraEval-Audio pipeline.

## Dataset Information

### Source Data
- **Location**: `/raw/BingChat_AgentTestSet_FY26/`
- **Languages**: English (en-us) and French (fr-fr)
- **Date**: 14112025 (November 14, 2025)
- **Format**: JSON metadata files + WAV audio files

### Dataset Structure

#### Original Format
Each language directory contains:
- **JSON metadata files**: 
  - `BingChat_AgentTestSet_FY26_{lang}_BTEST_TxResults.json`
  - `BingChat_AgentTestSet_FY26_{lang}_DTEST_TxResults.json`
- **WAV audio files**: UUID-named files (e.g., `5a2b885d-640b-4eab-b281-735f99921a48.wav`)

#### JSON Schema
```json
{
  "FlowId": "UUID",
  "FlowName": "BingChat_AgentTestSet_FY26",
  "TxLocal": "en-us",
  "SRLocal": "en-us",
  "BatchId": "string",
  "ListOfUtterances": [
    {
      "CompareKey": "5a2b885d-640b-4eab-b281-735f99921a48",
      "Transcription": "Mail but. Kanye West net worth.",
      "AudioUrl": "https://txflowmediaprod01eus.blob.core.windows.net/permanentmedia-en-us/{UUID}.wav",
      "PhraseId": 0
    }
  ]
}
```

### English BTEST Dataset
- **Total utterances**: 1585
- **Successfully converted**: 1583 (2 audio files missing)
- **Task type**: ASR (Automatic Speech Recognition)

## Conversion Process

### Script Location
`/UltraEval-Audio/scripts/convert_bingchat_dataset.py`

### Usage

#### Convert English BTEST dataset:
```bash
python3 UltraEval-Audio/scripts/convert_bingchat_dataset.py \
  --dataset-dir raw/BingChat_AgentTestSet_FY26/en-us_14112025 \
  --output-dir UltraEval-Audio/registry/dataset/data \
  --test-type BTEST
```

#### Convert all test types (BTEST + DTEST):
```bash
python3 UltraEval-Audio/scripts/convert_bingchat_dataset.py \
  --dataset-dir raw/BingChat_AgentTestSet_FY26/en-us_14112025 \
  --output-dir UltraEval-Audio/registry/dataset/data \
  --test-type both
```

#### Convert French dataset:
```bash
python3 UltraEval-Audio/scripts/convert_bingchat_dataset.py \
  --dataset-dir raw/BingChat_AgentTestSet_FY26/fr-fr_14112025 \
  --output-dir UltraEval-Audio/registry/dataset/data \
  --test-type both
```

### Output Format (JSONL)

Each line in the output file is a JSON record:
```json
{
  "audio": "raw/BingChat_AgentTestSet_FY26/en-us_14112025/5a2b885d-640b-4eab-b281-735f99921a48.wav",
  "question": "Mail but. Kanye West net worth.",
  "answer": "",
  "uuid": "5a2b885d-640b-4eab-b281-735f99921a48",
  "audio_url": "https://txflowmediaprod01eus.blob.core.windows.net/permanentmedia-en-us/5a2b885d-640b-4eab-b281-735f99921a48.wav"
}
```

### Field Mapping
| Source Field | Target Field | Description |
|-------------|--------------|-------------|
| CompareKey | uuid | Unique identifier (reference column) |
| Transcription | question | Ground truth transcription text |
| AudioUrl | audio_url | Original remote audio URL (for reference) |
| {UUID}.wav | audio | Local audio file path |
| N/A | answer | Empty (no QA answers in this dataset) |

## Dataset Configuration

### YAML Configuration File
`/UltraEval-Audio/registry/dataset/bingchat_agent_en_us.yaml`

```yaml
bingchat_agent_en_us_btest:
  class: audio_evals.dataset.dataset.JsonlFile
  args:
    default_task: asr  # ASR task - evaluates speech recognition quality
    f_name: /Volumes/GIGIMUNDO/Localrepos/voicelive-evaluation/voicelive-evaluation/UltraEval-Audio/registry/dataset/data/bingchat_agent_en-us_btest.jsonl
    ref_col: uuid
    col_aliases:
      question: label  # Map 'question' field to 'label' for compatibility
```

### Dataset Registry Name
Use `bingchat_agent_en_us_btest` when referencing this dataset in evaluation tasks.

## Usage in Evaluation

### Loading the Dataset

```python
from audio_evals.registry import registry

# Load the dataset
ds = registry.get_dataset('bingchat_agent_en_us_btest')

# Load samples (optionally limit the number)
samples = ds.load(limit=10)  # Load first 10 samples
# or
samples = ds.load()  # Load all 1583 samples
```

### Sample Structure
Each loaded sample has the following fields:
```python
{
    'audio': 'raw/BingChat_AgentTestSet_FY26/en-us_14112025/5a2b885d-640b-4eab-b281-735f99921a48.wav',
    'question': 'Mail but. Kanye West net worth.',
    'label': 'Mail but. Kanye West net worth.',  # Same as question (via col_aliases)
    'answer': '',  # Empty - no QA answers
    'uuid': '5a2b885d-640b-4eab-b281-735f99921a48',
    'audio_url': 'https://...'  # Remote URL for reference
}
```

### Suitable Evaluators

Since this is an **ASR dataset** (no QA answers), use evaluators that work with transcription:

✅ **Supported:**
- ASR/Transcription evaluators (comparing model output to ground truth transcription)
- Speech quality metrics (UTMOS, DNSMOS)
- Audio classification metrics

❌ **Not Supported:**
- `ResponseCompletenessEvaluator` - requires `ground_truth` answers (empty in this dataset)
- `GroundednessEvaluator` - requires `context` field (not applicable for ASR)

### Example Evaluation Task

Create a YAML file in `/UltraEval-Audio/registry/eval_task/` (e.g., `bingchat_asr_eval.yaml`):

```yaml
bingchat_asr_basic:
  dataset: bingchat_agent_en_us_btest
  model: your_asr_model_name
  evaluator: your_transcription_evaluator
  agg: avg  # or appropriate aggregation policy
  limit: 100  # Optional: limit evaluation to first 100 samples
```

## Important Notes

### Missing Audio Files
2 out of 1585 audio files were not found locally:
- `d3c480fb-e798-4aac-a597-21598adcdf3e.wav`
- `3892e32c-40c0-4d8b-9d99-7b5dea0d6af8.wav`

These records were skipped during conversion. If needed, they can be downloaded from the Azure blob storage URLs.

### Audio File Locations
- **Local files**: UUID-named WAV files in the dataset directory
- **Remote URLs**: Azure blob storage (txflowmediaprod01eus.blob.core.windows.net)
- The conversion script uses local files by default

### Dataset Characteristics
- **Purpose**: ASR evaluation (speech-to-text quality)
- **No QA answers**: This is not a question-answering dataset
- **Transcription ground truth**: The `question` field contains the expected transcription
- **Language**: English (en-us) - separate config needed for French

## Next Steps

1. **Convert DTEST dataset** (if needed):
   ```bash
   python3 UltraEval-Audio/scripts/convert_bingchat_dataset.py \
     --dataset-dir raw/BingChat_AgentTestSet_FY26/en-us_14112025 \
     --output-dir UltraEval-Audio/registry/dataset/data \
     --test-type DTEST
   ```

2. **Create French dataset configuration** (similar process for fr-fr subdirectory)

3. **Create evaluation task configuration** to run your model against this dataset

4. **Choose appropriate evaluators** that work with ASR transcription comparison

## File Locations Summary

| File Type | Path |
|-----------|------|
| Original JSON (en-us BTEST) | `/raw/BingChat_AgentTestSet_FY26/en-us_14112025/BingChat_AgentTestSet_FY26_en-us_BTEST_TxResults.json` |
| Original WAV files | `/raw/BingChat_AgentTestSet_FY26/en-us_14112025/*.wav` |
| Conversion script | `/UltraEval-Audio/scripts/convert_bingchat_dataset.py` |
| Converted JSONL | `/UltraEval-Audio/registry/dataset/data/bingchat_agent_en-us_btest.jsonl` |
| Dataset config YAML | `/UltraEval-Audio/registry/dataset/bingchat_agent_en_us.yaml` |

## Contact
For issues or questions about this dataset configuration, refer to the UltraEval-Audio documentation or check the evaluation pipeline logs.
