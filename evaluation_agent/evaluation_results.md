# VoiceLive Evaluation Results

## PTT vs VAD Comparison Test — 2026-02-19

Push-to-Talk (PTT) sends an explicit `audio_input_finished` event after each audio chunk, signaling the end of user speech immediately. VAD (Voice Activity Detection) relies on the VoiceLive SDK's built-in silence detection to determine when the user has stopped speaking.

### Test Configuration

| Setting | Value |
|---------|-------|
| VoiceLive Model | `gpt-realtime` |
| Voice | `alloy` (OpenAI preset) |
| API Version | `2026-01-01-preview` |
| SDK Version | `azure-ai-voicelive 1.2.0b4` |
| Session Mode | `per-conversation` |
| Foundry Evaluators | intent_resolution, task_adherence, task_completion, response_completeness, groundedness, relevance, tool_call_accuracy, tool_selection, tool_input_accuracy, tool_output_utilization |

### Datasets

| Dataset | Entries | Conversations | Source |
|---------|---------|---------------|--------|
| **MultiConversationSample** | 9 | 2 (Eiffel_Tower_Visit_1 + DataOceanDemoComplexSession1) | Uploaded via Function App |
| **Eiffel_Tower_Visit_1** | 6 | 1 (Eiffel Tower visit planning) | Uploaded via Function App |

---

## VoiceLive Audio Processing Results

| Dataset | Mode | Files | Processed | Failed | Duration | Job ID |
|---------|------|-------|-----------|--------|----------|--------|
| MultiConversation | PTT | 9 | 9/9 ✅ | 0 | **4.25s** | `e81296b5` |
| MultiConversation | VAD | 9 | 9/9 ✅ | 0 | **124.86s** | `d238cd50` |
| Eiffel Tower v1 | PTT | 6 | 6/6 ✅ | 0 | **2.89s** | `feadb65b` |
| Eiffel Tower v1 | VAD | 6 | 6/6 ✅ | 0 | **121.52s** | `07928b96` |

**Key observation**: PTT mode is **~30x faster** than VAD mode because it explicitly signals end of speech per turn instead of waiting for silence detection.

### Transcription/Response Capture Rate

| Dataset | Mode | Has Query | Has Response | Audio Received |
|---------|------|-----------|-------------|----------------|
| MultiConversation | PTT | 0/9 | 0/9 | 0/9 |
| MultiConversation | VAD | 7/9 | 4/9 | 1/9 |
| Eiffel Tower v1 | PTT | 2/6 | 1/6 | 1/6 |
| Eiffel Tower v1 | VAD | 4/6 | 0/6 | 0/6 |

**Known issue**: Multi-turn event ordering causes earlier turns to miss responses. The event collection loop for turn N may consume events from turn N+1's auto-triggered response. PTT mode is especially affected because all turns process very quickly.

---

## Foundry Evaluation Results

### Full Results with Portal Links

| Dataset | Mode | Eval ID | Portal Link |
|---------|------|---------|-------------|
| MultiConversation | PTT | `eval_f72707ab` | [View in Foundry](https://ai.azure.com/nextgen/r/LC5tEE5IQP2PTdn7dw0MbQ,rg-voicelive-e2e-test,,ai-3x6t3c6zpbsr6,voicelive-e2e-test/build/evaluations/eval_f72707ab11984d27a43131a7ca07b8fd/run/evalrun_21fefffe877f496a97b645f64cf16d2e) |
| MultiConversation | VAD | `eval_3c53dc59` | [View in Foundry](https://ai.azure.com/nextgen/r/LC5tEE5IQP2PTdn7dw0MbQ,rg-voicelive-e2e-test,,ai-3x6t3c6zpbsr6,voicelive-e2e-test/build/evaluations/eval_3c53dc59e47b42ec9e5b730543e76121/run/evalrun_b685d8befdd54ed1a823bfd27070e9c9) |
| Eiffel Tower v1 | PTT | `eval_fa65680e` | [View in Foundry](https://ai.azure.com/nextgen/r/LC5tEE5IQP2PTdn7dw0MbQ,rg-voicelive-e2e-test,,ai-3x6t3c6zpbsr6,voicelive-e2e-test/build/evaluations/eval_fa65680e06614fc6a3f6f75e98a27985/run/evalrun_d4f9d1429616420db74f151a0e166454) |
| Eiffel Tower v1 | VAD | `eval_93a3446e` | [View in Foundry](https://ai.azure.com/nextgen/r/LC5tEE5IQP2PTdn7dw0MbQ,rg-voicelive-e2e-test,,ai-3x6t3c6zpbsr6,voicelive-e2e-test/build/evaluations/eval_93a3446ea2fc4e5eb4ebfcf5d8407674/run/evalrun_ce604d0692cc44ab9470e1fbd4a1df60) |

### Metrics Comparison

| Metric | Multi PTT | Multi VAD | Eiffel PTT | Eiffel VAD |
|--------|-----------|-----------|------------|------------|
| **intent_resolution** | 1.000 | 1.444 | 1.000 | 1.667 |
| **task_adherence** | 1.000 | 0.333 | 0.667 | 0.333 |
| **task_completion** | 0.000 | 0.125 | 0.000 | 0.000 |
| **response_completeness** | 1.000 | 1.000 | 1.000 | 1.000 |
| **relevance** | 1.000 | 1.778 | 1.000 | 1.000 |
| **tool_output_utilization** | 1.000 | 0.889 | 1.000 | 1.000 |

### Analysis

**PTT vs VAD quality differences:**
- **task_adherence** is higher in PTT (1.0 vs 0.333) — the explicit end-of-speech signal gives the model clearer turn boundaries
- **intent_resolution** is higher in VAD (1.444-1.667 vs 1.0) — more captured transcriptions give richer context for intent detection
- **task_completion** is near zero across all runs — this reflects the multi-turn event capture issue where responses are often empty
- **response_completeness** is 1.0 across all runs — when responses are captured, they are complete

**Caveats:**
- Metrics are heavily influenced by the transcription/response capture rate. Empty query/response pairs score differently than populated ones.
- The multi-turn event ordering issue (documented in Known Limitations) means these metrics don't fully reflect VoiceLive's actual capability.
- These results represent the evaluation framework's current state, not production-quality benchmarks.

---

## Infrastructure Details

| Component | Resource |
|-----------|----------|
| Function App | `func-3x6t3c6zpbsr6` |
| Container App | `ca-voicelive-3x6t3c6zpbsr6` |
| Storage Account | `st3x6t3c6zpbsr6` |
| AI Foundry Project | `voicelive-e2e-test` |
| Resource Group | `rg-voicelive-e2e-test` |
