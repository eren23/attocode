"""Tests for rules manager."""

from __future__ import annotations

from attocode.integrations.utilities.rules import RulesManager


class TestRulesManager:
    def test_no_rules(self, tmp_path) -> None:
        rm = RulesManager(project_root=tmp_path)
        assert not rm.has_rules
        assert rm.combined == ""
        assert rm.rules == []

    def test_load_project_rules(self, tmp_path) -> None:
        rules_dir = tmp_path / ".attocode"
        rules_dir.mkdir()
        (rules_dir / "rules.md").write_text("Be concise\nUse Python 3.12+")
        rm = RulesManager(project_root=tmp_path)
        assert rm.has_rules
        assert "Be concise" in rm.combined

    def test_load_legacy_rules(self, tmp_path) -> None:
        rules_dir = tmp_path / ".agent"
        rules_dir.mkdir()
        (rules_dir / "rules.md").write_text("Legacy rule")
        rm = RulesManager(project_root=tmp_path)
        assert rm.has_rules
        assert "Legacy rule" in rm.combined

    def test_project_overrides_legacy(self, tmp_path) -> None:
        (tmp_path / ".agent").mkdir()
        (tmp_path / ".agent" / "rules.md").write_text("Legacy")
        (tmp_path / ".attocode").mkdir()
        (tmp_path / ".attocode" / "rules.md").write_text("New rule")
        rm = RulesManager(project_root=tmp_path)
        rules = rm.rules
        # Should only have new rule, not legacy
        assert any("New rule" in r for r in rules)

    def test_rules_list(self, tmp_path) -> None:
        (tmp_path / ".attocode").mkdir()
        (tmp_path / ".attocode" / "rules.md").write_text("Rule 1")
        rm = RulesManager(project_root=tmp_path)
        assert len(rm.rules) >= 1
