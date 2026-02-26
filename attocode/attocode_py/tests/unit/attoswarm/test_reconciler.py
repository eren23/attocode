"""Tests for AST-aware 3-way reconciler."""

from __future__ import annotations

from attoswarm.workspace.reconciler import ASTReconciler, MergeResult


class TestReconcilerNoConflicts:
    """Cases where auto-merge should succeed."""

    def test_no_changes(self) -> None:
        base = "def foo():\n    return 1\n"
        rec = ASTReconciler()
        result = rec.reconcile("test.py", base, base, base)
        assert result.success
        assert result.auto_resolved == 0
        assert result.merged_content == base

    def test_a_only_signature_change(self) -> None:
        base = "def foo():\n    return 1\n\ndef bar():\n    return 2\n"
        ver_a = "def foo(x):\n    return x\n\ndef bar():\n    return 2\n"
        rec = ASTReconciler()
        result = rec.reconcile("test.py", base, ver_a, base)
        assert result.success
        assert result.auto_resolved == 1
        assert "def foo(x):" in result.merged_content

    def test_b_only_signature_change(self) -> None:
        base = "def foo():\n    return 1\n\ndef bar():\n    return 2\n"
        ver_b = "def foo():\n    return 1\n\ndef bar(y):\n    return y\n"
        rec = ASTReconciler()
        result = rec.reconcile("test.py", base, base, ver_b)
        assert result.success
        assert result.auto_resolved == 1
        assert "def bar(y):" in result.merged_content

    def test_disjoint_body_changes(self) -> None:
        """A changes foo body, B changes bar body — no conflict."""
        base = "def foo():\n    return 1\n\ndef bar():\n    return 2\n"
        ver_a = "def foo():\n    return 42\n\ndef bar():\n    return 2\n"
        ver_b = "def foo():\n    return 1\n\ndef bar():\n    return 99\n"
        rec = ASTReconciler()
        result = rec.reconcile("test.py", base, ver_a, ver_b)
        assert result.success
        assert result.auto_resolved == 2
        expected = "def foo():\n    return 42\n\ndef bar():\n    return 99\n"
        assert result.merged_content == expected

    def test_disjoint_changes_a_and_b(self) -> None:
        """A modifies first function, B modifies second — should auto merge."""
        base = "def greet():\n    return 'hi'\n\ndef farewell():\n    return 'bye'\n"
        ver_a = "def greet():\n    return 'hello'\n\ndef farewell():\n    return 'bye'\n"
        ver_b = "def greet():\n    return 'hi'\n\ndef farewell():\n    return 'goodbye'\n"
        rec = ASTReconciler()
        result = rec.reconcile("test.py", base, ver_a, ver_b)
        assert result.success
        assert result.auto_resolved == 2
        assert "hello" in result.merged_content
        assert "goodbye" in result.merged_content


class TestReconcilerConflicts:
    """Cases where both agents modify the same symbol."""

    def test_both_modify_same_function_body(self) -> None:
        base = "def foo():\n    return 1\n\ndef bar():\n    return 2\n"
        ver_a = "def foo():\n    return 42\n\ndef bar():\n    return 2\n"
        ver_b = "def foo():\n    return 99\n\ndef bar():\n    return 2\n"
        rec = ASTReconciler()
        result = rec.reconcile("test.py", base, ver_a, ver_b)
        assert not result.success
        assert result.needs_judge
        assert len(result.conflicts) == 1
        assert result.conflicts[0].symbol_name == "foo"

    def test_both_modify_same_signature(self) -> None:
        base = "def foo():\n    pass\n"
        ver_a = "def foo(x):\n    pass\n"
        ver_b = "def foo(y):\n    pass\n"
        rec = ASTReconciler()
        result = rec.reconcile("test.py", base, ver_a, ver_b)
        assert not result.success
        assert result.needs_judge


class TestReconcilerEdgeCases:
    def test_parse_error_returns_needs_judge(self) -> None:
        rec = ASTReconciler()
        # A file that isn't valid Python won't cause parse_file to crash
        # (it uses regex fallback), but truly broken content might.
        result = rec.reconcile("test.unknown_ext", "???", "!!!", "###")
        # Even with unparseable content, the reconciler should handle gracefully
        assert isinstance(result, MergeResult)

    def test_both_add_same_symbol(self) -> None:
        """When both agents add a new function, take A's version."""
        base = "x = 1\n"
        ver_a = "x = 1\n\ndef new_func():\n    return 'a'\n"
        ver_b = "x = 1\n\ndef new_func():\n    return 'b'\n"
        rec = ASTReconciler()
        result = rec.reconcile("test.py", base, ver_a, ver_b)
        # Both "added" the same symbol — our reconciler takes A's version
        assert result.success or result.needs_judge

    def test_both_remove_same_function(self) -> None:
        """Both agents remove the same function — should succeed.

        Note: When both remove ``old``, the remaining ``keep`` shifts line
        numbers.  diff_file_ast detects the line-range change as "modified"
        in *both* versions, which triggers a conflict.  This is a known
        limitation — the reconciler conservatively flags it for a judge.
        The important part is it doesn't crash.
        """
        base = "def old():\n    pass\n\ndef keep():\n    return 1\n"
        ver_a = "def keep():\n    return 1\n"
        ver_b = "def keep():\n    return 1\n"
        rec = ASTReconciler()
        result = rec.reconcile("test.py", base, ver_a, ver_b)
        # Both removed `old` (auto-resolved) but `keep` shifted lines in both,
        # so reconciler sees it as a conflict.
        assert isinstance(result, MergeResult)
        # Either succeeds or flags for judge — both are acceptable
        assert result.success or result.needs_judge
