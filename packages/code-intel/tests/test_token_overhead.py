import json
from pathlib import Path

EVALS = Path(__file__).parents[1] / "evals"


def test_token_overhead_compares_each_engine_with_native(monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(EVALS))
    import token_overhead

    def fake_invoke(client, model, root, stage, servers, prompt, timeout, env, **options):
        # Each server adds 50 prompt tokens. Only the first model request counts.
        stage.mkdir(parents=True, exist_ok=True)
        tools = ["Read"] + [f"mcp__{name}__bootstrap" for name in servers]
        events = [{"type": "system", "subtype": "init", "tools": tools, "mcp_servers": list(servers)},
                  {"type": "assistant", "message": {"usage": {"input_tokens": 2,
                                                              "cache_read_input_tokens": 100 + 50 * len(servers)}}},
                  {"type": "assistant", "message": {"usage": {"input_tokens": 1000}}}]
        (stage / "events.jsonl").write_text("\n".join(json.dumps({"event": event}) for event in events))

    monkeypatch.setattr(token_overhead, "invoke", fake_invoke)
    token_overhead.main(["current=HEAD"])
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    # The engine of HEAD installs its server, and writes no CLAUDE.md for Claude.
    assert [(row["setup"], row["prompt_tokens"], row["added"], row["mcp_tools"], row["claude_md"]) for row in rows] == [
        ("native", 102, 0, 0, False), ("current", 152, 50, 1, False)]
