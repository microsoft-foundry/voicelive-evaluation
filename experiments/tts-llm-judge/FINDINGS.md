# TTS Speech-LLM-as-a-Judge: Investigation & Findings

**Author:** Solar Rezaei
**Context:** Evaluating whether a Speech LLM (audio-native model) can serve as the
TTS quality judge for voice-agent evaluation, replacing/augmenting MOS metrics
(UTMOS). Prompted by the discussion on the 0612 Voice Agent Eval Strategy.

---

## TL;DR

- **Gemini is out for production** — the commonly used tier isn't licensed for
  commercial use (it trains on submitted data); commercial use needs paid
  Vertex AI plus shipping our eval audio to Google. Not viable.
- **We can use GPT-4o-audio (`gpt-audio`)** via the OpenAI partnership, natively
  in **Azure AI Foundry** as a `score_model` audio grader. Audio stays in Azure.
  Verified working end-to-end in this harness.
- **The judge is reliable for *content fidelity*** (names, acronyms, phone/
  confirmation digits) — exactly the dimension flagged as important. It listens
  to the waveform and catches specific pronunciation errors.
- **The judge is NOT reliable for *naturalness/MOS*.** Scores cluster near the
  top by default, anchor to the prompt when pushed, and in a direct A/B test it
  picked an obviously degraded telephone-quality clip as the *more* natural one.
- **Recommendation: split the rubric by tool.**
  - Tone + content fidelity → `gpt-audio` score-model grader.
  - Naturalness / audio quality → a purpose-built MOS predictor (UTMOS / DNSMOS),
    not the LLM. This is *complementary* to the Speech-LLM-judge idea, not a
    rejection of it.

---

## What was tested

3 lines were synthesized that deliberately exercise critical content (a name, the
acronyms IRS/TIN/RMA, and phone/confirmation digit sequences), each in 3 conditions:

| Condition | Voice | Format |
|-----------|-------|--------|
| HD        | `en-US-Ava:DragonHDLatestNeural` | 24 kHz |
| Standard  | `en-US-AvaNeural`                | 24 kHz |
| Degraded  | `en-US-AvaNeural`                | 8 kHz narrowband (telephone) |

Clips are in `clips/`. Each was graded by `gpt-audio` on three rubric dimensions
(naturalness, content_fidelity, tone_appropriateness) and cross-checked with the
harness DNSMOS predictor.

---

## Results

### 1. Default rubric (gpt-audio) — scores compress near the top
Average by condition (0–1, higher = better):

| Condition | naturalness | content_fidelity | tone_appropriateness |
|-----------|-------------|------------------|----------------------|
| HD        | 0.90 | 0.98 | 0.93 |
| Standard  | 0.88 | 1.00 | 0.95 |
| Degraded  | 0.88 | 1.00 | 0.95 |

Note the degraded 8 kHz clip is barely distinguished from the good ones on
naturalness. Content fidelity *did* surface real, specific errors in the per-clip
reasons (e.g. "TIN mispronounced as TN", "1040 read as 'ten four do'",
"Dr. Nguyen mispronounced").

### 2. Strict, anchored rubric — over-corrects / anchors to prompt numbers
Forcing a critical rubric collapsed most scores to ~0.4 naturalness regardless of
condition (the model copies the example anchor values rather than truly measuring),
and several HD calls failed to return valid JSON. Not a reliable fix.

### 3. Pairwise A/B (HD vs Degraded) — judge gets it backwards
LLM judges are usually better at A/B than absolute scoring, so this was the
strongest test. Result: **HD chosen as more natural in 0/3 pairs.** The judge
described the 8 kHz telephone-quality clip as "clearer, fuller bandwidth, less
muffling" — the opposite of reality (likely position bias + genuine inability to
perceive bandwidth).

### 4. DNSMOS (purpose-built MOS predictor, already in the harness)
Average by condition (1–5, higher = better):

| Condition | sig | ovrl | p808_mos |
|-----------|-----|------|----------|
| HD        | 3.65 | 3.44 | 3.91 |
| Standard  | 3.67 | 3.45 | 4.09 |
| Degraded  | 3.64 | 3.42 | **3.67** |

`p808_mos` correctly flags the degraded clip lowest. HD vs Standard remain close —
**corroborating, via an independent method, that the two voice tiers are genuinely
close on short utterances** (so the lack of HD-vs-Standard separation is a real
finding, not a measurement artifact).

---

## Interpretation vs. the UTMOS / Gemini discussion

There is no real conflict:
- UTMOS/DNSMOS (MOS predictors) are **blind to tone and content fidelity** — correct
  reason to not rely on them alone.
- The Speech-LLM judge is **strong on content fidelity, weak on naturalness**.
- So: **three dimensions, two tools**, each pointed at what it actually measures.
  UTMOS is in fact well suited to the naturalness dimension (trained on TTS MOS),
  so it should be *kept for that one dimension*, not dropped entirely.

---

## Verified platform facts

- `score_model` graders are a native Azure AI Foundry feature and support audio via
  a `gpt-audio` / `gpt-4o-audio` deployment (the grader ingests `input_audio`).
  - Docs: https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/azure-openai-graders
  - Audio model: https://learn.microsoft.com/en-us/azure/foundry/openai/audio-completions-quickstart
- **Auth/RBAC:** the grader calls the AOAI Evals API (`POST /openai/evals`), which
  needs the `Microsoft.CognitiveServices/accounts/OpenAI/*` data action. That lives
  in **`Azure AI Developer`** / **`Cognitive Services OpenAI Contributor`**, NOT in
  `Cognitive Services Contributor`. With the right role, `DefaultAzureCredential`
  (no key) works; otherwise an api-key is the fallback. Both paths verified.

See `scripts/` for the exact, runnable scripts used to produce every number above.
