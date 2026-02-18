# E2E Test Conversation Script — Manual Replay Guide

> **Agent:** `voicelive-evaluation-agent-cloud`
> **Project:** `voicelive-e2e-test` on `ai-3x6t3c6zpbsr6`
> **Date passed:** 2026-02-18 | **Result:** 20/20 ✅

Use this script to manually replay the full E2E test conversation in the Foundry Agent Playground
or any Responses API client. Each section is a standalone prompt — paste it, read the expected behavior,
then verify.

---

## Category 1 — Dataset Discovery & Listing

### 1.1 List All Datasets
```
List all datasets
```
**Expected:** Returns BOTH blob storage datasets (eval_ready_test, raw_audio_test, minimal_test)
AND Foundry data store datasets (eval_ready_test, minimal_test, raw_audio_test, results_*).
Two distinct sections should be visible.

---

### 1.2 List VoiceLive Datasets
```
List only the VoiceLive audio datasets from blob storage
```
**Expected:** Lists only blob storage datasets. Must include `raw_audio_test`.
Should show path, size, and last modified date for each.

---

### 1.3 List Evaluation Datasets
```
List only the evaluation-ready datasets from Foundry data store
```
**Expected:** Lists only Foundry datasets with version counts.
Must include `eval_ready_test` with version info.

---

## Category 2 — Dataset Validation

### 2.1 Validate VoiceLive Dataset
```
Validate the raw_audio_test dataset for VoiceLive processing
```
**Expected:** Calls `validate_voicelive_dataset` tool. Reports validation passed — mentions
number of entries (4), number of conversations (2), and confirms no errors/warnings.

---

### 2.2 Validate Eval-Ready Dataset
```
Validate the eval_ready_test dataset for evaluation
```
**Expected:** Calls `validate_eval_dataset` tool. Reports validation passed — mentions
required fields (query, response) and optional fields (ground_truth, context) are present
across all 5 entries.

---

### 2.3 Schema Check
```
Check the schema of the eval_ready_test dataset
```
**Expected:** Calls `check_dataset_schema` tool. Lists fields present in the dataset
including at minimum `query` and `response`. May recommend next steps (validate, evaluate).

---

### 2.4 Validate Nonexistent Dataset
```
Validate the dataset called totally_fake_dataset_xyz
```
**Expected:** Returns a graceful error — "not found", "doesn't exist", or similar.
Must NOT return a 500 internal server error. The agent surfaces the API's 404 error
in a user-friendly way.

---

## Category 3 — Session Configuration

### 3.1 Get Session Config
```
Show me details of the 'default' session configuration
```
**Expected:** Returns full config details including:
- Model: `gpt-4.1`
- Sample rate: 24000 Hz (may be formatted as "24,000")
- Voice: alloy (preset)
- VAD type: azure_semantic_vad_multilingual
- EOU enabled with azure_semantic_v1_multilingual model
- Noise reduction: azure_deep_noise_suppression

---

### 3.2 List Session Configs
```
List all session configurations
```
**Expected:** Lists 7-8 configs including `default` and `conf1` through `conf6`
(plus optionally `audio_test`). Brief descriptions of each config's key parameters
(sample rate, VAD type, model).

---

## Category 4 — Foundry Evaluation

### 4.1 Run Evaluation
```
Run evaluation on eval_ready_test dataset with only fluency evaluator
```
**Expected:** Calls `run_voicelive_evaluation` tool. Returns a confirmation that
the evaluation has started with an instance ID (UUID). Should mention that it
typically takes a few minutes and suggest checking status later.

> ⚠️ This actually triggers a real evaluation run in Foundry.

---

### 4.2 Get Evaluation Recommendations
```
What evaluation settings do you recommend for the eval_ready_test dataset?
```
**Expected:** Provides advice on recommended settings — mentions evaluators,
timeout, parallel workers, or similar configuration suggestions tailored to
the dataset size (5 entries = small dataset).

---

## Category 5 — Resource Management

### 5.1 List Evaluation Groups
```
List all evaluation groups
```
**Expected:** Calls `list_evaluation_groups` tool. Lists evaluation group IDs
and names. May show groups named `gptrealtime_alloy_0.5_500` or similar from
previous test runs.

---

### 5.2 List Foundry Datasets
```
List all Foundry datasets with their versions
```
**Expected:** Lists all datasets in Foundry data store with version counts.
Must mention "version" in the response. Shows latest version number for each dataset.

---

### 5.3 List Evaluators
```
What evaluators can I use?
```
**Expected:** Lists all available evaluators. Must include at minimum:
- `intent_resolution`
- `fluency`
- `relevance`

Plus others like task_adherence, task_completion, response_completeness,
groundedness, tool_call_accuracy, coherence, etc.

---

## Category 6 — Streaming

### 6.1 Streaming Response
```
List datasets briefly
```
**How to test:** Use the Responses API with `stream: true`. Verify that the response
arrives as incremental streaming chunks (SSE events of type `response.output_text.delta`)
rather than a single block. Should receive many chunks (100+).

> This test requires API-level access — in the Playground, all responses stream by default.

---

## Category 7 — Multi-turn Conversation

### 7.1 Multi-turn Context Retention

**Turn 1:**
```
List all datasets
```
*Wait for response, then send Turn 2 in the same conversation:*

**Turn 2:**
```
Check the schema of the first eval-ready dataset you listed
```
**Expected:** Agent uses context from Turn 1 to identify which dataset was listed first.
The response should mention schema fields (query, response, field, column, or schema).
Demonstrates that the agent can follow multi-turn conversation context.

---

## Category 8 — Edge Cases & Off-Track Prompts

### 8.1 Off-Topic Question
```
What is the capital of France?
```
**Expected:** Agent either:
- (a) Answers briefly ("Paris") and redirects to its VoiceLive evaluation purpose, OR
- (b) Politely declines and explains what it can help with

Either behavior is acceptable. The key assertion is that it does NOT crash.

---

### 8.2 Ambiguous Request
```
Run a test
```
**Expected:** Agent asks for clarification — "which dataset?", "what kind of test?",
"could you specify?", etc. Should present options (VoiceLive audio test vs. Foundry
evaluation vs. dataset validation). May list available datasets to help the user choose.

---

### 8.3 Capabilities Query
```
What can you do? What are your capabilities?
```
**Expected:** Agent describes its capabilities covering at least 2 of these 5 areas:
1. **Dataset** management (list, upload, discover)
2. **Evaluation** (run evaluations, check status)
3. **VoiceLive** audio processing
4. **Validation** (validate datasets)
5. **Configuration** (session configs)

---

### 8.4 No Polling Promise
```
Run evaluation on eval_ready_test with fluency only. Track the progress for me and let me know when done.
```
**Expected:** Agent starts the evaluation but does NOT promise to continuously monitor it.
It should suggest that the user manually ask for status updates ("ask me to check the status",
"check the status whenever you'd like"). It must NOT say "I will monitor", "I'll keep checking",
or "I'll let you know when it's done" — because the agent cannot poll autonomously.

> ⚠️ This also triggers a real evaluation run in Foundry.

---

## Summary Checklist

| # | Test | Category | Key Assertion |
|---|------|----------|---------------|
| 1.1 | List All Datasets | discovery | Shows both blob + Foundry datasets |
| 1.2 | List VoiceLive | discovery | Shows blob datasets only |
| 1.3 | List Eval Datasets | discovery | Shows Foundry datasets with versions |
| 2.1 | Validate VoiceLive | validation | Reports valid, entry count, conversation count |
| 2.2 | Validate Eval | validation | Reports valid, lists required fields |
| 2.3 | Schema Check | validation | Shows query/response fields |
| 2.4 | Validate Missing | validation | Graceful error, no 500 |
| 3.1 | Get Config | config | Shows gpt-4.1, 24kHz, alloy, VAD details |
| 3.2 | List Configs | config | Lists 7+ configs including default/conf1 |
| 4.1 | Run Evaluation | evaluation | Returns instance ID, starts eval |
| 4.2 | Recommendations | evaluation | Gives advice on settings |
| 5.1 | Eval Groups | resources | Lists evaluation group IDs |
| 5.2 | Foundry Datasets | resources | Lists datasets with version info |
| 5.3 | List Evaluators | resources | Lists intent_resolution, fluency, relevance |
| 6.1 | Streaming | streaming | Receives incremental chunks |
| 7.1 | Multi-turn | conversation | Context retained across turns |
| 8.1 | Off-Topic | edge_cases | No crash, answers or redirects |
| 8.2 | Ambiguous | edge_cases | Asks for clarification |
| 8.3 | Capabilities | edge_cases | Describes ≥2 feature areas |
| 8.4 | No Polling | edge_cases | Doesn't promise autonomous tracking |
