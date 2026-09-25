"""Score every corpus finding with all three scorers. One row per finding."""
from __future__ import annotations

import argparse
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

rules = load_builtin_rules()
for manifest in list_example_packs():
    rules.extend(load_pack(manifest))

registry.set_override("CONFIDENCE", "off")  # constants only for the baseline pass

meta: dict[str, tuple[str, str, dict[int, str]]] = {}
owner: dict[int, str] = {}
all_findings: list = []
for fp, lang, cwe in discover_corpus(CORPUS_DIR):
    expectations, _is_tn = _parse_file_annotations(fp)
    meta[fp] = (lang, cwe, expectations)
    found = execute_rules([fp], rules, project_dir=str(Path(fp).parent))
    enrich_findings(found, project_dir=str(Path(fp).parent))
    _strip_annotations(found)
    for f in found:
        owner[id(f)] = fp
    all_findings.extend(found)

scored = run_pipeline(all_findings, min_confidence=0.0)
registry.clear_override("CONFIDENCE")
print(f"{len(scored)} findings after dedup")

constants = [f.confidence for f in scored]
print("scoring with jev...")
jev_p = jev_scorer.estimate(scored, min_confidence=0.5)
print("scoring with llm...")
llm_p = llm_scorer.estimate(scored, min_confidence=0.5)

rows = []
for f, c, j, classifier in zip(scored, constants, jev_p, llm_p, strict=True):
    fp = owner[id(f)]
    lang, cwe, expectations = meta[fp]
    expected = expectations.get(f.line)
    rows.append({
        "file": Path(fp).name,
        "lang": lang,
        "cwe": cwe,
        "line": f.line,
        "rule": f.rule_id,
        "severity": str(f.severity),
        "snippet": redact(f.code_snippet)[:120],
        "is_tp": bool(expected is not None and _finding_matches(f.rule_id, expected)),
        "constant": round(c, 4),
        "jev": round(j, 4) if j is not None else None,
        "llm": round(classifier, 4) if classifier is not None else None,
    })

out = (Path(args.output_dir) / "findings.json")
write_json(out, rows)
tp = sum(r["is_tp"] for r in rows)
print(f"wrote {len(rows)} rows ({tp} TP / {len(rows)-tp} FP) -> {out}")
print("jev nulls:", sum(1 for r in rows if r["jev"] is None),
      "| llm nulls:", sum(1 for r in rows if r["llm"] is None))
