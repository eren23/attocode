"""Derived stats from findings.json — all numbers in the narrative come from here."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser(description="Explicit refresh; scoring scripts may call paid providers.")
parser.add_argument("--output-dir", required=True)
args = parser.parse_args()
Path(args.output_dir).mkdir(parents=True, exist_ok=True)


SCRATCH = Path(args.output_dir)
rows = json.loads((SCRATCH / "findings.json").read_text())

def effective(r, scorer):
    """What the pipeline would actually use: the estimate, or the constant if none."""
    if scorer == "constant":
        return r["constant"]
    v = r[scorer]
    return r["constant"] if v is None else v

def ece(pairs, n_bins=10):
    bins = [[0, 0] for _ in range(n_bins)]          # [count, tp]
    for p, tp in pairs:
        i = min(int(p * n_bins), n_bins - 1)
        bins[i][0] += 1
        bins[i][1] += tp
    total = len(pairs)
    out = 0.0
    for i, (n, tp) in enumerate(bins):
        if not n:
            continue
        observed = tp / n
        expected = (i + 0.5) / n_bins
        out += (n / total) * abs(observed - expected)
    return out

def reliability(pairs, n_bins=10):
    bins = [[0, 0] for _ in range(n_bins)]
    for p, tp in pairs:
        i = min(int(p * n_bins), n_bins - 1)
        bins[i][0] += 1
        bins[i][1] += tp
    return [
        {"lo": round(i / n_bins, 2), "hi": round((i + 1) / n_bins, 2),
         "n": n, "observed": round(tp / n, 4), "expected": round((i + 0.5) / n_bins, 2)}
        for i, (n, tp) in enumerate(bins) if n
    ]

def prf(pairs, thr):
    """Threshold semantics: keep p >= thr. Precision over kept, recall over all TPs."""
    kept = [(p, tp) for p, tp in pairs if p >= thr]
    all_tp = sum(tp for _, tp in pairs)
    tp_kept = sum(tp for _, tp in kept)
    prec = tp_kept / len(kept) if kept else None
    rec = tp_kept / all_tp if all_tp else None
    f1 = (2 * prec * rec / (prec + rec)) if prec and rec else 0.0
    return {"thr": thr, "kept": len(kept), "precision": prec, "recall": rec, "f1": f1}

summary = {}
for scorer in ("constant", "jev", "llm"):
    pairs = [(effective(r, scorer), r["is_tp"]) for r in rows]
    summary[scorer] = {
        "ece": round(ece(pairs), 4),
        "reliability": reliability(pairs),
        "sweep": [prf(pairs, t) for t in (0.0, 0.3, 0.5, 0.7, 0.9)],
        "at_half": prf(pairs, 0.5),
        "abstained": sum(1 for r in rows if scorer != "constant" and r[scorer] is None),
    }

print(f"{len(rows)} findings, {sum(r['is_tp'] for r in rows)} TP\n")
print(f"{'scorer':10} {'ECE':>7} {'P@.5':>6} {'R@.5':>6} {'F1@.5':>6} {'kept':>5} {'abstain':>7}")
for s, d in summary.items():
    h = d["at_half"]
    print(f"{s:10} {d['ece']:7.4f} {h['precision']:6.2f} {h['recall']:6.2f} "
          f"{h['f1']:6.2f} {h['kept']:5d} {d['abstained']:7d}")

# Where do jev and the classifier actually disagree?
both = [r for r in rows if r["jev"] is not None and r["llm"] is not None]
gap = sorted(both, key=lambda r: -abs(r["jev"] - r["llm"]))
print(f"\nboth scored: {len(both)}. Widest disagreements:")
for r in gap[:6]:
    print(f"  jev={r['jev']:.2f} llm={r['llm']:.2f} tp={str(r['is_tp']):5} {r['rule'][:34]:34} {r['file']}")

(SCRATCH / "stats.json").write_text(json.dumps(summary, indent=1))
print("\nwrote stats.json")

