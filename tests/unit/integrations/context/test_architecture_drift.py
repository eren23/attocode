"""Tests for architecture drift detection.

Validates YAML config loading, layer classification, dependency checking,
violation reporting, and edge cases.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from attocode.integrations.context.architecture_drift import (
    ArchLayer,
    ArchReport,
    ArchRule,
    ArchViolation,
    check_drift,
    classify_file,
    format_report,
    load_architecture,
)


# ---------------------------------------------------------------------------
# Layer classification
# ---------------------------------------------------------------------------


class TestClassifyFile:
    def test_matches_prefix(self):
        layers = [ArchLayer(name="api", paths=["src/api/"])]
        assert classify_file("src/api/routes.py", layers) == "api"

    def test_no_match_returns_empty(self):
        layers = [ArchLayer(name="api", paths=["src/api/"])]
        assert classify_file("src/models/user.py", layers) == ""

    def test_first_match_wins(self):
        layers = [
            ArchLayer(name="api", paths=["src/api/"]),
            ArchLayer(name="all_src", paths=["src/"]),
        ]
        assert classify_file("src/api/routes.py", layers) == "api"

    def test_multiple_paths_per_layer(self):
        layers = [ArchLayer(name="data", paths=["src/models/", "src/db/"])]
        assert classify_file("src/models/user.py", layers) == "data"
        assert classify_file("src/db/connect.py", layers) == "data"

    def test_layer_matches_method(self):
        layer = ArchLayer(name="api", paths=["src/api/", "src/routes/"])
        assert layer.matches("src/api/health.py") is True
        assert layer.matches("src/routes/index.py") is True
        assert layer.matches("src/models/user.py") is False


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


class TestLoadArchitecture:
    def test_missing_file_returns_empty(self, tmp_path):
        layers, rules, exceptions = load_architecture(str(tmp_path))
        assert layers == []
        assert rules == []
        assert exceptions == {}

    def test_loads_layers(self, tmp_path):
        config_dir = tmp_path / ".attocode"
        config_dir.mkdir()
        (config_dir / "architecture.yaml").write_text(
            "layers:\n"
            "  - name: api\n"
            "    paths: ['src/api/']\n"
            "  - name: data\n"
            "    paths: ['src/models/', 'src/db/']\n"
        )
        layers, rules, exceptions = load_architecture(str(tmp_path))
        assert len(layers) == 2
        assert layers[0].name == "api"
        assert layers[1].name == "data"
        assert "src/models/" in layers[1].paths

    def test_loads_rules(self, tmp_path):
        config_dir = tmp_path / ".attocode"
        config_dir.mkdir()
        (config_dir / "architecture.yaml").write_text(
            "layers:\n"
            "  - name: api\n"
            "    paths: ['src/api/']\n"
            "  - name: data\n"
            "    paths: ['src/db/']\n"
            "rules:\n"
            "  - from: api\n"
            "    to: [data]\n"
            "    deny: []\n"
        )
        layers, rules, exceptions = load_architecture(str(tmp_path))
        assert len(rules) == 1
        assert rules[0].from_layer == "api"
        assert rules[0].allowed == ["data"]

    def test_loads_deny_rules(self, tmp_path):
        config_dir = tmp_path / ".attocode"
        config_dir.mkdir()
        (config_dir / "architecture.yaml").write_text(
            "layers:\n"
            "  - name: api\n"
            "    paths: ['src/api/']\n"
            "  - name: data\n"
            "    paths: ['src/db/']\n"
            "rules:\n"
            "  - from: api\n"
            "    deny: [data]\n"
        )
        _, rules, _ = load_architecture(str(tmp_path))
        assert rules[0].denied == ["data"]

    def test_loads_exceptions(self, tmp_path):
        config_dir = tmp_path / ".attocode"
        config_dir.mkdir()
        (config_dir / "architecture.yaml").write_text(
            "layers:\n"
            "  - name: api\n"
            "    paths: ['src/api/']\n"
            "exceptions:\n"
            "  - file: src/api/health.py\n"
            "    allowed: ['src/db/health.py']\n"
        )
        _, _, exceptions = load_architecture(str(tmp_path))
        assert "src/api/health.py" in exceptions
        assert "src/db/health.py" in exceptions["src/api/health.py"]

    def test_empty_yaml_returns_empty(self, tmp_path):
        config_dir = tmp_path / ".attocode"
        config_dir.mkdir()
        (config_dir / "architecture.yaml").write_text("")
        layers, rules, exceptions = load_architecture(str(tmp_path))
        assert layers == []

    def test_invalid_yaml_returns_empty(self, tmp_path):
        config_dir = tmp_path / ".attocode"
        config_dir.mkdir()
        (config_dir / "architecture.yaml").write_text(": : : bad yaml [[[")
        layers, rules, exceptions = load_architecture(str(tmp_path))
        assert layers == []


# ---------------------------------------------------------------------------
# Drift checking
# ---------------------------------------------------------------------------


class TestCheckDrift:
    def _setup_config(self, tmp_path):
        """Create a standard 3-layer architecture config."""
        config_dir = tmp_path / ".attocode"
        config_dir.mkdir()
        (config_dir / "architecture.yaml").write_text(
            "layers:\n"
            "  - name: api\n"
            "    paths: ['src/api/']\n"
            "  - name: service\n"
            "    paths: ['src/services/']\n"
            "  - name: data\n"
            "    paths: ['src/models/', 'src/db/']\n"
            "rules:\n"
            "  - from: api\n"
            "    to: [service]\n"
            "    deny: [data]\n"
            "  - from: service\n"
            "    to: [data]\n"
            "    deny: [api]\n"
            "  - from: data\n"
            "    to: []\n"
            "    deny: [api, service]\n"
        )

    def test_no_violations(self, tmp_path):
        self._setup_config(tmp_path)
        deps = {
            "src/api/routes.py": {"src/services/auth.py"},
            "src/services/auth.py": {"src/models/user.py"},
        }
        report = check_drift(str(tmp_path), dependencies=deps)
        assert len(report.violations) == 0
        assert report.files_checked == 2
        assert report.compliant_files == 2

    def test_deny_violation(self, tmp_path):
        self._setup_config(tmp_path)
        deps = {
            "src/api/routes.py": {"src/models/user.py"},  # api -> data is denied
        }
        report = check_drift(str(tmp_path), dependencies=deps)
        assert len(report.violations) == 1
        v = report.violations[0]
        assert v.source_layer == "api"
        assert v.target_layer == "data"
        assert v.severity == "high"
        assert "deny" in v.rule.lower()

    def test_unlisted_dependency_violation(self, tmp_path):
        self._setup_config(tmp_path)
        deps = {
            "src/services/auth.py": {"src/api/routes.py"},  # service -> api is denied
        }
        report = check_drift(str(tmp_path), dependencies=deps)
        assert len(report.violations) == 1
        assert report.violations[0].severity == "high"

    def test_intra_layer_always_allowed(self, tmp_path):
        self._setup_config(tmp_path)
        deps = {
            "src/api/routes.py": {"src/api/middleware.py"},  # same layer
        }
        report = check_drift(str(tmp_path), dependencies=deps)
        assert len(report.violations) == 0

    def test_exception_overrides_deny(self, tmp_path):
        config_dir = tmp_path / ".attocode"
        config_dir.mkdir()
        (config_dir / "architecture.yaml").write_text(
            "layers:\n"
            "  - name: api\n"
            "    paths: ['src/api/']\n"
            "  - name: data\n"
            "    paths: ['src/db/']\n"
            "rules:\n"
            "  - from: api\n"
            "    deny: [data]\n"
            "exceptions:\n"
            "  - file: src/api/health.py\n"
            "    allowed: ['src/db/health.py']\n"
        )
        deps = {
            "src/api/health.py": {"src/db/health.py"},  # allowed by exception
        }
        report = check_drift(str(tmp_path), dependencies=deps)
        assert len(report.violations) == 0

    def test_unclassified_files_skipped(self, tmp_path):
        self._setup_config(tmp_path)
        deps = {
            "scripts/deploy.py": {"src/models/user.py"},  # scripts not in any layer
        }
        report = check_drift(str(tmp_path), dependencies=deps)
        assert len(report.violations) == 0
        assert report.files_checked == 0

    def test_no_config_returns_empty_report(self, tmp_path):
        report = check_drift(str(tmp_path), dependencies={})
        assert report.layers_defined == 0
        assert report.rules_defined == 0
        assert len(report.violations) == 0

    def test_multiple_violations_sorted(self, tmp_path):
        self._setup_config(tmp_path)
        deps = {
            "src/api/routes.py": {"src/models/user.py"},  # deny -> high
            "src/data/extra.py": set(),
        }
        report = check_drift(str(tmp_path), dependencies=deps)
        # high severity should come first
        if report.violations:
            assert report.violations[0].severity == "high"


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


class TestFormatReport:
    def test_no_violations_message(self):
        report = ArchReport(
            violations=[], layers_defined=3, rules_defined=3,
            files_checked=10, compliant_files=10,
        )
        text = format_report(report)
        assert "No architecture violations detected" in text
        assert "Layers defined: 3" in text

    def test_violations_in_output(self):
        v = ArchViolation(
            source_file="src/api/routes.py",
            target_file="src/models/user.py",
            source_layer="api",
            target_layer="data",
            rule="Layer 'api' must NOT depend on 'data' (deny rule)",
            severity="high",
        )
        report = ArchReport(
            violations=[v], layers_defined=2, rules_defined=1,
            files_checked=1, compliant_files=0,
        )
        text = format_report(report)
        assert "HIGH" in text
        assert "src/api/routes.py" in text
        assert "src/models/user.py" in text
        assert "1 violation" in text

    def test_mixed_severities(self):
        high = ArchViolation(
            source_file="a.py", target_file="b.py",
            source_layer="api", target_layer="data",
            rule="deny", severity="high",
        )
        medium = ArchViolation(
            source_file="c.py", target_file="d.py",
            source_layer="api", target_layer="infra",
            rule="unlisted", severity="medium",
        )
        report = ArchReport(
            violations=[high, medium], layers_defined=3, rules_defined=2,
            files_checked=2, compliant_files=0,
        )
        text = format_report(report)
        assert "HIGH" in text
        assert "MEDIUM" in text
        assert "2 violation" in text
