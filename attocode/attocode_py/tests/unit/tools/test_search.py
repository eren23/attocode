"""Tests for search tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from attocode.tools.search import create_search_tools, grep_search


class TestGrepSearch:
    @pytest.mark.asyncio
    async def test_basic_search(self, tmp_workdir: Path) -> None:
        (tmp_workdir / "test.py").write_text("def hello():\n    return 'world'\n")
        result = await grep_search({"pattern": "hello", "path": str(tmp_workdir)})
        assert "hello" in result
        assert "test.py" in result

    @pytest.mark.asyncio
    async def test_regex_search(self, tmp_workdir: Path) -> None:
        (tmp_workdir / "test.py").write_text("def foo_bar():\ndef baz_qux():\n")
        result = await grep_search({"pattern": r"def \w+_\w+", "path": str(tmp_workdir)})
        assert "foo_bar" in result
        assert "baz_qux" in result

    @pytest.mark.asyncio
    async def test_case_insensitive(self, tmp_workdir: Path) -> None:
        (tmp_workdir / "test.txt").write_text("Hello World\nhello world\nHELLO WORLD\n")
        result = await grep_search({
            "pattern": "hello",
            "path": str(tmp_workdir),
            "case_insensitive": True,
        })
        assert result.count(":") >= 3  # Should find all 3 lines

    @pytest.mark.asyncio
    async def test_glob_filter(self, tmp_workdir: Path) -> None:
        (tmp_workdir / "code.py").write_text("import os\n")
        (tmp_workdir / "readme.md").write_text("import os\n")
        result = await grep_search({
            "pattern": "import",
            "path": str(tmp_workdir),
            "glob": "*.py",
        })
        assert "code.py" in result
        assert "readme.md" not in result

    @pytest.mark.asyncio
    async def test_max_results(self, tmp_workdir: Path) -> None:
        lines = "\n".join([f"match line {i}" for i in range(100)])
        (tmp_workdir / "big.txt").write_text(lines)
        result = await grep_search({
            "pattern": "match",
            "path": str(tmp_workdir),
            "max_results": 5,
        })
        assert "limited to 5" in result.lower()

    @pytest.mark.asyncio
    async def test_no_matches(self, tmp_workdir: Path) -> None:
        (tmp_workdir / "test.txt").write_text("hello world\n")
        result = await grep_search({"pattern": "nonexistent", "path": str(tmp_workdir)})
        assert "No matches" in result

    @pytest.mark.asyncio
    async def test_invalid_regex(self, tmp_workdir: Path) -> None:
        result = await grep_search({"pattern": "[invalid", "path": str(tmp_workdir)})
        assert "Error" in result
        assert "regex" in result.lower()

    @pytest.mark.asyncio
    async def test_nonexistent_path(self) -> None:
        result = await grep_search({"pattern": "test", "path": "/nonexistent/path"})
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_search_single_file(self, tmp_workdir: Path) -> None:
        f = tmp_workdir / "single.py"
        f.write_text("def foo():\n    pass\ndef bar():\n    pass\n")
        result = await grep_search({"pattern": "def", "path": str(f)})
        assert "foo" in result
        assert "bar" in result

    @pytest.mark.asyncio
    async def test_line_numbers(self, tmp_workdir: Path) -> None:
        (tmp_workdir / "lines.txt").write_text("aaa\nbbb\nccc\n")
        result = await grep_search({"pattern": "bbb", "path": str(tmp_workdir)})
        assert ":2:" in result

    @pytest.mark.asyncio
    async def test_skips_binary_files(self, tmp_workdir: Path) -> None:
        (tmp_workdir / "binary.bin").write_bytes(b"\x00\x01\x02\xff")
        (tmp_workdir / "text.txt").write_text("searchable\n")
        result = await grep_search({"pattern": "searchable", "path": str(tmp_workdir)})
        assert "text.txt" in result

    @pytest.mark.asyncio
    async def test_recursive_search(self, tmp_workdir: Path) -> None:
        sub = tmp_workdir / "sub" / "deep"
        sub.mkdir(parents=True)
        (sub / "nested.py").write_text("found_me = True\n")
        result = await grep_search({"pattern": "found_me", "path": str(tmp_workdir)})
        assert "found_me" in result


class TestCreateSearchTools:
    def test_creates_grep_tool(self) -> None:
        tools = create_search_tools()
        assert len(tools) == 1
        assert tools[0].name == "grep"
