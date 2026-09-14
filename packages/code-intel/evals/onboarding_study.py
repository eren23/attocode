"""Isolated replay of the shipped installer, with excluded guidance and transport checks."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import statistics
import subprocess
from pathlib import Path

LANES = ("native", "intel_available", "intel_installed")
TASK_IDS = ("express:quality_stale", "fastapi:quality_dependency_discovery")
NAME = "attocode-code-intel"
GUIDANCE = {"codex": "AGENTS.md", "claude": "CLAUDE.md"}


def claude_exclusions(root):
    """Exclude personal/ancestor memory without disabling the installed project file."""
    paths = [str(Path.home() / ".claude/CLAUDE.md"), str(Path.home() / ".claude/rules/**")]
    for parent in root.resolve().parents:
        paths.extend(str(parent / name) for name in
                     ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md", ".claude/rules/**"))
    return sorted(set(paths))


def check_codex_guidance():
    # --ignore-rules controls execpolicy, NOT AGENTS.md. Do not move user files
    # or replace CODEX_HOME (which also controls subscription authentication).
    base = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    for name in ("AGENTS.override.md", "AGENTS.md"):
        path = base / name
        if path.exists() and path.read_text().strip():
            raise ValueError("Onboarding diagnostic requires empty Codex global guidance; user files were not changed")


def configure_setup(manifest, study, root, lane, stage_dir, client):
    """Run the FROZEN installer. Replay its MCP entry with a pinned executable/env.

    This isolates configuration loading from personal settings. It tests the
    real project guidance loader, not global config discovery or an IDE restart.
    """
    from study_clients import subscription_env
    if lane not in LANES or client not in GUIDANCE:
        raise ValueError("Unsupported onboarding setup")
    if client == "codex":
        check_codex_guidance()
    # Refuse competing instructions instead of silently modifying benchmark input.
    for pattern in ("AGENTS*.md", "CLAUDE*.md", ".claude/*.md", ".claude/rules/*", ".claude/settings*.json",
                    ".claude/skills/*", ".codex/config.toml", ".mcp.json"):
        if any(root.rglob(pattern)):
            raise ValueError("Onboarding snapshot already contains client guidance/configuration")
    audit = {"lane": lane, "servers": {}, "guidance_path": GUIDANCE[client], "guidance_sha256": None,
             "guidance_present": False, "cache_state": "fresh_repository",
             "configuration_loading": "installed MCP entry replayed through isolated CLI overrides"}
    if lane == "native":
        return audit
    env = subscription_env()
    env["PYTHONPATH"] = str(study / "engine")
    script = ("import json,sys; from attocode_intel.onboarding import configure_client; "
              "print(json.dumps(configure_client(sys.argv[1], sys.argv[2], profile='daily')))")
    installed = subprocess.run([manifest["python"], "-c", script, client, str(root)], env=env,
                               capture_output=True, text=True, check=True, timeout=30)
    paths = json.loads(installed.stdout)
    config = Path(paths["config"])
    if client == "codex":
        import tomllib
        entry = tomllib.loads(config.read_text())["mcp_servers"][NAME]
    else:
        entry = json.loads(config.read_text())["mcpServers"][NAME]
    # Installed console scripts may point at the working checkout. Keep the
    # installer's project/profile arguments but run the frozen package directly.
    args = entry["args"]
    if args[:2] == ["-m", "attocode_intel.entrypoint"]:
        args = args[2:]
    if args != ["--profile", "daily", "--project", str(root.resolve())]:
        raise ValueError("Installer arguments changed; review the benchmark adapter")
    entry = {**entry, "command": manifest["python"], "args": ["-m", "attocode_intel.entrypoint", *args],
             "env": {"PYTHONPATH": str(study / "engine"), "ATTOCODE_INTEL_PRECISION": "off",
                     "ATTOCODE_INTEL_TRACE": str(stage_dir / "engine.jsonl")}}
    audit["servers"] = {NAME: entry}
    guidance = Path(paths["guidance"])
    audit["installed_guidance_sha256"] = hashlib.sha256(guidance.read_bytes()).hexdigest()
    audit["installed_config_sha256"] = hashlib.sha256(config.read_bytes()).hexdigest()
    if lane == "intel_available":
        guidance.unlink()
    else:
        audit["guidance_present"] = True
        audit["guidance_sha256"] = audit["installed_guidance_sha256"]
    return audit


def wiring_ready(study, manifest, client):
    path = study / "wiring" / client / "result.json"
    if not path.exists():
        return False
    row = json.loads(path.read_text())
    return (row.get("study_id") == manifest["study_id"] and row.get("excluded") is True
            and row.get("passed") is True and all(row.get("checks", {}).get(k) is True
                                                 for k in ("guidance_loaded_without_reads", "transport")))


def guidance_checks(result, token):
    return (not result["exit_code"] and not result["timed_out"] and not result["quota_exhausted"]
            and not result.get("terminal_error") and not result["permission_denials"]
            and all(c["name"] == "StructuredOutput" for c in result["tool_calls"])
            and result["output"].get("readiness_token") == token)


def wiring(args):
    from pilot import wiring_checks
    from study import manifest_for, write_json
    from study_clients import invoke, parse_events, preflight, subscription_env
    from workflows import SCENARIOS
    manifest = manifest_for(args.study)
    env = subscription_env()
    task = next(t for t in SCENARIOS if t["repo"] == "express")
    schema = {"type": "object", "properties": {"readiness_token": {"type": "string"}},
              "required": ["readiness_token"], "additionalProperties": False}
    for client in args.clients or manifest["onboarding"]["clients"]:
        if client not in manifest["onboarding"]["clients"]:
            raise ValueError("Client is outside this frozen diagnostic")
        directory = args.study / "wiring" / client
        if directory.exists():
            if wiring_ready(args.study, manifest, client):
                continue
            raise ValueError("Preserve failed/interrupted onboarding checks; freeze a new diagnostic after fixing them")
        quota = json.loads(args.quota.read_text()) if args.quota and args.quota.exists() else {}
        status = preflight(client, quota, env)
        if not status["ready"]:
            print(json.dumps({"client": client, "blocked": status}), flush=True)
            continue
        root = directory / "repository"
        shutil.copytree(args.study / "sources/express", root,
                        ignore=shutil.ignore_patterns("node_modules", ".git", ".attocode", "__pycache__"))
        directory.chmod(0o700)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        setup = configure_setup(manifest, args.study, root, "intel_installed", directory / "transport", client)
        guidance = root / GUIDANCE[client]
        original = guidance.read_bytes()
        token = secrets.token_hex(16)
        # Canary is ONLY in this excluded project file, never the task prompt,
        # environment, MCP server or any scored repository.
        guidance.write_text(guidance.read_text() + f"\nReadiness token: {token}\n")
        prompt = ("Excluded readiness check: return the readiness token already supplied in your project instructions. "
                  "Do not call tools, read files, delegate or edit anything. If no token is loaded, return 'missing'.")
        try:
            loaded = invoke(client, manifest["models"][client], root, directory / "guidance", setup["servers"], prompt,
                            120, env, answer_schema=schema, project_guidance=True)
        finally:
            guidance.write_bytes(original)
        checks = {"guidance_loaded_without_reads": guidance_checks(loaded, token), "transport": False}
        write_json(directory / "guidance-result.json", {"excluded": True, "execution": loaded, "checks": checks})
        execution = None
        quota = json.loads(args.quota.read_text()) if args.quota and args.quota.exists() else {}
        if checks["guidance_loaded_without_reads"] and preflight(client, quota, env)["ready"]:
            prompt = ("Excluded wiring check. Read lib/response.js with a native tool and call "
                      "attocode-code-intel.inspect_symbol(symbol_name='json', file_path='lib/response.js'). "
                      "Read a real usage with native tools. Return JSON with definition and usage (path, 1-based line, "
                      "exact source-line quote), tests (paths or []), and summary. Use repository-relative paths. "
                      "Do not edit files, delegate, install packages, use the network, or change settings.")
            stage = directory / "transport"
            execution = invoke(client, manifest["models"][client], root, stage, setup["servers"], prompt,
                               manifest["timeout"], env, project_guidance=True)
            parsed = parse_events(client, (stage / "events.jsonl").read_text(), stage / "answer.json")
            # Reuse the source/transport checker without adding competitor tools.
            for call in parsed["tool_calls"]:
                call["name"] = call["name"].replace(f"mcp__{NAME}__", "mcp__current__")
            transport = wiring_checks(parsed, execution, root, task, manifest["models"][client])
            transport.pop("previous_source_result")
            transport.pop("serena_source_result")
            checks["transport"] = all(transport.values())
            checks["transport_details"] = transport
        write_json(directory / "result.json", {"study_id": manifest["study_id"], "client": client,
                   "excluded": True, "selection": "forced_readiness", "passed":
                   checks["guidance_loaded_without_reads"] and checks["transport"], "checks": checks,
                   "setup": setup, "execution": execution})
        print(json.dumps({"client": client, "checks": checks}), flush=True)


def summarize(manifest, rows):
    from quality_scoring import summarize as quality_summary
    quality = quality_summary(manifest, rows)
    if quality["issues"]:
        return {"issues": quality["issues"], "release_eligible": False}
    groups = []
    for client in manifest["onboarding"]["clients"]:
        for lane in LANES:
            selected = [r for r in rows if r["client"] == client and r["lane"] == lane]
            stages = [s for r in selected for s in r.get("stages", [])]
            groups.append({"client": client, "lane": lane, "attempted": len(selected),
                           "mcp_used_runs": sum(any(s.get("mcp_used") for s in r.get("stages", [])) for r in selected),
                           "first_tool_mcp_runs": sum(bool(s.get("tool_calls")) and
                                                      s["tool_calls"][0]["name"].startswith("mcp__") for s in stages),
                           "median_setup_seconds": statistics.median(values) if
                           (values := [r["setup_seconds"] for r in selected if "setup_seconds" in r]) else None,
                           "usage": [s.get("usage", {}) for s in stages],
                           "observations": [s.get("observations", {}) for s in stages]})
    return {"groups": groups, "scope": manifest["onboarding"]["scope"], "release_eligible": False,
            "guidance_readiness": "Excluded canary requires exact token without tool reads; absent from scored tasks",
            "cache_state": "Fresh per-run repository and MCP process; OS caches uncontrolled; no warm-use claim",
            "useful_evidence_reuse": "Requires trace review; a tool call or later native read alone does not prove reuse or redundancy"}
