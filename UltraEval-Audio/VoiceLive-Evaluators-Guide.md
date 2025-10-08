# VoiceLive S2T Compatible Evaluators Guide

This guide lists all evaluators compatible with the VoiceLive S2T model when using `extract_text` post-processing.

## Overview

The VoiceLive S2T model outputs structured JSON containing:
```json
{
  "audio": "path/to/output.wav", 
  "text": "The capital of France is Paris.",
  "input_text": "What is the capital of France?"
}
```

The `extract_text` post-processor extracts the `text` field, providing a clean string for evaluation.

## ✅ Compatible Evaluators

### 1. Basic String Matching

| Evaluator | Description | Use Case |
|-----------|-------------|----------|
| `em` | Exact Match - strict string equality | When you need perfect matches |
| `exist-match` | Checks if reference exists in prediction | Flexible matching for partial answers |
| `prefix-match` | Checks if prediction starts with reference | When answers should begin with specific text |
| `dump` | Records pred/ref without scoring | For data collection/debugging |

**Example:**
```bash
python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2T --evaluator em --post_process extract_text --workers 2 --limit 2
```

### 2. Speech Recognition Metrics

| Evaluator | Description | Use Case |
|-----------|-------------|----------|
| `wer` | Word Error Rate (case-insensitive) | **Most common for ASR evaluation** |
| `wer-sensitive-case` | Word Error Rate (case-sensitive) | When case matters |
| `cer` | Character Error Rate | Detailed character-level analysis |
| `wer-jp` | Word Error Rate for Japanese | Japanese text evaluation |
| `wer-kr` | Word Error Rate for Korean | Korean text evaluation |
| `wer-yue` | Word Error Rate for Cantonese | Cantonese text evaluation |

**Example:**
```bash
python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2T --evaluator wer --post_process extract_text --workers 2 --limit 2
```

### 3. Natural Language Generation Metrics

| Evaluator | Description | Use Case |
|-----------|-------------|----------|
| `bleu` | BLEU Score (English) | Text similarity and fluency |
| `bleu-zh` | BLEU Score (Chinese) | Chinese text evaluation |
| `bleu-jp` | BLEU Score (Japanese) | Japanese text evaluation |
| `bleu-char` | BLEU Score (Character-level) | Character-based similarity |
| `coco` | COCO evaluation metrics | Image captioning style evaluation |

**Example:**
```bash
python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2T --evaluator bleu --post_process extract_text --workers 2 --limit 2
```

### 4. Question Answering Evaluators

| Evaluator | Description | Use Case |
|-----------|-------------|----------|
| `qa-exist-match` | QA-specialized existence matching | **Default for llama-questions dataset** |

**Example:**
```bash
python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2T --evaluator qa-exist-match --post_process extract_text --workers 2 --limit 2
```

### 5. AI-Powered Evaluators

| Evaluator | Description | Requirements |
|-----------|-------------|--------------|
| `alpaca_eval_gpt4` | GPT-4 based evaluation | Requires OpenAI API key |
| `chatbot_eval` | Chatbot response evaluation | Requires OpenAI API key |
| `ref_qa_geval` | Reference-based QA evaluation | Requires model API access |

**Example:**
```bash
# Requires OPENAI_API_KEY environment variable
python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2T --evaluator alpaca_eval_gpt4 --post_process extract_text --workers 2 --limit 2
```

## ❌ Incompatible Evaluators

These evaluators require audio input and are **NOT compatible** with text output:

- `dnsmos` - DNS Mean Opinion Score (audio quality)
- `utmos` - UTokyo Mean Opinion Score (audio quality)  
- `simo` - Speech quality metrics
- Any evaluators in `speech_quality.yaml`

## 📋 Recommended Evaluators by Use Case

### For Speech-to-Text Tasks
```bash
--evaluator wer          # Word Error Rate (most common for ASR)
--evaluator bleu         # BLEU score for fluency  
--evaluator cer          # Character Error Rate for detailed analysis
```

### For Question Answering Tasks
```bash
--evaluator qa-exist-match    # Default for llama-questions dataset
--evaluator exist-match       # Simpler existence check
--evaluator em               # Strict exact match
```

### For General Text Comparison
```bash
--evaluator exist-match      # Flexible matching
--evaluator prefix-match     # Partial matching  
--evaluator bleu            # Similarity scoring
```

## 🚀 Quick Start Examples

### Single Dataset/Evaluator Tests

```bash
# Default QA evaluation (uses dataset's default evaluator)
python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2T --post_process extract_text --workers 2 --limit 2

# Word Error Rate evaluation
python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2T --evaluator wer --post_process extract_text --workers 2 --limit 2

# BLEU score evaluation  
python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2T --evaluator bleu --post_process extract_text --workers 2 --limit 2

# Test different datasets
python audio_evals/main.py --dataset librispeech-test-clean --model VoiceLiveS2T --evaluator wer --post_process extract_text --workers 2 --limit 2
python audio_evals/main.py --dataset cv-15-en --model VoiceLiveS2T --evaluator cer --post_process extract_text --workers 2 --limit 2
```

### Automated Multi-Dataset Testing

Use the provided PowerShell script to test multiple datasets and evaluators. The script is currently configured to test three datasets with various evaluators:

**Currently Active Datasets:**

- `llama-questions` - Question Answering tasks
- `speech-triviaqa` - Trivia question answering
- `speech-web-questions` - Web-based question answering

**Available Evaluators:**

- `qa-exist-match` (currently active - default for QA tasks)
- `wer`, `bleu`, `em`, `exist-match` (commented out, can be activated)

```powershell
# Run all configured tests (default: 2 workers, limit 2)
.\runtest.ps1

# Run with custom parameters
.\runtest.ps1 -Workers 4 -Limit 10

# Example output structure with multi-dataset support:
# res/VoiceLiveS2T/
# ├── llama-questions/qa-exist-match/
# ├── speech-triviaqa/qa-exist-match/
# └── speech-web-questions/qa-exist-match/
```

**To modify active datasets/evaluators:** Edit the `$datasets` and `$evaluators` arrays in `runtest.ps1`

## � Available Datasets

### English Datasets Compatible with VoiceLive S2T

| Dataset | Description | Task Type | Reference Column |
|---------|-------------|----------|------------------|
| `llama-questions` | Question Answering (English) | QA | Answer |
| `speech-triviaqa` | Speech Trivia Question Answering | QA | Answer |
| `speech-web-questions` | Web-based Question Answering | QA | Answer |
| `librispeech-test-clean` | LibriSpeech Clean Test Set | ASR | text |
| `librispeech-dev-clean` | LibriSpeech Clean Dev Set | ASR | text |
| `cv-15-en` | Common Voice 15 English | ASR | sentence |
| `fleurs-en_us` | FLEURS English US | ASR | raw_transcription |
| `tedlium-test` | TED-LIUM Test Set | ASR | text |
| `peoples_speech-test` | People's Speech Test Set | ASR | text |

### Usage Examples by Dataset Type

**Question Answering:**

```bash
python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2T --evaluator qa-exist-match --post_process extract_text
python audio_evals/main.py --dataset speech-triviaqa --model VoiceLiveS2T --evaluator qa-exist-match --post_process extract_text  
python audio_evals/main.py --dataset speech-web-questions --model VoiceLiveS2T --evaluator qa-exist-match --post_process extract_text
```

**Speech Recognition (ASR):**
```bash
python audio_evals/main.py --dataset librispeech-test-clean --model VoiceLiveS2T --evaluator wer --post_process extract_text
python audio_evals/main.py --dataset cv-15-en --model VoiceLiveS2T --evaluator cer --post_process extract_text
```

## �📁 Output Structure

Results are organized by dataset and evaluator:

```
res/VoiceLiveS2T/
├── llama-questions/
│   ├── qa-exist-match/
│   │   ├── YYYY-MM-DD_HH-MM-SS_qa-exist-match.jsonl
│   │   └── YYYY-MM-DD_HH-MM-SS_qa-exist-match-overall.json
│   └── wer/
│       ├── YYYY-MM-DD_HH-MM-SS_wer.jsonl
│       └── YYYY-MM-DD_HH-MM-SS_wer-overall.json
├── librispeech-test-clean/
│   └── wer/
│       ├── YYYY-MM-DD_HH-MM-SS_wer.jsonl  
│       └── YYYY-MM-DD_HH-MM-SS_wer-overall.json
└── test-summary-YYYY-MM-DD_HH-MM-SS.md
```

## 🔧 Troubleshooting

- **Error: 'NoneType' object is not callable**: The evaluator name doesn't exist. Check available evaluators in `registry/evaluator/`
- **No evaluator specified**: The system will use the dataset's default evaluator (`qa-exist-match` for llama-questions)
- **Poor evaluation scores**: Consider using `exist-match` or `prefix-match` for more flexible matching

## 📚 Additional Resources

- **Dataset Configuration**: `registry/dataset/llama_questions.yaml`
- **Evaluator Definitions**: `registry/evaluator/`
- **Post-Processor Definitions**: `registry/process/speech_model_output.yaml`