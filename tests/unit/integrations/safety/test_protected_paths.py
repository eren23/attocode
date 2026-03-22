"""Tests for protected path enforcement (QW7).

Verifies that .git, .attocode, and .env directories are always
read-only regardless of permission mode or approval status.
"""

from __future__ import annotations

from attocode.integrations.safety.bash_policy import CommandRisk, classify_command
from attocode.integrations.safety.policy_engine import (
    DangerLevel,
    PolicyDecision,
    PolicyEngine,
    is_protected_path,
)


# ---------------------------------------------------------------------------
# is_protected_path unit tests
# ---------------------------------------------------------------------------

class TestIsProtectedPath:
    def test_git_directory(self) -> None:
        assert is_protected_path(".git/config")
        assert is_protected_path(".git/hooks/pre-commit")

    def test_attocode_directory(self) -> None:
        assert is_protected_path(".attocode/settings.json")
        assert is_protected_path(".attocode/db/store.sqlite")

    def test_env_file(self) -> None:
        assert is_protected_path(".env")
        assert is_protected_path("subdir/.env")

    def test_nested_protected(self) -> None:
        assert is_protected_path("project/subdir/.git/objects/pack")

    def test_non_protected(self) -> None:
        assert not is_protected_path("src/main.py")
        assert not is_protected_path("tests/test_app.py")
        assert not is_protected_path("README.md")

    def test_similar_names_not_protected(self) -> None:
        """Names that contain a protected name as substring should not match."""
        assert not is_protected_path("src/git_utils.py")
        assert not is_protected_path("docs/attocode_design.md")

    def test_absolute_path(self) -> None:
        assert is_protected_path("/home/user/project/.git/config")
        assert is_protected_path("/home/user/project/.attocode/db.sqlite")

    def test_empty_path(self) -> None:
        assert not is_protected_path("")


# ---------------------------------------------------------------------------
# PolicyEngine protected-path enforcement
# ---------------------------------------------------------------------------

class TestProtectedPathPolicyEnforcement:
    """Policy engine must deny write operations on protected paths."""

    def test_write_file_to_git_denied(self) -> None:
        pe = PolicyEngine()
        result = pe.evaluate("write_file", {"path": ".git/config"})
        assert result.decision == PolicyDecision.DENY
        assert result.danger_level == DangerLevel.CRITICAL
        assert ".git/config" in result.reason

    def test_edit_file_in_attocode_denied(self) -> None:
        pe = PolicyEngine()
        result = pe.evaluate("edit_file", {"path": ".attocode/settings.json"})
        assert result.decision == PolicyDecision.DENY
        assert result.danger_level == DangerLevel.CRITICAL

    def test_create_file_in_git_denied(self) -> None:
        pe = PolicyEngine()
        result = pe.evaluate("create_file", {"path": ".git/hooks/post-commit"})
        assert result.decision == PolicyDecision.DENY

    def test_delete_file_in_git_denied(self) -> None:
        pe = PolicyEngine()
        result = pe.evaluate("delete_file", {"path": ".git/index"})
        assert result.decision == PolicyDecision.DENY

    def test_rename_file_in_attocode_denied(self) -> None:
        pe = PolicyEngine()
        result = pe.evaluate("rename_file", {"path": ".attocode/old.json"})
        assert result.decision == PolicyDecision.DENY

    def test_write_to_env_denied(self) -> None:
        pe = PolicyEngine()
        result = pe.evaluate("write_file", {"path": ".env"})
        assert result.decision == PolicyDecision.DENY
        assert result.danger_level == DangerLevel.CRITICAL

    def test_read_file_in_git_allowed(self) -> None:
        """Read operations on protected paths must remain allowed."""
        pe = PolicyEngine()
        result = pe.evaluate("read_file", {"path": ".git/config"})
        assert result.decision == PolicyDecision.ALLOW

    def test_glob_in_git_allowed(self) -> None:
        pe = PolicyEngine()
        result = pe.evaluate("glob", {"path": ".git"})
        assert result.decision == PolicyDecision.ALLOW

    def test_non_protected_write_unaffected(self) -> None:
        """Normal write operations on non-protected paths must not be blocked."""
        pe = PolicyEngine()
        result = pe.evaluate("write_file", {"path": "src/main.py"})
        assert result.decision == PolicyDecision.ALLOW

    def test_non_protected_edit_unaffected(self) -> None:
        pe = PolicyEngine()
        result = pe.evaluate("edit_file", {"path": "tests/test_app.py"})
        assert result.decision == PolicyDecision.ALLOW

    def test_protected_path_overrides_approve_all(self) -> None:
        """Even approve_all must not bypass protected-path denial."""
        pe = PolicyEngine()
        pe.approve_all()
        result = pe.evaluate("write_file", {"path": ".git/config"})
        assert result.decision == PolicyDecision.DENY

    def test_protected_path_overrides_session_grant(self) -> None:
        """Session-approved commands must not bypass protected-path denial."""
        pe = PolicyEngine()
        pe.approve_command("write_file", "*")
        result = pe.evaluate("write_file", {"path": ".git/config"})
        assert result.decision == PolicyDecision.DENY

    def test_file_path_key_also_checked(self) -> None:
        """The 'file_path' argument key should also be checked."""
        pe = PolicyEngine()
        result = pe.evaluate("write_file", {"file_path": ".git/config"})
        assert result.decision == PolicyDecision.DENY

    def test_no_arguments_passes_through(self) -> None:
        """Write operations without arguments should not crash."""
        pe = PolicyEngine()
        result = pe.evaluate("write_file")
        # No path to check — falls through to normal rule matching
        assert result.decision == PolicyDecision.ALLOW


# ---------------------------------------------------------------------------
# Bash policy: destructive commands targeting .git / .attocode
# ---------------------------------------------------------------------------

class TestBashProtectedPaths:
    def test_rm_git_blocked(self) -> None:
        result = classify_command("rm -rf .git")
        assert result.risk == CommandRisk.BLOCK

    def test_rm_attocode_blocked(self) -> None:
        result = classify_command("rm -rf .attocode")
        assert result.risk == CommandRisk.BLOCK

    def test_rm_git_subdirectory_blocked(self) -> None:
        result = classify_command("rm .git/config")
        assert result.risk == CommandRisk.BLOCK

    def test_rm_unrelated_not_blocked_by_git_pattern(self) -> None:
        """rm on non-protected paths should not be blocked (may warn)."""
        result = classify_command("rm temp_file.txt")
        assert result.risk != CommandRisk.BLOCK
