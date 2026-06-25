"""
TTS rubric sensitivity demo: HD vs Standard vs Degraded (narrowband).

Shows whether the gpt-audio score rubric varies with real quality differences.
  - HD:        en-US-Ava:DragonHDLatestNeural   @ 24kHz
  - Standard:  en-US-AvaNeural                  @ 24kHz
  - Degraded:  en-US-AvaNeural                  @ 8kHz narrowband (telephone)

Grades each clip on naturalness / content_fidelity / tone_appropriateness in a
single gpt-audio call (with JSON retry), then prints a comparison table.
"""
from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from openai import AzureOpenAI

HARNESS = Path(__file__).resolve().parents[3] / "evaluation_harness"
OUTDIR = Path(__file__).resolve().parents[1] / "clips"
OUTDIR.mkdir(parents=True, exist_ok=True)
REGION = "eastus2"
RESOURCE_HOST = "https://solarrezaei-1471-resource.cognitiveservices.azure.com"
GRADER_MODEL = "gpt-audio"
API_VERSION = "2025-04-01-preview"
KEY = os.environ["AZURE_OPENAI_KEY"]
client = AzureOpenAI(azure_endpoint=RESOURCE_HOST, api_key=KEY, api_version=API_VERSION)

LINES = {
    "L1": ("Hi, this is Sarah from the IRS. Please call us back at 1 800 829 1040 about your TIN.",
           "Sarah from the IRS; callback 1-800-829-1040; mentions TIN."),
    "L2": ("Your appointment with Doctor Nguyen is confirmed for 3 PM. Your confirmation number is A 4 7 2 9.",
           "Appointment with Dr. Nguyen at 3 PM; confirmation A-4-7-2-9."),
    "L3": ("Thanks for contacting Contoso. Your R M A number is RMA 2024 XJ 58. We'll email support at contoso dot com.",
           "From Contoso; RMA number RMA-2024-XJ-58; email support@contoso.com."),
}
# label -> (voice, output format)
CONDITIONS = {
    "HD":       ("en-US-Ava:DragonHDLatestNeural", "riff-24khz-16bit-mono-pcm"),
    "Standard": ("en-US-AvaNeural",                "riff-24khz-16bit-mono-pcm"),
    "Degraded": ("en-US-AvaNeural",                "riff-8khz-16bit-mono-pcm"),
}
DIMS = ["naturalness", "content_fidelity", "tone_appropriateness"]


def synth(text: str, voice: str, fmt: str) -> bytes:
    ssml = f"<speak version='1.0' xml:lang='en-US'><voice name='{voice}'>{text}</voice></speak>"
    resp = requests.post(
        f"https://{REGION}.tts.speech.microsoft.com/cognitiveservices/v1",
        headers={"Ocp-Apim-Subscription-Key": KEY, "Content-Type": "application/ssml+xml",
                 "X-Microsoft-OutputFormat": fmt, "User-Agent": "vl-tts-demo"},
        data=ssml.encode("utf-8"), timeout=60)
    resp.raise_for_status()
    return resp.content


def grade_all(wav_b64: str, reference: str) -> dict:
    sys_prompt = (
        "You are a TTS quality judge. An audio clip IS attached to this message. Listen to it "
        "(do not ask for the audio, it is already provided) and rate three dimensions, each float 0..1:\n"
        "- naturalness: human-like prosody/rhythm/intonation and audio clarity. 1.0=human/clear, 0.0=robotic/muffled.\n"
        "- content_fidelity: names, acronyms, digit sequences pronounced clearly/correctly vs reference. 1.0=all correct.\n"
        "- tone_appropriateness: appropriate/professional for a polite customer-service call. 1.0=perfect.\n"
        'Output JSON ONLY, no preamble: {"naturalness":{"result":float,"reason":"..."},'
        '"content_fidelity":{"result":float,"reason":"..."},"tone_appropriateness":{"result":float,"reason":"..."}}'
    )
    for _ in range(3):
        resp = client.chat.completions.create(
            model=GRADER_MODEL, modalities=["text"], temperature=0,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": [
                    {"type": "input_audio", "input_audio": {"data": wav_b64, "format": "wav"}},
                    {"type": "text", "text": f"Reference: {reference}\nReturn JSON only."},
                ]},
            ])
        txt = resp.choices[0].message.content.strip()
        if txt.startswith("```"):
            txt = txt.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
        i, j = txt.find("{"), txt.rfind("}")
        if i != -1 and j != -1:
            try:
                return json.loads(txt[i:j + 1])
            except Exception:
                pass
    return {d: {"result": None, "reason": txt[:80]} for d in DIMS}


results = {}
print("[synth+grade] ...")
for lid, (text, ref) in LINES.items():
    for clabel, (voice, fmt) in CONDITIONS.items():
        wav = synth(text, voice, fmt)
        (OUTDIR / f"{lid}_{clabel}.wav").write_bytes(wav)
        row = grade_all(base64.b64encode(wav).decode("ascii"), ref)
        results[f"{lid}_{clabel}"] = row
        line = "  ".join(f"{d.split('_')[0]}={row.get(d,{}).get('result')}" for d in DIMS)
        print(f"  {lid}_{clabel:<9} {line}")
        sys.stdout.flush()

ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
results_path = OUTDIR / f"{ts}_tts_sensitivity.jsonl"
with results_path.open("w", encoding="utf-8") as fh:
    for lid in LINES:
        for c in CONDITIONS:
            row = results[f"{lid}_{c}"]
            fh.write(json.dumps({"line_id": lid, "condition": c,
                                 "scores": {d: row.get(d, {}).get("result") for d in DIMS},
                                 "reasons": {d: row.get(d, {}).get("reason") for d in DIMS}}) + "\n")

print("\n" + "=" * 84)
print(f"{'Line':<6}{'Condition':<11}" + "".join(f"{d:<23}" for d in DIMS))
print("=" * 84)
for lid in LINES:
    for c in CONDITIONS:
        row = results[f"{lid}_{c}"]
        print(f"{lid:<6}{c:<11}" + "".join(f"{str(row.get(d,{}).get('result')):<23}" for d in DIMS))
    print("-" * 84)

print("\nAVERAGE BY CONDITION:")
for c in CONDITIONS:
    parts = []
    for d in DIMS:
        vals = [results[f"{l}_{c}"].get(d, {}).get("result") for l in LINES]
        vals = [x for x in vals if isinstance(x, (int, float))]
        parts.append(f"{d}={sum(vals)/len(vals):.2f}" if vals else f"{d}=-")
    print(f"  {c:<10} " + "  ".join(parts))

print(f"\n[done] results JSONL: {results_path}")
print(f"[done] WAVs in: {OUTDIR}")
