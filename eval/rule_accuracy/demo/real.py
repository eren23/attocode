"""Score a diverse sample of findings from the repo's own source. No ground truth here."""
from __future__ import annotations

import argparse
import collections
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from attocode_intel.confidence import jev as jev_scorer
from attocode_intel.confidence import llm as llm_scorer
from attocode_intel.confidence.redact import redact

from attocode.code_intel.rules.enricher import enrich_findings
from attocode.code_intel.rules.executor import execute_rules
from attocode.code_intel.rules.loader import load_builtin_rules
from attocode.code_intel.rules.packs.pack_loader import list_example_packs, load_pack
from eval.rule_accuracy.demo.scan import write_json

parser = argparse.ArgumentParser(description="Explicit refresh; scoring scripts may call paid providers.")
parser.add_argument("--output-dir", required=True)
args = parser.parse_args()
Path(args.output_dir).mkdir(parents=True, exist_ok=True)

S = Path(args.output_dir)
rules = load_builtin_rules()
for m in list_example_packs():
    rules.extend(load_pack(m))

root = Path("packages/code-intel/src/attocode_intel")
files = [str(p) for p in sorted(root.rglob("*.py")) if "__pycache__" not in str(p)]
found = execute_rules(files, rules, project_dir=".")
print("total findings:", len(found))

# Stratify: at most 4 per rule, prefer lines with real code around them.
by_rule = collections.defaultdict(list)
for f in found:
    by_rule[f.rule_id].append(f)
sample = []
for _rid, fs in sorted(by_rule.items()):
    fs.sort(key=lambda f: -len(f.code_snippet.strip()))
    sample.extend(fs[:4])
print("sampled:", len(sample), "across", len(by_rule), "rules")
enrich_findings(sample, project_dir=".")

def window(path: str, line: int, span: int = 9):
    try:
        src = Path(path).read_text().splitlines()
    except OSError:
        return [], ""
    lo, hi = max(0, line - 1 - span), min(len(src), line + span)
    return [{"n": i + 1, "t": src[i]} for i in range(lo, hi)], "\n".join(src[lo:hi])

questions = {"p": {"type": "noul", "instructions": jev_scorer.QUESTION, "criteria": jev_scorer.CRITERIA}}
jev_scorer._load_env()
chosen = jev_scorer.backend()

def jev_task(f):
    t0 = time.monotonic()
    try:
        row = jev_scorer._decide("demo_real", jev_scorer._state(f), questions,
                        "yes" if f.confidence >= 0.5 else "no", chosen)
        a = (row.get("answers") or {}).get("p") or {}
        v = a.get("noul")
        p = float(v) if not isinstance(v, bool) and isinstance(v, (int, float)) and 0 <= v <= 1 else None
    except Exception:
        p = None
    return p, round((time.monotonic() - t0) * 1000)

def llm_task(f):
    t0 = time.monotonic()
    c = llm_scorer.classify_finding(
        rule_id=f.rule_id, severity=str(f.severity), description=f.description,
        cwe=f.cwe, file=f.file, line=f.line, matched_line=f.code_snippet,
        code_context="\n".join([*f.context_before, f.code_snippet, *f.context_after]),
        explanation=f.explanation)
    p = c.confidence if c.verdict == llm_scorer.FPVerdict.TRUE_POSITIVE else (
        1.0 - c.confidence if c.verdict == llm_scorer.FPVerdict.FALSE_POSITIVE else None)
    return p, round((time.monotonic() - t0) * 1000), str(c.verdict), redact(c.reasoning)[:420]

print("scoring jev...")
with ThreadPoolExecutor(max_workers=jev_scorer.WORKERS) as pool:
    jres = list(pool.map(jev_task, sample))
print("scoring classifier...")
with ThreadPoolExecutor(max_workers=llm_scorer._WORKERS) as pool:
    mres = list(pool.map(llm_task, sample))

out = []
for f, (jp, jms), (mp, mms, verdict, why) in zip(sample, jres, mres, strict=True):
    lines, raw = window(f.file, f.line)
    sent = "\n".join([*f.context_before, f.code_snippet, *f.context_after])
    out.append({
        "rule": f.rule_id, "file": f.file, "line": f.line,
        "sev": str(f.severity), "cwe": f.cwe or "", "desc": f.description,
        "snippet": f.code_snippet, "lines": lines,
        "redacted": redact(sent) != sent,
        "c": round(f.confidence, 3), "j": jp, "jms": jms,
        "m": mp, "mms": mms, "verdict": verdict, "why": why,
    })
write_json(S / "real.json", out)
print("wrote", len(out), "->", (S / "real.json").stat().st_size, "bytes")

agree = sum(1 for r in out if r["j"] is not None and r["m"] is not None and abs(r["j"] - r["m"]) < .25)
jhi = sum(1 for r in out if r["j"] is not None and r["m"] is not None and r["j"] - r["m"] > .4)
mhi = sum(1 for r in out if r["j"] is not None and r["m"] is not None and r["m"] - r["j"] > .4)
dec = sum(1 for r in out if r["m"] is None)
print(f"agree(<.25) {agree} | jev higher by .4+ {jhi} | classifier higher by .4+ {mhi} | declined {dec}")
