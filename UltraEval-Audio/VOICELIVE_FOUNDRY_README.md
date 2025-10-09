# VoiceLive + Azure AI Foundry Evaluation Framework

A comprehensive evaluation framework that combines **VoiceLive S2T (Speech-to-Speech-to-Text)** models with **Azure AI Foundry evaluators** to assess voice assistant performance across multiple dimensions.

## 🎯 Overview

This framework processes audio files through VoiceLive S2T models and evaluates the results using Azure AI Foundry's advanced evaluation metrics:

- **Intent Resolution** - Evaluates how well the assistant understands user intent
- **Task Adherence** - Assesses whether the assistant completes the requested task  
- **Response Completeness** - Measures the completeness of the assistant's response
- **Groundedness** - Evaluates whether the response is grounded in provided context

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
# Azure AI configuration (required)
export AZURE_OPENAI_API_KEY="your-api-key"
export AZURE_OPENAI_ENDPOINT="your-endpoint"
export AZURE_OPENAI_API_VERSION="2025-01-01-preview"

# Azure AI Foundry (optional - for result upload)
export AZURE_AI_PROJECT="your-project-name"
export AZURE_AI_EVALUATION_NAME="voicelive-evaluation"
export AZURE_AI_FOUNDRY_UPLOAD="true"

# VoiceLive endpoint (required for model)
export VOICELIVE_ENDPOINT="your-voicelive-endpoint"
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
    "text": "Assistant response",        # → response
    "input_text": "User query",        # → query  
    "audio": "path/to/audio.wav",      # → (metadata)
    "barge-in": false                  # → (metadata)
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
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_AI_PROJECT=your-project-name
AZURE_AI_FOUNDRY_UPLOAD=true
VOICELIVE_ENDPOINT=https://your-voicelive-endpoint/
```

## 🎯 Key Features

### Unified Architecture

- **Single Codebase**: Both single and multi-evaluators use the same Azure AI `evaluate()` function
- **Complete Response Preservation**: Full Azure AI response data stored for analysis
- **Automatic Upload**: Seamless integration with Azure AI Foundry projects

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
echo $AZURE_OPENAI_API_KEY
echo $AZURE_OPENAI_ENDPOINT

# Test connection
python -c "from azure.ai.evaluation import evaluate; print('Azure AI SDK working')"
```

#### VoiceLive Connection Issues

```bash
# Check VoiceLive endpoint
echo $VOICELIVE_ENDPOINT

# Test basic connectivity
curl -I $VOICELIVE_ENDPOINT/health
```

#### Missing Dependencies

```bash
# Install all required packages
pip install -r requirements.txt
pip install azure-ai-evaluation
```

## 📚 Additional Resources

- [Azure AI Foundry Documentation](https://docs.microsoft.com/azure/ai-foundry/)
- [VoiceLive S2T Model Guide](./VoiceLive-Evaluators-Guide.md)
- [Evaluation Registry Configuration](./registry/evaluator/azure_ai_foundry.yaml)

---

For more detailed information about specific evaluators and configurations, see the individual documentation files in the `docs/` directory.
