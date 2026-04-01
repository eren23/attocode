"""Tests for path_security (UNC blocking, traversal heuristics)."""

from __future__ import annotations

import pytest

from attocode.integrations.path_security import contains_traversal, is_unc_path


class TestIsUncPath:
    @pytest.mark.parametrize(
        "path",
        [
            r"\\fileserver\share\doc.txt",
            r"//fileserver/share/x",
            "file:////server/share",
            r"C:\\\server\share",
        ],
    )
    def test_detects_unc_or_network_forms(self, path: str) -> None:
        assert is_unc_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            r"C:\Users\dev\project\main.py",
            r"D:\data\file.txt",
            "/home/user/repo/src/main.py",
            "relative/path/to/file.py",
            "",
        ],
    )
    def test_allows_normal_paths(self, path: str) -> None:
        assert is_unc_path(path) is False


class TestContainsTraversal:
    def test_mid_path_parent_segments_blocked(self) -> None:
        assert contains_traversal("foo/../bar") is True

    def test_system_escape_blocked(self) -> None:
        assert contains_traversal("../../etc/passwd") is True

    def test_user_space_relative_allowed(self) -> None:
        assert contains_traversal("../../pkg/module.py") is False

    def test_encoded_traversal_blocked(self) -> None:
        assert contains_traversal("x/%2e%2e/etc") is True
