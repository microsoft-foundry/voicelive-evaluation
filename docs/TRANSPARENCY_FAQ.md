# Responsible AI FAQ — VoiceLive Evaluation Harness

## What is the VoiceLive Evaluation Harness?

The VoiceLive Evaluation Harness is a solution template that automates end-to-end quality evaluation of voice agents built on Azure AI Voice Live. It sends pre-recorded audio through the Voice Live API, collects responses, and scores them using Azure AI Foundry evaluators across dimensions like intent resolution, task adherence, task completion, and response completeness.

## What can the VoiceLive Evaluation Harness do?

- **Automated voice agent testing**: Process pre-recorded audio datasets through Voice Live endpoints in Push-to-Talk (PTT), Voice Activity Detection (VAD), or Agent modes.
- **Multi-turn conversation evaluation**: Evaluate complex multi-turn conversations including tool calls and grounding scenarios.
- **Quality scoring**: Score voice agent responses using Azure AI Foundry evaluators (up to 13 built-in evaluators).
- **Batch processing**: Run evaluations across multiple conversations and datasets in parallel.
- **Results analysis**: View per-turn and aggregate quality scores in the Azure AI Foundry portal.

## What is the VoiceLive Evaluation Harness's intended use?

The harness is designed for developers and engineering teams who have built voice agents on Azure AI Voice Live and want to systematically evaluate their agent's quality before deployment or as part of a continuous evaluation pipeline. Common scenarios include:

- Pre-deployment quality gates for customer-service voice agents
- A/B testing different voice agent configurations
- Regression testing after agent updates
- Benchmarking voice agent performance across datasets

## How was the VoiceLive Evaluation Harness evaluated?

The harness was validated through:

- **End-to-end testing** across 5 datasets, 3 modes (VAD/PTT/Agent), 9 evaluation runs, and 400+ evaluator judgments.
- **Cross-configuration testing** with different Voice Live settings (noise suppression, echo cancellation, VAD types).
- **Evaluator alignment testing** comparing Foundry evaluator outputs against human judgment baselines.

## What are the limitations of the VoiceLive Evaluation Harness?

- **Region availability**: Voice Live and Azure AI Foundry evaluators may not be available in all Azure regions. Check [Azure AI services regional availability](https://learn.microsoft.com/azure/ai-services/speech-service/regions) for supported regions.
- **Audio format requirements**: Input audio must be in WAV format (16-bit PCM, 16kHz or 24kHz mono).
- **Evaluator scope**: Quality evaluators assess text-level semantics (intent, task adherence, completeness). They do not evaluate audio-level qualities like speech naturalness, prosody, or pronunciation.
- **Cost**: Each evaluation run incurs Azure AI Services and Azure OpenAI costs for the evaluator model deployments.
- **Latency**: Evaluation runs process audio in real-time; large datasets may take significant time to complete.

## How can I provide feedback?

- **GitHub Issues**: [github.com/microsoft-foundry/voicelive-evaluation/issues](https://github.com/microsoft-foundry/voicelive-evaluation/issues)
- **Microsoft Q&A**: Tag your question with `azure-ai-speech` and `voice-live`
- **Direct feedback**: Contact the Speech Metrics team via the repository's discussion board
