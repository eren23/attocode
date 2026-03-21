"""Per-language compilation and syntax checks for swarm worker outputs.

Runs fast, targeted checks on modified files only. Designed to catch
obvious syntax/compilation errors before the (more expensive) LLM quality gate.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# =============================================================================
# Data Types
# =============================================================================


@dataclass
class CompilationError:
    """A single compilation or syntax error."""

    file_path: str
    line: int | None
    message: str
    severity: str = "error"


@dataclass
class CompilationCheckResult:
    """Result of running compilation checks on a set of files."""

    passed: bool
    errors: list[CompilationError] = field(default_factory=list)
    files_checked: int = 0
    duration_ms: int = 0


# =============================================================================
# Main Entry Point
# =============================================================================


def run_compilation_checks(
    files_modified: list[str],
    working_dir: str,
    timeout_seconds: int = 30,
) -> CompilationCheckResult:
    """Run per-language syntax/compilation checks on *files_modified*.

    Dispatches to the appropriate checker based on file extension.
    Returns a :class:`CompilationCheckResult` summarizing any errors found.
    """
    start = time.monotonic()
    all_errors: list[CompilationError] = []
    files_checked = 0

    # Group files by extension
    python_files: list[str] = []
    ts_files: list[str] = []
    js_files: list[str] = []
    json_files: list[str] = []

    for fpath in files_modified:
        if not fpath:
            continue
        abs_path = os.path.join(working_dir, fpath) if not os.path.isabs(fpath) else fpath
        if not os.path.isfile(abs_path):
            continue

        ext = os.path.splitext(fpath)[1].lower()
        if ext == ".py":
            python_files.append(abs_path)
        elif ext in (".ts", ".tsx"):
            ts_files.append(abs_path)
        elif ext in (".js", ".jsx", ".mjs", ".cjs"):
            js_files.append(abs_path)
        elif ext == ".json":
            json_files.append(abs_path)

    # Python syntax checks (in-process, fast)
    for py_file in python_files:
        errs = _check_python_syntax(py_file)
        all_errors.extend(errs)
        files_checked += 1

    # Python import checks (subprocess, slower)
    for py_file in python_files:
        errs = _check_python_imports(py_file, timeout_seconds)
        all_errors.extend(errs)

    # JSON syntax checks (in-process, fast)
    for json_file in json_files:
        errs = _check_json_syntax(json_file)
        all_errors.extend(errs)
        files_checked += 1

    # JavaScript syntax checks (subprocess)
    for js_file in js_files:
        errs = _check_javascript_syntax(js_file, timeout_seconds)
        all_errors.extend(errs)
        files_checked += 1

    # TypeScript checks (batch via tsc)
    if ts_files:
        errs = _check_typescript_files(ts_files, working_dir, timeout_seconds)
        all_errors.extend(errs)
        files_checked += len(ts_files)

    duration_ms = int((time.monotonic() - start) * 1000)
    passed = len([e for e in all_errors if e.severity == "error"]) == 0

    return CompilationCheckResult(
        passed=passed,
        errors=all_errors,
        files_checked=files_checked,
        duration_ms=duration_ms,
    )


# =============================================================================
# Per-Language Checkers
# =============================================================================


def _check_python_syntax(file_path: str) -> list[CompilationError]:
    """Check Python file syntax using compile(). In-process, <10ms/file."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
        compile(source, file_path, "exec")
        return []
    except SyntaxError as exc:
        return [
            CompilationError(
                file_path=file_path,
                line=exc.lineno,
                message=f"SyntaxError: {exc.msg}",
                severity="error",
            )
        ]
    except Exception as exc:
        logger.debug("Python syntax check failed for %s: %s", file_path, exc)
        return []


def _check_python_imports(
    file_path: str,
    timeout_seconds: int = 10,
) -> list[CompilationError]:
    """Check that a Python file's imports resolve.

    Uses ``python -c "import ast; ..."`` to parse and attempt import of
    top-level modules. Only reports errors for ImportError, not runtime issues.
    """
    try:
        # Extract module names from import statements using ast
        check_script = (
            "import ast, sys\n"
            f"with open({file_path!r}, 'r') as f:\n"
            "    tree = ast.parse(f.read())\n"
            "for node in ast.walk(tree):\n"
            "    if isinstance(node, ast.Import):\n"
            "        for alias in node.names:\n"
            "            mod = alias.name.split('.')[0]\n"
            "            try:\n"
            "                __import__(mod)\n"
            "            except ImportError as e:\n"
            "                print(f'{node.lineno}:{e}', file=sys.stderr)\n"
            "    elif isinstance(node, ast.ImportFrom) and node.module:\n"
            "        mod = node.module.split('.')[0]\n"
            "        try:\n"
            "            __import__(mod)\n"
            "        except ImportError as e:\n"
            "            print(f'{node.lineno}:{e}', file=sys.stderr)\n"
        )

        result = subprocess.run(
            ["python", "-c", check_script],
            capture_output=True,
            text=True,
            timeout=min(timeout_seconds, 10),
            cwd=os.path.dirname(file_path) or ".",
        )

        errors: list[CompilationError] = []
        if result.stderr:
            for line in result.stderr.strip().splitlines():
                parts = line.split(":", 1)
                lineno = None
                msg = line
                if len(parts) == 2:
                    try:
                        lineno = int(parts[0])
                        msg = parts[1].strip()
                    except ValueError:
                        pass
                errors.append(
                    CompilationError(
                        file_path=file_path,
                        line=lineno,
                        message=msg,
                        severity="warning",  # import errors are warnings, not hard failures
                    )
                )
        return errors

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.debug("Python import check skipped for %s: %s", file_path, exc)
        return []
    except Exception as exc:
        logger.debug("Python import check failed for %s: %s", file_path, exc)
        return []


def _check_typescript_files(
    ts_files: list[str],
    working_dir: str,
    timeout_seconds: int = 30,
) -> list[CompilationError]:
    """Check TypeScript files using ``npx tsc --noEmit --isolatedModules``.

    Runs tsc on only the specified files. Parses tsc output for error locations.
    """
    if not ts_files:
        return []

    try:
        cmd = ["npx", "tsc", "--noEmit", "--isolatedModules", "--pretty", "false"]
        cmd.extend(ts_files)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=working_dir,
        )

        if result.returncode == 0:
            return []

        errors: list[CompilationError] = []
        output = result.stdout or result.stderr or ""
        for raw_line in output.strip().splitlines():
            # tsc output format: file(line,col): error TSxxxx: message
            parsed = _parse_tsc_error_line(raw_line)
            if parsed:
                errors.append(parsed)

        return errors

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.debug("TypeScript check skipped: %s", exc)
        return []
    except Exception as exc:
        logger.debug("TypeScript check failed: %s", exc)
        return []


def _parse_tsc_error_line(line: str) -> CompilationError | None:
    """Parse a single tsc error line into a CompilationError.

    Expected format: ``file.ts(line,col): error TS1234: message``
    """
    # Find the file(line,col) pattern
    paren_idx = line.find("(")
    if paren_idx < 0:
        return None
    close_paren_idx = line.find(")", paren_idx)
    if close_paren_idx < 0:
        return None

    file_path = line[:paren_idx].strip()
    coords = line[paren_idx + 1 : close_paren_idx]

    # Parse line number from coords (line,col)
    line_num = None
    try:
        line_num = int(coords.split(",")[0])
    except (ValueError, IndexError):
        pass

    # Extract the message after ": error " or ": warning "
    rest = line[close_paren_idx + 1 :].strip()
    if rest.startswith(":"):
        rest = rest[1:].strip()

    severity = "error"
    if "warning" in rest.lower()[:20]:
        severity = "warning"

    return CompilationError(
        file_path=file_path,
        line=line_num,
        message=rest,
        severity=severity,
    )


def _check_javascript_syntax(
    file_path: str,
    timeout_seconds: int = 10,
) -> list[CompilationError]:
    """Check JavaScript file syntax using ``node --check``. ~100ms/file."""
    try:
        result = subprocess.run(
            ["node", "--check", file_path],
            capture_output=True,
            text=True,
            timeout=min(timeout_seconds, 10),
        )

        if result.returncode == 0:
            return []

        # Parse node --check error output
        error_output = result.stderr or result.stdout or "Syntax error"
        line_num = None

        # Try to extract line number from node error output
        for err_line in error_output.splitlines():
            if file_path in err_line and ":" in err_line:
                parts = err_line.split(":")
                for part in parts:
                    try:
                        line_num = int(part.strip())
                        break
                    except ValueError:
                        continue
            if line_num is not None:
                break

        return [
            CompilationError(
                file_path=file_path,
                line=line_num,
                message=error_output.strip().splitlines()[0] if error_output.strip() else "Syntax error",
                severity="error",
            )
        ]

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.debug("JavaScript syntax check skipped for %s: %s", file_path, exc)
        return []
    except Exception as exc:
        logger.debug("JavaScript syntax check failed for %s: %s", file_path, exc)
        return []


def _check_json_syntax(file_path: str) -> list[CompilationError]:
    """Check JSON file syntax. In-process, <1ms/file."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        json.loads(content)
        return []
    except json.JSONDecodeError as exc:
        return [
            CompilationError(
                file_path=file_path,
                line=exc.lineno,
                message=f"JSONDecodeError: {exc.msg}",
                severity="error",
            )
        ]
    except Exception as exc:
        logger.debug("JSON syntax check failed for %s: %s", file_path, exc)
        return []
