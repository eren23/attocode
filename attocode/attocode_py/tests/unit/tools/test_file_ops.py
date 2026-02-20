"""Tests for file operation tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from attocode.tools.file_ops import (
    edit_file,
    glob_files,
    list_files,
    read_file,
    write_file,
    create_file_tools,
)


class TestReadFile:
    @pytest.mark.asyncio
    async def test_read_existing_file(self, tmp_workdir: Path) -> None:
        f = tmp_workdir / "test.txt"
        f.write_text("line1\nline2\nline3\n")
        result = await read_file({"path": str(f)})
        assert "line1" in result
        assert "line2" in result
        assert "line3" in result

    @pytest.mark.asyncio
    async def test_read_with_line_numbers(self, tmp_workdir: Path) -> None:
        f = tmp_workdir / "test.txt"
        f.write_text("alpha\nbeta\ngamma\n")
        result = await read_file({"path": str(f)})
        # Should have line numbers
        assert "1" in result
        assert "alpha" in result

    @pytest.mark.asyncio
    async def test_read_nonexistent(self, tmp_workdir: Path) -> None:
        result = await read_file({"path": str(tmp_workdir / "missing.txt")})
        assert "Error" in result
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_read_directory(self, tmp_workdir: Path) -> None:
        result = await read_file({"path": str(tmp_workdir)})
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_read_with_offset_and_limit(self, tmp_workdir: Path) -> None:
        f = tmp_workdir / "test.txt"
        f.write_text("line1\nline2\nline3\nline4\nline5\n")
        result = await read_file({"path": str(f), "offset": 1, "limit": 2})
        assert "line2" in result
        assert "line3" in result
        assert "line1" not in result
        assert "line4" not in result

    @pytest.mark.asyncio
    async def test_read_empty_file(self, tmp_workdir: Path) -> None:
        f = tmp_workdir / "empty.txt"
        f.write_text("")
        result = await read_file({"path": str(f)})
        assert "empty" in result.lower()

    @pytest.mark.asyncio
    async def test_read_relative_path(self, tmp_workdir: Path) -> None:
        f = tmp_workdir / "relative.txt"
        f.write_text("content here")
        result = await read_file({"path": "relative.txt"}, working_dir=str(tmp_workdir))
        assert "content here" in result


class TestWriteFile:
    @pytest.mark.asyncio
    async def test_write_new_file(self, tmp_workdir: Path) -> None:
        f = tmp_workdir / "new.txt"
        result = await write_file({"path": str(f), "content": "hello world"})
        assert "Successfully" in result
        assert f.read_text() == "hello world"

    @pytest.mark.asyncio
    async def test_write_creates_dirs(self, tmp_workdir: Path) -> None:
        f = tmp_workdir / "sub" / "dir" / "file.txt"
        result = await write_file({"path": str(f), "content": "nested"})
        assert "Successfully" in result
        assert f.read_text() == "nested"

    @pytest.mark.asyncio
    async def test_write_overwrite(self, tmp_workdir: Path) -> None:
        f = tmp_workdir / "existing.txt"
        f.write_text("old content")
        await write_file({"path": str(f), "content": "new content"})
        assert f.read_text() == "new content"


class TestEditFile:
    @pytest.mark.asyncio
    async def test_edit_replace(self, tmp_workdir: Path) -> None:
        f = tmp_workdir / "edit.txt"
        f.write_text("hello world")
        result = await edit_file({
            "path": str(f),
            "old_string": "world",
            "new_string": "python",
        })
        assert "Successfully" in result
        assert f.read_text() == "hello python"

    @pytest.mark.asyncio
    async def test_edit_not_found(self, tmp_workdir: Path) -> None:
        f = tmp_workdir / "edit.txt"
        f.write_text("hello world")
        result = await edit_file({
            "path": str(f),
            "old_string": "missing",
            "new_string": "replaced",
        })
        assert "Error" in result
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_edit_multiple_occurrences(self, tmp_workdir: Path) -> None:
        f = tmp_workdir / "edit.txt"
        f.write_text("foo bar foo baz foo")
        result = await edit_file({
            "path": str(f),
            "old_string": "foo",
            "new_string": "qux",
        })
        assert "Error" in result
        assert "3 times" in result

    @pytest.mark.asyncio
    async def test_edit_replace_all(self, tmp_workdir: Path) -> None:
        f = tmp_workdir / "edit.txt"
        f.write_text("foo bar foo baz foo")
        result = await edit_file({
            "path": str(f),
            "old_string": "foo",
            "new_string": "qux",
            "replace_all": True,
        })
        assert "Successfully" in result
        assert f.read_text() == "qux bar qux baz qux"

    @pytest.mark.asyncio
    async def test_edit_nonexistent_file(self, tmp_workdir: Path) -> None:
        result = await edit_file({
            "path": str(tmp_workdir / "missing.txt"),
            "old_string": "a",
            "new_string": "b",
        })
        assert "Error" in result


class TestListFiles:
    @pytest.mark.asyncio
    async def test_list_directory(self, tmp_workdir: Path) -> None:
        (tmp_workdir / "a.txt").write_text("a")
        (tmp_workdir / "b.py").write_text("b")
        (tmp_workdir / "subdir").mkdir()
        result = await list_files({"path": str(tmp_workdir)})
        assert "a.txt" in result
        assert "b.py" in result
        assert "subdir/" in result

    @pytest.mark.asyncio
    async def test_list_hides_dotfiles(self, tmp_workdir: Path) -> None:
        (tmp_workdir / ".hidden").write_text("hidden")
        (tmp_workdir / "visible.txt").write_text("visible")
        result = await list_files({"path": str(tmp_workdir)})
        assert ".hidden" not in result
        assert "visible.txt" in result

    @pytest.mark.asyncio
    async def test_list_nonexistent(self, tmp_workdir: Path) -> None:
        result = await list_files({"path": str(tmp_workdir / "missing")})
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_list_empty(self, tmp_workdir: Path) -> None:
        result = await list_files({"path": str(tmp_workdir)})
        assert "empty" in result.lower()


class TestGlobFiles:
    @pytest.mark.asyncio
    async def test_glob_pattern(self, tmp_workdir: Path) -> None:
        (tmp_workdir / "a.py").write_text("a")
        (tmp_workdir / "b.py").write_text("b")
        (tmp_workdir / "c.txt").write_text("c")
        result = await glob_files({"pattern": "*.py", "path": str(tmp_workdir)})
        assert "a.py" in result
        assert "b.py" in result
        assert "c.txt" not in result

    @pytest.mark.asyncio
    async def test_glob_recursive(self, tmp_workdir: Path) -> None:
        sub = tmp_workdir / "sub"
        sub.mkdir()
        (sub / "deep.py").write_text("deep")
        result = await glob_files({"pattern": "**/*.py", "path": str(tmp_workdir)})
        assert "deep.py" in result

    @pytest.mark.asyncio
    async def test_glob_no_matches(self, tmp_workdir: Path) -> None:
        result = await glob_files({"pattern": "*.xyz", "path": str(tmp_workdir)})
        assert "No matches" in result

    @pytest.mark.asyncio
    async def test_glob_max_results(self, tmp_workdir: Path) -> None:
        for i in range(10):
            (tmp_workdir / f"file{i}.txt").write_text(str(i))
        result = await glob_files({
            "pattern": "*.txt",
            "path": str(tmp_workdir),
            "max_results": 3,
        })
        assert "more" in result.lower()


class TestCreateFileTools:
    def test_creates_five_tools(self) -> None:
        tools = create_file_tools("/tmp/test")
        assert len(tools) == 5
        names = [t.name for t in tools]
        assert "read_file" in names
        assert "write_file" in names
        assert "edit_file" in names
        assert "list_files" in names
        assert "glob_files" in names
