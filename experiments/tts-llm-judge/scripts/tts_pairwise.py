"""
Pairwise naturalness test: HD vs Degraded for each line. LLM judges are more
reliable at A/B comparison than absolute scoring. Expect HD to win on naturalness.
Reuses saved WAVs.
"""
from __future__ import annotations

import base64, json, os, sys
from pathlib import Path
from openai import AzureOpenAI

OUTDIR = Path(__file__).resolve().parents[1] / "clips"
RESOURCE_HOST = "https://solarrezaei-1471-resource.cognitiveservices.azure.com"
GRADER_MODEL = "gpt-audio"
KEY = os.environ["AZURE_OPENAI_KEY"]
client = AzureOpenAI(azure_endpoint=RESOURCE_HOST, api_key=KEY, api_version="2025-04-01-preview")
LINES = ["L1", "L2", "L3"]


def b64(name):
    return base64.b64encode((OUTDIR / name).read_bytes()).decode("ascii")


def pairwise(a_b64, b_b64):
    sysp = ('Two audio clips are attached: clip A (first) and clip B (second). They say the same words. '
            'Judge which sounds MORE natural and higher audio quality (clearer, fuller bandwidth, less muffled). '
            'Output JSON ONLY: {"winner":"A"|"B"|"tie","reason":"..."}.')
    for _ in range(3):
        resp = client.chat.completions.create(
            model=GRADER_MODEL, modalities=["text"], temperature=0,
            messages=[{"role": "system", "content": sysp},
                      {"role": "user", "content": [
                          {"type": "text", "text": "Clip A:"},
                          {"type": "input_audio", "input_audio": {"data": a_b64, "format": "wav"}},
                          {"type": "text", "text": "Clip B:"},
                          {"type": "input_audio", "input_audio": {"data": b_b64, "format": "wav"}},
                          {"type": "text", "text": "Which is more natural/higher quality? JSON only."}]}])
        txt = resp.choices[0].message.content.strip()
        i, j = txt.find("{"), txt.rfind("}")
        if i != -1 and j != -1:
            try:
                return json.loads(txt[i:j + 1])
            except Exception:
                pass
    return {"winner": "?", "reason": txt[:80]}


print("Pairwise: A = HD, B = Degraded (8kHz). Expected winner: A (HD)\n")
hd_wins = 0
for lid in LINES:
    # randomize order would be ideal; keep A=HD, B=Degraded for clarity
    res = pairwise(b64(f"{lid}_HD.wav"), b64(f"{lid}_Degraded.wav"))
    w = res.get("winner")
    if w == "A":
        hd_wins += 1
    print(f"  {lid}: winner={w} (A=HD)  -- {res.get('reason','')[:80]}")
    sys.stdout.flush()

print(f"\nHD chosen as more natural in {hd_wins}/{len(LINES)} pairs.")
