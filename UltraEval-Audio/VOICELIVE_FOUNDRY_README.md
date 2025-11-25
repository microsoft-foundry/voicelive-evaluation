# VoiceLive + Azure AI Foundry Evaluation Framework

A comprehensive evaluation framework that combines **VoiceLive S2T (Speech-to-Speech-to-Text)** models with **Azure AI Foundry evaluators** to assess voice assistant performance across multiple dimensions.

> **Note:** This documentation was generated with AI assistance to ensure comprehensive coverage and accuracy.

## 🎯 Overview

This framework processes audio files through VoiceLive S2T models and evaluates the results using Azure AI Foundry's advanced evaluation metrics:

**Voice Agent Metrics:**
- **Intent Resolution** - Evaluates how well the assistant understands user intent
- **Task Adherence** - Assesses whether the assistant completes the requested task  
- **Response Completeness** - Measures the completeness of the assistant's response
- **Tool Call Accuracy** - Evaluates accuracy of function/tool calling behavior

**Quality Metrics:**
- **Groundedness** - Evaluates whether the response is grounded in provided context
- **Coherence** - Assesses logical flow and consistency of the response
- **Fluency** - Measures grammatical correctness and naturalness
- **Relevance** - Evaluates how relevant the response is to the query

**Question Answering:**
- **QA Evaluator** - Comprehensive Q&A evaluation with F1 score, precision, and recall metrics

## 🚀 Quick Start

### Single Evaluator

```bash
# Test intent resolution with 5 samples
python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2T --evaluator azure-ai-intent-resolution --post_process extract_text --limit 5
```

### Multi-Evaluator (Recommended)

```bash
# Run all four evaluators together for comprehensive assessment
python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2T --evaluator azure-ai-combined-four --post_process extract_text --limit 10
```

### With Azure AI Foundry Upload

```bash
# Enable automatic project upload for result tracking
set AZURE_AI_FOUNDRY_UPLOAD=true && python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2T --evaluator azure-ai-combined-four --post_process extract_text --limit 10
```

## 📋 Requirements

### Python Dependencies

```bash
pip install azure-ai-evaluation azure-identity azure-openai pandas
```

### Environment Variables

```bash
# Azure OpenAI Service (required for evaluators)
export AOAI_ENDPOINT="https://your-resource.openai.azure.com/"
export AOAI_API_KEY="your-api-key"
export AOAI_API_VERSION="2025-01-01-preview"
export AOAI_DEPLOYMENT_NAME="gpt-4.1-mini"

# Azure AI Foundry (optional - for result upload)
export AZURE_AI_PROJECT="https://your-resource.services.ai.azure.com/api/projects/your-project"
export AZURE_AI_FOUNDRY_UPLOAD="true"
export AZURE_AI_EVALUATION_NAME="voicelive-evaluation"  # Optional: custom evaluation name

# VoiceLive endpoint (required for VoiceLiveS2T model)
export AZURE_VOICELIVE_ENDPOINT="https://your-voicelive-endpoint.services.ai.azure.com/"
export AZURE_VOICELIVE_MODEL="gpt-realtime"
export AZURE_VOICELIVE_TRANSCRIPTION_MODEL="gpt-4o-transcribe"
export AZURE_VOICELIVE_VOICE="en-US-Ava:DragonHDLatestNeural"
export AZURE_VOICELIVE_INSTRUCTIONS="You are a helpful AI assistant..."
```

## 🏗️ Architecture

### Pipeline Flow

```text
Audio File → VoiceLive S2T → Azure AI Evaluators → Results + Upload
     ↓              ↓                  ↓                    ↓
   WAV/MP3    Speech-to-Text     1-4 Evaluation      JSON Output
              + Text Response      Metrics         + Azure Project
```

### Data Flow

```python
# VoiceLive Output → Azure AI Input
{
    "response": "Assistant response text",      # → response
    "transcript": "User input transcript",      # → query (from dataset)
    "context": "",                              # → context (conversation history)
    "audio": "path/to/reply.wav",              # → metadata
    "barge_in": false,                         # → metadata
    "session_id": "unique-session-id"          # → metadata
}

# Azure AI Evaluation Result
{
    "azure_evaluate_response": {
        "rows": [...],                 # Complete evaluation data
        "metrics": {...},              # Aggregated scores
        "studio_url": "..."            # Azure AI Foundry link
    }
}
```

## 📁 File Structure

```text
UltraEval-Audio/
├── audio_evals/
│   ├── models/voicelive_s2t.py         # VoiceLive S2T model
│   └── evaluator/azure_ai_foundry.py   # Unified Azure AI evaluators
├── registry/
│   └── evaluator/azure_ai_foundry.yaml # Evaluator configurations
├── raw/                                # Audio datasets
└── res/                                # Evaluation results
```

## 🔧 Available Evaluators

### Single Evaluators

**Voice Agent Evaluators:**

- `azure-ai-intent-resolution` - Intent understanding evaluation
- `azure-ai-task-adherence` - Task completion evaluation  
- `azure-ai-response-completeness` - Response completeness evaluation
- `azure-ai-groundedness` - Context grounding evaluation
- `azure-ai-tool-call-accuracy` - Tool/function call accuracy evaluation

**Quality Evaluators:**

- `azure-ai-coherence` - Logical flow and consistency evaluation
- `azure-ai-fluency` - Grammatical correctness and naturalness evaluation
- `azure-ai-relevance` - Response relevance to query evaluation

### Multi-Evaluators (Combined)

- `azure-ai-combined-four` - Core voice agent metrics (Intent + Task + Completeness + Groundedness)
- `azure-ai-combined-agent` - Extended agent evaluation (Above + Tool Call Accuracy)
- `azure-ai-combined-quality` - Quality-focused evaluation (Coherence + Fluency + Relevance + Groundedness)

### Batch Evaluators (Optimized)

**Important:** Batch evaluators collect all samples during processing and send them to Azure AI in a single batch API call at the end. This is much more efficient for large datasets (1 API call vs hundreds).

- `azure-ai-batch-qaevaluator` - Batch Q&A evaluator using Azure AI's QAEvaluator
- `azure-ai-batch-agent-base` - Batch evaluation with Intent + Task Adherence + Response Completeness
- `azure-ai-batch-agent-full+tool` - Batch evaluation with all agent metrics including Tool Call Accuracy
- `azure-ai-batch-intent` - Batch version of `azure-ai-intent-resolution`

**Configuration:** All batch evaluators use `batch_size: 0`, which means they process all samples in a single batch with no artificial size limits.

## 📊 Usage Examples

### Command Line Usage

#### Single Evaluator Test

```bash
python audio_evals/main.py \
  --dataset llama-questions \
  --model VoiceLiveS2T \
  --evaluator azure-ai-intent-resolution \
  --post_process extract_text \
  --limit 5
```

#### Comprehensive Multi-Evaluator

```bash
python audio_evals/main.py \
  --dataset llama-questions \
  --model VoiceLiveS2T \
  --evaluator azure-ai-combined-four \
  --post_process extract_text \
  --limit 10
```

#### Production Run with Upload

```bash
set AZURE_AI_FOUNDRY_UPLOAD=true
python audio_evals/main.py \
  --dataset llama-questions \
  --model VoiceLiveS2T \
  --evaluator azure-ai-combined-four \
  --post_process extract_text \
  --limit 50
```

#### Batch Evaluation (Optimized for Large Datasets)

```bash
# Batch evaluation collects all samples and processes in one API call
# More efficient than running evaluators individually
python audio_evals/main.py \
  --dataset llama-questions \
  --model VoiceLiveS2T \
  --evaluator azure-ai-batch-intent \
  --post_process extract_text \
  --limit 100

# Or use a comprehensive batch evaluator
python audio_evals/main.py \
  --dataset llama-questions \
  --model VoiceLiveS2T \
  --evaluator azure-ai-batch-agent-base \
  --post_process extract_text \
  --limit 200
```

#### Separate Post-processing and Evaluation

```bash
# Step 1: Run pipeline without evaluation
python audio_evals/main.py \
  --dataset llama-questions \
  --model VoiceLiveS2T \
  --evaluator dump \
  --post_process extract_text \
  --limit 100

# Step 2: Run batch evaluation on results
python batch_foundry_eval.py \
  --input log/results.jsonl \
  --evaluator azure-ai-combined-four \
  --output batch_results.jsonl
```

## 📈 Results Format

### Single Sample Result

```json
{
  "type": "eval",
  "id": 0,
  "data": {
    "pred": "The capital of France is Paris...",
    "ref": "Paris",
    "azure_evaluate_response": {
      "rows": [{
        "inputs.query": "",
        "inputs.response": "The capital of France is Paris...",
        "inputs.context": "Paris",
        "inputs.ground_truth": "Paris",
        "outputs.intent_resolution.intent_resolution": 5.0,
        "outputs.intent_resolution.intent_resolution_reason": "User asked for the capital of France. Agent provided correct answer...",
        "outputs.task_adherence.task_adherence": 5.0,
        "outputs.response_completeness.response_completeness": 5,
        "outputs.groundedness.groundedness": 3.0
      }],
      "metrics": {
        "intent_resolution.intent_resolution": 5.0,
        "task_adherence.task_adherence": 5.0,
        "response_completeness.response_completeness": 5.0,
        "groundedness.groundedness": 3.0
      },
      "studio_url": "https://ai.azure.com/resource/build/evaluation/..."
    }
  }
}
```

### Summary Metrics

```json
{
  "intent_resolution": {
    "average": 4.8,
    "pass_rate": 0.9,
    "total_samples": 10
  },
  "task_adherence": {
    "average": 4.9,
    "pass_rate": 1.0,
    "total_samples": 10
  },
  "response_completeness": {
    "average": 4.7,
    "pass_rate": 0.8,
    "total_samples": 10
  },
  "groundedness": {
    "average": 3.2,
    "pass_rate": 1.0,
    "total_samples": 10
  }
}
```

## 🔧 Advanced Configuration

### Custom Dataset

```json
{
  "sample_dataset": [
    {
      "id": "test_1",
      "audio_file": "path/to/audio.wav",
      "ground_truth": "Expected response text",
      "context": "Additional context for grounding"
    }
  ]
}
```

### Environment Configuration

```bash
# .env file
AOAI_API_KEY=your-api-key
AOAI_ENDPOINT=https://your-resource.openai.azure.com/
AOAI_API_VERSION=2025-01-01-preview
AOAI_DEPLOYMENT_NAME=gpt-4.1-mini

# Azure AI Foundry (optional)
AZURE_AI_PROJECT=https://your-resource.services.ai.azure.com/api/projects/your-project
AZURE_AI_FOUNDRY_UPLOAD=true
AZURE_AI_EVALUATION_NAME=voicelive-evaluation  # Optional: leave empty for auto-generated names

# VoiceLive settings
AZURE_VOICELIVE_ENDPOINT=https://your-voicelive-endpoint.services.ai.azure.com/
AZURE_VOICELIVE_MODEL=gpt-realtime
AZURE_VOICELIVE_TRANSCRIPTION_MODEL=gpt-4o-transcribe
AZURE_VOICELIVE_VOICE=en-US-Ava:DragonHDLatestNeural
AZURE_VOICELIVE_INSTRUCTIONS="You are a helpful AI assistant..."
```

## 🎯 Key Features

### Unified Architecture

- **Single Codebase**: Both single and multi-evaluators use the same Azure AI `evaluate()` function
- **Complete Response Preservation**: Full Azure AI response data stored for analysis
- **Automatic Upload**: Seamless integration with Azure AI Foundry projects

### Batch Evaluation Optimization

- **Single API Call**: Batch evaluators collect all samples during processing and send them in one batch
- **No Artificial Limits**: Removed `max_azure_evaluate_size` limit - can process datasets of any size
- **Controlled by --limit**: Use `--limit` parameter to control dataset size (not environment variables)
- **Efficient Processing**: One API call for 1000 samples vs. 1000 individual calls with single evaluators
- **Example**: `--limit 500` processes all 500 samples in a single batch API call at the end

### Performance Optimized

- **Parallel Processing**: Multi-evaluator runs all metrics in one Azure AI call
- **Efficient Scaling**: Handles 1-1000+ samples with consistent performance
- **Smart Caching**: Optimized for repeated evaluations

### Production Ready

- **Error Handling**: Graceful degradation for Azure connectivity issues
- **Comprehensive Logging**: Detailed execution logs for debugging
- **Flexible Configuration**: YAML-based evaluator registry system

## 🆘 Troubleshooting

### Common Issues

#### Azure AI Connection Issues

```bash
# Check environment variables
echo $AOAI_API_KEY
echo $AOAI_ENDPOINT

# Test connection
python -c "from azure.ai.evaluation import evaluate; print('Azure AI SDK working')"
```

#### VoiceLive Connection Issues

```bash
# Check VoiceLive endpoint
echo $AZURE_VOICELIVE_ENDPOINT

# Test basic connectivity
curl -I $AZURE_VOICELIVE_ENDPOINT/health
```

#### Missing Dependencies

```bash
# Install all required packages
pip install -r requirements.txt
pip install azure-ai-evaluation
```

---

## � Performance & Cost Optimization

### Dataset Size Recommendations

Choose the right evaluator type based on your dataset size:

| Dataset Size | Recommended Evaluator Type | API Calls | Use Case |
|--------------|---------------------------|-----------|----------|
| 1-50 samples | Single evaluators | 1-50 calls | Development, quick testing |
| 10-100 samples | Multi evaluators | 10-100 calls | Model comparison, validation |
| 100+ samples | **Batch evaluators** | **1 call** | Production, comprehensive testing |
| 1000+ samples | **Batch evaluators** | **1 call** | Large-scale evaluation |

**Example:**
```bash
# ✅ OPTIMAL: Batch evaluator for 500 samples = 1 API call
python audio_evals/main.py --evaluator azure-ai-batch-qaevaluator --limit 500

# ❌ INEFFICIENT: Single evaluator for 500 samples = 500 API calls
python audio_evals/main.py --evaluator azure-ai-intent-resolution --limit 500
```

### Cost Optimization Tips

#### 1. Use Batch Evaluators for Large Datasets

**Cost Comparison:**
```
Single Evaluator (100 samples):
  - API Calls: 100
  - Est. Cost: ~$5.00 (at $0.05/call)
  - Time: ~10 minutes

Batch Evaluator (100 samples):
  - API Calls: 1
  - Est. Cost: ~$0.15 (single batch call)
  - Time: ~2 minutes

💰 Savings: 97% cost reduction, 80% time reduction
```

#### 2. Multi-Evaluators are More Cost-Effective

**Running Multiple Metrics:**
```bash
# ❌ EXPENSIVE: Run 4 single evaluators separately
python audio_evals/main.py --evaluator azure-ai-intent-resolution --limit 100  # $5
python audio_evals/main.py --evaluator azure-ai-task-adherence --limit 100     # $5
python audio_evals/main.py --evaluator azure-ai-groundedness --limit 100       # $5
python audio_evals/main.py --evaluator azure-ai-coherence --limit 100          # $5
# Total: ~$20, 400 API calls

# ✅ COST-EFFECTIVE: Use multi-evaluator (all metrics in one call per sample)
python audio_evals/main.py --evaluator azure-ai-combined-four --limit 100      # $5
# Total: ~$5, 100 API calls
# 💰 Savings: 75% cost reduction

# ✅ OPTIMAL: Use batch multi-evaluator (all metrics, all samples in one call)
python audio_evals/main.py --evaluator azure-ai-batch-agent-base --limit 100   # $0.15
# Total: ~$0.15, 1 API call
# 💰 Savings: 99% cost reduction vs single evaluators
```

#### 3. Use `--limit` During Development

```bash
# Development phase: Test with small sample
python audio_evals/main.py --evaluator azure-ai-batch-qaevaluator --limit 10

# Validation phase: Medium sample for verification
python audio_evals/main.py --evaluator azure-ai-batch-qaevaluator --limit 50

# Production phase: Full dataset
python audio_evals/main.py --evaluator azure-ai-batch-qaevaluator --limit 0  # No limit
```

#### 4. Reuse Inference Results

```bash
# Step 1: Run inference once (API calls to VoiceLive)
python audio_evals/main.py --model VoiceLiveS2T --evaluator dump --limit 100 --save inference.jsonl

# Step 2: Try different evaluators on same inference (no VoiceLive calls)
python audio_evals/main.py --inf_file inference.jsonl --evaluator azure-ai-batch-qaevaluator
python audio_evals/main.py --inf_file inference.jsonl --evaluator azure-ai-batch-agent-base
python audio_evals/main.py --inf_file inference.jsonl --evaluator qa-exist-match

# 💰 Saves: VoiceLive API costs for evaluators 2 and 3
```

### Performance Comparison

#### Single vs Multi vs Batch Evaluators

| Metric | Single Evaluator | Multi Evaluator | Batch Evaluator |
|--------|-----------------|----------------|----------------|
| **10 samples** | | | |
| API calls | 10 | 10 | 1 |
| Time (est.) | ~1 min | ~1 min | ~10 sec |
| Cost (est.) | $0.50 | $0.50 | $0.05 |
| **100 samples** | | | |
| API calls | 100 | 100 | 1 |
| Time (est.) | ~10 min | ~10 min | ~2 min |
| Cost (est.) | $5.00 | $5.00 | $0.15 |
| **1000 samples** | | | |
| API calls | 1000 | 1000 | 1 |
| Time (est.) | ~100 min | ~100 min | ~15 min |
| Cost (est.) | $50.00 | $50.00 | $1.50 |
| **5000 samples** | | | |
| API calls | 5000 | 5000 | 1 |
| Time (est.) | ~500 min | ~500 min | ~60 min |
| Cost (est.) | $250.00 | $250.00 | $7.50 |

**Key Insights:**
- ✅ **Batch evaluators scale linearly** - Same 1 API call whether 100 or 5000 samples
- ✅ **97-99% cost savings** on large datasets
- ✅ **80-90% time savings** due to reduced API overhead

### Best Practices Summary

#### ✅ DO:
- Use **batch evaluators** for datasets > 100 samples
- Use **multi-evaluators** when you need multiple metrics
- Use `--limit` parameter for development/testing
- Reuse inference results with `--inf_file` when experimenting with evaluators
- Run inference once, evaluate multiple times

#### ❌ DON'T:
- Run single evaluators on large datasets (>100 samples)
- Run multiple single evaluators sequentially (use multi-evaluator instead)
- Re-run VoiceLive inference when only changing evaluators
- Skip using batch evaluators for production workloads

### Production Workflow Example

```bash
# 1. Development: Test with small sample
./runtest.ps1 -TestSuite firsteval -Limit 10

# 2. Validation: Verify with medium sample
./runtest.ps1 -TestSuite llama-test -Limit 50

# 3. Production: Full dataset with batch evaluators
./runtest.ps1 -TestSuite comprehensive-nollama -Limit 0 -Workers 30

# Result: Optimal cost and performance for production scale
```

---

## �🔥 Advanced: Multi-Dataset and Multi-Model Batch Testing with runtest.ps1

For production-grade evaluation workflows, use `runtest.ps1` - a powerful PowerShell script that automates testing across multiple models, datasets, and evaluators with organized result management.

### Overview

`runtest.ps1` provides:
- ✅ **Automated test suites** - Predefined configurations for common testing scenarios
- ✅ **Multi-model testing** - Run evaluations across different VoiceLive models in sequence or parallel
- ✅ **Multi-dataset testing** - Test against multiple datasets automatically
- ✅ **Batch evaluation** - Efficient batch processing with organized results
- ✅ **Resume capability** - Separate inference and evaluation phases for faster iteration
- ✅ **Cross-platform** - Works on Windows, macOS, and Linux
- ✅ **Organized results** - Hierarchical directory structure for easy analysis

### Quick Start

```powershell
# Run a quick test (1 model, 1 dataset, 1 evaluator)
./runtest.ps1 -TestSuite firsteval -Limit 5

# Run comprehensive test across all models and datasets
./runtest.ps1 -TestSuite comprehensive -Limit 100 -Workers 20

# Test specific model with specific evaluators
./runtest.ps1 -ModelConfigs @("VoiceLive-gpt-realtime") `
              -Datasets @("speech-triviaqa") `
              -Evaluators @("azure-ai-batch-qaevaluator", "qa-exist-match") `
              -Limit 50
```

### Key Parameters

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `-TestSuite` | String | Predefined test configuration | `comprehensive-nollama` |
| `-Workers` | Int | Parallel workers for processing | `20` |
| `-Limit` | Int | Max samples per dataset | `2` |
| `-InferenceOnly` | Switch | Run only inference phase | `false` |
| `-EvaluationOnly` | Switch | Run only evaluation (requires `-InferenceFile`) | `false` |
| `-InferenceFile` | String | Path to existing inference results | `""` |
| `-ModelConfigs` | Array | Override model configurations | `@()` |
| `-Datasets` | Array | Override datasets to test | `@()` |
| `-Evaluators` | Array | Override evaluators to use | `@()` |
| `-DryRun` | Switch | Show execution plan without running | `false` |
| `-ParallelModels` | Switch | Run models in parallel (experimental) | `false` |

### Available Test Suites

#### Production Test Suites

**`firsteval`** - Quick validation test
- 1 model: VoiceLive-gpt-realtime
- 1 dataset: llama-questions-voicelive
- 1 evaluator: azure-ai-batch-agent-base
- Use case: Quick validation before production deployment

**`llama-test`** - Full LLAMA dataset test
- 3 models: gpt-realtime, phi4-mm-realtime, gpt-4.1-mini
- 1 dataset: llama-questions-voicelive
- 3 evaluators: qa-exist-match, batch-qaevaluator, batch-agent-base
- Use case: Comprehensive model comparison on LLAMA dataset

**`foundry-batch-speech-trivia`** - TriviaQA evaluation
- 1 model: VoiceLive-gpt-realtime
- 1 dataset: speech-triviaqa
- 2 evaluators: batch-agent-base, batch-qaevaluator
- Use case: Question answering performance testing

**`foundry-batch-speech-web`** - WebQuestions evaluation
- 1 model: VoiceLive-gpt-realtime
- 1 dataset: speech-web-questions
- 2 evaluators: batch-agent-base, batch-qaevaluator
- Use case: Web-based question answering testing

**`comprehensive`** - Full test suite
- 3 models: All VoiceLive configurations
- 3 datasets: llama-questions, speech-triviaqa, speech-web-questions
- 3 evaluators: qa-exist-match, batch-qaevaluator, batch-agent-base
- Use case: Complete system validation

**`comprehensive-nollama`** - Comprehensive without LLAMA
- 3 models: All VoiceLive configurations
- 2 datasets: speech-triviaqa, speech-web-questions
- 3 evaluators: qa-exist-match, batch-qaevaluator, batch-agent-base
- Use case: Production testing without LLAMA dataset

### Available Model Configurations

| Model Config | VoiceLive Model | Transcription | Use Case |
|--------------|-----------------|---------------|----------|
| `VoiceLive-gpt-realtime` | gpt-realtime | gpt-4o-transcribe | Best quality, highest cost |
| `VoiceLive-phi4-mm-realtime` | phi4-mm-realtime | azure-speech | Cost-effective, good quality |
| `VoiceLive-gpt-4.1-mini` | gpt-4.1-mini | azure-speech | Fast, lower cost |

### Available Datasets

**Question Answering:**
- `llama-questions` - General Q&A (English)
- `llama-questions-voicelive` - VoiceLive-optimized Q&A
- `speech-triviaqa` - TriviaQA dataset
- `speech-web-questions` - WebQuestions dataset

**ASR (Automatic Speech Recognition):**
- `librispeech-test-clean` - LibriSpeech clean test
- `librispeech-dev-clean` - LibriSpeech clean dev
- `cv-15-en` - Common Voice 15 English
- `fleurs-en_us` - FLEURS English US
- `tedlium-test` - TED-LIUM test set
- `peoples_speech-test` - People's Speech test

### Available Evaluators

**Batch Evaluators (Recommended for large datasets):**
- `azure-ai-batch-qaevaluator` - Batch Q&A evaluation
- `azure-ai-batch-agent-base` - Intent + Task Adherence + Response Completeness
- `azure-ai-batch-agent-full+tool` - Full agent evaluation with tool accuracy
- `azure-ai-batch-quality` - Coherence + Fluency + Relevance

**Single Evaluators:**
- `azure-ai-intent-resolution` - Intent understanding
- `azure-ai-task-adherence` - Task completion
- `azure-ai-groundedness` - Context grounding
- `qa-exist-match` - Q&A existence match
- `em` - Exact match
- `wer` - Word Error Rate
- `cer` - Character Error Rate

### Results Directory Structure

```
res/
└── VoiceLiveS2T/
    └── VoiceLive-gpt-realtime/              # Model configuration
        └── speech-triviaqa/                 # Dataset
            ├── inference/
            │   └── 2025-11-19_10-30-00_inference.jsonl
            ├── azure-ai-batch-qaevaluator/
            │   └── 2025-11-19_10-30-00_azure-ai-batch-qaevaluator.jsonl
            ├── azure-ai-batch-agent-base/
            │   └── 2025-11-19_10-30-00_azure-ai-batch-agent-base.jsonl
            └── qa-exist-match/
                └── 2025-11-19_10-30-00_qa-exist-match.jsonl
```

### Usage Examples

#### Example 1: Quick Validation Test

```powershell
# Test one model with 5 samples
./runtest.ps1 -TestSuite firsteval -Limit 5 -Workers 10

# Output:
# ✅ Model: VoiceLive-gpt-realtime
# ✅ Dataset: llama-questions-voicelive (5 samples)
# ✅ Evaluator: azure-ai-batch-agent-base
# Results: res/VoiceLiveS2T/VoiceLive-gpt-realtime/llama-questions-voicelive/
```

#### Example 2: Multi-Model Comparison

```powershell
# Compare all 3 models on TriviaQA dataset
./runtest.ps1 -TestSuite foundry-batch-speech-trivia -Limit 100 -Workers 20

# This will test:
# - VoiceLive-gpt-realtime
# - VoiceLive-phi4-mm-realtime  
# - VoiceLive-gpt-4.1-mini
# Each with 100 samples from speech-triviaqa
```

#### Example 3: Custom Multi-Dataset Test

```powershell
# Custom test: One model, multiple datasets
./runtest.ps1 `
    -ModelConfigs @("VoiceLive-gpt-realtime") `
    -Datasets @("speech-triviaqa", "speech-web-questions", "llama-questions-voicelive") `
    -Evaluators @("azure-ai-batch-qaevaluator", "qa-exist-match") `
    -Limit 50 `
    -Workers 20

# Tests 3 datasets with 2 evaluators each = 6 evaluation runs
```

#### Example 4: Two-Phase Workflow (Inference → Evaluation)

**Phase 1: Generate inference results**
```powershell
# Run inference only (no evaluation)
./runtest.ps1 -InferenceOnly `
              -TestSuite comprehensive `
              -Limit 200 `
              -Workers 30

# Saves inference to: res/VoiceLiveS2T/{model}/{dataset}/inference/
```

**Phase 2: Run multiple evaluations on same inference**
```powershell
# Reuse inference results with different evaluators
$inferenceFile = "res/VoiceLiveS2T/VoiceLive-gpt-realtime/speech-triviaqa/inference/2025-11-19_10-00-00_inference.jsonl"

./runtest.ps1 -EvaluationOnly `
              -InferenceFile $inferenceFile `
              -Datasets @("speech-triviaqa") `
              -Evaluators @("azure-ai-batch-qaevaluator", "azure-ai-batch-agent-base", "qa-exist-match") `
              -Limit 200

# Runs 3 evaluators on the same inference results
# Much faster than re-running VoiceLive!
```

#### Example 5: Production Full Test

```powershell
# Complete production validation
./runtest.ps1 -TestSuite comprehensive-nollama `
              -Limit 500 `
              -Workers 30

# Tests:
# - 3 models × 2 datasets × 3 evaluators = 18 evaluation runs
# - 500 samples per dataset
# - Organized results in res/VoiceLiveS2T/
```

#### Example 6: Dry Run (Preview)

```powershell
# See what would be executed without running
./runtest.ps1 -DryRun -TestSuite comprehensive

# Output shows:
# - Models to test
# - Datasets to process
# - Evaluators to run
# - Expected result paths
```

### Best Practices

#### 1. **Start Small, Scale Up**
```powershell
# Development: Quick test
./runtest.ps1 -TestSuite firsteval -Limit 5

# Validation: Medium test
./runtest.ps1 -TestSuite llama-test -Limit 50

# Production: Full test
./runtest.ps1 -TestSuite comprehensive -Limit 500
```

#### 2. **Use Two-Phase Workflow for Iteration**
```powershell
# Generate inference once (expensive)
./runtest.ps1 -InferenceOnly -TestSuite comprehensive -Limit 200

# Try different evaluators (cheap - reuses inference)
./runtest.ps1 -EvaluationOnly -InferenceFile "..." -Evaluators @("evaluator1")
./runtest.ps1 -EvaluationOnly -InferenceFile "..." -Evaluators @("evaluator2")
./runtest.ps1 -EvaluationOnly -InferenceFile "..." -Evaluators @("evaluator3")
```

#### 3. **Optimize Worker Count**
```powershell
# For I/O bound (VoiceLive API calls): Use more workers
./runtest.ps1 -Workers 30 -Limit 100

# For CPU bound (local evaluators): Use fewer workers
./runtest.ps1 -Workers 10 -Limit 100
```

#### 4. **Batch Evaluators for Large Datasets**
```powershell
# ✅ GOOD: Use batch evaluators (1 API call)
./runtest.ps1 -Evaluators @("azure-ai-batch-qaevaluator") -Limit 500

# ❌ AVOID: Single evaluators on large datasets (500 API calls)
./runtest.ps1 -Evaluators @("azure-ai-intent-resolution") -Limit 500
```

#### 5. **Use Test Suites for Reproducibility**
```powershell
# ✅ GOOD: Named test suite (documented, reproducible)
./runtest.ps1 -TestSuite comprehensive -Limit 200

# ⚠️ OK: Custom config (flexible but document it)
./runtest.ps1 -ModelConfigs @(...) -Datasets @(...) -Evaluators @(...)
```

### Troubleshooting

#### Issue: "Inference failed"
```powershell
# Check VoiceLive endpoint connectivity
echo $env:AZURE_VOICELIVE_ENDPOINT

# Reduce workers to avoid rate limiting
./runtest.ps1 -TestSuite firsteval -Workers 5
```

#### Issue: "Evaluation only mode requires -InferenceFile"
```powershell
# ❌ WRONG: Missing inference file
./runtest.ps1 -EvaluationOnly

# ✅ CORRECT: Provide inference file path
./runtest.ps1 -EvaluationOnly -InferenceFile "path/to/inference.jsonl"
```

#### Issue: Results in wrong directory
```powershell
# Results are organized as:
# res/VoiceLiveS2T/{ModelConfig}/{Dataset}/{Evaluator}/

# Example:
# res/VoiceLiveS2T/VoiceLive-gpt-realtime/speech-triviaqa/azure-ai-batch-qaevaluator/
```

### Advanced: Custom Test Suite

You can create custom test suites by modifying `runtest.ps1`:

```powershell
# Add to the Get-TestSuiteConfig function:
"my-custom-suite" {
    return @{
        ModelConfigs = @("VoiceLive-gpt-realtime", "VoiceLive-phi4-mm-realtime")
        Datasets = @("speech-triviaqa", "speech-web-questions")
        Evaluators = @("azure-ai-batch-qaevaluator", "azure-ai-batch-agent-base")
        Description = "My custom evaluation suite"
    }
}

# Then use it:
./runtest.ps1 -TestSuite my-custom-suite -Limit 100
```

---

## � Additional Resources

- [Azure AI Foundry Documentation](https://docs.microsoft.com/azure/ai-foundry/)
- [VoiceLive S2T Model Guide](./VoiceLive-Evaluators-Guide.md)
- [Evaluation Registry Configuration](./registry/evaluator/azure_ai_foundry.yaml)

For more detailed information about specific evaluators and configurations, see the individual documentation files in the `docs/` directory.
