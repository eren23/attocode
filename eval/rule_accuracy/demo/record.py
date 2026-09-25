"""Record a real scoring run: per-call start/end offsets, scores, reasoning."""
from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from attocode_intel._internal.integrations.feature_flags import registry
from attocode_intel.confidence import jev as jev_scorer
from attocode_intel.confidence import llm as llm_scorer
from attocode_intel.confidence.redact import redact

from attocode.code_intel.rules.enricher import enrich_findings
from attocode.code_intel.rules.executor import execute_rules
from attocode.code_intel.rules.filters.pipeline import run_pipeline
from attocode.code_intel.rules.loader import load_builtin_rules
from attocode.code_intel.rules.packs.pack_loader import list_example_packs, load_pack
from eval.rule_accuracy.demo.scan import write_json
from eval.rule_accuracy.runner import (
    CORPUS_DIR,
    _finding_matches,
    _parse_file_annotations,
    _strip_annotations,
    discover_corpus,
)

parser = argparse.ArgumentParser(description="Explicit refresh; scoring scripts may call paid providers.")
parser.add_argument("--output-dir", required=True)
args = parser.parse_args()
Path(args.output_dir).mkdir(parents=True, exist_ok=True)

S = Path(args.output_dir)

rules = load_builtin_rules()
for m in list_example_packs():
    rules.extend(load_pack(m))
registry.set_override("CONFIDENCE", "off")

meta, owner, everything = {}, {}, []
for fp, lang, cwe in discover_corpus(CORPUS_DIR):
    exp, _ = _parse_file_annotations(fp)
    meta[fp] = (lang, cwe, exp)
    found = execute_rules([fp], rules, project_dir=str(Path(fp).parent))
    enrich_findings(found, project_dir=str(Path(fp).parent))
    _strip_annotations(found)
    for f in found:
        owner[id(f)] = fp
    everything.extend(found)
findings = run_pipeline(everything, min_confidence=0.0)
registry.clear_override("CONFIDENCE")
print(f"{len(findings)} findings")

questions = {"p": {"type": "noul", "instructions": jev_scorer.QUESTION, "criteria": jev_scorer.CRITERIA}}
chosen = jev_scorer.backend()
jev_scorer._load_env()

# ---- jev, at its production worker count -----------------------------------
jev_rec: dict[int, dict] = {}
def jev_task(i_f):
    i, f = i_f
    t0 = time.monotonic()
    try:
        row = jev_scorer._decide("demo_race", jev_scorer._state(f), questions,
                        "yes" if f.confidence >= 0.5 else "no", chosen)
        a = (row.get("answers") or {}).get("p") or {}
        v = a.get("noul")
        p = float(v) if not isinstance(v, bool) and isinstance(v, (int, float)) and 0 <= v <= 1 else None
    except Exception as e:
        p = None
        print("jev err", e)
    return i, t0, time.monotonic(), p

t_jev0 = time.monotonic()
with ThreadPoolExecutor(max_workers=jev_scorer.WORKERS) as pool:
    for i, t0, t1, p in pool.map(jev_task, list(enumerate(findings))):
        jev_rec[i] = {"s": round((t0 - t_jev0) * 1000), "e": round((t1 - t_jev0) * 1000), "p": p}
jev_wall = round((time.monotonic() - t_jev0) * 1000)
print(f"jev wall {jev_wall}ms  workers={jev_scorer.WORKERS}")

# ---- classifier, at its production worker count ----------------------------
llm_rec: dict[int, dict] = {}
def llm_task(i_f):
    i, f = i_f
    t0 = time.monotonic()
    c = llm_scorer.classify_finding(
        rule_id=f.rule_id, severity=str(f.severity), description=f.description,
        cwe=f.cwe, file=f.file, line=f.line, matched_line=f.code_snippet,
        code_context="\n".join([*f.context_before, f.code_snippet, *f.context_after]),
        explanation=f.explanation,
    )
    return i, t0, time.monotonic(), c

t_llm0 = time.monotonic()
with ThreadPoolExecutor(max_workers=llm_scorer._WORKERS) as pool:
    for i, t0, t1, c in pool.map(llm_task, list(enumerate(findings))):
        if c.verdict == llm_scorer.FPVerdict.TRUE_POSITIVE:
            p = c.confidence
        elif c.verdict == llm_scorer.FPVerdict.FALSE_POSITIVE:
            p = 1.0 - c.confidence
        else:
            p = None
        llm_rec[i] = {"s": round((t0 - t_llm0) * 1000), "e": round((t1 - t_llm0) * 1000),
                      "p": p, "verdict": str(c.verdict), "why": redact(c.reasoning)[:400]}
llm_wall = round((time.monotonic() - t_llm0) * 1000)
print(f"llm wall {llm_wall}ms  workers={llm_scorer._WORKERS}")

out = []
for i, f in enumerate(findings):
    fp = owner[id(f)]
    lang, cwe, exp = meta[fp]
    e = exp.get(f.line)
    out.append({
        "rule": f.rule_id, "file": Path(fp).name, "line": f.line, "lang": lang,
        "sec": 1 if (f.rule_id.startswith("security/") or cwe.startswith("CWE")) else 0,
        "tp": 1 if (e is not None and _finding_matches(f.rule_id, e)) else 0,
        "desc": f.description, "snippet": f.code_snippet,
        "before": f.context_before[-3:], "after": f.context_after[:3],
        "constant": round(f.confidence, 4),
        "jev": jev_rec[i], "llm": llm_rec[i],
    })
write_json(S / "timeline.json",
    {"findings": out, "jev_wall": jev_wall, "llm_wall": llm_wall,
     "jev_workers": jev_scorer.WORKERS, "llm_workers": llm_scorer._WORKERS})
jl = sorted(r["jev"]["e"] - r["jev"]["s"] for r in out)
ll = sorted(r["llm"]["e"] - r["llm"]["s"] for r in out)
def med(a):
    return a[len(a)//2]
print(f"jev per-call median {med(jl)}ms  min {jl[0]} max {jl[-1]}")
print(f"llm per-call median {med(ll)}ms  min {ll[0]} max {ll[-1]}")
