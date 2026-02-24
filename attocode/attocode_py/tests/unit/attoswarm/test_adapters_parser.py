from attoswarm.adapters.base import SubprocessAdapter


def test_parse_json_event_and_usage() -> None:
    adapter = SubprocessAdapter("claude")
    parsed = adapter._parse_stdout_line('{"event":"task_done","message":"ok","token_usage":{"total":42},"cost_usd":0.12}')
    assert parsed["type"] == "task_done"
    assert parsed["token_usage"] == {"total": 42}
    assert parsed["cost_usd"] == 0.12


def test_parse_inline_usage_fallback() -> None:
    adapter = SubprocessAdapter("codex")
    parsed = adapter._parse_stdout_line("tokens=100 cost=0.05")
    assert parsed["type"] == "log"
    assert parsed["token_usage"] == {"total": 100}
    assert parsed["cost_usd"] == 0.05
