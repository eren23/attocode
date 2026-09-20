"""Tests for the confidence scorers.

No network: fakes stand in for both providers. What matters is that the
dispatcher is inert by default, harmless in shadow, that a broken scorer never
costs a caller its findings, and that nothing leaves the machine unredacted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from attocode_intel import confidence
from attocode_intel._internal.integrations.feature_flags import registry
from attocode_intel.confidence import jev as jev_scorer
from attocode_intel.confidence.redact import redact


@dataclass
class FakeFinding:
    """Stands in for EnrichedFinding — the scorers only need these fields."""

    file: str = "app.py"
    line: int = 7
    confidence: float = 0.6
    rule_id: str = "py/test-rule"
    description: str = "something looks wrong"
    code_snippet: str = "cursor.execute(q)"
    context_before: list[str] = field(default_factory=list)
    context_after: list[str] = field(default_factory=list)


class FakeJev:
    """Records calls and returns a fixed probability."""

    def __init__(self, noul: float | None = 0.9, error: str = "", raises: bool = False) -> None:
        self.noul = noul
        self.error = error
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    def load_env(self) -> None:
        pass

    def decide(self, site, state, questions, incumbent=None, backend=None, ref_id=None):  # noqa: ANN001, ANN201
        self.calls.append({"site": site, "state": state, "incumbent": incumbent})
        if self.raises:
            raise RuntimeError("backend exploded")
        if self.error:
            return {"error": self.error, "answers": None}
        return {"error": None, "answers": {"p": {"type": "noul", "noul": self.noul}}}


@pytest.fixture
def fake_jev(monkeypatch: pytest.MonkeyPatch) -> FakeJev:
    fake = FakeJev()
    monkeypatch.setattr(jev_scorer, "jev", fake)
    monkeypatch.setattr(jev_scorer, "_HAS_JEV", True)
    monkeypatch.setattr(jev_scorer, "_env_loaded", True)
    yield fake
    registry.clear_override("CONFIDENCE")
    registry.clear_override("CONFIDENCE_MODE")


def _select(scorer: str, mode: str = "live") -> None:
    registry.set_override("CONFIDENCE", scorer)
    registry.set_override("CONFIDENCE_MODE", mode)


class TestDispatcher:
    def test_off_by_default(self, fake_jev: FakeJev) -> None:
        registry.clear_override("CONFIDENCE")
        findings = [FakeFinding()]
        confidence.score(findings, min_confidence=0.5)
        assert fake_jev.calls == []
        assert findings[0].confidence == 0.6

    def test_off_when_no_backend_reachable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(jev_scorer, "_HAS_JEV", False)
        monkeypatch.setattr(jev_scorer, "_env_loaded", True)  # do not read .env
        for var in ("OPENROUTER_API_KEY", "TYPESAFE_API_KEY", "ATTOCODE_LOCAL_ONLY"):
            monkeypatch.delenv(var, raising=False)
        _select("jev")
        try:
            assert confidence.scorer_name() == "off"
        finally:
            registry.clear_override("CONFIDENCE")
            registry.clear_override("CONFIDENCE_MODE")

    def test_works_without_the_jev_cli(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A key is enough: the scorer POSTs to the public endpoint itself."""
        monkeypatch.setattr(jev_scorer, "_HAS_JEV", False)
        monkeypatch.setattr(jev_scorer, "_env_loaded", True)
        monkeypatch.delenv("ATTOCODE_LOCAL_ONLY", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        _select("jev")
        try:
            assert confidence.scorer_name() == "jev"
        finally:
            registry.clear_override("CONFIDENCE")
            registry.clear_override("CONFIDENCE_MODE")

    def test_unknown_scorer_is_off(self, fake_jev: FakeJev) -> None:
        _select("nonsense")
        assert confidence.scorer_name() == "off"

    def test_shadow_calls_but_does_not_mutate(self, fake_jev: FakeJev) -> None:
        _select("jev", "shadow")
        findings = [FakeFinding(), FakeFinding(line=9)]
        confidence.score(findings, min_confidence=0.5)
        assert len(fake_jev.calls) == 2
        assert [f.confidence for f in findings] == [0.6, 0.6]

    def test_live_replaces_confidence(self, fake_jev: FakeJev) -> None:
        _select("jev")
        findings = [FakeFinding()]
        confidence.score(findings, min_confidence=0.5)
        assert findings[0].confidence == pytest.approx(0.9)

    def test_incumbent_is_the_constants_own_verdict(self, fake_jev: FakeJev) -> None:
        _select("jev", "shadow")
        confidence.score(
            [FakeFinding(confidence=0.6), FakeFinding(confidence=0.4)],
            min_confidence=0.5,
        )
        assert [c["incumbent"] for c in fake_jev.calls] == ["yes", "no"]

    @pytest.mark.parametrize("kwargs", [{"raises": True}, {"error": "timeout"}, {"noul": None}])
    def test_broken_scorer_leaves_confidence_alone(
        self, monkeypatch: pytest.MonkeyPatch, kwargs: dict[str, Any],
    ) -> None:
        monkeypatch.setattr(jev_scorer, "jev", FakeJev(**kwargs))
        monkeypatch.setattr(jev_scorer, "_HAS_JEV", True)
        _select("jev")
        try:
            findings = [FakeFinding()]
            confidence.score(findings, min_confidence=0.5)  # must not raise
            assert findings[0].confidence == 0.6
            assert confidence.last_run() == (0, 1)
        finally:
            registry.clear_override("CONFIDENCE")
            registry.clear_override("CONFIDENCE_MODE")

    def test_call_cap(self, fake_jev: FakeJev) -> None:
        _select("jev", "shadow")
        confidence.score([FakeFinding(line=i) for i in range(40)], min_confidence=0.5)
        assert len(fake_jev.calls) == confidence.MAX_CALLS

    def test_empty_input_makes_no_calls(self, fake_jev: FakeJev) -> None:
        _select("jev")
        confidence.score([], min_confidence=0.5)
        assert fake_jev.calls == []
        assert confidence.last_run() == (0, 0)

    def test_last_run_counts(self, fake_jev: FakeJev) -> None:
        _select("jev")
        confidence.score([FakeFinding(), FakeFinding(line=8)], min_confidence=0.5)
        assert confidence.last_run() == (2, 2)


class TestRedaction:
    def test_literal_secret_is_blanked(self) -> None:
        assert "abcdefghijklmnopqrstuvwxyz123" not in redact(
            'api_key = "abcdefghijklmnopqrstuvwxyz123"'
        )

    def test_placeholder_keeps_the_shape_not_the_value(self) -> None:
        out = redact('API_KEY = "sk-proj-abc123def456ghi789jkl012"')
        assert out == 'API_KEY = "[REDACTED:32 chars]"'
        assert "sk-proj" not in out

    def test_env_lookup_is_left_alone(self) -> None:
        line = 'client = OpenAI(api_key=os.environ["OPENROUTER_API_KEY"])'
        assert redact(line) == line

    def test_ordinary_code_is_untouched(self) -> None:
        line = "cursor.execute(query)  # a normal comment"
        assert redact(line) == line

    def test_state_sent_to_jev_is_redacted(self, fake_jev: FakeJev) -> None:
        _select("jev", "shadow")
        finding = FakeFinding(code_snippet='api_key = "abcdefghijklmnopqrstuvwxyz123"')
        confidence.score([finding], min_confidence=0.5)
        sent = fake_jev.calls[0]["state"]["code"]
        assert "abcdefghijklmnopqrstuvwxyz123" not in sent
        assert "[REDACTED:" in sent


class TestBackendChoice:
    def test_local_only_forces_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ATTOCODE_LOCAL_ONLY", "1")
        assert jev_scorer.backend() == "local"

    def test_no_key_falls_back_to_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ATTOCODE_LOCAL_ONLY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setattr(jev_scorer, "jev", FakeJev())
        assert jev_scorer.backend() == "local"

    def test_key_means_openrouter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ATTOCODE_LOCAL_ONLY", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setattr(jev_scorer, "jev", FakeJev())
        assert jev_scorer.backend() == "openrouter"

    def test_explicit_backend_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ATTOCODE_LOCAL_ONLY", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("JEV_BACKEND", "typesafe")
        monkeypatch.setattr(jev_scorer, "jev", FakeJev())
        assert jev_scorer.backend() == "typesafe"
