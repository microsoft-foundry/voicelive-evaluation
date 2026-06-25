"""
Re-grade the 9 saved clips with a STRICT, anchored rubric to test whether the
gpt-audio judge can produce meaningful variation (vs the lenient default).
Reuses WAVs already in output/tts_voice_comparison/.
"""
from __future__ import annotations

import base64, json, os, sys
from pathlib import Path
from openai import AzureOpenAI

OUTDIR = Path(__file__).resolve().parents[1] / "clips"
RESOURCE_HOST = "https://solarrezaei-1471-resource.cognitiveservices.azure.com"
GRADER_MODEL = "gpt-audio"
API_VERSION = "2025-04-01-preview"
KEY = os.environ["AZURE_OPENAI_KEY"]
client = AzureOpenAI(azure_endpoint=RESOURCE_HOST, api_key=KEY, api_version=API_VERSION)

LINES = {
    "L1": "Sarah from the IRS; callback 1-800-829-1040; mentions TIN.",
    "L2": "Appointment with Dr. Nguyen at 3 PM; confirmation A-4-7-2-9.",
    "L3": "From Contoso; RMA number RMA-2024-XJ-58; email support@contoso.com.",
}
CONDITIONS = ["HD", "Standard", "Degraded"]
DIMS = ["naturalness", "content_fidelity", "tone_appropriateness"]

STRICT = (
    "You are a STRICT, critical TTS quality judge. Scores must SPREAD across the full 0..1 range; "
    "do not cluster near 1.0. An audio clip is attached, listen carefully and assess the ACTUAL ACOUSTICS "
    "(bandwidth, clarity, artifacts, prosody), not just the words.\n"
    "Anchors for naturalness: 1.0=flawless studio human; 0.8=good neural TTS, minor stiffness; "
    "0.5=clearly synthetic or noticeably muffled/narrowband telephone audio; 0.2=robotic or heavily degraded.\n"
    "If the audio sounds narrowband / muffled / telephone-quality (limited high frequencies), cap naturalness at 0.5.\n"
    "content_fidelity: deduct 0.15 for EACH mispronounced name, acronym, or wrong/unclear digit vs the reference.\n"
    "tone_appropriateness: 1.0=ideal service tone; deduct for flat, rushed, or robotic delivery.\n"
    'Output JSON ONLY: {"naturalness":{"result":float,"reason":"..."},'
    '"content_fidelity":{"result":float,"reason":"..."},"tone_appropriateness":{"result":float,"reason":"..."}}'
)


def grade(b64: str, ref: str) -> dict:
    for _ in range(3):
        resp = client.chat.completions.create(
            model=GRADER_MODEL, modalities=["text"], temperature=0,
            messages=[{"role": "system", "content": STRICT},
                      {"role": "user", "content": [
                          {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}},
                          {"type": "text", "text": f"Reference: {ref}\nJSON only."}]}])
        txt = resp.choices[0].message.content.strip()
        i, j = txt.find("{"), txt.rfind("}")
        if i != -1 and j != -1:
            try:
                return json.loads(txt[i:j + 1])
            except Exception:
                pass
    return {d: {"result": None, "reason": txt[:80]} for d in DIMS}


results = {}
for lid, ref in LINES.items():
    for c in CONDITIONS:
        b64 = base64.b64encode((OUTDIR / f"{lid}_{c}.wav").read_bytes()).decode("ascii")
        row = grade(b64, ref)
        results[f"{lid}_{c}"] = row
        print(f"  {lid}_{c:<9} " + "  ".join(f"{d.split('_')[0]}={row.get(d,{}).get('result')}" for d in DIMS))
        sys.stdout.flush()

print("\n" + "=" * 84)
print(f"{'Line':<6}{'Condition':<11}" + "".join(f"{d:<23}" for d in DIMS))
print("=" * 84)
for lid in LINES:
    for c in CONDITIONS:
        row = results[f"{lid}_{c}"]
        print(f"{lid:<6}{c:<11}" + "".join(f"{str(row.get(d,{}).get('result')):<23}" for d in DIMS))
    print("-" * 84)
print("\nAVERAGE BY CONDITION (strict rubric):")
for c in CONDITIONS:
    parts = []
    for d in DIMS:
        vals = [results[f"{l}_{c}"].get(d, {}).get("result") for l in LINES]
        vals = [x for x in vals if isinstance(x, (int, float))]
        parts.append(f"{d}={sum(vals)/len(vals):.2f}" if vals else f"{d}=-")
    print(f"  {c:<10} " + "  ".join(parts))

# show the degraded reasons to confirm it heard the bandwidth drop
print("\nDEGRADED naturalness reasons:")
for lid in LINES:
    print(f"  {lid}: {results[f'{lid}_Degraded'].get('naturalness',{}).get('reason','')[:90]}")
