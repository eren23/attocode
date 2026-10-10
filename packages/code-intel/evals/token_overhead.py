"""How many tokens the code-intel MCP server adds to a Claude Code request.

Each setup sends one short request from a new temporary project. The setups are the same as in
the localize study: read-only native tools, no ToolSearch, the installer of the engine, and
project guidance only. `native` has no MCP server. Each NAME=REVISION argument adds a setup with
the engine of that git revision. For each setup, the script prints the prompt size of the first
model request (input, cache creation and cache read tokens) and the difference to `native`.
The requests use the Claude subscription, so the user starts this script.

    python packages/code-intel/evals/token_overhead.py before=0e63006 after=97c703b
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from localize_study import LOCAL_ENV, NATIVE, intel_setup, sweep  # noqa: E402
from study_clients import invoke, subscription_env  # noqa: E402

PROMPT = "Measurement only. Reply with the word ready. Do not call tools or read files."


def first_request(events):
    """The prompt size of the first model request, and the MCP servers and tools of the init event."""
    init = {}
    for line in events.read_text().splitlines():
        event = json.loads(line).get("event", {})
        if event.get("subtype") == "init":
            init = event
        if event.get("type") == "assistant":
            usage = event["message"]["usage"]
            return {"prompt_tokens": sum(usage.get(key, 0) for key in
                                         ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
                    "mcp_servers": init.get("mcp_servers"),
                    "mcp_tools": sum(tool.startswith("mcp__") for tool in init.get("tools", []))}
    raise RuntimeError(f"No model request in {events}")


def measure(name, revision, model, base):
    folder = base / name
    root, stage = folder / "repository", folder / "stage"
    root.mkdir(parents=True)
    (root / "fixture.py").write_text("def value():\n    return 42\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    servers = {}
    try:
        if revision:
            # The study runs the installer and the server of the frozen engine.
            engine = folder / "study" / "engine"
            engine.mkdir(parents=True)
            archive = subprocess.run(["git", "-C", str(HERE), "archive", f"{revision}:packages/code-intel/src"],
                                     check=True, capture_output=True).stdout
            subprocess.run(["tar", "-x", "-f", "-", "-C", str(engine)], input=archive, check=True)
            servers = intel_setup({"python": sys.executable, "server_env": LOCAL_ENV}, engine.parent, root,
                                  stage)["servers"]
        guidance = (root / "CLAUDE.md").is_file()
        invoke("claude", model, root, stage, servers, PROMPT, 180, subscription_env(), project_guidance=True,
               plain_text=True, tools=NATIVE)
        return {"setup": name, "revision": revision, "claude_md": guidance, **first_request(stage / "events.jsonl")}
    finally:
        sweep(f"{folder}/")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tokens that the code-intel MCP server adds to a Claude Code request")
    parser.add_argument("engines", nargs="+", metavar="NAME=REVISION")
    parser.add_argument("--model", default="claude-sonnet-5-5")
    args = parser.parse_args(argv)
    setups = [("native", None)] + [tuple(item.split("=", 1)) for item in args.engines]
    with tempfile.TemporaryDirectory(prefix="token-overhead-") as base:
        rows = [measure(name, revision, args.model, Path(base).resolve()) for name, revision in setups]
    for row in rows:
        row["added"] = row["prompt_tokens"] - rows[0]["prompt_tokens"]
        print(json.dumps(row))


if __name__ == "__main__":
    main()
