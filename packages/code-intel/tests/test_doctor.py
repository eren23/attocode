"""Exercise installation diagnostics through the actual stdio protocol."""

import pytest
from attocode_intel.onboarding import configure_client, diagnose


@pytest.mark.asyncio
@pytest.mark.parametrize("client", ["codex", "claude", "cursor"])
@pytest.mark.parametrize("profile", ["daily", "full", "lean"])
async def test_doctor_reads_both_wire_formats(tmp_path, client, profile):
    (tmp_path / "main.py").write_text("def example(): return 1\n")
    configure_client(client, tmp_path, profile=profile)
    result = await diagnose(client, tmp_path)
    assert result["status"] == "ok"
    assert result["metadata"]["workspace"] == str(tmp_path.resolve())
    assert result["tools"] > 0
    assert "python" in result["languages"]
    assert "typescript" in result["languages"]


@pytest.mark.asyncio
async def test_doctor_reports_a_client_without_configuration(tmp_path):
    result = await diagnose("claude", tmp_path)
    assert result["status"] == "not configured"
    assert "init --client claude" in result["hint"]


def test_doctor_for_all_clients_fails_only_when_none_is_ready(tmp_path, capsys):
    from attocode_intel import entrypoint

    with pytest.raises(SystemExit) as stop:
        entrypoint.main(["doctor", "--project", str(tmp_path)])
    assert stop.value.code == 1
    assert capsys.readouterr().out.count('"not configured"') == 3


def test_doctor_names_a_timeout(tmp_path, monkeypatch, capsys):
    from attocode_intel import entrypoint, onboarding

    async def slow(*args, **kwargs):
        raise TimeoutError

    monkeypatch.setattr(onboarding, "diagnose", slow)
    with pytest.raises(SystemExit):
        entrypoint.main(["doctor", "--client", "claude", "--project", str(tmp_path)])
    assert "claude: the server did not answer in 30 s" in capsys.readouterr().err


def test_help_lists_the_commands_for_people(capsys):
    from attocode_intel import entrypoint

    with pytest.raises(SystemExit):
        entrypoint.main(["--help"])
    out = capsys.readouterr().out
    for command in ("init", "doctor", "query <text>", "symbols <file>", "impact <file>", "deps <file>"):
        assert command in out
    entrypoint.main(["commands"])
    out = capsys.readouterr().out
    assert out.startswith("Usage: attocode-code-intel <command>")
    assert "reindex" in out
