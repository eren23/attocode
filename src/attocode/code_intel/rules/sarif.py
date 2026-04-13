"""SARIF v2.1.0 output formatter for rule findings.

Produces Static Analysis Results Interchange Format (SARIF) JSON
compatible with GitHub Code Scanning, VS Code SARIF Viewer, and
Azure DevOps.

Reference: https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html
"""

from __future__ import annotations

import json
from typing import Any

from attocode.code_intel.rules.model import EnrichedFinding, RuleSeverity

# SARIF severity mapping
_LEVEL_MAP: dict[str, str] = {
    RuleSeverity.CRITICAL: "error",
    RuleSeverity.HIGH: "error",
    RuleSeverity.MEDIUM: "warning",
    RuleSeverity.LOW: "note",
    RuleSeverity.INFO: "note",
}


def _build_rule_descriptor(finding: EnrichedFinding) -> dict[str, Any]:
    """Build a SARIF reportingDescriptor for a rule."""
    descriptor: dict[str, Any] = {
        "id": finding.rule_id,
        "shortDescription": {"text": finding.rule_name},
    }
    if finding.description:
        descriptor["fullDescription"] = {"text": finding.description}
    if finding.explanation:
        descriptor["help"] = {
            "text": finding.explanation,
            "markdown": finding.explanation,
        }
    if finding.recommendation:
        descriptor.setdefault("help", {})
        help_md = descriptor["help"].get("markdown", "")
        if help_md:
            help_md += "\n\n**Recommendation:** " + finding.recommendation
        else:
            help_md = "**Recommendation:** " + finding.recommendation
        descriptor["help"]["markdown"] = help_md
        descriptor["help"]["text"] = descriptor["help"].get("text", "") + " " + finding.recommendation

    # CWE relationship
    if finding.cwe:
        cwe_id = finding.cwe.replace("CWE-", "")
        descriptor["relationships"] = [{
            "target": {
                "id": finding.cwe,
                "guid": f"cwe-{cwe_id}",
                "toolComponent": {"name": "CWE"},
            },
            "kinds": ["superset"],
        }]

    # Tags
    tags = list(finding.tags)
    if finding.cwe:
        tags.append(f"external/cwe/{finding.cwe.lower()}")
    tags.append(f"security-severity/{finding.severity}")
    if tags:
        descriptor["properties"] = {"tags": tags}

    # Few-shot examples in property bag
    if finding.examples:
        descriptor.setdefault("properties", {})["fewShotExamples"] = [
            {
                "bad": ex.bad_code,
                "good": ex.good_code,
                "explanation": ex.explanation,
            }
            for ex in finding.examples
        ]

    return descriptor


def _build_result(finding: EnrichedFinding) -> dict[str, Any]:
    """Build a SARIF result object from an EnrichedFinding."""
    result: dict[str, Any] = {
        "ruleId": finding.rule_id,
        "level": _LEVEL_MAP.get(finding.severity, "warning"),
        "message": {"text": finding.description},
        "locations": [{
            "physicalLocation": {
                "artifactLocation": {
                    "uri": finding.file.replace("\\", "/"),
                    "uriBaseId": "%SRCROOT%",
                },
                "region": {
                    "startLine": finding.line,
                    "startColumn": 1,
                    "snippet": {"text": finding.code_snippet},
                },
            },
        }],
    }

    # Function scope
    if finding.function_name:
        result["locations"][0]["logicalLocations"] = [{
            "name": finding.function_name,
            "kind": "function",
        }]

    # Confidence + captures in property bag
    props: dict[str, Any] = {"confidence": finding.confidence}
    if finding.captures:
        props["captures"] = finding.captures
    if finding.suggested_fix:
        props["suggestedFix"] = finding.suggested_fix
    result["properties"] = props

    # Related findings as relatedLocations
    if finding.related_findings:
        result["relatedLocations"] = [
            {"id": i, "message": {"text": rid}}
            for i, rid in enumerate(finding.related_findings)
        ]

    return result


def findings_to_sarif(
    findings: list[EnrichedFinding],
    *,
    tool_name: str = "attocode-code-intel",
    tool_version: str = "",
) -> dict[str, Any]:
    """Convert a list of EnrichedFinding into a SARIF v2.1.0 document.

    Args:
        findings: Analysis findings to convert.
        tool_name: Name of the analysis tool.
        tool_version: Tool version string.

    Returns:
        SARIF JSON-compatible dict.
    """
    # Deduplicate rules by rule_id
    rules_by_id: dict[str, dict[str, Any]] = {}
    for f in findings:
        if f.rule_id not in rules_by_id:
            rules_by_id[f.rule_id] = _build_rule_descriptor(f)

    # Build rule index for ruleIndex references
    rule_index: dict[str, int] = {}
    rules_list = []
    for i, (rid, desc) in enumerate(rules_by_id.items()):
        rule_index[rid] = i
        rules_list.append(desc)

    # Build results
    results = []
    for f in findings:
        result = _build_result(f)
        result["ruleIndex"] = rule_index[f.rule_id]
        results.append(result)

    sarif: dict[str, Any] = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": tool_name,
                    "version": tool_version,
                    "informationUri": "https://github.com/attocode/code-intel",
                    "rules": rules_list,
                },
            },
            "results": results,
        }],
    }

    return sarif


def sarif_to_json(sarif: dict[str, Any], *, indent: int = 2) -> str:
    """Serialize a SARIF document to JSON string."""
    return json.dumps(sarif, indent=indent, ensure_ascii=False)
