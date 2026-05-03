"""Tests for the call_graph MCP tool, the CodeIntelService.call_graph
method, and the PyCG evaluator harness end-to-end."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from attocode.code_intel.service import CodeIntelService

SIMPLE_MODULE = '''\
def helper():
    return 42


def caller():
    return helper()


def chain_a():
    chain_b()


def chain_b():
    chain_c()


def chain_c():
    return 1


class Greeter:
    def hello(self):
        return self._build()

    def _build(self):
        return "hi"
'''


@pytest.fixture
def project_with_calls():
    """Tiny project containing well-defined call edges."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "module.py").write_text(SIMPLE_MODULE, encoding="utf-8")
        yield tmp


class TestCallGraphService:
    def test_callees_direct(self, project_with_calls):
        svc = CodeIntelService(project_with_calls)
        svc.reindex()
        data = svc.call_graph_data("caller", direction="callees", depth=1)
        assert "helper" in data["edges"]
        assert data["direction"] == "callees"
        assert data["depth"] == 1

    def test_callees_transitive(self, project_with_calls):
        svc = CodeIntelService(project_with_calls)
        svc.reindex()
        data = svc.call_graph_data("chain_a", direction="callees", depth=3)
        assert {"chain_b", "chain_c"} <= set(data["edges"])

    def test_callers_direction(self, project_with_calls):
        svc = CodeIntelService(project_with_calls)
        svc.reindex()
        data = svc.call_graph_data("helper", direction="callers", depth=1)
        assert "caller" in data["edges"]

    def test_unknown_symbol_returns_empty_edges(self, project_with_calls):
        svc = CodeIntelService(project_with_calls)
        svc.reindex()
        data = svc.call_graph_data("does_not_exist", direction="callees", depth=1)
        assert data["edges"] == []
        assert data["definitions"] == []

    def test_call_graph_text_contains_edges(self, project_with_calls):
        svc = CodeIntelService(project_with_calls)
        svc.reindex()
        text = svc.call_graph("caller", direction="callees", depth=1)
        assert "caller" in text
        assert "helper" in text
        assert "callees" in text

    def test_invalid_direction(self, project_with_calls):
        svc = CodeIntelService(project_with_calls)
        text = svc.call_graph("caller", direction="sideways")
        assert "Error" in text

    def test_invalid_depth(self, project_with_calls):
        svc = CodeIntelService(project_with_calls)
        text = svc.call_graph("caller", depth=0)
        assert "Error" in text


class TestPyCGHarness:
    def test_evaluate_module_meets_targets(self, tmp_path):
        """End-to-end: a tiny synthetic 'PyCG-style' benchmark should hit
        the roadmap's P>0.8 / R>0.5 targets on call edges we definitely
        emit. The benchmark mimics PyCG's directory layout: one module
        directory, a callgraph.json, and the Python source files."""
        from eval.pycg.__main__ import evaluate_module

        module_dir = tmp_path / "category" / "simple"
        module_dir.mkdir(parents=True)
        (module_dir / "main.py").write_text(SIMPLE_MODULE, encoding="utf-8")

        # Ground-truth edges that our regex+enclosing-caller path will
        # actually produce. PyCG uses dotted names; we compare bare ones.
        ground_truth = {
            "main.caller": ["main.helper"],
            "main.chain_a": ["main.chain_b"],
            "main.chain_b": ["main.chain_c"],
            "main.Greeter.hello": ["main.Greeter._build"],
        }
        (module_dir / "callgraph.json").write_text(
            json.dumps(ground_truth), encoding="utf-8",
        )

        benchmark = {
            "category": "synthetic",
            "module": "simple",
            "path": str(module_dir),
            "callgraph": ground_truth,
            "py_files": [str(module_dir / "main.py")],
            "edge_count": sum(len(v) for v in ground_truth.values()),
        }
        result = evaluate_module(benchmark)
        assert "error" not in result, result

        # Targets from the v0.2.21 roadmap.
        assert result["precision"] >= 0.8, result
        assert result["recall"] >= 0.5, result


class TestMcpToolDelegation:
    """Smoke-test the MCP tool wrapper delegates to CodeIntelService.

    We exercise the underlying logic via a service instance directly
    rather than spinning up MCP dispatch — same pattern other rule_tools
    tests use.
    """

    def test_mcp_tool_uses_service_call_graph(self, project_with_calls, monkeypatch):
        from attocode.code_intel.tools import analysis_tools as at

        svc = CodeIntelService(project_with_calls)
        svc.reindex()
        monkeypatch.setattr(at, "_get_service", lambda: svc)

        result = at.call_graph("caller", direction="callees", depth=1)
        assert "helper" in result
