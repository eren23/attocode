from pathlib import Path

from attocode_core.ast_index.indexer import CodeIndex


def test_code_index_builds_python_symbols(tmp_path: Path) -> None:
    src = tmp_path / "mod.py"
    src.write_text("import os\n\nclass C:\n    pass\n\ndef f():\n    return 1\n", encoding="utf-8")

    idx = CodeIndex.build(tmp_path)
    assert len(idx.files) == 1
    f = idx.files[0]
    assert f.file_path == "mod.py"
    names = {s.name for s in f.symbols}
    assert {"C", "f"}.issubset(names)
