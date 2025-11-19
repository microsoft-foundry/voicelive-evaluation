# VoiceLive S2T Compatible Evaluators Guide

> **Note:** This documentation was generated with AI assistance to ensure comprehensive coverage and accuracy.

This guide lists all evaluators compatible with the VoiceLive S2T model and explains how to use different post-processors to extract the appropriate fields.

## Overview

The VoiceLive S2T model outputs structured JSON containing:
```json
{
  "audio": "path/to/output.wav",
  "response": "The capital of France is Paris.",
  "transcript": "What is the capital of France?",
  "context": "",
  "barge_in": false,
  "session_id": "unique-session-id"
}
```

### Output Fields Explained

| Field | Description | Used By |
|-------|-------------|---------|
| `response` | Assistant's spoken response (text) | Most evaluators via `extract_response` or `passthrough` |
| `transcript` | User's input transcription | ASR evaluators via `extract_transcription` |
| `audio` | Path to response audio file | Audio quality evaluators (future) |
| `context` | Conversation history (multi-turn) | Context-aware evaluators |
| `barge_in` | Whether user interrupted | Conversation flow analysis |
| `session_id` | Unique session identifier | Session tracking |

### Post-Processors

| Post-Processor | Extracts | Use Case |
|----------------|----------|----------|
| `passthrough` | Full JSON object | Azure AI Foundry evaluators (access all fields) |
| `extract_response` | `response` field only | Text-based evaluators (QA, NLG) |
| `extract_transcription` | `transcript` field only | ASR evaluators (WER, CER) |
| `extract_text` | **Legacy:** `text` field | **Deprecated - use `extract_response` instead** |

## ✅ Compatible Evaluators

### 1. Azure AI Foundry Evaluators (Recommended)

**Post-Processor:** `passthrough` (preserves full JSON for Azure AI SDK)

| Evaluator | Description | Use Case |
|-----------|-------------|----------|
| `azure-ai-batch-qaevaluator` | **Batch Q&A evaluation with F1 score** | Question answering tasks (recommended) |
| `azure-ai-batch-agent-base` | Intent + Task + Completeness (batch) | Voice agent evaluation |
| `azure-ai-batch-agent-full+tool` | Full agent metrics + tool calling | Advanced agent testing |
| `azure-ai-intent-resolution` | Intent understanding | Single-sample evaluation |
| `azure-ai-task-adherence` | Task completion | Single-sample evaluation |
| `azure-ai-response-completeness` | Response completeness | Single-sample evaluation |
| `azure-ai-groundedness` | Context grounding | Single-sample evaluation |
| `azure-ai-coherence` | Logical flow | Quality assessment |
| `azure-ai-fluency` | Grammar and naturalness | Quality assessment |
| `azure-ai-relevance` | Response relevance | Quality assessment |
| `azure-ai-combined-four` | 4 metrics in parallel | Multi-metric evaluation |

**Example:**
```bash
# Batch Q&A evaluation (most efficient for large datasets)
python audio_evals/main.py \
  --dataset llama-questions \
  --model VoiceLiveS2T \
  --evaluator azure-ai-batch-qaevaluator \
  --post_process passthrough \
  --limit 100

# Multi-metric evaluation
python audio_evals/main.py \
  --dataset llama-questions \
  --model VoiceLiveS2T \
  --evaluator azure-ai-combined-four \
  --post_process passthrough \
  --limit 10
```

### 2. Basic String Matching

**Post-Processor:** `extract_response` (extracts `response` field)

| Evaluator | Description | Use Case |
|-----------|-------------|----------|
| `em` | Exact Match - strict string equality | When you need perfect matches |
| `exist-match` | Checks if reference exists in prediction | Flexible matching for partial answers |
| `prefix-match` | Checks if prediction starts with reference | When answers should begin with specific text |
| `dump` | Records pred/ref without scoring | For data collection/debugging |

**Example:**
```bash
python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2T --evaluator em --post_process extract_response --workers 2 --limit 2
```

### 3. Speech Recognition Metrics

**Post-Processor:** `extract_transcription` (extracts `transcript` field for ASR evaluation)

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
python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2T --evaluator wer --post_process extract_transcription --workers 2 --limit 2
```

### 4. Natural Language Generation Metrics

**Post-Processor:** `extract_response` (evaluates assistant's response)

| Evaluator | Description | Use Case |
|-----------|-------------|----------|
| `bleu` | BLEU Score (English) | Text similarity and fluency |
| `bleu-zh` | BLEU Score (Chinese) | Chinese text evaluation |
| `bleu-jp` | BLEU Score (Japanese) | Japanese text evaluation |
| `bleu-char` | BLEU Score (Character-level) | Character-based similarity |
| `coco` | COCO evaluation metrics | Image captioning style evaluation |

**Example:**
```bash
python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2T --evaluator bleu --post_process extract_response --workers 2 --limit 2
```

### 5. Question Answering Evaluators

**Post-Processor:** `extract_response` (evaluates assistant's answer)

| Evaluator | Description | Use Case |
|-----------|-------------|----------|
| `qa-exist-match` | QA-specialized existence matching | **Default for llama-questions dataset** |

**Example:**
```bash
python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2T --evaluator qa-exist-match --post_process extract_response --workers 2 --limit 2
```

### 6. AI-Powered Evaluators

**Post-Processor:** `extract_response` (evaluates assistant's response)

| Evaluator | Description | Requirements |
|-----------|-------------|--------------|
| `alpaca_eval_gpt4` | GPT-4 based evaluation | Requires OpenAI API key |
| `chatbot_eval` | Chatbot response evaluation | Requires OpenAI API key |
| `ref_qa_geval` | Reference-based QA evaluation | Requires model API access |

**Example:**
```bash
# Requires OPENAI_API_KEY environment variable
python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2T --evaluator alpaca_eval_gpt4 --post_process extract_response --workers 2 --limit 2
```

## 📋 Recommended Evaluators by Use Case

### For Voice Agent Evaluation (Recommended)
```bash
# Best: Batch evaluation with comprehensive metrics
--evaluator azure-ai-batch-agent-base --post_process passthrough

# Alternative: Multi-metric parallel evaluation
--evaluator azure-ai-combined-four --post_process passthrough

# Single metric evaluation
--evaluator azure-ai-intent-resolution --post_process passthrough
```

### For Question Answering Tasks
```bash
# Best: Azure AI batch Q&A with F1 score
--evaluator azure-ai-batch-qaevaluator --post_process passthrough

# Alternative: Traditional QA matching
--evaluator qa-exist-match --post_process extract_response
--evaluator exist-match --post_process extract_response
--evaluator em --post_process extract_response
```

### For Speech-to-Text Evaluation (ASR)
```bash
# Evaluate user input transcription quality
--evaluator wer --post_process extract_transcription        # Word Error Rate (most common)
--evaluator cer --post_process extract_transcription        # Character Error Rate
```

### For Response Quality Assessment
```bash
# Best: Batch quality metrics
--evaluator azure-ai-combined-quality --post_process passthrough

# Alternative: Traditional metrics
--evaluator bleu --post_process extract_response            # BLEU score for fluency
```

## ❌ Incompatible Evaluators

These evaluators require audio input and are **NOT compatible** with VoiceLive S2T text output:

- `dnsmos` - DNS Mean Opinion Score (audio quality)
- `utmos` - UTokyo Mean Opinion Score (audio quality)  
- `simo` - Speech quality metrics
- Any evaluators in `speech_quality.yaml`

**Note:** VoiceLive S2T outputs audio to the `audio` field, but current evaluators focus on text evaluation. Audio quality evaluation may be supported in future versions.

## 🚀 Quick Start Examples

### Azure AI Foundry Evaluators (Recommended)

```bash
# Batch Q&A evaluation (best for large datasets)
python audio_evals/main.py \
  --dataset llama-questions \
  --model VoiceLiveS2T \
  --evaluator azure-ai-batch-qaevaluator \
  --post_process passthrough \
  --limit 100

# Multi-metric voice agent evaluation
python audio_evals/main.py \
  --dataset llama-questions \
  --model VoiceLiveS2T \
  --evaluator azure-ai-batch-agent-base \
  --post_process passthrough \
  --limit 50

# Combined quality metrics
python audio_evals/main.py \
  --dataset llama-questions \
  --model VoiceLiveS2T \
  --evaluator azure-ai-combined-quality \
  --post_process passthrough \
  --limit 10
```

### Traditional Evaluators

### Traditional Evaluators

```bash
# Question Answering evaluation
python audio_evals/main.py \
  --dataset llama-questions \
  --model VoiceLiveS2T \
  --evaluator qa-exist-match \
  --post_process extract_response \
  --workers 2 \
  --limit 10

# Word Error Rate (for transcription quality)
python audio_evals/main.py \
  --dataset llama-questions \
  --model VoiceLiveS2T \
  --evaluator wer \
  --post_process extract_transcription \
  --workers 2 \
  --limit 10

# BLEU score (for response fluency)
python audio_evals/main.py \
  --dataset llama-questions \
  --model VoiceLiveS2T \
  --evaluator bleu \
  --post_process extract_response \
  --workers 2 \
  --limit 10

# Test different datasets
python audio_evals/main.py --dataset librispeech-test-clean --model VoiceLiveS2T --evaluator wer --post_process extract_transcription --workers 2 --limit 2
python audio_evals/main.py --dataset cv-15-en --model VoiceLiveS2T --evaluator cer --post_process extract_transcription --workers 2 --limit 2
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

**Advanced multi-dataset testing:** See VOICELIVE_FOUNDRY_README.md for comprehensive runtest.ps1 guide with 6+ test suites including Azure AI Foundry batch evaluations.

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

**Question Answering (use extract_response):**

```bash
python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2T --evaluator qa-exist-match --post_process extract_response
python audio_evals/main.py --dataset speech-triviaqa --model VoiceLiveS2T --evaluator qa-exist-match --post_process extract_response  
python audio_evals/main.py --dataset speech-web-questions --model VoiceLiveS2T --evaluator qa-exist-match --post_process extract_response
```

**Speech Recognition (ASR - use extract_transcription):**
```bash
python audio_evals/main.py --dataset librispeech-test-clean --model VoiceLiveS2T --evaluator wer --post_process extract_transcription
python audio_evals/main.py --dataset cv-15-en --model VoiceLiveS2T --evaluator cer --post_process extract_transcription
```

**Azure AI Foundry Evaluators (use passthrough):**
```bash
python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2T --evaluator azure-ai-groundedness --post_process passthrough
python audio_evals/main.py --dataset speech-triviaqa --model VoiceLiveS2T --evaluator azure-ai-coherence --post_process passthrough
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
- **Azure AI Foundry evaluator fails**: Ensure you're using `--post_process passthrough` (not extract_response)
- **Wrong field evaluated**: 
  - For response evaluation: use `--post_process extract_response`
  - For transcription evaluation: use `--post_process extract_transcription`
  - For Azure AI evaluators: use `--post_process passthrough`

## 📚 Additional Resources

- **Main Documentation**: `VOICELIVE_FOUNDRY_README.md` - Comprehensive guide including Azure AI Foundry integration
- **Dataset Configuration**: `registry/dataset/llama_questions.yaml`
- **Evaluator Definitions**: `registry/evaluator/`
- **Post-Processor Definitions**: `registry/process/speech_model_output.yaml`
- **Advanced Testing**: See runtest.ps1 guide in VOICELIVE_FOUNDRY_README.md

---

**NOTE**: This guide was generated with AI assistance and has been reviewed for accuracy with the current VoiceLive S2T implementation.