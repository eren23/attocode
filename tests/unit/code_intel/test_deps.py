"""Tests for the DI module (api/deps.py)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from attocode.code_intel.api import deps
from attocode.code_intel.config import CodeIntelConfig


@pytest.fixture(autouse=True)
def _reset():
    deps.reset()
    yield
    deps.reset()


def test_configure_sets_config():
    cfg = CodeIntelConfig(project_dir="")
    deps.configure(cfg)
    assert deps.get_config() is cfg


def test_get_config_fallback_from_env(monkeypatch):
    monkeypatch.setenv("ATTOCODE_PORT", "9999")
    # No configure() called — should fall back to from_env()
    cfg = deps.get_config()
    assert cfg.port == 9999


def test_get_service_unknown_raises():
    with pytest.raises(ValueError, match="not found"):
        deps.get_service("nonexistent")


def test_register_and_get(tmp_path):
    deps.configure(CodeIntelConfig())
    svc = deps.register_project("test1", str(tmp_path))
    assert deps.get_service("test1") is svc


def test_list_projects(tmp_path):
    deps.configure(CodeIntelConfig())
    deps.register_project("a", str(tmp_path))
    deps.register_project("b", str(tmp_path))
    projects = deps.list_projects()
    assert "a" in projects
    assert "b" in projects


def test_get_service_or_404():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        deps.get_service_or_404("unknown")
    assert exc_info.value.status_code == 404


def test_configure_warns_double_call(caplog):
    cfg = CodeIntelConfig()
    deps.configure(cfg)
    with caplog.at_level(logging.WARNING):
        deps.configure(cfg)
    assert "more than once" in caplog.text


def test_reset_clears_all(tmp_path):
    deps.configure(CodeIntelConfig())
    deps.register_project("x", str(tmp_path))
    assert deps.list_projects()
    deps.reset()
    assert not deps.list_projects()
    assert deps.get_default_project_id() == ""


def test_get_service_empty_string_uses_default(tmp_path):
    deps.configure(CodeIntelConfig(project_dir=str(tmp_path)))
    svc = deps.get_service("")
    assert svc is deps.get_service("default")


def test_register_overwrites_existing_id(tmp_path):
    deps.configure(CodeIntelConfig())
    d1 = tmp_path / "a"
    d2 = tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    deps.register_project("test", str(d1))
    deps.register_project("test", str(d2))
    svc = deps.get_service("test")
    assert svc.project_dir == str(d2)
