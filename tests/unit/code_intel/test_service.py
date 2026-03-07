"""Tests for CodeIntelService."""

from __future__ import annotations

import os

from attocode.code_intel.config import CodeIntelConfig
from attocode.code_intel.service import CodeIntelService


def setup_function():
    CodeIntelService._reset_instances()


def teardown_function():
    CodeIntelService._reset_instances()


def test_get_instance_returns_same(tmp_path):
    a = CodeIntelService.get_instance(str(tmp_path))
    b = CodeIntelService.get_instance(str(tmp_path))
    assert a is b


def test_get_instance_different_paths(tmp_path):
    d1 = tmp_path / "a"
    d2 = tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    a = CodeIntelService.get_instance(str(d1))
    b = CodeIntelService.get_instance(str(d2))
    assert a is not b


def test_project_dir_is_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    svc = CodeIntelService(".")
    assert os.path.isabs(svc.project_dir)
    assert svc.project_dir == str(tmp_path)


def test_reset_instances(tmp_path):
    a = CodeIntelService.get_instance(str(tmp_path))
    CodeIntelService._reset_instances()
    b = CodeIntelService.get_instance(str(tmp_path))
    assert a is not b
