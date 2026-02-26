"""Tests for ASTService and CrossRefIndex."""

from __future__ import annotations

from pathlib import Path

import pytest

from attocode.integrations.context.ast_service import ASTService
from attocode.integrations.context.cross_references import (
    CrossRefIndex,
    SymbolLocation,
    SymbolRef,
)


# ---------------------------------------------------------------------------
# CrossRefIndex unit tests
# ---------------------------------------------------------------------------

class TestCrossRefIndex:
    def test_add_and_get_definition(self) -> None:
        idx = CrossRefIndex()
        loc = SymbolLocation(
            name="foo",
            qualified_name="mod.foo",
            kind="function",
            file_path="a.py",
            start_line=1,
            end_line=5,
        )
        idx.add_definition(loc)
        defs = idx.get_definitions("mod.foo")
        assert len(defs) == 1
        assert defs[0].name == "foo"

    def test_get_definitions_suffix_match(self) -> None:
        idx = CrossRefIndex()
        loc = SymbolLocation(
            name="bar",
            qualified_name="pkg.mod.bar",
            kind="function",
            file_path="b.py",
            start_line=10,
            end_line=20,
        )
        idx.add_definition(loc)
        # Simple name "bar" matches via suffix (".bar" endswith check)
        assert len(idx.get_definitions("bar")) == 1
        # Partial qualified name also works
        defs = idx.get_definitions("mod.bar")
        assert len(defs) == 1
        # Full qualified name works via exact match
        defs = idx.get_definitions("pkg.mod.bar")
        assert len(defs) == 1
        # Non-matching name returns empty
        assert len(idx.get_definitions("baz")) == 0

    def test_add_and_get_reference(self) -> None:
        idx = CrossRefIndex()
        ref = SymbolRef(
            symbol_name="foo",
            ref_kind="call",
            file_path="caller.py",
            line=10,
        )
        idx.add_reference(ref)
        refs = idx.get_references("foo")
        assert len(refs) == 1
        assert refs[0].file_path == "caller.py"

    def test_file_dependency_tracking(self) -> None:
        idx = CrossRefIndex()
        idx.add_file_dependency("a.py", "b.py")
        idx.add_file_dependency("a.py", "c.py")
        assert idx.get_dependencies("a.py") == {"b.py", "c.py"}
        assert idx.get_dependents("b.py") == {"a.py"}

    def test_remove_file(self) -> None:
        idx = CrossRefIndex()
        loc = SymbolLocation(
            name="foo", qualified_name="foo", kind="function",
            file_path="a.py", start_line=1, end_line=5,
        )
        idx.add_definition(loc)
        idx.add_reference(SymbolRef(
            symbol_name="foo", ref_kind="call", file_path="a.py", line=10,
        ))
        idx.add_file_dependency("a.py", "b.py")

        idx.remove_file("a.py")
        assert "a.py" not in idx.file_symbols
        assert idx.get_dependencies("a.py") == set()


# ---------------------------------------------------------------------------
# ASTService unit tests
# ---------------------------------------------------------------------------

class TestASTService:
    @pytest.fixture
    def project_dir(self, tmp_path: Path) -> Path:
        """Create a minimal Python project."""
        (tmp_path / "main.py").write_text(
            "from utils import helper\n\ndef main():\n    helper()\n"
        )
        (tmp_path / "utils.py").write_text(
            "def helper():\n    return 42\n\ndef unused():\n    pass\n"
        )
        return tmp_path

    def test_get_instance_singleton(self, project_dir: Path) -> None:
        ASTService.clear_instances()
        svc1 = ASTService.get_instance(str(project_dir))
        svc2 = ASTService.get_instance(str(project_dir))
        assert svc1 is svc2
        ASTService.clear_instances()

    def test_initialize_and_find_symbol(self, project_dir: Path) -> None:
        ASTService.clear_instances()
        svc = ASTService.get_instance(str(project_dir))
        svc.initialize()
        results = svc.find_symbol("helper")
        assert len(results) >= 1
        assert any(loc.name == "helper" for loc in results)
        ASTService.clear_instances()

    def test_get_file_symbols(self, project_dir: Path) -> None:
        ASTService.clear_instances()
        svc = ASTService.get_instance(str(project_dir))
        svc.initialize()
        syms = svc.get_file_symbols("utils.py")
        names = {s.name for s in syms}
        assert "helper" in names
        assert "unused" in names
        ASTService.clear_instances()

    def test_notify_file_changed(self, project_dir: Path) -> None:
        ASTService.clear_instances()
        svc = ASTService.get_instance(str(project_dir))
        svc.initialize()

        # Modify a file
        (project_dir / "utils.py").write_text(
            "def helper():\n    return 99\n\ndef new_func():\n    pass\n"
        )
        changes = svc.notify_file_changed("utils.py")
        # Should detect modifications
        assert isinstance(changes, list)
        ASTService.clear_instances()

    def test_detect_conflicts(self, project_dir: Path) -> None:
        ASTService.clear_instances()
        svc = ASTService.get_instance(str(project_dir))
        svc.initialize()
        # Same file in both sets → conflict
        conflicts = svc.detect_conflicts(["utils.py"], ["utils.py"])
        assert len(conflicts) > 0
        assert any("direct" in c.get("kind", "") for c in conflicts)
        ASTService.clear_instances()

    def test_detect_no_conflicts(self, project_dir: Path) -> None:
        ASTService.clear_instances()
        svc = ASTService.get_instance(str(project_dir))
        svc.initialize()
        # Different files → no direct conflict
        conflicts = svc.detect_conflicts(["main.py"], ["utils.py"])
        direct = [c for c in conflicts if c.get("kind") == "direct_overlap"]
        assert len(direct) == 0
        ASTService.clear_instances()

    def test_suggest_related_files(self, project_dir: Path) -> None:
        ASTService.clear_instances()
        svc = ASTService.get_instance(str(project_dir))
        svc.initialize()
        related = svc.suggest_related_files(["main.py"])
        # utils.py is imported by main.py, so it should be suggested
        assert isinstance(related, list)
        ASTService.clear_instances()

    def test_get_impact(self, project_dir: Path) -> None:
        ASTService.clear_instances()
        svc = ASTService.get_instance(str(project_dir))
        svc.initialize()
        impact = svc.get_impact(["utils.py"])
        assert isinstance(impact, set)
        ASTService.clear_instances()
