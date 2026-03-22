"""Tests for /export command (HTML session export)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from attocode.commands import _export_command


@dataclass
class FakeMetrics:
    llm_calls: int = 5
    tool_calls: int = 10
    total_tokens: int = 50000
    estimated_cost: float = 0.25


@dataclass
class FakeMessage:
    role: str = "user"
    content: str = "Hello, world!"


@dataclass
class FakeContext:
    session_id: str = "test-session-123"
    messages: list = field(default_factory=lambda: [
        FakeMessage(role="user", content="How do I fix this bug?"),
        FakeMessage(role="assistant", content="Let me look at the code."),
        FakeMessage(role="tool", content="File contents here..."),
        FakeMessage(role="assistant", content="I found the issue."),
    ])
    metrics: FakeMetrics = field(default_factory=FakeMetrics)
    iteration: int = 3
    goal: str = "Fix the authentication bug"
    mode_manager: None = None


@dataclass
class FakeConfig:
    model: str = "claude-sonnet-4-20250514"


class TestExportCommand:
    """Tests for _export_command."""

    def test_export_html_creates_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """HTML export creates a file."""
        monkeypatch.chdir(tmp_path)
        agent = MagicMock()
        agent.context = FakeContext()
        agent.config = FakeConfig()

        result = _export_command(agent, "html")
        assert "exported to" in result.output.lower()
        assert "Messages: 4" in result.output

        # Check file was created
        exports = list((tmp_path / ".attocode" / "exports").glob("*.html"))
        assert len(exports) == 1

        html_content = exports[0].read_text()
        assert "Attocode Session Export" in html_content
        assert "test-session-123" in html_content
        assert "How do I fix this bug?" in html_content
        assert "claude-sonnet-4" in html_content

    def test_export_default_is_html(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default export format is HTML."""
        monkeypatch.chdir(tmp_path)
        agent = MagicMock()
        agent.context = FakeContext()
        agent.config = FakeConfig()

        result = _export_command(agent, "")
        assert "exported to" in result.output.lower()
        exports = list((tmp_path / ".attocode" / "exports").glob("*.html"))
        assert len(exports) == 1

    def test_export_html_escapes_content(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """HTML content is properly escaped."""
        monkeypatch.chdir(tmp_path)
        agent = MagicMock()
        agent.context = FakeContext()
        agent.context.messages = [
            FakeMessage(role="user", content='<script>alert("xss")</script>'),
        ]
        agent.config = FakeConfig()

        result = _export_command(agent, "html")
        exports = list((tmp_path / ".attocode" / "exports").glob("*.html"))
        html_content = exports[0].read_text()
        assert "<script>" not in html_content
        assert "&lt;script&gt;" in html_content

    def test_export_no_context(self) -> None:
        """Returns error when no context."""
        agent = MagicMock()
        agent.context = None
        result = _export_command(agent, "html")
        assert "no active context" in result.output.lower()

    def test_export_html_stats(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """HTML export includes stats."""
        monkeypatch.chdir(tmp_path)
        agent = MagicMock()
        agent.context = FakeContext()
        agent.config = FakeConfig()

        _export_command(agent, "html")
        exports = list((tmp_path / ".attocode" / "exports").glob("*.html"))
        html = exports[0].read_text()
        assert "50,000" in html  # tokens
        assert "$0.2500" in html  # cost
        assert "5" in html  # llm_calls
