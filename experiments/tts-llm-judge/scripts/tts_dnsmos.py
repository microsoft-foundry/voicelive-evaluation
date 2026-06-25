"""Run the harness DNSMOS on the 9 saved clips to see if it discriminates
HD / Standard / Degraded where the gpt-audio judge did not."""
from __future__ import annotations

import sys, wave
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[3] / "evaluation_harness"
sys.path.insert(0, str(HARNESS.parent))
from evaluation_harness.dnsmos_utils import compute_dnsmos

OUTDIR = Path(__file__).resolve().parents[1] / "clips"
LINES = ["L1", "L2", "L3"]
CONDITIONS = ["HD", "Standard", "Degraded"]


def read_pcm(path: Path):
    with wave.open(str(path), "rb") as w:
        return w.readframes(w.getnframes()), w.getframerate()


results = {}
for lid in LINES:
    for c in CONDITIONS:
        pcm, sr = read_pcm(OUTDIR / f"{lid}_{c}.wav")
        r = compute_dnsmos([pcm], source_sample_rate=sr)
        results[f"{lid}_{c}"] = r
        print(f"  {lid}_{c:<9} sr={sr:<6} {r}")
        sys.stdout.flush()

print("\n" + "=" * 64)
print(f"{'Line':<6}{'Condition':<11}{'sig':<8}{'bak':<8}{'ovrl':<8}{'p808':<8}")
print("=" * 64)
for lid in LINES:
    for c in CONDITIONS:
        r = results.get(f"{lid}_{c}") or {}
        print(f"{lid:<6}{c:<11}{r.get('sig','-'):<8}{r.get('bak','-'):<8}{r.get('ovrl','-'):<8}{r.get('p808_mos','-'):<8}")
    print("-" * 64)

print("\nAVERAGE BY CONDITION (DNSMOS, 1-5 higher=better):")
for c in CONDITIONS:
    for k in ["sig", "ovrl", "p808_mos"]:
        vals = [results[f"{l}_{c}"].get(k) for l in LINES if results.get(f"{l}_{c}")]
        vals = [v for v in vals if isinstance(v, (int, float))]
        avg = f"{sum(vals)/len(vals):.2f}" if vals else "-"
        print(f"  {c:<10} {k:<10} {avg}")
    print()
