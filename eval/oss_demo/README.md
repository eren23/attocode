# OSS Big-3 Demo Kit (Code-Intel)

This package runs a reproducible comparison of 3 coding-agent lanes on large
OSS repos using `attocode-code-intel` MCP tools.

## Scope
- Agents: Codex CLI, Claude Code, Cursor Composer 1.5
- Repos: `microsoft/vscode`, `django/django`, `pytorch/pytorch`
- Style: local-first, non-destructive (analysis + plan-only tasks)

## Quick Start

1. Ensure MCP integration status:

```bash
uv run attocode code-intel status
```

2. Generate agent task packets from manifest:

```bash
python -m eval.oss_demo prepare \
  --manifest eval/oss_demo/run_manifest.yaml \
  --out eval/oss_demo/generated
```

3. Execute packets in each agent and collect rows into `results.jsonl`.

4. Build comparative markdown report:

```bash
python -m eval.oss_demo summarize \
  --manifest eval/oss_demo/run_manifest.yaml \
  --results eval/oss_demo/results.jsonl \
  --out eval/oss_demo/report.md
```

## Result Row Contract (`results.jsonl`)
One JSON object per `{agent, repo, task}` with the required fields:

- `run_id` (string)
- `agent_id` (string)
- `repo_id` (string)
- `task_id` (string)
- `status` (`passed` | `failed` | `error` | `skipped`)
- `time_s` (number)
- `estimated_cost_usd` (number)
- `tool_calls` (integer)
- `score_task_completion` (0-5)
- `score_evidence_quality` (0-5)
- `score_technical_correctness` (0-5)
- `score_actionability` (0-5)
- `score_clarity` (0-5)
- `evidence_paths` (array of strings)
- `notes` (string, optional)

Optional for ablation mode:
- `mode` (`with_code_intel` | `without_code_intel`)

## Codespaces Roadmap
This kit is local-first. For parity in constrained environments, add a
per-repo `devcontainer.json` and execute the same packets in GitHub Codespaces.
