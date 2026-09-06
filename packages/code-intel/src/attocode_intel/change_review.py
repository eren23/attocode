"""Compose findings as data so incomplete passes cannot become a clean review."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path


def review(service, files, mode="full"):
    from attocode_intel.tools.composite_tools import _git_modified_files

    files = files if files is not None else _git_modified_files(service.project_dir)
    if mode not in {"quick", "full"}:
        raise ValueError("mode must be quick or full")
    root = Path(service.project_dir)
    selected = {str((root / path).resolve().relative_to(root)) for path in files}
    findings, passes = [], []
    if not selected:
        return {
            "files": [],
            "findings": [],
            "passes": [],
            "complete": False,
            "assessment": "No files selected; review did not run.",
        }
    try:
        report = service.security_scan_data(mode="full")
        for finding in report["findings"]:
            path = str((root / finding["file_path"]).resolve().relative_to(root))
            if path in selected:
                findings.append({**finding, "file_path": path, "pass": "security"})
        passes.append({"name": "security", "status": "completed"})
    except Exception as exc:
        passes.append({"name": "security", "status": "failed", "error": str(exc)})
    if mode == "full":
        try:
            from attocode_intel.rules.enricher import enrich_findings
            from attocode_intel.rules.executor import execute_rules
            from attocode_intel.rules.filters.pipeline import run_pipeline
            from attocode_intel.tools.rule_tools import _collect_files, _get_registry

            rules = _get_registry().query(min_confidence=0.5)
            scanned = _collect_files(sorted(selected), "", service.project_dir)
            result = run_pipeline(
                execute_rules(scanned, rules, project_dir=service.project_dir), min_confidence=0.5
            )
            enrich_findings(result, project_dir=service.project_dir)
            findings.extend(
                {**asdict(finding), "file_path": finding.file, "pass": "rules"}
                for finding in result
            )
            passes.append(
                {
                    "name": "rules",
                    "status": "completed" if rules and scanned else "unavailable",
                    "files_scanned": len(scanned),
                }
            )
        except Exception as exc:
            passes.append({"name": "rules", "status": "failed", "error": str(exc)})
    complete = all(item["status"] == "completed" for item in passes)
    return {
        "files": sorted(selected),
        "findings": findings,
        "passes": passes,
        "complete": complete,
        "assessment": f"{len(findings)} findings from completed checks."
        if complete
        else "Review incomplete. Inspect the failed or unavailable passes.",
    }
