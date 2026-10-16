"""Production-path regressions for workspace-local live scoring. No network."""
from __future__ import annotations

import http.server
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import TYPE_CHECKING

import pytest
from attocode_intel import confidence
from attocode_intel.confidence import jev, settings
from attocode_intel.request_context import RequestContext, bind_request
from attocode_intel.rules.model import EnrichedFinding, RuleCategory, RuleSeverity, UnifiedRule
from attocode_intel.rules.registry import RuleRegistry

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def no_ambient_configuration(monkeypatch):
    for name in ("CONFIDENCE", "CONFIDENCE_MODE"):
        confidence.settings.registry.clear_override(name)
        monkeypatch.delenv("ATTOCODE_FLAG_" + name, raising=False)
    for name in ("JEV_BACKEND", "ATTOCODE_LOCAL_ONLY", "OPENROUTER_API_KEY", "TYPESAFE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(jev, "_env_loaded", True)
    monkeypatch.setattr(jev, "_HAS_JEV", False)
    yield
    for name in ("CONFIDENCE", "CONFIDENCE_MODE"):
        confidence.settings.registry.clear_override(name)


def configure(root: Path, scorer="jev"):
    (root / ".attocode").mkdir(exist_ok=True, parents=True)
    (root / ".attocode/config.toml").write_text(
        f'[confidence]\nscorer="{scorer}"\nmode="live"\nbackend="openrouter"\n'
    )
    (root / ".env").write_text('OPENROUTER_API_KEY="test-only"\n')


def finding(line=1):
    return EnrichedFinding(rule_id="test/rule", rule_name="Rule", severity=RuleSeverity.HIGH,
                           category=RuleCategory.SECURITY, confidence=.35, file="app.py",
                           line=line, code_snippet="danger()", description="Bad call")


def test_workspace_and_override_precedence(tmp_path, monkeypatch):
    configure(tmp_path)
    with settings.workspace(str(tmp_path)):
        assert confidence.scorer_name() == "jev"
        assert confidence.mode() == "live"
        monkeypatch.setenv("ATTOCODE_FLAG_CONFIDENCE", "off")
        assert confidence.scorer_name() == "off"
        settings.registry.set_override("CONFIDENCE", "jev")
        assert confidence.scorer_name() == "jev"
    settings.registry.clear_override("CONFIDENCE")
    monkeypatch.delenv("ATTOCODE_FLAG_CONFIDENCE")
    assert confidence.scorer_name() == "off"
    assert "OPENROUTER_API_KEY" not in __import__("os").environ


def test_remote_does_not_load_repository_configuration(tmp_path):
    configure(tmp_path)
    with bind_request(RequestContext(str(tmp_path), "remote-id", source="remote")), settings.workspace(str(tmp_path)):
        assert settings.selected() == "off"
        assert settings.project_dir() == ""


def test_analysis_promotes_rule_and_scores_context_before_threshold(tmp_path, monkeypatch):
    from attocode_intel.tools import rule_tools
    configure(tmp_path)
    (tmp_path / "app.py").write_text("trusted = True\ndanger()\ncleanup()\n")
    registry = RuleRegistry()
    registry.register(UnifiedRule(id="test", name="test", description="bad", confidence=.35,
                                 severity=RuleSeverity.HIGH, category=RuleCategory.SECURITY,
                                 pattern=re.compile(r"danger\(")))
    monkeypatch.setattr(rule_tools, "_get_registry", lambda: registry)
    def estimate(items, **kwargs):
        assert items[0].context_before == ["trusted = True"]
        assert items[0].context_after == ["cleanup()"]
        return [.9]
    monkeypatch.setattr(jev, "estimate", estimate)
    text = rule_tools._analyze_impl(files=["app.py"], project_dir=str(tmp_path))
    assert "90%" in text and "1/1 scored" in text
    assert confidence.last_report()["findings"][0]["baseline"] == .35
    monkeypatch.setattr(jev, "estimate", lambda *a, **k: [.05])
    text = rule_tools._analyze_impl(files=["app.py"], project_dir=str(tmp_path))
    assert "No findings" in text and "1/1 scored" in text


def test_outage_and_cap_are_visible_with_suppressed_rows(tmp_path, monkeypatch):
    configure(tmp_path)
    monkeypatch.setattr(jev, "estimate", lambda *a, **k: [None, .1])
    with settings.workspace(str(tmp_path)):
        confidence.score([finding(i) for i in range(27)], min_confidence=.5)
        report = confidence.last_report()
        assert (report["estimated"], report["fallback"], report["skipped"]) == (1, 24, 2)
        assert len(report["findings"]) == 27
        assert report["findings"][1]["kept"] is False
        report["findings"].clear()
        assert len(confidence.last_report()["findings"]) == 27
        monkeypatch.setattr(jev, "estimate", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
        f = finding()
        confidence.score([f], min_confidence=.5)
        assert f.confidence == .35 and "1 fallback" in confidence.summary()


def test_diagnostics_and_credentials_follow_concurrent_requests(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    configure(a)
    configure(b)
    (b / ".env").write_text('OPENROUTER_API_KEY="different-key"\n')
    barrier = Barrier(2)
    def decide(*args):
        key = settings.environment()["OPENROUTER_API_KEY"]
        return {"answers": {"p": {"noul": .8 if key == "test-only" else .2}}}
    monkeypatch.setattr(jev, "_decide", decide)
    def run(root):
        with settings.workspace(str(root)):
            confidence.score([finding()], min_confidence=.5)
            barrier.wait(timeout=5)
            return confidence.last_report()["findings"][0]["effective"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run, [a, b])) == [.8, .2]


@pytest.mark.parametrize("value", [True, -1, 1.01, 10**1000, float("nan"), float("inf"), "0.8", None])
def test_invalid_provider_values_are_abstentions(value, monkeypatch):
    monkeypatch.setenv("JEV_BACKEND", "local")
    monkeypatch.setattr(jev, "_decide", lambda *a: {"answers": {"p": {"noul": value}}})
    assert jev.estimate([finding()], min_confidence=.5) == [None]
    monkeypatch.setenv("ATTOCODE_FLAG_CONFIDENCE", "jev")
    monkeypatch.setattr(jev, "estimate", lambda *a, **kw: [value])
    confidence.score([finding()], min_confidence=.5)
    assert confidence.last_report()["findings"][0]["status"] == "fallback"


def test_redact_every_source_field_before_truncation():
    f = finding()
    secret = "abcdef" * 800
    f.description = f'api_key = "{secret}"'
    f.code_snippet = f.description
    state = jev._state(f)
    assert "abcdef" not in str(state)
    assert "[REDACTED:" in state["message"] and "[REDACTED:" in state["code"]


def test_typesafe_only_and_explicit_local(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake")
    assert jev.backend() == "typesafe" and jev.available()
    monkeypatch.setenv("JEV_BACKEND", "local")
    assert jev.backend() == "local" and jev.available()


def test_disabled_scope_prevents_any_model_call(tmp_path, monkeypatch):
    configure(tmp_path)
    monkeypatch.setattr(jev, "estimate", lambda *a, **k: pytest.fail("network attempted"))
    with settings.workspace(str(tmp_path)), settings.disabled():
        confidence.score([finding()], min_confidence=0)
        assert confidence.last_run() == (0, 0)


def test_ci_reports_scoring_even_when_empty(tmp_path, monkeypatch):
    from attocode_intel.rules.ci import CIRunner, format_ci_summary
    configure(tmp_path)
    (tmp_path / "app.py").write_text("eval(user_input)\n")
    monkeypatch.setattr(jev, "estimate", lambda items, **k: [.01] * len(items))
    result = CIRunner(str(tmp_path)).run(files=[str(tmp_path / "app.py")])
    assert not result.findings
    assert result.confidence["estimated"] > 0
    assert "Confidence: jev" in format_ci_summary(result)


@pytest.mark.parametrize(("repo_url", "process_url", "local_only", "sent"), [
    ("https://jev.example", None, False, False),  # repository picks the host
    (None, "https://jev.example", True, False),  # local-only stays on this machine
    (None, "https://jev.example", False, True),  # the operator picked it
    ("http://127.0.0.1:9000", None, False, True),
])
def test_local_backend_host_needs_operator_or_loopback(tmp_path, monkeypatch, repo_url, process_url,
                                                       local_only, sent):
    configure(tmp_path)
    (tmp_path / ".env").write_text(f'JEV_BASE_URL="{repo_url}"\n' if repo_url else "")
    monkeypatch.setenv("OPENJEV_API_KEY", "machine-key")
    monkeypatch.setenv("JEV_BACKEND", "local")
    if process_url:
        monkeypatch.setenv("JEV_BASE_URL", process_url)
    else:
        monkeypatch.delenv("JEV_BASE_URL", raising=False)
    if local_only:
        monkeypatch.setenv("ATTOCODE_LOCAL_ONLY", "1")
    urls = []
    def urlopen(request, timeout):
        urls.append(request.full_url)
        raise OSError("no network in tests")
    monkeypatch.setattr(jev, "_open", urlopen)
    with settings.workspace(str(tmp_path)):
        assert jev.estimate([finding()], min_confidence=.5) == [None]
    assert bool(urls) is sent


def test_local_backend_key_stays_on_loopback(tmp_path, monkeypatch):
    seen = []

    class Recorder(http.server.BaseHTTPRequestHandler):  # a redirect target, and the ambient proxy
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            seen.append(("elsewhere", self.headers.get("Authorization")))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")
        do_GET = do_POST  # noqa: N815 - a followed 302 arrives as a GET

        def log_message(self, *args):
            pass

    class Redirector(Recorder):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            seen.append(("jev", self.headers.get("Authorization")))
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{elsewhere.server_port}/stolen")
            self.end_headers()

    elsewhere = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
    local = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Redirector)
    for server in (elsewhere, local):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    configure(tmp_path)
    monkeypatch.setenv("OPENJEV_API_KEY", "machine-key")
    monkeypatch.setenv("JEV_BACKEND", "local")
    monkeypatch.setenv("JEV_BASE_URL", f"http://127.0.0.1:{local.server_port}")
    monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{elsewhere.server_port}")
    for name in ("no_proxy", "NO_PROXY", "HTTP_PROXY"):
        monkeypatch.delenv(name, raising=False)
    try:
        with settings.workspace(str(tmp_path)):
            assert jev.estimate([finding()], min_confidence=.5) == [None]
    finally:
        for server in (elsewhere, local):
            server.shutdown()
    assert seen == [("jev", "Bearer machine-key")]


def test_bug_scan_uses_the_workspace_scorer(tmp_path, monkeypatch):
    import subprocess

    from attocode_intel.tools import analysis_tools
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / "app.py").write_text("x = 1\n")
    subprocess.run([*git, "add", "."], cwd=tmp_path, check=True)
    subprocess.run([*git, "commit", "-qm", "base"], cwd=tmp_path, check=True)
    subprocess.run(["git", "checkout", "-qb", "feature"], cwd=tmp_path, check=True)
    (tmp_path / "app.py").write_text("x = 1\ny = eval(user_input)\n")
    subprocess.run([*git, "commit", "-qam", "change"], cwd=tmp_path, check=True)
    configure(tmp_path)
    monkeypatch.setattr(analysis_tools, "_get_remote_service", lambda: None)
    monkeypatch.setattr(analysis_tools, "_get_project_dir", lambda: str(tmp_path))
    monkeypatch.setattr(jev, "estimate", lambda items, **kwargs: [.05] * len(items))
    assert "No findings" in analysis_tools.bug_scan() and "1/1 scored" in analysis_tools.bug_scan()
    monkeypatch.setattr(jev, "estimate", lambda items, **kwargs: [.97] * len(items))
    assert "[97%] app.py:2" in analysis_tools.bug_scan()
