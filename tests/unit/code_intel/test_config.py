"""Tests for CodeIntelConfig."""

from __future__ import annotations

import os

import pytest

from attocode.code_intel.config import CodeIntelConfig


def test_defaults():
    cfg = CodeIntelConfig()
    assert cfg.project_dir == ""
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8080
    assert cfg.api_key == ""
    assert cfg.cors_origins == ["*"]
    assert cfg.log_level == "info"


def test_from_env(monkeypatch):
    monkeypatch.setenv("ATTOCODE_PROJECT_DIR", "/tmp/proj")
    monkeypatch.setenv("ATTOCODE_HOST", "0.0.0.0")
    monkeypatch.setenv("ATTOCODE_PORT", "9090")
    monkeypatch.setenv("ATTOCODE_API_KEY", "secret123")
    monkeypatch.setenv("ATTOCODE_CORS_ORIGINS", "http://a.com,http://b.com")
    monkeypatch.setenv("ATTOCODE_LOG_LEVEL", "debug")

    cfg = CodeIntelConfig.from_env()
    assert cfg.project_dir == "/tmp/proj"
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9090
    assert cfg.api_key == "secret123"
    assert cfg.cors_origins == ["http://a.com", "http://b.com"]
    assert cfg.log_level == "debug"


def test_from_env_defaults(monkeypatch):
    for var in ("ATTOCODE_PROJECT_DIR", "ATTOCODE_HOST", "ATTOCODE_PORT",
                "ATTOCODE_API_KEY", "ATTOCODE_CORS_ORIGINS", "ATTOCODE_LOG_LEVEL"):
        monkeypatch.delenv(var, raising=False)

    cfg = CodeIntelConfig.from_env()
    assert cfg.project_dir == ""
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8080
    assert cfg.api_key == ""
    assert cfg.cors_origins == ["*"]
    assert cfg.log_level == "info"


def test_from_env_port_non_numeric_raises(monkeypatch):
    monkeypatch.setenv("ATTOCODE_PORT", "abc")
    with pytest.raises(ValueError):
        CodeIntelConfig.from_env()
