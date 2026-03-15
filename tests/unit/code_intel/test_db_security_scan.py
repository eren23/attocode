"""Tests for DB-backed security scanning."""

from __future__ import annotations

from attocode.code_intel.storage.security_scanner_db import (
    _detect_language,
    _is_scannable,
)


def test_is_scannable_python():
    assert _is_scannable("src/main.py")
    assert _is_scannable("test.pyi")


def test_is_scannable_js():
    assert _is_scannable("app.js")
    assert _is_scannable("component.tsx")


def test_is_scannable_config():
    assert _is_scannable("config.yaml")
    assert _is_scannable(".env")
    assert _is_scannable("settings.toml")


def test_not_scannable():
    assert not _is_scannable("image.png")
    assert not _is_scannable("binary.exe")
    assert not _is_scannable("document.pdf")


def test_detect_language():
    assert _detect_language("main.py") == "python"
    assert _detect_language("app.ts") == "typescript"
    assert _detect_language("index.js") == "javascript"
    assert _detect_language("main.go") == "go"
    assert _detect_language("lib.rs") == "rust"
    assert _detect_language("README.md") == ""


def test_secret_patterns_import():
    """Verify we can import the patterns used by the scanner."""
    from attocode.integrations.security.patterns import (
        ANTI_PATTERNS,
        SECRET_PATTERNS,
    )

    assert len(SECRET_PATTERNS) > 0
    assert len(ANTI_PATTERNS) > 0


def test_aws_key_pattern():
    """Verify AWS key pattern matches correctly."""
    import re

    from attocode.integrations.security.patterns import SECRET_PATTERNS

    aws_pattern = next(p for p in SECRET_PATTERNS if p.name == "aws_access_key")
    assert aws_pattern.pattern.search("AKIAIOSFODNN7EXAMPLE")
    assert not aws_pattern.pattern.search("not_an_aws_key")


def test_private_key_pattern():
    """Verify private key pattern matches."""
    import re

    from attocode.integrations.security.patterns import SECRET_PATTERNS

    pk_pattern = next(p for p in SECRET_PATTERNS if p.name == "private_key")
    assert pk_pattern.pattern.search("-----BEGIN RSA PRIVATE KEY-----")
    assert pk_pattern.pattern.search("-----BEGIN PRIVATE KEY-----")
    assert not pk_pattern.pattern.search("-----BEGIN PUBLIC KEY-----")
