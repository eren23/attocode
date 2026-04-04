"""Focused tests for CLI query-oriented command handlers."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_cmd_query_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from attocode.code_intel.cli import _cmd_query

    observed: dict[str, object] = {}

    class _FakeService:
        def __init__(self, project_dir: str):
            observed["project_dir"] = project_dir

        def semantic_search_data(self, query: str, top_k: int, file_filter: str) -> dict[str, object]:
            observed["query"] = query
            observed["top_k"] = top_k
            observed["file_filter"] = file_filter
            return {"results": [{"file_path": "src/app.py"}], "query": query, "total": 1}

    monkeypatch.setattr("attocode.code_intel.service.CodeIntelService", _FakeService)
    monkeypatch.setattr(
        "attocode.code_intel.cli._print_search_results",
        lambda data: observed.setdefault("printed", data),
    )

    _cmd_query(["find", "router", "--top", "7", "--filter", "*.py", "--project", str(tmp_path)])

    assert observed["project_dir"] == str(tmp_path.resolve())
    assert observed["query"] == "find router"
    assert observed["top_k"] == 7
    assert observed["file_filter"] == "*.py"
    assert observed["printed"] == {"results": [{"file_path": "src/app.py"}], "query": "find router", "total": 1}


def test_cmd_query_requires_text(capsys: pytest.CaptureFixture[str]) -> None:
    from attocode.code_intel.cli import _cmd_query

    with pytest.raises(SystemExit) as exc_info:
        _cmd_query([])
    captured = capsys.readouterr()

    assert exc_info.value.code == 1
    assert "Usage: attocode code-intel query <text>" in captured.err


def test_cmd_symbols_search_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from attocode.code_intel.cli import _cmd_symbols

    observed: dict[str, object] = {}

    class _FakeService:
        def __init__(self, project_dir: str):
            observed["project_dir"] = project_dir

        def search_symbols_data(self, search_name: str) -> list[dict[str, object]]:
            observed["search_name"] = search_name
            return [{"name": "Router", "kind": "class"}]

    monkeypatch.setattr("attocode.code_intel.service.CodeIntelService", _FakeService)
    monkeypatch.setattr(
        "attocode.code_intel.cli._print_symbols_table",
        lambda data, title="Symbols": observed.setdefault("printed", (data, title)),
    )

    _cmd_symbols(["--search", "Router", "--project", str(tmp_path)])

    assert observed["project_dir"] == str(tmp_path.resolve())
    assert observed["search_name"] == "Router"
    assert observed["printed"] == ([{"name": "Router", "kind": "class"}], "Search results for 'Router'")


def test_cmd_symbols_file_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from attocode.code_intel.cli import _cmd_symbols

    observed: dict[str, object] = {}

    class _FakeService:
        def __init__(self, project_dir: str):
            observed["project_dir"] = project_dir

        def symbols_data(self, target_file: str) -> list[dict[str, object]]:
            observed["target_file"] = target_file
            return [{"name": "main", "kind": "function"}]

    monkeypatch.setattr("attocode.code_intel.service.CodeIntelService", _FakeService)
    monkeypatch.setattr(
        "attocode.code_intel.cli._print_symbols_table",
        lambda data, title="Symbols": observed.setdefault("printed", (data, title)),
    )

    _cmd_symbols(["src/app.py", "--project", str(tmp_path)])

    assert observed["target_file"] == "src/app.py"
    assert observed["printed"] == ([{"name": "main", "kind": "function"}], "Symbols in src/app.py")


def test_cmd_symbols_requires_target_or_search(capsys: pytest.CaptureFixture[str]) -> None:
    from attocode.code_intel.cli import _cmd_symbols

    with pytest.raises(SystemExit) as exc_info:
        _cmd_symbols([])
    captured = capsys.readouterr()

    assert exc_info.value.code == 1
    assert "Usage: attocode code-intel symbols <file>" in captured.err


def test_cmd_impact_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from attocode.code_intel.cli import _cmd_impact

    observed: dict[str, object] = {}

    class _FakeService:
        def __init__(self, project_dir: str):
            observed["project_dir"] = project_dir

        def impact_analysis_data(self, files: list[str]) -> dict[str, object]:
            observed["files"] = files
            return {"changed_files": files, "impacted_files": [], "total_impacted": 0, "layers": []}

    monkeypatch.setattr("attocode.code_intel.service.CodeIntelService", _FakeService)
    monkeypatch.setattr(
        "attocode.code_intel.cli._print_impact_analysis",
        lambda data: observed.setdefault("printed", data),
    )

    _cmd_impact(["src/a.py", "src/b.py", "--project", str(tmp_path)])

    assert observed["files"] == ["src/a.py", "src/b.py"]
    assert observed["printed"]["changed_files"] == ["src/a.py", "src/b.py"]


def test_cmd_impact_requires_files(capsys: pytest.CaptureFixture[str]) -> None:
    from attocode.code_intel.cli import _cmd_impact

    with pytest.raises(SystemExit) as exc_info:
        _cmd_impact([])
    captured = capsys.readouterr()

    assert exc_info.value.code == 1
    assert "Usage: attocode code-intel impact <file>" in captured.err


def test_cmd_hotspots_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from attocode.code_intel.cli import _cmd_hotspots

    observed: dict[str, object] = {}

    class _FakeService:
        def __init__(self, project_dir: str):
            observed["project_dir"] = project_dir

        def hotspots_data(self, top_n: int) -> dict[str, object]:
            observed["top_n"] = top_n
            return {"file_hotspots": [], "function_hotspots": [], "orphan_files": []}

    monkeypatch.setattr("attocode.code_intel.service.CodeIntelService", _FakeService)
    monkeypatch.setattr(
        "attocode.code_intel.cli._print_hotspots",
        lambda data: observed.setdefault("printed", data),
    )

    _cmd_hotspots(["--top=6", "--project", str(tmp_path)])

    assert observed["top_n"] == 6
    assert observed["printed"] == {"file_hotspots": [], "function_hotspots": [], "orphan_files": []}


def test_cmd_deps_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from attocode.code_intel.cli import _cmd_deps

    observed: dict[str, object] = {}

    class _FakeService:
        def __init__(self, project_dir: str):
            observed["project_dir"] = project_dir

        def dependencies_data(self, target_file: str) -> dict[str, object]:
            observed["target_file"] = target_file
            return {"path": target_file, "imports": ["a.py"], "imported_by": ["b.py"]}

    monkeypatch.setattr("attocode.code_intel.service.CodeIntelService", _FakeService)
    monkeypatch.setattr(
        "attocode.code_intel.cli._print_dependencies",
        lambda data: observed.setdefault("printed", data),
    )

    _cmd_deps(["src/app.py", "--project", str(tmp_path)])

    assert observed["target_file"] == "src/app.py"
    assert observed["printed"]["path"] == "src/app.py"


def test_cmd_deps_requires_target(capsys: pytest.CaptureFixture[str]) -> None:
    from attocode.code_intel.cli import _cmd_deps

    with pytest.raises(SystemExit) as exc_info:
        _cmd_deps([])
    captured = capsys.readouterr()

    assert exc_info.value.code == 1
    assert "Usage: attocode code-intel deps <file>" in captured.err
