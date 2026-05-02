"""Rule-based analysis tools for the code-intel MCP server.

Tools:
  Core:     analyze, list_rules, list_packs, install_pack, register_rule
  Testing:  test_rules
  CI:       ci_scan
  Feedback: rule_stats, rule_feedback
  Community: search_community_packs, install_community_pack, validate_pack_tool
  Import:   import_rules

These expose the pluggable rule engine to the connected coding agent,
providing rich, pre-filtered, context-laden findings that enable the
agent to do LLMCheck-quality validation natively.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING

from attocode.code_intel._shared import _get_project_dir, mcp

if TYPE_CHECKING:
    from attocode.code_intel.rules.registry import RuleRegistry

logger = logging.getLogger(__name__)

# Lazy singleton for the rule registry
_registry: RuleRegistry | None = None
_registry_loaded = False
_registry_lock = threading.Lock()


def _get_registry() -> RuleRegistry:
    """Get or create the global rule registry (lazy singleton)."""
    global _registry, _registry_loaded
    # Read-only fast path (safe: both reads are atomic in CPython;
    # the lock below re-checks to avoid races with install_pack resets)
    reg = _registry
    if reg is not None and _registry_loaded:
        return reg
    with _registry_lock:
        if _registry is not None and _registry_loaded:
            return _registry

        from attocode.code_intel.rules.registry import RuleRegistry
        from attocode.code_intel.rules.loader import load_builtin_rules, load_user_rules
        from attocode.code_intel.rules.packs.pack_loader import load_all_packs
        from attocode.code_intel.rules.plugins.plugin_loader import load_all_plugins

        reg = RuleRegistry()
        project_dir = _get_project_dir()

        # Load builtins
        builtins = load_builtin_rules()
        reg.register_many(builtins)

        # Load language packs (builtin + user packs from .attocode/packs/)
        pack_manifests, pack_rules = load_all_packs(project_dir)
        reg.register_many(pack_rules)

        # Load user plugins (from .attocode/plugins/)
        plugin_count = 0
        if project_dir:
            plugin_manifests, plugin_rules = load_all_plugins(project_dir)
            reg.register_many(plugin_rules)
            plugin_count = len(plugin_rules)

        # Load user rules (from .attocode/rules/)
        user_count = 0
        if project_dir:
            user_rules = load_user_rules(project_dir)
            reg.register_many(user_rules)
            user_count = len(user_rules)

        # Assign pointer LAST — fully populated before visible
        _registry = reg
        _registry_loaded = True

        logger.info(
            "Rule registry: %d rules (%d builtin, %d from %d packs, %d plugins, %d user)",
            reg.count,
            len(builtins),
            len(pack_rules),
            len(pack_manifests),
            plugin_count,
            user_count,
        )
    return _registry


def _collect_files(
    files: list[str] | None,
    path: str,
    project_dir: str,
) -> list[str]:
    """Resolve file list from explicit files or path glob.

    All resolved paths are checked for containment within project_dir
    to prevent path traversal attacks via the HTTP API.
    """
    root = os.path.realpath(project_dir)

    def _is_within_project(abs_path: str) -> bool:
        real = os.path.realpath(abs_path)
        return real == root or real.startswith(root + os.sep)

    if files:
        result = []
        for f in files:
            abs_f = os.path.realpath(
                f if os.path.isabs(f) else os.path.join(project_dir, f)
            )
            if not _is_within_project(abs_f):
                logger.warning("Skipping path outside project root: %s", f)
                continue
            if os.path.isfile(abs_f):
                result.append(abs_f)
        return result

    # Walk path (or whole project)
    scan_dir = os.path.realpath(
        os.path.join(project_dir, path) if path else project_dir
    )
    if not _is_within_project(scan_dir):
        logger.warning("Scan path escapes project root: %s", path)
        return []
    if not os.path.isdir(scan_dir):
        return []

    from attocode.code_intel.rules.executor import _EXT_LANG

    _SKIP_DIRS = frozenset({
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        ".tox", "dist", "build", ".next", ".nuxt", ".attocode",
    })

    result = []
    for dirpath, dirnames, filenames in os.walk(scan_dir):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in _EXT_LANG:
                result.append(os.path.join(dirpath, fname))
    return result


def _analyze_impl(
    files: list[str] | None = None,
    path: str = "",
    language: str = "",
    category: str = "",
    severity: str = "",
    pack: str = "",
    min_confidence: float = 0.5,
    max_findings: int = 50,
    project_dir: str = "",
) -> str:
    """Internal implementation — accepts explicit project_dir for service layer."""
    if not project_dir:
        project_dir = _get_project_dir()
    reg = _get_registry()

    # Query applicable rules
    rules = reg.query(
        language=language,
        category=category,
        severity=severity,
        pack=pack,
        min_confidence=min_confidence,
    )

    if not rules:
        return "No rules match the given filters."

    # Collect files
    file_list = _collect_files(files, path, project_dir)
    if not file_list:
        return "No scannable source files found."

    # Execute
    from attocode.code_intel.rules.executor import execute_rules
    from attocode.code_intel.rules.enricher import enrich_findings
    from attocode.code_intel.rules.filters.pipeline import run_pipeline
    from attocode.code_intel.rules.formatter import format_findings

    findings = execute_rules(file_list, rules, project_dir=project_dir)

    # Pre-filter pipeline (dedup, test-file adjustment, confidence threshold)
    findings = run_pipeline(findings, min_confidence=min_confidence)

    # Enrich with context
    enrich_findings(findings, project_dir=project_dir)

    # Format for agent
    return format_findings(findings, max_findings=max_findings)


@mcp.tool()
def analyze(
    files: list[str] | None = None,
    path: str = "",
    language: str = "",
    category: str = "",
    severity: str = "",
    pack: str = "",
    min_confidence: float = 0.5,
    max_findings: int = 50,
) -> str:
    """Run rule-based analysis on source files with rich context for reasoning.

    Returns structured findings with: code context (10 lines before/after),
    antipattern explanations, few-shot examples, suggested fixes, confidence
    scores, and CWE references. Designed to give you everything needed to
    triage, fix, and explain issues.

    Language-specific rules require installing a pack first via install_pack().
    Builtin security rules (secrets, CWE patterns) are always active.

    Args:
        files: Specific file paths to analyze (relative or absolute).
            If empty, scans all source files under path.
        path: Directory to scan (relative to project root). Default: entire project.
        language: Filter rules to this language (e.g. "python", "go").
        category: Filter by category: correctness, suspicious, complexity,
            performance, style, security, deprecated.
        severity: Filter by minimum severity: critical, high, medium, low, info.
        pack: Filter rules from a specific language pack.
        min_confidence: Minimum confidence threshold (0.0-1.0). Default 0.5.
        max_findings: Maximum findings to return. Default 50.
    """
    return _analyze_impl(
        files=files, path=path, language=language, category=category,
        severity=severity, pack=pack, min_confidence=min_confidence,
        max_findings=max_findings,
    )


@mcp.tool()
def list_rules(
    language: str = "",
    category: str = "",
    severity: str = "",
    pack: str = "",
    verbose: bool = False,
) -> str:
    """List available analysis rules with optional filters.

    Shows all registered rules grouped by category, with severity tags.
    Use verbose=True to include rule descriptions.

    Args:
        language: Filter to rules for this language.
        category: Filter by category (correctness, security, performance, etc.).
        severity: Filter by severity level.
        pack: Filter to rules from a specific language pack.
        verbose: Include rule descriptions in output.
    """
    reg = _get_registry()
    rules = reg.query(
        language=language,
        category=category,
        severity=severity,
        pack=pack,
        enabled_only=False,
    )

    from attocode.code_intel.rules.formatter import format_rules_list
    output = format_rules_list(rules, verbose=verbose)

    # Append stats
    stats = reg.stats()
    output += f"\n---\nTotal: {stats['total']} rules | "
    output += f"Enabled: {stats['enabled']} | "
    output += f"Languages: {stats['languages']} | "
    output += f"Packs: {stats['packs']}"

    return output


@mcp.tool()
def list_packs() -> str:
    """List installed and available example language packs.

    Shows installed packs (active, from .attocode/packs/) and available
    example packs that can be installed with install_pack().

    Language packs provide language-specific rules for performance
    antipatterns, correctness bugs, security issues, and idiomatic style.
    They are NOT auto-loaded — install the ones relevant to your project.
    """
    from attocode.code_intel.rules.packs.pack_loader import list_example_packs
    from attocode.code_intel.rules.formatter import format_packs_list

    reg = _get_registry()
    pack_names = reg.packs()

    lines: list[str] = []

    # Installed packs
    if pack_names:
        packs = []
        for name in pack_names:
            pack_rules = reg.query(pack=name, enabled_only=False)
            packs.append({
                "name": name,
                "languages": sorted(set(
                    lang for r in pack_rules for lang in r.languages
                )),
                "rules_count": len(pack_rules),
                "description": "",
            })
        lines.append(format_packs_list(packs))
    else:
        lines.append("## Installed Packs: none\n")
        lines.append("No packs installed. Use `install_pack(name)` to activate one.\n")

    # Available examples
    examples = list_example_packs()
    if examples:
        lines.append("## Available Example Packs\n")
        lines.append("These ship with attocode but are NOT auto-loaded.")
        lines.append("Install with `install_pack(name)` to activate.\n")
        for ex in examples:
            langs = ", ".join(ex.languages)
            lines.append(f"- **{ex.name}** ({langs}) — {ex.description}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def install_pack(name: str) -> str:
    """Install an example language pack into this project.

    Copies the pack from attocode's shipped examples into
    .attocode/packs/<name>/ where it becomes active. You can then
    customize the rules in .attocode/packs/<name>/rules/*.yaml.

    Available packs: go, python, typescript, rust, java.

    Args:
        name: Pack name to install (e.g. "go", "python").
    """
    from attocode.code_intel.rules.packs.pack_loader import install_pack as _install

    project_dir = _get_project_dir()
    result = _install(name, project_dir)

    # Reload registry to pick up new pack
    global _registry, _registry_loaded
    with _registry_lock:
        _registry = None
        _registry_loaded = False

    return result


@mcp.tool()
def register_rule(yaml_content: str) -> str:
    """Register a custom analysis rule at runtime from YAML.

    The rule is added to the registry immediately and will be used
    by subsequent analyze() calls. Rules persist for the session.

    For permanent rules, add YAML files to .attocode/rules/.

    Format:
        id: my-rule-name
        pattern: "regex_pattern"
        message: "What was detected"
        severity: high
        category: performance
        languages: [python]
        recommendation: "How to fix"
        explanation: "Why this matters"
        examples:
          - bad: "slow_code()"
            good: "fast_code()"
            explanation: "Why good is better"

    Args:
        yaml_content: YAML rule definition (single rule or list).
    """
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return "Error: PyYAML not installed. Run: pip install pyyaml"

    from attocode.code_intel.rules.loader import _parse_yaml_rule
    from attocode.code_intel.rules.model import RuleSource

    data = yaml.safe_load(yaml_content)
    if data is None:
        return "Error: Empty YAML content."

    items = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
    if not items:
        return "Error: YAML must be a dict (single rule) or list (multiple rules)."

    reg = _get_registry()
    registered = 0
    errors: list[str] = []

    for i, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"Rule at index {i}: expected dict, got {type(item).__name__}")
            continue
        rule = _parse_yaml_rule(item, source=RuleSource.USER, origin=f"runtime[{i}]")
        if rule is None:
            errors.append(f"Rule at index {i}: invalid (check id, pattern, message, severity)")
        else:
            reg.register(rule)
            registered += 1

    parts = [f"Registered {registered} rule(s)."]
    if errors:
        parts.append("Errors:\n" + "\n".join(f"  - {e}" for e in errors))
    parts.append(f"Registry now has {reg.count} rules total.")

    return "\n".join(parts)


@mcp.tool()
def test_rules(
    fixtures_dir: str = "",
    rule_id: str = "",
) -> str:
    """Run rule tests against fixture files with expect/ok/todoruleid annotations.

    Fixture files should contain inline annotations:
      # expect: rule-id    — rule MUST fire on this line
      # ok: rule-id        — rule must NOT fire on this line (false-positive guard)
      # todoruleid: rule-id — rule SHOULD fire but is known-missing

    Args:
        fixtures_dir: Directory containing annotated test files.
            Default: .attocode/test_fixtures/ or tests/fixtures/rule_violations/.
        rule_id: Optional — only test this specific rule.
    """
    from attocode.code_intel.rules.testing import (
        RuleTestRunner,
        format_test_report,
    )

    reg = _get_registry()
    project_dir = _get_project_dir()

    # Resolve fixtures directory
    if not fixtures_dir:
        import os
        for candidate in [
            os.path.join(project_dir, ".attocode", "test_fixtures"),
            os.path.join(project_dir, "tests", "fixtures", "rule_violations"),
        ]:
            if os.path.isdir(candidate):
                fixtures_dir = candidate
                break
        if not fixtures_dir:
            return "No test fixtures directory found. Provide fixtures_dir or create .attocode/test_fixtures/."

    if rule_id:
        rule = reg.get(rule_id)
        if rule is None:
            return f"Rule '{rule_id}' not found in registry."
        rules = [rule]
    else:
        rules = reg.all_rules(enabled_only=False)

    runner = RuleTestRunner(rules, project_dir=project_dir)
    suite = runner.run_test_suite(fixtures_dir)

    if not suite.file_results:
        return f"No annotated test files found in {fixtures_dir}."

    return format_test_report(suite)


@mcp.tool()
def ci_scan(
    path: str = "",
    language: str = "",
    category: str = "",
    fail_on: str = "high",
    diff_only: bool = False,
    output_format: str = "summary",
) -> str:
    """Run CI-style rule scan with exit-code semantics and SARIF output.

    Designed for CI/CD pipelines: scans source files, applies rules,
    and reports findings with pass/fail status. Supports diff-only mode
    to scan only changed lines since a baseline git ref.

    Args:
        path: Directory to scan (relative to project root). Default: entire project.
        language: Filter rules to this language.
        category: Filter by category (correctness, security, etc.).
        fail_on: Minimum severity to trigger failure: critical, high, medium, low.
        diff_only: Only report findings on lines changed since baseline.
        output_format: Output format — "summary" (human-readable),
            "sarif" (SARIF JSON), "annotations" (GitHub Actions format).
    """
    from attocode.code_intel.rules.ci import (
        CIConfig, CIRunner, format_ci_summary, format_github_annotations,
    )
    from attocode.code_intel.rules.sarif import findings_to_sarif, sarif_to_json
    from attocode.code_intel.rules.model import RuleSeverity

    project_dir = _get_project_dir()

    config = CIConfig()
    sev_str = fail_on.lower()
    if sev_str in {s.value for s in RuleSeverity}:
        config.fail_on = RuleSeverity(sev_str)

    runner = CIRunner(project_dir, config=config)
    result = runner.run(path=path, language=language, category=category, diff_only=diff_only)

    if output_format == "sarif":
        sarif = findings_to_sarif(result.findings)
        return sarif_to_json(sarif)
    elif output_format == "annotations":
        annotations = format_github_annotations(result.findings)
        status = "PASS" if result.passed else "FAIL"
        return f"Status: {status}\n{annotations}"
    else:
        return format_ci_summary(result)


@mcp.tool()
def rule_stats(rule_id: str = "") -> str:
    """Show profiling stats and confidence calibration for rules.

    Shows execution time, match count, true/false positive feedback,
    and calibrated confidence from persistent feedback data.

    Args:
        rule_id: Specific rule ID, or empty for all rules with feedback.
    """
    from attocode.code_intel.rules.profiling import (
        FeedbackStore, RuleStats, format_rule_stats,
    )

    project_dir = _get_project_dir()
    store = FeedbackStore(project_dir)
    feedback = store.all_feedback()

    if not feedback:
        return "No rule feedback recorded yet. Use rule_feedback() to record TP/FP observations."

    # Build stats from feedback data
    stats: dict[str, RuleStats] = {}
    for rid, fb in feedback.items():
        if rule_id and rid != rule_id:
            continue
        s = RuleStats(
            rule_id=rid,
            true_positives=fb.get("tp", 0),
            false_positives=fb.get("fp", 0),
        )
        stats[rid] = s

    if rule_id and not stats:
        return f"No feedback for rule '{rule_id}'."

    return format_rule_stats(stats, feedback)


@mcp.tool()
def rule_feedback(
    rule_id: str,
    is_true_positive: bool,
    finding_line: int = 0,
) -> str:
    """Record whether a finding was a true or false positive.

    This feedback is used to calibrate rule confidence scores over time.
    After 5+ observations, a calibrated confidence replaces the rule's
    default confidence for more accurate triage.

    Args:
        rule_id: The rule that produced the finding.
        is_true_positive: True if the finding was a real issue, False if it was a false positive.
        finding_line: Optional line number for context (not used in calibration).
    """
    from attocode.code_intel.rules.profiling import FeedbackStore

    project_dir = _get_project_dir()
    store = FeedbackStore(project_dir)
    store.record(rule_id, is_true_positive=is_true_positive)

    fb = store.get_feedback(rule_id)
    tp, fp = fb.get("tp", 0), fb.get("fp", 0)
    total = tp + fp
    cal = store.get_calibrated_confidence(rule_id)

    parts = [f"Recorded {'TP' if is_true_positive else 'FP'} for `{rule_id}`."]
    parts.append(f"Total: {tp} TP, {fp} FP ({total} observations)")
    if cal is not None:
        parts.append(f"Calibrated confidence: {cal:.1%}")
    else:
        remaining = 5 - total
        parts.append(f"Need {remaining} more observation(s) for calibration.")

    return "\n".join(parts)


@mcp.tool()
def search_community_packs(
    query: str = "",
    language: str = "",
) -> str:
    """Search the community rule pack registry.

    Finds rule packs shared by the community, filterable by keyword
    and language. Install found packs with install_community_pack().

    Args:
        query: Search by name, description, or tags.
        language: Filter to packs supporting this language.
    """
    from attocode.code_intel.rules.marketplace import search_packs, format_registry_search

    entries = search_packs(query=query, language=language)
    return format_registry_search(entries)


@mcp.tool()
def install_community_pack(
    name: str,
    url: str = "",
) -> str:
    """Install a community rule pack from a Git repository.

    Downloads and validates the pack, then installs to .attocode/packs/.

    Args:
        name: Pack name (used as directory name).
        url: Git clone URL. If empty, looks up from community registry.
    """
    from attocode.code_intel.rules.marketplace import (
        install_remote_pack,
        search_packs,
    )

    project_dir = _get_project_dir()
    if not project_dir:
        return "Error: No project directory detected. Open a project first."

    if not url:
        entries = search_packs(query=name)
        matching = [e for e in entries if e.name == name]
        if matching:
            url = matching[0].url
        else:
            return f"Pack '{name}' not found in registry. Provide a URL directly."

    result = install_remote_pack(url, project_dir, pack_name=name)

    # Reload registry
    global _registry, _registry_loaded
    with _registry_lock:
        _registry = None
        _registry_loaded = False

    return result


@mcp.tool()
def validate_pack_tool(pack_path: str = "") -> str:
    """Validate a rule pack for correctness before publishing.

    Checks manifest, rule syntax, regex compilation, and inline tests.

    Args:
        pack_path: Path to pack directory. Default: validates all installed packs.
    """
    from attocode.code_intel.rules.marketplace import validate_pack, prepare_pack_for_publish

    project_dir = _get_project_dir()
    if not project_dir and not pack_path:
        return "Error: No project directory detected. Provide pack_path or open a project."

    if pack_path:
        import os
        if not os.path.isabs(pack_path):
            pack_path = os.path.join(project_dir, pack_path)
        return prepare_pack_for_publish(pack_path)

    import os
    packs_dir = os.path.join(project_dir, ".attocode", "packs")
    if not os.path.isdir(packs_dir):
        return "No packs installed (.attocode/packs/ not found)."

    results: list[str] = []
    for entry in sorted(os.listdir(packs_dir)):
        pack_dir = os.path.join(packs_dir, entry)
        if os.path.isdir(pack_dir):
            errors = validate_pack(pack_dir)
            status = "PASS" if not errors else "FAIL"
            results.append(f"**{entry}**: {status}")
            if errors:
                for e in errors:
                    results.append(f"  - {e}")

    return "\n".join(results) if results else "No packs found."


@mcp.tool()
def import_rules(
    source_format: str,
    content: str,
) -> str:
    """Import rules from another tool's format into attocode YAML.

    Converts rules from Semgrep or other formats to attocode YAML.
    Output can be saved to .attocode/rules/ or registered via register_rule().

    Supported formats: semgrep

    Args:
        source_format: Source format — "semgrep".
        content: YAML content in the source format.
    """
    if source_format.lower() == "semgrep":
        from attocode.code_intel.rules.importers.semgrep import convert_semgrep_to_yaml
        return convert_semgrep_to_yaml(content)
    else:
        return f"Unsupported format '{source_format}'. Supported: semgrep"
