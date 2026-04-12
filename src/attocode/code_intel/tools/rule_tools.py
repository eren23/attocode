"""Rule-based analysis tools for the code-intel MCP server.

Tools: analyze, list_rules, list_packs, register_rule.

These expose the pluggable rule engine to the connected coding agent,
providing rich, pre-filtered, context-laden findings that enable the
agent to do LLMCheck-quality validation natively.
"""

from __future__ import annotations

import logging
import os
import threading

from attocode.code_intel._shared import _get_project_dir, mcp

logger = logging.getLogger(__name__)

# Lazy singleton for the rule registry
_registry = None
_registry_loaded = False
_registry_lock = threading.Lock()


def _get_registry():
    """Get or create the global rule registry (lazy singleton)."""
    global _registry, _registry_loaded
    if _registry is not None and _registry_loaded:
        return _registry
    with _registry_lock:
        # Double-check under lock
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
    """Resolve file list from explicit files or path glob."""
    if files:
        result = []
        for f in files:
            abs_f = f if os.path.isabs(f) else os.path.join(project_dir, f)
            if os.path.isfile(abs_f):
                result.append(abs_f)
        return result

    # Walk path (or whole project)
    scan_dir = os.path.join(project_dir, path) if path else project_dir
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
