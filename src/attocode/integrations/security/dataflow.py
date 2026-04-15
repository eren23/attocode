"""Lightweight intra-procedural data flow analysis.

Tracks taint from sources (user input, request parameters) through
assignments and function calls to sinks (SQL execution, shell commands,
HTML output) within individual functions. Uses tree-sitter ASTs for
Python and JavaScript/TypeScript.

This is NOT a full compiler-grade taint tracker. It provides best-effort
detection of common vulnerability patterns (CWE-89, CWE-78, CWE-79,
CWE-22, CWE-918) without requiring compilation or type information.

Limitations:
- Intra-procedural only (does not follow function calls across files)
- No alias analysis (reassignment through containers not tracked)
- No type inference (relies on naming conventions and API patterns)
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Source / Sink definitions
# ---------------------------------------------------------------------------

@dataclass(slots=True, frozen=True)
class TaintSource:
    """A source of tainted (user-controlled) data."""
    name: str
    pattern: re.Pattern[str]
    language: str  # "python", "javascript", or "" for all


@dataclass(slots=True, frozen=True)
class TaintSink:
    """A dangerous function that should not receive tainted data."""
    name: str
    pattern: re.Pattern[str]
    cwe: str
    message: str
    language: str


@dataclass(slots=True)
class DataFlowFinding:
    """A taint flow from source to sink within a function."""
    file_path: str
    function_name: str
    source_line: int
    source_desc: str
    sink_line: int
    sink_desc: str
    tainted_var: str
    cwe: str
    message: str
    severity: str = "high"


@dataclass(slots=True)
class DataFlowReport:
    """Results of data flow analysis."""
    findings: list[DataFlowFinding]
    functions_analyzed: int
    files_analyzed: int
    scan_time_ms: float = 0.0


# ---------------------------------------------------------------------------
# Python sources and sinks
# ---------------------------------------------------------------------------

_PYTHON_SOURCES: list[TaintSource] = [
    TaintSource("request_param", re.compile(
        r"""\b(?:request\.(?:args|form|json|data|values|files|headers|cookies|GET|POST)|"""
        r"""flask\.request\.\w+|"""
        r"""self\.request\.\w+)"""
    ), "python"),
    TaintSource("input_builtin", re.compile(r"""\binput\s*\("""), "python"),
    TaintSource("sys_argv", re.compile(r"""\bsys\.argv\b"""), "python"),
    TaintSource("environ_get", re.compile(r"""\bos\.environ\b"""), "python"),
    TaintSource("query_param", re.compile(
        r"""\b(?:params|query_params|request_data)\b"""
    ), "python"),
]

_PYTHON_SINKS: list[TaintSink] = [
    TaintSink("sql_execute", re.compile(
        r"""\b(?:cursor\.execute|\.execute|\.executemany|\.raw)\s*\("""
    ), "CWE-89", "SQL injection: tainted data reaches SQL execution", "python"),
    TaintSink("os_system", re.compile(
        r"""\b(?:os\.system|os\.popen|subprocess\.(?:call|run|Popen|check_output|check_call))\s*\("""
    ), "CWE-78", "Command injection: tainted data reaches shell execution", "python"),
    TaintSink("open_file", re.compile(
        r"""\bopen\s*\("""
    ), "CWE-22", "Path traversal: tainted data used in file path", "python"),
    TaintSink("url_request", re.compile(
        r"""\b(?:requests\.(?:get|post|put|delete|patch|head)|urllib\.request\.urlopen|httpx\.(?:get|post))\s*\("""
    ), "CWE-918", "SSRF: tainted data used in URL construction", "python"),
    TaintSink("html_output", re.compile(
        r"""\b(?:render_template_string|Markup|mark_safe|SafeString)\s*\("""
    ), "CWE-79", "XSS: tainted data rendered as HTML without escaping", "python"),
]

# ---------------------------------------------------------------------------
# JavaScript/TypeScript sources and sinks
# ---------------------------------------------------------------------------

_JS_SOURCES: list[TaintSource] = [
    TaintSource("req_param", re.compile(
        r"""\b(?:req\.(?:body|params|query|headers|cookies)|"""
        r"""request\.(?:body|params|query|headers))\b"""
    ), "javascript"),
    TaintSource("url_search_params", re.compile(
        r"""\b(?:URLSearchParams|location\.search|location\.hash|window\.location)\b"""
    ), "javascript"),
    TaintSource("document_input", re.compile(
        r"""\b(?:document\.getElementById|document\.querySelector|\.value)\b"""
    ), "javascript"),
]

_JS_SINKS: list[TaintSink] = [
    TaintSink("sql_query", re.compile(
        r"""\b(?:\.query|\.execute|\.run)\s*\("""
    ), "CWE-89", "SQL injection: tainted data in database query", "javascript"),
    TaintSink("exec_cmd", re.compile(
        r"""\b(?:exec|execSync|spawn|spawnSync|execFile)\s*\("""
    ), "CWE-78", "Command injection: tainted data in shell command", "javascript"),
    TaintSink("inner_html", re.compile(
        r"""\.innerHTML\s*="""
    ), "CWE-79", "XSS: tainted data assigned to innerHTML", "javascript"),
    TaintSink("redirect", re.compile(
        r"""\b(?:res\.redirect|location\.href|window\.location)\s*="""
    ), "CWE-601", "Open redirect: tainted data in redirect URL", "javascript"),
    TaintSink("fs_access", re.compile(
        r"""\b(?:fs\.(?:readFile|writeFile|readFileSync|writeFileSync|createReadStream|unlink)|"""
        r"""path\.(?:join|resolve))\s*\("""
    ), "CWE-22", "Path traversal: tainted data in file system path", "javascript"),
]


# ---------------------------------------------------------------------------
# Taint analysis engine
# ---------------------------------------------------------------------------

_ASSIGNMENT_RE = re.compile(
    r"""^\s*(?:(?:const|let|var)\s+)?(\w+)\s*=\s*(.+)$"""
)

_AUGMENTED_ASSIGN_RE = re.compile(
    r"""^\s*(?:(?:const|let|var)\s+)?(\w+)\s*(?:\+=|\|=|\.append\(|\.extend\(|\.update\()(.+)"""
)

_FSTRING_VAR_RE = re.compile(r"""\{(\w+)""")
_FORMAT_VAR_RE = re.compile(r"""\.format\s*\([^)]*?(\w+)""")
_PERCENT_VAR_RE = re.compile(r"""%\s*(?:\((\w+)\)|(\w+))""")
_TEMPLATE_VAR_RE = re.compile(r"""\$\{(\w+)\}""")
_CONCAT_VAR_RE = re.compile(r"""\+\s*(\w+)""")


def _extract_variables_from_expr(expr: str) -> set[str]:
    """Extract variable names referenced in an expression."""
    variables: set[str] = set()

    # f-string interpolation: f"...{var}..."
    variables.update(_FSTRING_VAR_RE.findall(expr))

    # .format() calls
    variables.update(_FORMAT_VAR_RE.findall(expr))

    # %-formatting
    for groups in _PERCENT_VAR_RE.findall(expr):
        variables.update(g for g in groups if g)

    # Template literal interpolation: `...${var}...`
    variables.update(_TEMPLATE_VAR_RE.findall(expr))

    # String concatenation: "..." + var
    variables.update(_CONCAT_VAR_RE.findall(expr))

    # Direct variable reference (simple identifier on RHS)
    tokens = re.findall(r'\b([a-zA-Z_]\w*)\b', expr)
    variables.update(tokens)

    # Filter out keywords and builtins
    _KEYWORDS = frozenset({
        "True", "False", "None", "true", "false", "null", "undefined",
        "if", "else", "for", "while", "return", "import", "from",
        "def", "class", "function", "const", "let", "var", "new",
        "not", "and", "or", "in", "is", "as", "with", "try", "except",
        "finally", "raise", "yield", "async", "await", "self", "cls",
        "this", "super", "typeof", "instanceof",
    })
    return variables - _KEYWORDS


def analyze_function_taint(
    lines: list[str],
    sources: list[TaintSource],
    sinks: list[TaintSink],
    function_name: str,
    start_line: int,
) -> list[tuple[str, int, str, int, str, str, str]]:
    """Analyze a single function body for source-to-sink taint flows.

    Returns list of (tainted_var, source_line, source_desc, sink_line, sink_desc, cwe, message).
    """
    # Phase 1: Identify tainted variables (variables assigned from sources)
    tainted: dict[str, tuple[int, str]] = {}  # var_name → (line_no, source_desc)

    for i, line in enumerate(lines):
        line_no = start_line + i
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue

        # Check if line contains a source
        for source in sources:
            if source.pattern.search(line):
                # Find the variable being assigned from this source
                m = _ASSIGNMENT_RE.match(line)
                if m:
                    var_name = m.group(1)
                    tainted[var_name] = (line_no, source.name)
                else:
                    # Source used directly (e.g., as function parameter)
                    # Track any variable on the left side of any assignment-like pattern
                    am = _AUGMENTED_ASSIGN_RE.match(line)
                    if am:
                        tainted[am.group(1)] = (line_no, source.name)

    if not tainted:
        return []

    # Phase 2: Propagate taint through assignments
    # Simple forward propagation: if `b = f(a)` and `a` is tainted, `b` is tainted
    changed = True
    max_iterations = 10
    iteration = 0
    while changed and iteration < max_iterations:
        changed = False
        iteration += 1
        for i, line in enumerate(lines):
            m = _ASSIGNMENT_RE.match(line)
            if not m:
                continue
            var_name = m.group(1)
            if var_name in tainted:
                continue  # already tainted
            rhs = m.group(2)
            rhs_vars = _extract_variables_from_expr(rhs)
            for rv in rhs_vars:
                if rv in tainted:
                    tainted[var_name] = (start_line + i, f"propagated from {rv}")
                    changed = True
                    break

    # Phase 3: Check if tainted variables reach sinks
    findings: list[tuple[str, int, str, int, str, str, str]] = []

    for i, line in enumerate(lines):
        line_no = start_line + i
        for sink in sinks:
            if not sink.pattern.search(line):
                continue
            # Check if any tainted variable appears in this sink call
            line_vars = _extract_variables_from_expr(line)
            for var in line_vars:
                if var in tainted:
                    source_line, source_desc = tainted[var]
                    findings.append((
                        var, source_line, source_desc,
                        line_no, sink.name, sink.cwe, sink.message,
                    ))
                    break  # one finding per sink line

    return findings


# ---------------------------------------------------------------------------
# File-level analysis
# ---------------------------------------------------------------------------

def _extract_function_bodies(content: str, language: str) -> list[tuple[str, int, int]]:
    """Extract function name, start line, end line from source content.

    Uses simple regex-based extraction (not tree-sitter) for portability.
    Returns list of (function_name, start_line, end_line) 1-indexed.
    """
    functions: list[tuple[str, int, int]] = []
    lines = content.splitlines()

    if language == "python":
        func_re = re.compile(r"""^(\s*)def\s+(\w+)\s*\(""")
        in_func = False
        func_name = ""
        func_start = 0
        func_indent = 0

        for i, line in enumerate(lines, 1):
            m = func_re.match(line)
            if m:
                if in_func:
                    functions.append((func_name, func_start, i - 1))
                func_indent = len(m.group(1))
                func_name = m.group(2)
                func_start = i
                in_func = True
            elif in_func and line.strip() and not line.startswith(" " * (func_indent + 1)) and not line.strip().startswith("#"):
                # Dedented line = end of function
                if not line[0].isspace() or (len(line) - len(line.lstrip())) <= func_indent:
                    functions.append((func_name, func_start, i - 1))
                    in_func = False

        if in_func:
            functions.append((func_name, func_start, len(lines)))

    elif language in ("javascript", "typescript"):
        # Match: function name(...), const name = (...) =>, async function name(...)
        func_re = re.compile(
            r"""(?:(?:async\s+)?function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>)"""
        )
        # Simple brace-counting for JS function boundaries
        for i, line in enumerate(lines, 1):
            m = func_re.search(line)
            if m:
                func_name = m.group(1) or m.group(2)
                # Find the end by counting braces
                brace_count = 0
                started = False
                end_line = i
                for j in range(i - 1, len(lines)):
                    for ch in lines[j]:
                        if ch == "{":
                            brace_count += 1
                            started = True
                        elif ch == "}":
                            brace_count -= 1
                    if started and brace_count <= 0:
                        end_line = j + 1
                        break
                else:
                    end_line = len(lines)
                functions.append((func_name, i, end_line))

    return functions


def analyze_file(
    file_path: str,
    language: str = "",
) -> list[DataFlowFinding]:
    """Analyze a single file for data flow vulnerabilities.

    Args:
        file_path: Absolute path to the source file.
        language: Language hint (auto-detected from extension if empty).

    Returns:
        List of DataFlowFinding instances.
    """
    if not language:
        ext = os.path.splitext(file_path)[1].lower()
        lang_map = {
            ".py": "python", ".pyi": "python",
            ".js": "javascript", ".jsx": "javascript",
            ".ts": "typescript", ".tsx": "typescript",
            ".mjs": "javascript", ".cjs": "javascript",
        }
        language = lang_map.get(ext, "")

    if language not in ("python", "javascript", "typescript"):
        return []

    try:
        content = Path(file_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    # Select sources and sinks for the language
    if language == "python":
        sources = _PYTHON_SOURCES
        sinks = _PYTHON_SINKS
    else:
        sources = _JS_SOURCES
        sinks = _JS_SINKS

    # Extract functions and analyze each
    functions = _extract_function_bodies(content, language)
    lines = content.splitlines()
    findings: list[DataFlowFinding] = []

    for func_name, start, end in functions:
        func_lines = lines[start - 1:end]
        raw_findings = analyze_function_taint(
            func_lines, sources, sinks, func_name, start,
        )
        for tvar, src_line, src_desc, snk_line, snk_desc, cwe, msg in raw_findings:
            findings.append(DataFlowFinding(
                file_path=file_path,
                function_name=func_name,
                source_line=src_line,
                source_desc=src_desc,
                sink_line=snk_line,
                sink_desc=snk_desc,
                tainted_var=tvar,
                cwe=cwe,
                message=msg,
            ))

    return findings


# ---------------------------------------------------------------------------
# Project-level analysis
# ---------------------------------------------------------------------------

def analyze_project(
    project_dir: str,
    paths: list[str] | None = None,
) -> DataFlowReport:
    """Run data flow analysis across a project or specific files.

    Args:
        project_dir: Project root directory.
        paths: Specific file paths to analyze (relative to project root).
            If None, scans all Python and JavaScript files.
    """
    import time

    start = time.monotonic()
    findings: list[DataFlowFinding] = []
    files_analyzed = 0
    functions_analyzed = 0

    _SKIP_DIRS = frozenset({
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        ".tox", "dist", "build", ".next", ".nuxt",
    })
    _SCAN_EXTS = frozenset({".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"})

    if paths:
        file_list = [os.path.join(project_dir, p) for p in paths]
    else:
        file_list = []
        for dirpath, dirnames, filenames in os.walk(project_dir):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext in _SCAN_EXTS:
                    file_list.append(os.path.join(dirpath, fname))

    for abs_path in file_list:
        if not os.path.isfile(abs_path):
            continue
        file_findings = analyze_file(abs_path)
        # Fix relative paths in findings
        for f in file_findings:
            try:
                f.file_path = os.path.relpath(abs_path, project_dir)
            except ValueError:
                f.file_path = abs_path
        findings.extend(file_findings)
        files_analyzed += 1

    elapsed = (time.monotonic() - start) * 1000

    return DataFlowReport(
        findings=findings,
        functions_analyzed=functions_analyzed,
        files_analyzed=files_analyzed,
        scan_time_ms=round(elapsed, 1),
    )


def format_report(report: DataFlowReport) -> str:
    """Format a DataFlowReport as human-readable text."""
    lines: list[str] = []

    lines.append("Data Flow Analysis Report")
    lines.append(f"Files: {report.files_analyzed} | "
                 f"Findings: {len(report.findings)} | "
                 f"Time: {report.scan_time_ms:.0f}ms")
    lines.append("")

    if not report.findings:
        lines.append("No data flow vulnerabilities detected.")
        return "\n".join(lines)

    # Group by CWE
    by_cwe: dict[str, list[DataFlowFinding]] = {}
    for f in report.findings:
        by_cwe.setdefault(f.cwe, []).append(f)

    cwe_labels = {
        "CWE-89": "SQL Injection",
        "CWE-78": "Command Injection",
        "CWE-79": "Cross-Site Scripting (XSS)",
        "CWE-22": "Path Traversal",
        "CWE-918": "Server-Side Request Forgery (SSRF)",
        "CWE-601": "Open Redirect",
    }

    for cwe, cwe_findings in sorted(by_cwe.items()):
        label = cwe_labels.get(cwe, cwe)
        lines.append(f"## {label} [{cwe}] ({len(cwe_findings)} finding(s))")
        for f in cwe_findings[:10]:
            lines.append(f"  {f.file_path}:{f.sink_line} in {f.function_name}()")
            lines.append(f"    Tainted variable '{f.tainted_var}' flows from "
                        f"line {f.source_line} ({f.source_desc}) to sink ({f.sink_desc})")
            lines.append(f"    {f.message}")
        if len(cwe_findings) > 10:
            lines.append(f"  ... and {len(cwe_findings) - 10} more")
        lines.append("")

    return "\n".join(lines)
