"""Tests for attoswarm.protocol.io — atomic writes, JSON read, JSONL append.

P0 critical: these 49 LOC underlie ALL state persistence.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import pytest

from attoswarm.protocol.io import (
    append_jsonl,
    ensure_parent,
    read_json,
    write_json_atomic,
    write_json_fast,
)


# ── ensure_parent ─────────────────────────────────────────────────────


class TestEnsureParent:
    def test_creates_nested_dirs(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "c" / "file.json"
        ensure_parent(target)
        assert target.parent.is_dir()

    def test_existing_dir_no_error(self, tmp_path: Path) -> None:
        target = tmp_path / "file.json"
        ensure_parent(target)
        ensure_parent(target)  # idempotent


# ── read_json ─────────────────────────────────────────────────────────


class TestReadJson:
    def test_missing_file_returns_default(self, tmp_path: Path) -> None:
        result = read_json(tmp_path / "nope.json", default={"ok": True})
        assert result == {"ok": True}

    def test_valid_json(self, tmp_path: Path) -> None:
        p = tmp_path / "data.json"
        p.write_text('{"key": "value"}', encoding="utf-8")
        assert read_json(p, default={}) == {"key": "value"}

    def test_corrupt_json_returns_default(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("{not valid json", encoding="utf-8")
        assert read_json(p, default="fallback") == "fallback"

    def test_empty_file_returns_default(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.json"
        p.write_text("", encoding="utf-8")
        assert read_json(p, default=[]) == []

    def test_reads_list(self, tmp_path: Path) -> None:
        p = tmp_path / "list.json"
        p.write_text("[1, 2, 3]", encoding="utf-8")
        assert read_json(p, default=[]) == [1, 2, 3]

    def test_reads_scalar(self, tmp_path: Path) -> None:
        p = tmp_path / "scalar.json"
        p.write_text("42", encoding="utf-8")
        assert read_json(p, default=0) == 42

    def test_permission_error_returns_default(self, tmp_path: Path) -> None:
        p = tmp_path / "no_read.json"
        p.write_text('{"a": 1}', encoding="utf-8")
        p.chmod(0o000)
        try:
            assert read_json(p, default="safe") == "safe"
        finally:
            p.chmod(0o644)

    def test_unicode_content(self, tmp_path: Path) -> None:
        p = tmp_path / "unicode.json"
        p.write_text('{"emoji": "\\u2603"}', encoding="utf-8")
        assert read_json(p, default={}) == {"emoji": "\u2603"}


# ── write_json_atomic ─────────────────────────────────────────────────


class TestWriteJsonAtomic:
    def test_roundtrip(self, tmp_path: Path) -> None:
        p = tmp_path / "out.json"
        data = {"tasks": [1, 2, 3], "nested": {"key": True}}
        write_json_atomic(p, data)
        assert read_json(p, default=None) == data

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        p = tmp_path / "deep" / "nested" / "out.json"
        write_json_atomic(p, {"ok": True})
        assert p.exists()
        assert read_json(p, default=None) == {"ok": True}

    def test_tmp_file_cleaned_up(self, tmp_path: Path) -> None:
        p = tmp_path / "clean.json"
        write_json_atomic(p, {"data": 1})
        tmp_file = p.with_suffix(".json.tmp")
        assert not tmp_file.exists()

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        p = tmp_path / "over.json"
        write_json_atomic(p, {"v": 1})
        write_json_atomic(p, {"v": 2})
        assert read_json(p, default=None) == {"v": 2}

    def test_file_ends_with_newline(self, tmp_path: Path) -> None:
        p = tmp_path / "nl.json"
        write_json_atomic(p, {"a": 1})
        assert p.read_text(encoding="utf-8").endswith("\n")

    def test_preserves_key_order(self, tmp_path: Path) -> None:
        """sort_keys=False should preserve insertion order."""
        p = tmp_path / "order.json"
        data = {"z": 1, "a": 2, "m": 3}
        write_json_atomic(p, data)
        content = p.read_text(encoding="utf-8")
        z_pos = content.index('"z"')
        a_pos = content.index('"a"')
        m_pos = content.index('"m"')
        assert z_pos < a_pos < m_pos


# ── write_json_fast ───────────────────────────────────────────────────


class TestWriteJsonFast:
    def test_roundtrip(self, tmp_path: Path) -> None:
        p = tmp_path / "fast.json"
        data = {"speed": True}
        write_json_fast(p, data)
        assert read_json(p, default=None) == data

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        p = tmp_path / "sub" / "fast.json"
        write_json_fast(p, [1, 2])
        assert p.exists()

    def test_tmp_file_cleaned_up(self, tmp_path: Path) -> None:
        p = tmp_path / "clean_fast.json"
        write_json_fast(p, {"x": 1})
        tmp_file = p.with_suffix(".json.tmp")
        assert not tmp_file.exists()


# ── append_jsonl ──────────────────────────────────────────────────────


class TestAppendJsonl:
    def test_creates_file(self, tmp_path: Path) -> None:
        p = tmp_path / "events.jsonl"
        append_jsonl(p, {"type": "spawn"})
        assert p.exists()
        lines = p.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0]) == {"type": "spawn"}

    def test_appends_multiple(self, tmp_path: Path) -> None:
        p = tmp_path / "multi.jsonl"
        append_jsonl(p, {"seq": 1})
        append_jsonl(p, {"seq": 2})
        append_jsonl(p, {"seq": 3})
        lines = p.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3
        assert [json.loads(line)["seq"] for line in lines] == [1, 2, 3]

    def test_each_line_is_valid_json(self, tmp_path: Path) -> None:
        p = tmp_path / "valid.jsonl"
        for i in range(5):
            append_jsonl(p, {"i": i, "nested": {"a": [1, 2]}})
        for line in p.read_text(encoding="utf-8").strip().splitlines():
            json.loads(line)  # should not raise

    def test_lines_end_with_newline(self, tmp_path: Path) -> None:
        p = tmp_path / "nl.jsonl"
        append_jsonl(p, {"a": 1})
        raw = p.read_text(encoding="utf-8")
        assert raw.endswith("\n")

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        p = tmp_path / "sub" / "dir" / "events.jsonl"
        append_jsonl(p, {"ok": True})
        assert p.exists()

    def test_ordering_under_sequential_appends(self, tmp_path: Path) -> None:
        """Multiple sequential appends maintain insertion order."""
        p = tmp_path / "order.jsonl"
        for i in range(20):
            append_jsonl(p, {"seq": i})
        lines = p.read_text(encoding="utf-8").strip().splitlines()
        seqs = [json.loads(line)["seq"] for line in lines]
        assert seqs == list(range(20))


# ── Integration: concurrent writers ───────────────────────────────────


class TestConcurrentAccess:
    def test_concurrent_jsonl_appends(self, tmp_path: Path) -> None:
        """Multiple threads appending JSONL should not corrupt the file."""
        p = tmp_path / "concurrent.jsonl"
        n_threads = 4
        n_writes = 25

        def writer(thread_id: int) -> None:
            for i in range(n_writes):
                append_jsonl(p, {"tid": thread_id, "seq": i})

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        lines = p.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == n_threads * n_writes
        # Every line should be parseable JSON
        for line in lines:
            obj = json.loads(line)
            assert "tid" in obj and "seq" in obj

    def test_concurrent_atomic_writes_to_separate_files(self, tmp_path: Path) -> None:
        """Concurrent atomic writes to separate files should not corrupt any."""
        n_threads = 4
        n_writes = 15

        def writer(thread_id: int) -> None:
            p = tmp_path / f"atomic-{thread_id}.json"
            for i in range(n_writes):
                write_json_atomic(p, {"tid": thread_id, "seq": i})

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Each file should be valid JSON with last write
        for t in range(n_threads):
            result = read_json(tmp_path / f"atomic-{t}.json", default=None)
            assert result is not None
            assert result["tid"] == t
            assert result["seq"] == n_writes - 1
