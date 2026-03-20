"""Tests for CausalChainAnalyzer."""

from __future__ import annotations

from attoswarm.coordinator.aot_graph import AoTGraph, AoTNode
from attoswarm.coordinator.causal_analyzer import CausalChainAnalyzer
from attoswarm.coordinator.failure_analyzer import FailureAnalyzer, FailureAttribution


class TestCausalChainAnalyzer:
    def _build_chain_graph(self) -> AoTGraph:
        """Build a->b->c dependency chain."""
        g = AoTGraph()
        g.add_task(AoTNode(task_id="a"))
        g.add_task(AoTNode(task_id="b", depends_on=["a"]))
        g.add_task(AoTNode(task_id="c", depends_on=["b"]))
        g.compute_levels()
        return g

    def test_direct_failure(self) -> None:
        g = self._build_chain_graph()
        g.mark_failed("a")
        analyzer = CausalChainAnalyzer(g, FailureAnalyzer())

        chain = analyzer.analyze_failure("a", FailureAttribution(
            task_id="a", cause="timeout", confidence=0.9,
        ))
        assert chain.task_id == "a"
        assert chain.cause in ("timeout", "agent_error")

    def test_dep_failure_chain(self) -> None:
        g = self._build_chain_graph()
        g.mark_failed("a")
        g.mark_failed("b")
        analyzer = CausalChainAnalyzer(g, FailureAnalyzer())

        # Analyze b first (failed because of a)
        chain_a = analyzer.analyze_failure("a", FailureAttribution(
            task_id="a", cause="timeout", confidence=0.9,
        ))
        chain_b = analyzer.analyze_failure("b")
        assert chain_b.root_cause_id == "a"

    def test_blast_radius(self) -> None:
        g = self._build_chain_graph()
        g.mark_failed("a")
        analyzer = CausalChainAnalyzer(g, FailureAnalyzer())

        blast = analyzer.get_blast_radius("a")
        assert "b" in blast.directly_blocked
        assert blast.total_blocked == 2  # b and c

    def test_root_causes(self) -> None:
        g = self._build_chain_graph()
        g.mark_failed("a")
        analyzer = CausalChainAnalyzer(g, FailureAnalyzer())

        analyzer.analyze_failure("a", FailureAttribution(
            task_id="a", cause="timeout", confidence=0.9,
        ))
        roots = analyzer.get_root_causes()
        assert len(roots) >= 1
        assert roots[0].task_id == "a"

    def test_wasted_cost(self) -> None:
        g = self._build_chain_graph()
        analyzer = CausalChainAnalyzer(g, FailureAnalyzer())
        analyzer.record_task_cost("a", 1.0)
        analyzer.record_task_cost("b", 0.5)

        blast = analyzer.get_blast_radius("a")
        assert blast.wasted_cost == 0.5  # cost of b

    def test_to_dict(self) -> None:
        g = self._build_chain_graph()
        g.mark_failed("a")
        analyzer = CausalChainAnalyzer(g, FailureAnalyzer())
        analyzer.analyze_failure("a")
        d = analyzer.to_dict()
        assert "chains" in d
        assert "root_causes" in d
