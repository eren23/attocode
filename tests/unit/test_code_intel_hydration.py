"""Tests for CodeIntelService progressive hydration integration."""
from __future__ import annotations

from pathlib import Path

import pytest

from attocode.integrations.context.ast_service import ASTService


def _create_python_files(root: Path, count: int) -> None:
    src = root / "src"
    src.mkdir(exist_ok=True)
    for i in range(count):
        (src / f"mod_{i}.py").write_text(
            f"def func_{i}():\n    return {i}\n",
            encoding="utf-8",
        )


class TestTierAwareInit:
    def setup_method(self):
        ASTService.clear_instances()

    def test_small_repo_uses_eager(self, tmp_path: Path):
        from attocode.code_intel.service import CodeIntelService
        from attocode.integrations.context.hydration import TIER_SMALL
        _create_python_files(tmp_path, 10)
        svc = CodeIntelService(str(tmp_path))
        ast_svc = svc._get_ast_service()
        state = ast_svc._hydration_state
        assert state is not None
        assert state.tier == TIER_SMALL
        assert state.phase == "ready"

    def test_indexing_depth_eager_forces_full(self, tmp_path: Path):
        from attocode.code_intel.service import CodeIntelService
        from attocode.integrations.context.hydration import TIER_SMALL
        _create_python_files(tmp_path, 1500)
        svc = CodeIntelService(str(tmp_path))
        ast_svc = svc._get_ast_service(indexing_depth="eager")
        state = ast_svc._hydration_state
        assert state.tier == TIER_SMALL
        assert state.phase == "ready"


class TestHydrationStatus:
    def setup_method(self):
        ASTService.clear_instances()

    def test_returns_status_dict(self, tmp_path: Path):
        from attocode.code_intel.service import CodeIntelService
        _create_python_files(tmp_path, 10)
        svc = CodeIntelService(str(tmp_path))
        status = svc.hydration_status()
        assert "tier" in status
        assert "phase" in status
        assert "parse_coverage" in status


class TestOnDemandGapFilling:
    def setup_method(self):
        ASTService.clear_instances()

    def test_symbols_parses_on_demand(self, tmp_path: Path):
        from attocode.code_intel.service import CodeIntelService
        src = tmp_path / "src"
        src.mkdir(exist_ok=True)
        for i in range(1500):
            (src / f"mod_{i}.py").write_text(
                f"def func_{i}():\n    return {i}\n",
                encoding="utf-8",
            )
        svc = CodeIntelService(str(tmp_path))
        ast_svc = svc._get_ast_service()
        ast_svc.stop_hydration()  # stop background so we test on-demand only

        result = svc.symbols("src/mod_999.py")
        assert "func_999" in result
