"""Tests for dynamic tool creation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from attocode.tools.dynamic import (
    DynamicToolError,
    DynamicToolRegistry,
    DynamicToolSpec,
)


class TestDynamicToolSpec:
    def test_to_dict_roundtrip(self) -> None:
        spec = DynamicToolSpec(
            name="greet",
            description="Greet someone",
            parameters_schema={"type": "object", "properties": {"name": {"type": "string"}}},
            python_code="def run(name='World'):\n    return f'Hello, {name}!'",
        )
        data = spec.to_dict()
        restored = DynamicToolSpec.from_dict(data)
        assert restored.name == spec.name
        assert restored.python_code == spec.python_code


class TestDynamicToolRegistry:
    def test_define_and_execute(self) -> None:
        registry = DynamicToolRegistry()
        registry.define(
            "add",
            "Add two numbers",
            {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}},
            "def run(a=0, b=0):\n    return a + b",
            persist=False,
        )
        result = registry.execute("add", a=3, b=4)
        assert result == 7

    def test_define_invalid_name(self) -> None:
        registry = DynamicToolRegistry()
        with pytest.raises(DynamicToolError, match="Invalid tool name"):
            registry.define("123bad", "desc", {"type": "object"}, "def run(): pass", persist=False)

    def test_define_underscore_name(self) -> None:
        registry = DynamicToolRegistry()
        with pytest.raises(DynamicToolError, match="underscore"):
            registry.define("_private", "desc", {"type": "object"}, "def run(): pass", persist=False)

    def test_define_bad_schema(self) -> None:
        registry = DynamicToolRegistry()
        with pytest.raises(DynamicToolError, match="type"):
            registry.define("foo", "desc", {"properties": {}}, "def run(): pass", persist=False)

    def test_define_syntax_error(self) -> None:
        registry = DynamicToolRegistry()
        with pytest.raises(DynamicToolError, match="Syntax error"):
            registry.define("foo", "desc", {"type": "object"}, "def run(:\n  pass", persist=False)

    def test_blocked_builtins(self) -> None:
        registry = DynamicToolRegistry()
        with pytest.raises(DynamicToolError, match="blocked builtin"):
            registry.define(
                "evil", "bad", {"type": "object"},
                "def run():\n    return open('/etc/passwd').read()",
                persist=False,
            )

    def test_execute_unknown_tool(self) -> None:
        registry = DynamicToolRegistry()
        with pytest.raises(DynamicToolError, match="Unknown"):
            registry.execute("nonexistent")

    def test_execute_no_run_function(self) -> None:
        registry = DynamicToolRegistry()
        registry.define("norun", "desc", {"type": "object"}, "x = 42", persist=False)
        with pytest.raises(DynamicToolError, match="run"):
            registry.execute("norun")

    def test_execute_runtime_error(self) -> None:
        registry = DynamicToolRegistry()
        registry.define(
            "divzero", "desc", {"type": "object"},
            "def run():\n    return 1 / 0",
            persist=False,
        )
        with pytest.raises(DynamicToolError, match="execution failed"):
            registry.execute("divzero")

    def test_unregister(self) -> None:
        registry = DynamicToolRegistry()
        registry.define("foo", "desc", {"type": "object"}, "def run(): return 1", persist=False)
        assert registry.unregister("foo") is True
        assert registry.unregister("foo") is False
        assert "foo" not in registry.tools

    def test_list_tools(self) -> None:
        registry = DynamicToolRegistry()
        registry.define("a", "Tool A", {"type": "object"}, "def run(): return 'a'", persist=False)
        registry.define("b", "Tool B", {"type": "object"}, "def run(): return 'b'", persist=False)
        tools = registry.list_tools()
        assert len(tools) == 2
        names = {t["name"] for t in tools}
        assert names == {"a", "b"}

    def test_persistence_roundtrip(self, tmp_path: Path) -> None:
        persist_dir = tmp_path / "tools"
        reg1 = DynamicToolRegistry(persist_dir=persist_dir)
        reg1.define(
            "greet", "Say hello",
            {"type": "object", "properties": {"name": {"type": "string"}}},
            "def run(name='World'):\n    return f'Hello, {name}!'",
        )
        assert (persist_dir / "greet.json").exists()

        reg2 = DynamicToolRegistry(persist_dir=persist_dir)
        count = reg2.load_persisted()
        assert count == 1
        assert reg2.execute("greet", name="Alice") == "Hello, Alice!"

    def test_unregister_removes_persisted(self, tmp_path: Path) -> None:
        persist_dir = tmp_path / "tools"
        registry = DynamicToolRegistry(persist_dir=persist_dir)
        registry.define("temp", "Temp", {"type": "object"}, "def run(): return 1")
        assert (persist_dir / "temp.json").exists()
        registry.unregister("temp")
        assert not (persist_dir / "temp.json").exists()

    def test_load_persisted_skips_bad_files(self, tmp_path: Path) -> None:
        persist_dir = tmp_path / "tools"
        persist_dir.mkdir()
        (persist_dir / "bad.json").write_text("not valid json")
        registry = DynamicToolRegistry(persist_dir=persist_dir)
        count = registry.load_persisted()
        assert count == 0

    def test_load_persisted_empty_dir(self, tmp_path: Path) -> None:
        registry = DynamicToolRegistry(persist_dir=tmp_path / "nonexistent")
        assert registry.load_persisted() == 0
