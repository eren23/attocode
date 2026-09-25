"""Reconcile the saved sample, inventory current source, and optionally score it.

Example: python -m eval.rule_accuracy.demo.scan --score --verify-tool
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from attocode_intel import confidence
from attocode_intel.confidence import jev, settings
from attocode_intel.confidence.redact import redact
from attocode_intel.rules.enricher import enrich_findings
from attocode_intel.rules.executor import execute_rules
from attocode_intel.rules.loader import load_builtin_rules
from attocode_intel.rules.model import EnrichedFinding, RuleCategory, RuleSeverity
from attocode_intel.rules.packs.pack_loader import list_example_packs, load_pack

HERE = Path(__file__).parent


def clean(value):
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean(item) for item in value]
    return redact(value) if isinstance(value, str) else value


def write_json(path, value):
    path.write_text(json.dumps(clean(value), indent=2) + "\n", encoding="utf-8")


def reconcile(root, row):
    path = root / row["file"]
    if not path.is_file():
        return None, "missing_file"
    lines = path.read_text(encoding="utf-8").splitlines()
    first = row["snippet"].splitlines()[0].strip()
    candidates = [i + 1 for i, line in enumerate(lines)
                  if redact(line).strip() == first or redact(line).strip()[:200] == first]
    if row["line"] in candidates:
        return row["line"], "same_match"
    if len(candidates) == 1:
        return candidates[0], "relocated_match"
    return None, "ambiguous_or_changed"


async def verify_tool(root, output):
    """Use a fresh gateway running the current source and actual local configuration."""
    from attocode_intel.gateway import OperationGateway

    gateway = OperationGateway(str(root), "full", watch=False)
    args = {"workspace": str(root), "files": [
        "packages/code-intel/src/attocode_intel/tools/maintenance_tools.py"
    ], "max_tokens": 8000}
    try:
        live = await gateway.execute("analyze", args)
        write_json(output / "tool-live.json", live.model_dump(mode="json", exclude_none=True))
        live_text = "\n".join(c.text for c in live.content if c.type == "text")
        counts = re.search(r"(\d+)/(\d+) scored", live_text)
        if live.isError or "Confidence: jev (live)" not in live_text or not counts or int(counts[1]) == 0:
            raise RuntimeError("Local tool did not report live jev scoring")
        with patch.object(jev, "estimate", side_effect=RuntimeError("simulated outage")):
            outage = await gateway.execute("analyze", args)
        write_json(output / "tool-outage.json", outage.model_dump(mode="json", exclude_none=True))
        outage_text = "\n".join(c.text for c in outage.content if c.type == "text")
        if outage.isError or f"0/{counts[2]} scored" not in outage_text or f"{counts[2]} fallback" not in outage_text:
            raise RuntimeError("Outage diagnostic missing")
    finally:
        await gateway.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--score", action="store_true", help="Make paid jev calls for the saved sample")
    parser.add_argument("--verify-tool", action="store_true", help="Also run a live MCP analysis and outage simulation")
    args = parser.parse_args()
    root = args.project.resolve()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = args.output_dir or root / ".attocode/reports/jev" / stamp
    output.mkdir(parents=True, exist_ok=False)
    saved = json.loads((HERE / "data/real.json").read_text())
    decisions = json.loads((HERE / "triage.json").read_text())
    results, findings = [], []
    for i, (row, decision) in enumerate(zip(saved, decisions, strict=True)):
        line, reconciliation = reconcile(root, row)
        result = {**decision, "file": row["file"], "original_line": row["line"],
                  "line": line, "rule": row["rule"], "reconciliation": reconciliation,
                  "historical": {"constant": row["c"], "jev": row["j"], "classifier": row["m"]},
                  "id": hashlib.sha256(f"{row['file']}:{row['rule']}:{row['line']}".encode()).hexdigest()[:20]}
        if line is None:
            result.update(status="unresolved", rationale="Saved match could not be uniquely reconciled; inspect current source.")
        else:
            source = (root / row["file"]).read_text(encoding="utf-8")
            result["source_sha256"] = hashlib.sha256(source.encode()).hexdigest()
            finding = EnrichedFinding(rule_id=row["rule"], rule_name=row["rule"],
                severity=RuleSeverity(row["sev"]), category=RuleCategory.SECURITY,
                confidence=row["c"], file=row["file"], line=line,
                description=row["desc"], code_snippet=source.splitlines()[line - 1])
            enrich_findings([finding], project_dir=str(root))
            result["current_context"] = {"before": finding.context_before,
                                         "line": finding.code_snippet, "after": finding.context_after}
            findings.append((i, finding))
        results.append(result)
    if args.score:
        with settings.workspace(str(root)):
            if confidence.scorer_name() != "jev" or confidence.mode() != "live":
                raise RuntimeError("Configure local confidence scorer=jev, mode=live first")
            for offset in range(0, len(findings), confidence.MAX_CALLS):
                batch = findings[offset:offset + confidence.MAX_CALLS]
                confidence.score([f for _, f in batch], min_confidence=.5)
                for (index, _), scored in zip(batch, confidence.last_report()["findings"], strict=True):
                    results[index]["current_scoring"] = scored
                print(f"Scored batch {offset // confidence.MAX_CALLS + 1}: {confidence.summary()}", flush=True)
    write_json(output / "findings.json", results)

    rules = load_builtin_rules()
    for manifest in list_example_packs():
        rules.extend(load_pack(manifest))
    files = sorted((root / "packages/code-intel/src/attocode_intel").rglob("*.py"))
    raw = execute_rules([str(p) for p in files], rules, project_dir=str(root))
    inventory = [{"file": f.file, "line": f.line, "rule": f.rule_id,
                  "confidence": f.confidence, "description": f.description,
                  "status": "unreviewed"} for f in raw]
    write_json(output / "inventory.json", inventory)
    def git(*cmd):
        return subprocess.check_output(["git", *cmd], cwd=root, text=True).strip()
    meta = {"timestamp": stamp, "revision": git("rev-parse", "HEAD"),
            "worktree_changes": git("status", "--short"), "sample": len(saved),
            "reviewed": len(results), "dispositions": dict(Counter(r["status"] for r in results)),
            "raw_inventory_count": len(raw), "source_files": len(files),
            "raw_inventory_by_rule": dict(Counter(f.rule_id for f in raw)),
            "scored": sum(r.get("current_scoring", {}).get("status") == "estimated" for r in results),
            "coverage_note": "The 82-row stratified sample is reviewed; the broader raw inventory is not. Counts are not a security audit or a recall estimate."}
    write_json(output / "manifest.json", meta)
    lines = ["# Local jev findings review", "", f"Revision: `{meta['revision']}`; run: {stamp}.", "",
             f"Reviewed {len(results)} historical examples: {dict(Counter(r['status'] for r in results))}.",
             f"Current inventory: {len(raw)} raw matches across {len(files)} Python source files. Additional matches remain unreviewed.",
             "", "Model scores are triage signals. Dispositions below come from source and caller review.", "",
             "## Prioritized follow-up", "",
             "- P2: decide a restricted CORS policy for hosted/service deployments; wildcard mode already disables credentials.",
             "- P2: assess persistent development-account exposure; replace or gate the fixed bootstrap credential.",
             "- P2: improve detector syntax/context handling, especially strings, call-name boundaries and CLI output.",
             "- P2: test a rule-focused classifier prompt; preserve abstentions and redaction. Do not treat its old security-only scores as generic rule confidence.",
             "- P2: correct calibration metrics in a separate change: the archived ECE implementation uses bin midpoints, not mean predicted confidence. Preserve the historical numbers as a labeled proxy.",
             "- P3: measure the function-local tomllib import before treating it as a performance defect.",
             "- P3: cap descriptions in general tool output; retain full evidence in structured records.",
             "", "## Every saved example", ""]
    for r in results:
        lines.extend([f"### {r['sample_index'] + 1:02d}. {r['status']} — {r['rule']}", "",
            f"`{r['file']}:{r['line'] or r['original_line']}` · {r['priority']} · {r['reconciliation']}", "",
            r["rationale"], "", "Evidence: " + ", ".join(f"`{x}`" for x in r["evidence"]), "",
            "Follow-up: " + r["fix"], "", "Acceptance: " + r["acceptance"], ""])
    (output / "REPORT.md").write_text(redact("\n".join(lines)), encoding="utf-8")
    print(json.dumps(meta, indent=2), flush=True)
    if args.verify_tool:
        asyncio.run(verify_tool(root, output))
    print(f"Report: {output / 'REPORT.md'}", flush=True)


if __name__ == "__main__":
    main()
