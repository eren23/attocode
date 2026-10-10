"""Search must not depend on the order in which the file system lists a folder."""

import os

from attocode_intel._internal.integrations.context.codebase_context import CodebaseContextManager
from attocode_intel._internal.integrations.context.trigram_index import TrigramIndex


def test_file_lists_do_not_depend_on_the_file_system_order(tmp_path, monkeypatch):
    for name in ("b/x.py", "a/y.py", "a/x.py", "c.py", "b.py", "a/z/w.py"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def f():\n    return 1\n")

    def lists():
        found = CodebaseContextManager(root_dir=str(tmp_path)).discover_files()
        return [f.relative_path for f in found], TrigramIndex._enumerate_files(tmp_path)

    first = lists()
    real_walk = os.walk

    def reversed_walk(top, *args, **kwargs):  # macOS (APFS) and Linux list a folder in other orders
        for dirpath, dirnames, filenames in real_walk(top, *args, **kwargs):
            dirnames.reverse()
            filenames.reverse()
            yield dirpath, dirnames, filenames

    monkeypatch.setattr(os, "walk", reversed_walk)
    assert lists() == first
