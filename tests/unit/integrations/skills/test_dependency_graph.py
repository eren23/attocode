"""Tests for skill dependency graph resolution."""

from __future__ import annotations

import pytest

from attocode.integrations.skills.dependency_graph import (
    DependencyInfo,
    SkillDependencyError,
    SkillDependencyGraph,
)
from attocode.integrations.skills.loader import SkillDefinition


def _skill(
    name: str,
    depends_on: list[str] | str | None = None,
    version: str = "",
    compatible_versions: dict[str, str] | None = None,
) -> SkillDefinition:
    """Helper to create a SkillDefinition with dependency metadata."""
    metadata: dict = {}
    if depends_on is not None:
        metadata["depends_on"] = depends_on
    if version:
        metadata["version"] = version
    if compatible_versions:
        metadata["compatible_versions"] = compatible_versions
    return SkillDefinition(name=name, metadata=metadata)


class TestDependencyInfo:
    def test_defaults(self) -> None:
        info = DependencyInfo(skill_name="foo")
        assert info.skill_name == "foo"
        assert info.depends_on == []
        assert info.version == ""
        assert info.compatible_versions == {}


class TestAddSkill:
    def test_add_skill_no_dependencies(self) -> None:
        graph = SkillDependencyGraph()
        info = graph.add_skill(_skill("alpha"))
        assert info.skill_name == "alpha"
        assert info.depends_on == []
        assert info.version == ""

    def test_add_skill_with_list_dependencies(self) -> None:
        graph = SkillDependencyGraph()
        info = graph.add_skill(_skill("beta", depends_on=["alpha", "gamma"]))
        assert info.skill_name == "beta"
        assert info.depends_on == ["alpha", "gamma"]

    def test_add_skill_with_comma_separated_string_dependencies(self) -> None:
        graph = SkillDependencyGraph()
        info = graph.add_skill(_skill("beta", depends_on="alpha, gamma"))
        assert info.depends_on == ["alpha", "gamma"]

    def test_add_skill_with_version(self) -> None:
        graph = SkillDependencyGraph()
        info = graph.add_skill(_skill("alpha", version="1.2.0"))
        assert info.version == "1.2.0"

    def test_add_skill_with_compatible_versions(self) -> None:
        graph = SkillDependencyGraph()
        info = graph.add_skill(
            _skill("beta", compatible_versions={"alpha": "1.0.0"})
        )
        assert info.compatible_versions == {"alpha": "1.0.0"}

    def test_add_skill_no_metadata(self) -> None:
        """Skill with metadata=None should not raise."""
        skill = SkillDefinition(name="bare", metadata=None)  # type: ignore[arg-type]
        graph = SkillDependencyGraph()
        info = graph.add_skill(skill)
        assert info.depends_on == []

    def test_add_skill_empty_metadata(self) -> None:
        skill = SkillDefinition(name="empty", metadata={})
        graph = SkillDependencyGraph()
        info = graph.add_skill(skill)
        assert info.depends_on == []
        assert info.version == ""

    def test_add_skill_overwrites_existing(self) -> None:
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("alpha", version="1.0"))
        graph.add_skill(_skill("alpha", version="2.0"))
        # Should reflect the latest addition
        assert graph.to_dict()["alpha"]["version"] == "2.0"


class TestResolveOrder:
    def test_single_skill_no_deps(self) -> None:
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("alpha"))
        order = graph.resolve_order()
        assert order == ["alpha"]

    def test_two_independent_skills(self) -> None:
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("alpha"))
        graph.add_skill(_skill("beta"))
        order = graph.resolve_order()
        assert set(order) == {"alpha", "beta"}
        assert len(order) == 2

    def test_simple_dependency(self) -> None:
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("alpha"))
        graph.add_skill(_skill("beta", depends_on=["alpha"]))
        order = graph.resolve_order()
        assert order.index("alpha") < order.index("beta")

    def test_resolve_order_returns_topological_order(self) -> None:
        """A -> B -> C chain: C depends on B, B depends on A."""
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A"))
        graph.add_skill(_skill("B", depends_on=["A"]))
        graph.add_skill(_skill("C", depends_on=["B"]))
        order = graph.resolve_order()
        assert order.index("A") < order.index("B")
        assert order.index("B") < order.index("C")

    def test_resolve_order_with_specific_subset(self) -> None:
        """Requesting only C should pull in B and A transitively."""
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A"))
        graph.add_skill(_skill("B", depends_on=["A"]))
        graph.add_skill(_skill("C", depends_on=["B"]))
        graph.add_skill(_skill("D"))  # unrelated, should not appear
        order = graph.resolve_order(skill_names=["C"])
        assert set(order) == {"A", "B", "C"}
        assert order.index("A") < order.index("B")
        assert order.index("B") < order.index("C")

    def test_resolve_subset_includes_transitive_deps(self) -> None:
        """Requesting B and D should pull in A (transitive dep of B) but not C."""
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A"))
        graph.add_skill(_skill("B", depends_on=["A"]))
        graph.add_skill(_skill("C", depends_on=["B"]))
        graph.add_skill(_skill("D"))
        order = graph.resolve_order(skill_names=["B", "D"])
        assert set(order) == {"A", "B", "D"}
        assert order.index("A") < order.index("B")

    def test_diamond_dependency(self) -> None:
        """Diamond: D depends on B and C, both depend on A."""
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A"))
        graph.add_skill(_skill("B", depends_on=["A"]))
        graph.add_skill(_skill("C", depends_on=["A"]))
        graph.add_skill(_skill("D", depends_on=["B", "C"]))
        order = graph.resolve_order()
        assert order.index("A") < order.index("B")
        assert order.index("A") < order.index("C")
        assert order.index("B") < order.index("D")
        assert order.index("C") < order.index("D")

    def test_resolve_all_when_none_passed(self) -> None:
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("X"))
        graph.add_skill(_skill("Y"))
        order = graph.resolve_order(skill_names=None)
        assert set(order) == {"X", "Y"}

    def test_empty_graph(self) -> None:
        graph = SkillDependencyGraph()
        order = graph.resolve_order()
        assert order == []


class TestCycleDetection:
    def test_simple_cycle_raises(self) -> None:
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A", depends_on=["B"]))
        graph.add_skill(_skill("B", depends_on=["A"]))
        with pytest.raises(SkillDependencyError, match="Circular dependency"):
            graph.resolve_order()

    def test_three_node_cycle_raises(self) -> None:
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A", depends_on=["C"]))
        graph.add_skill(_skill("B", depends_on=["A"]))
        graph.add_skill(_skill("C", depends_on=["B"]))
        with pytest.raises(SkillDependencyError, match="Circular dependency"):
            graph.resolve_order()

    def test_self_cycle_raises(self) -> None:
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A", depends_on=["A"]))
        with pytest.raises(SkillDependencyError, match="Circular dependency"):
            graph.resolve_order()

    def test_cycle_error_lists_members(self) -> None:
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("X", depends_on=["Y"]))
        graph.add_skill(_skill("Y", depends_on=["X"]))
        with pytest.raises(SkillDependencyError, match="X") as exc_info:
            graph.resolve_order()
        assert "Y" in str(exc_info.value)


class TestMissingDependency:
    def test_missing_dep_raises(self) -> None:
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("beta", depends_on=["alpha"]))
        with pytest.raises(SkillDependencyError, match="Missing skill dependencies"):
            graph.resolve_order()

    def test_missing_dep_names_listed(self) -> None:
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("C", depends_on=["A", "B"]))
        with pytest.raises(SkillDependencyError, match="A") as exc_info:
            graph.resolve_order()
        assert "B" in str(exc_info.value)

    def test_missing_transitive_dep_raises(self) -> None:
        """B depends on A (registered), A depends on Z (not registered)."""
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A", depends_on=["Z"]))
        graph.add_skill(_skill("B", depends_on=["A"]))
        with pytest.raises(SkillDependencyError, match="Z"):
            graph.resolve_order()

    def test_missing_dep_in_subset_raises(self) -> None:
        """Even when resolving a subset, missing transitive deps should error."""
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("B", depends_on=["A"]))
        with pytest.raises(SkillDependencyError, match="A"):
            graph.resolve_order(skill_names=["B"])


class TestGetDependencies:
    def test_get_dependencies_returns_direct_deps(self) -> None:
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A"))
        graph.add_skill(_skill("B", depends_on=["A"]))
        assert graph.get_dependencies("B") == ["A"]

    def test_get_dependencies_no_deps(self) -> None:
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A"))
        assert graph.get_dependencies("A") == []

    def test_get_dependencies_unknown_skill(self) -> None:
        graph = SkillDependencyGraph()
        assert graph.get_dependencies("nonexistent") == []

    def test_get_dependencies_multiple(self) -> None:
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A"))
        graph.add_skill(_skill("B"))
        graph.add_skill(_skill("C", depends_on=["A", "B"]))
        deps = graph.get_dependencies("C")
        assert set(deps) == {"A", "B"}


class TestGetDependents:
    def test_get_dependents_returns_skills_that_depend_on_target(self) -> None:
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A"))
        graph.add_skill(_skill("B", depends_on=["A"]))
        graph.add_skill(_skill("C", depends_on=["A"]))
        dependents = graph.get_dependents("A")
        assert set(dependents) == {"B", "C"}

    def test_get_dependents_none(self) -> None:
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A"))
        graph.add_skill(_skill("B"))
        assert graph.get_dependents("A") == []

    def test_get_dependents_unknown_skill(self) -> None:
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A"))
        assert graph.get_dependents("nonexistent") == []


class TestCheckVersionCompatibility:
    def test_compatible_versions_no_warnings(self) -> None:
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A", version="1.0.0"))
        graph.add_skill(
            _skill("B", depends_on=["A"], compatible_versions={"A": "1.0.0"})
        )
        assert graph.check_version_compatibility("B") == []

    def test_incompatible_version_warns(self) -> None:
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A", version="2.0.0"))
        graph.add_skill(
            _skill("B", depends_on=["A"], compatible_versions={"A": "1.0.0"})
        )
        warnings = graph.check_version_compatibility("B")
        assert len(warnings) == 1
        assert "requires" in warnings[0]
        assert "v1.0.0" in warnings[0]
        assert "v2.0.0" in warnings[0]

    def test_no_compatible_versions_specified(self) -> None:
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A", version="1.0.0"))
        graph.add_skill(_skill("B", depends_on=["A"]))
        assert graph.check_version_compatibility("B") == []

    def test_unknown_skill_returns_empty(self) -> None:
        graph = SkillDependencyGraph()
        assert graph.check_version_compatibility("nonexistent") == []

    def test_dep_has_no_version_no_warning(self) -> None:
        """If the dependency has no version set, no comparison is made."""
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A"))  # no version
        graph.add_skill(
            _skill("B", compatible_versions={"A": "1.0.0"})
        )
        assert graph.check_version_compatibility("B") == []

    def test_required_version_empty_string_no_warning(self) -> None:
        """Empty required version string should not produce a warning."""
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A", version="1.0.0"))
        graph.add_skill(
            _skill("B", compatible_versions={"A": ""})
        )
        assert graph.check_version_compatibility("B") == []

    def test_multiple_incompatibilities(self) -> None:
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A", version="2.0"))
        graph.add_skill(_skill("C", version="3.0"))
        graph.add_skill(
            _skill(
                "B",
                compatible_versions={"A": "1.0", "C": "1.0"},
            )
        )
        warnings = graph.check_version_compatibility("B")
        assert len(warnings) == 2


class TestToDict:
    def test_empty_graph(self) -> None:
        graph = SkillDependencyGraph()
        assert graph.to_dict() == {}

    def test_serialization(self) -> None:
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A", version="1.0"))
        graph.add_skill(_skill("B", depends_on=["A"], version="2.0"))
        result = graph.to_dict()
        assert result == {
            "A": {"depends_on": [], "version": "1.0"},
            "B": {"depends_on": ["A"], "version": "2.0"},
        }

    def test_serialization_does_not_include_compatible_versions(self) -> None:
        """to_dict only serializes depends_on and version."""
        graph = SkillDependencyGraph()
        graph.add_skill(
            _skill("A", version="1.0", compatible_versions={"X": "1.0"})
        )
        result = graph.to_dict()
        assert "compatible_versions" not in result["A"]

    def test_serialization_multiple_skills(self) -> None:
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("X"))
        graph.add_skill(_skill("Y"))
        graph.add_skill(_skill("Z", depends_on=["X", "Y"]))
        result = graph.to_dict()
        assert len(result) == 3
        assert set(result["Z"]["depends_on"]) == {"X", "Y"}


class TestComplexDependencyChains:
    def test_long_chain(self) -> None:
        """A -> B -> C -> D -> E: linear chain of 5 skills."""
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A"))
        graph.add_skill(_skill("B", depends_on=["A"]))
        graph.add_skill(_skill("C", depends_on=["B"]))
        graph.add_skill(_skill("D", depends_on=["C"]))
        graph.add_skill(_skill("E", depends_on=["D"]))
        order = graph.resolve_order()
        assert order == ["A", "B", "C", "D", "E"]

    def test_wide_graph(self) -> None:
        """Root with many children: all depend on root."""
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("root"))
        children = [f"child-{i}" for i in range(10)]
        for child in children:
            graph.add_skill(_skill(child, depends_on=["root"]))
        order = graph.resolve_order()
        assert order[0] == "root"
        assert set(order[1:]) == set(children)

    def test_mixed_chain_and_diamond(self) -> None:
        """
        A -> B -> D
        A -> C -> D
        D -> E
        """
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A"))
        graph.add_skill(_skill("B", depends_on=["A"]))
        graph.add_skill(_skill("C", depends_on=["A"]))
        graph.add_skill(_skill("D", depends_on=["B", "C"]))
        graph.add_skill(_skill("E", depends_on=["D"]))
        order = graph.resolve_order()
        assert order.index("A") < order.index("B")
        assert order.index("A") < order.index("C")
        assert order.index("B") < order.index("D")
        assert order.index("C") < order.index("D")
        assert order.index("D") < order.index("E")

    def test_partial_cycle_in_larger_graph(self) -> None:
        """Non-cyclic skill A exists, but B<->C form a cycle."""
        graph = SkillDependencyGraph()
        graph.add_skill(_skill("A"))
        graph.add_skill(_skill("B", depends_on=["A", "C"]))
        graph.add_skill(_skill("C", depends_on=["B"]))
        with pytest.raises(SkillDependencyError, match="Circular dependency"):
            graph.resolve_order()
