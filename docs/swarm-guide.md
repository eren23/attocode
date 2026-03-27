# Swarm Mode — Quick Start

Attoswarm is the multi-agent orchestration engine. It decomposes goals into tasks, dispatches them to parallel agents, reviews changes, and merges results.

## Fastest Way to Start

```bash
# No config needed — auto-detects backends, sensible defaults
attoswarm quick "Build a REST API for user auth with tests"
```

This will:
1. Detect available backends (Claude, Codex, etc.)
2. Decompose your goal into subtasks
3. Spawn worker agents in parallel
4. Review and merge their changes
5. Open the TUI dashboard to monitor progress

## With a Config File

For more control over roles, budgets, and quality gates:

```bash
# Generate a config interactively
attoswarm init .

# Or copy the example
cp .attocode/swarm.hybrid.yaml.example .attocode/swarm.hybrid.yaml

# Run with TUI monitor
attoswarm start .attocode/swarm.hybrid.yaml "Build feature X"

# Preview the task decomposition before running
attoswarm start .attocode/swarm.hybrid.yaml --preview "Refactor module Y"
```

## Research Campaigns

For iterative experiments that optimize a metric:

```bash
attoswarm research start "Improve test pass rate" \
  -e 'python -m pytest tests/ -q --tb=no 2>&1 | tail -1' \
  -t src/mymodule.py --max-experiments 10 --monitor
```

See [Research Campaigns](research-guide.md) for the full guide.

## Key Commands

| Command | What it does |
|---------|-------------|
| `attoswarm quick "<goal>"` | Zero-config swarm run |
| `attoswarm start <config> "<goal>"` | Config-driven swarm run |
| `attoswarm start <config> --preview "<goal>"` | Preview decomposition first |
| `attoswarm research start "<goal>" -e "<eval>"` | Research campaign |
| `attoswarm doctor <config>` | Check backends are working |
| `attoswarm tui <run-dir>` | Reattach to running swarm |

## Next Steps

- [Hybrid Swarm Operations](hybrid-swarm-operations.md) — full runbook with scenarios
- [Swarm Quality](guides/swarm-quality.md) — quality gates and merge policies
- [Research Campaigns](research-guide.md) — iterative experiment workflows
- [CLI Reference](cli-reference.md) — complete command reference
