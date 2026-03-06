"""Edit validator for syntax validation on file edits.

Validates that file edits produce syntactically valid code by running
lightweight syntax checks after modifications. Catches broken edits
before they propagate through the codebase.
"""

from __future__ import annotations

import ast
import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ValidationResult:
    """Result of a syntax validation."""

    valid: bool
    language: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# Language detection by file extension
LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".rs": "rust",
    ".go": "go",
}


class EditValidator:
    """Validates file edits produce syntactically valid code.

    Supports multiple languages with lightweight syntax checks:
    - Python: ast.parse()
    - JSON: json.loads()
    - YAML: yaml.safe_load() if available
    - TypeScript/JavaScript: optional tsc/node check
    """

    def __init__(self, *, check_external: bool = False) -> None:
        """Args:
            check_external: If True, attempt external tool checks (tsc, rustc, etc.)
        """
        self._check_external = check_external

    def validate(self, file_path: str, content: str) -> ValidationResult:
        """Validate content for a given file path.

        Determines language from extension and runs appropriate checker.
        """
        ext = Path(file_path).suffix.lower()
        language = LANGUAGE_MAP.get(ext, "")

        if not language:
            return ValidationResult(valid=True, language="unknown")

        if language == "python":
            return self._validate_python(content)
        elif language == "json":
            return self._validate_json(content)
        elif language == "yaml":
            return self._validate_yaml(content)
        elif language in ("typescript", "javascript") and self._check_external:
            return self._validate_ts_js(content, language)
        else:
            return ValidationResult(valid=True, language=language)

    def validate_edit(
        self,
        file_path: str,
        original: str,
        edited: str,
    ) -> ValidationResult:
        """Validate an edit by checking the result.

        If the original was invalid but the edit is also invalid,
        reports as warning rather than error (can't make it worse).
        """
        result = self.validate(file_path, edited)

        if not result.valid:
            orig_result = self.validate(file_path, original)
            if not orig_result.valid:
                # Original was already broken — downgrade to warning
                result.warnings = [
                    f"Edit maintains pre-existing syntax error: {e}"
                    for e in result.errors
                ]
                result.errors = []
                result.valid = True

        return result

    def _validate_python(self, content: str) -> ValidationResult:
        """Validate Python syntax using ast.parse()."""
        try:
            ast.parse(content)
            return ValidationResult(valid=True, language="python")
        except SyntaxError as e:
            msg = f"Line {e.lineno}: {e.msg}" if e.lineno else str(e.msg)
            return ValidationResult(
                valid=False,
                language="python",
                errors=[msg],
            )

    def _validate_json(self, content: str) -> ValidationResult:
        """Validate JSON syntax."""
        try:
            json.loads(content)
            return ValidationResult(valid=True, language="json")
        except json.JSONDecodeError as e:
            return ValidationResult(
                valid=False,
                language="json",
                errors=[f"Line {e.lineno}, col {e.colno}: {e.msg}"],
            )

    def _validate_yaml(self, content: str) -> ValidationResult:
        """Validate YAML syntax."""
        try:
            import yaml
            yaml.safe_load(content)
            return ValidationResult(valid=True, language="yaml")
        except ImportError:
            return ValidationResult(valid=True, language="yaml", warnings=["yaml not installed"])
        except Exception as e:
            return ValidationResult(
                valid=False,
                language="yaml",
                errors=[str(e)],
            )

    def _validate_ts_js(self, content: str, language: str) -> ValidationResult:
        """Validate TypeScript/JavaScript using external tools."""
        ext = ".ts" if language == "typescript" else ".js"
        try:
            with tempfile.NamedTemporaryFile(suffix=ext, mode="w", delete=False) as f:
                f.write(content)
                f.flush()

                cmd = ["node", "--check", f.name] if ext == ".js" else ["npx", "tsc", "--noEmit", f.name]
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=10,
                )

                Path(f.name).unlink(missing_ok=True)

                if result.returncode == 0:
                    return ValidationResult(valid=True, language=language)
                return ValidationResult(
                    valid=False,
                    language=language,
                    errors=result.stderr.strip().split("\n")[:5],
                )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return ValidationResult(
                valid=True,
                language=language,
                warnings=[f"External {language} checker not available"],
            )
