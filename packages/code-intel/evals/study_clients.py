"""Subscription-only CLI adapters. No API keys, fallback models, or global config writes."""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from study_events import QUOTA, capture, observations
from study_events import parse_events as parse_events
from study_tasks import SCHEMA

CLIENTS = ("codex", "claude", "cursor")
NATIVE = ["Read", "Grep", "Glob", "ToolSearch", "Edit", "Write", "Bash"]


def subscription_env():
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(("ANTHROPIC_", "OPENAI_", "CURSOR_API_", "CLAUDE_CODE_USE_")) or key in {
                "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR"}:
            env.pop(key)
    env["NO_COLOR"] = "1"
    return env


def authentication(client, env):
    command = {"codex": ["codex", "login", "status"], "claude": ["claude", "auth", "status"],
               "cursor": ["cursor", "agent", "status"]}[client]
    try:
        result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=20)
        output = result.stdout + result.stderr
        if client == "claude":
            data = json.loads(result.stdout)
            okay = data.get("loggedIn") and data.get("authMethod") == "claude.ai" and data.get("subscriptionType") in {"pro", "max"}
        elif client == "codex":
            okay = "Logged in using ChatGPT" in output
        else:
            # Status alone cannot establish Cursor's subscription billing path.
            okay = False
        return {"authenticated_subscription": bool(okay), "exit_code": result.returncode,
                "reason": None if okay else "Subscription authentication not verified"}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"authenticated_subscription": False, "reason": "Client authentication unavailable"}


def quota_ready(client, report):
    """A fresh provider/settings check is required: login alone does not disable overage.

    The operator supplies a local JSON observation after checking usage/settings.
    It is not stored in source control and does not grant API fallback permission.
    """
    row = report.get(client, {})
    return (row.get("subscription_only") is True and row.get("extra_usage_disabled") is True
            and row.get("remaining") is True and isinstance(row.get("checked_at"), (int, float))
            and 0 <= time.time() - row["checked_at"] <= 3600)


def preflight(client, quota, env):
    result = authentication(client, env)
    # Cursor needs an operator observation of subscription login as well as billing settings.
    if client == "cursor" and quota_ready(client, quota):
        status = subprocess.run(["cursor", "agent", "status"], capture_output=True, text=True, env=env, timeout=20)
        text = (status.stdout + status.stderr).lower()
        result["authenticated_subscription"] = status.returncode == 0 and "not logged in" not in text and "logged in" in text
    result["quota_verified"] = quota_ready(client, quota)
    result["ready"] = result["authenticated_subscription"] and result["quota_verified"]
    if not result["quota_verified"]:
        result["reason"] = "Remaining subscription quota and disabled extra usage need a fresh check"
    return result


def toml_literal(value):
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k) + "=" + toml_literal(v) for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(map(toml_literal, value)) + "]"
    return json.dumps(value)


def command(client, model, root, directory, servers, prompt, *, answer_schema=None, project_guidance=False, plain_text=False, runtime_socket=None):
    directory.mkdir(parents=True, exist_ok=True)
    config = directory / "mcp.json"
    config.write_text(json.dumps({"mcpServers": servers}))
    schema = directory / "schema.json"
    response_schema = SCHEMA if answer_schema is None else answer_schema
    schema.write_text(json.dumps(response_schema))
    if client == "claude":
        settings = {"disableAllHooks": True, "autoMemoryEnabled": False}
        if project_guidance:
            from onboarding_study import claude_exclusions
            settings["claudeMdExcludes"] = claude_exclusions(root)
        return ["claude", "-p", "--model", model, "--strict-mcp-config", "--mcp-config", str(config),
                "--setting-sources", "project" if project_guidance else "", "--settings", json.dumps(settings),
                "--tools", ",".join(NATIVE), "--allowedTools", ",".join(NATIVE + ["mcp__" + name + "__*" for name in servers]),
                "--permission-mode", "dontAsk", "--no-session-persistence", "--disable-slash-commands",
                "--output-format", "stream-json", "--verbose",
                *([] if plain_text else ["--json-schema", json.dumps(response_schema)]), prompt]
    if client == "codex":
        if project_guidance:
            from onboarding_study import check_codex_guidance
            check_codex_guidance()
        permission_args = ["--sandbox", "workspace-write"]
        if runtime_socket:
            if not Path(runtime_socket).is_absolute():
                raise ValueError("Runtime socket must be an absolute local path")
            profile = {"extends": ":workspace", "network": {"enabled": True, "mode": "limited", "domains": {},
                       "unix_sockets": {runtime_socket: "allow"}}}
            permission_args = ["-c", 'default_permissions="external_benchmark"',
                               "-c", "permissions=" + toml_literal({"external_benchmark": profile}),
                               "-c", "features.network_proxy=true", "-c", 'web_search="disabled"']
        return ["codex", "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--skip-git-repo-check",
                "--model", model, *permission_args, "--json",
                *([] if plain_text else ["--output-schema", str(schema)]),
                "--output-last-message", str(directory / "answer.json"), "-c", 'approval_policy="never"',
                "-c", 'forced_login_method="chatgpt"', "-c", "features.multi_agent=false",
                "-c", "mcp_servers=" + toml_literal(servers), "-C", str(root), prompt]
    config = root / ".cursor/mcp.json"
    config.parent.mkdir(exist_ok=True)
    global_config = Path.home() / ".cursor/mcp.json"
    inherited = json.loads(global_config.read_text()).get("mcpServers", {}) if global_config.exists() else {}
    disabled = {name: {"disabled": True} for name in inherited}
    config.write_text(json.dumps({"mcpServers": {**disabled, **servers}}))
    return ["cursor", "agent", "--print", "--model", model, "--output-format", "stream-json",
            "--sandbox", "enabled", "--force", "--trust", "--approve-mcps", "--workspace", str(root), prompt]


def invoke(client, model, root, directory, servers, prompt, timeout, env, *, answer_schema=None, project_guidance=False, plain_text=False, runtime_socket=None):
    argv = command(client, model, root, directory, servers, prompt, answer_schema=answer_schema,
                   project_guidance=project_guidance, plain_text=plain_text, runtime_socket=runtime_socket)
    execution = capture(argv, root, directory, timeout, env)
    result = parse_events(client, (directory / "events.jsonl").read_text(), directory / "answer.json")
    if plain_text:
        if client == "codex" and (directory / "answer.json").is_file():
            result["answer_text"] = (directory / "answer.json").read_text()
        elif client == "claude":
            result["answer_text"] = ""
            for line in (directory / "events.jsonl").read_text().splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                event = row.get("event", row)
                if not isinstance(event, dict):
                    continue
                if event.get("type") == "result" and isinstance(event.get("result"), str):
                    result["answer_text"] = event["result"]
    result["observations"] = observations(result)
    result.update(execution)
    result["quota_exhausted"] |= bool(QUOTA.search((directory / "trace.jsonl").read_text(errors="replace")))
    # Raw tool results belong in private traces, not the portable report.
    result.pop("tool_results")
    return result
