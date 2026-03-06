# Hybrid Swarm Operations Guide (`attoswarm`)

This is the practical runbook for `attocodepy` + `attoswarm`.

## 1. Prerequisites

- Python env installed (`pip install -e ".[dev]"`)
- `attoswarm` and `attocode` commands available
- Worker CLIs available in `PATH` for the backends you use:
  - `claude`
  - `codex`
  - `aider` (optional)
  - `attocode` (optional)

If your CLI tools are already authenticated (`claude login`, `codex login`), you do not need to export API keys again for swarm runs.

## 2. Core Commands

Initialize interactively (minimal or demo):

```bash
attoswarm init .
# or
attocode swarm init .
```

Single launcher (run + monitor in one command):

```bash
attocode swarm start .attocode/swarm.hybrid.yaml "Implement a tiny feature and tests"
```

Preflight backend checks:

```bash
attocode swarm doctor .attocode/swarm.hybrid.yaml
```

Run with `attoswarm` directly:

```bash
attoswarm run .attocode/swarm.hybrid.yaml "Implement a tiny feature and tests"
```

Run through `attocode` wrapper:

```bash
attocode --swarm .attocode/swarm.hybrid.yaml --hybrid "Implement a tiny feature and tests"
```

Override run directory:

```bash
attoswarm run .attocode/swarm.hybrid.yaml --run-dir .agent/hybrid-swarm/demo-1 "task"
```

Resume from existing run-dir:

```bash
attoswarm run .attocode/swarm.hybrid.yaml --run-dir .agent/hybrid-swarm/demo-1 --resume "task"
# or
attoswarm resume .agent/hybrid-swarm/demo-1
```

Open dashboard:

```bash
attoswarm tui .agent/hybrid-swarm/demo-1
# or
attocode swarm monitor .agent/hybrid-swarm/demo-1
```

## 3. What Gets Written (Observability)

Run directory layout:

```text
.agent/hybrid-swarm/<run>/
  swarm.manifest.json
  swarm.state.json
  index.snapshot.json
  agents/
    agent-<id>.inbox.json
    agent-<id>.outbox.json
  tasks/
    task-<id>.json
  logs/
  locks/
  worktrees/
```

High-value files:

- `swarm.state.json`: phase, active agents, DAG, budget, merge queue, cursors, attempts.
- `agents/agent-*.outbox.json`: normalized events from worker subprocesses.
- `tasks/task-*.json`: per-task status, attempts, last error, assignment history.

Useful watch commands:

```bash
watch -n 1 'jq ".phase, .tasks, .budget, .merge_queue" .agent/hybrid-swarm/demo-1/swarm.state.json'
```

```bash
jq '.events[-20:]' .agent/hybrid-swarm/demo-1/agents/agent-impl-1.outbox.json
```

```bash
jq '.' .agent/hybrid-swarm/demo-1/tasks/task-t0.json
```

## 4. Recommended Minimal Configs

### A. Two Claude workers

```yaml
version: 1
run:
  working_dir: .
  run_dir: .agent/hybrid-swarm/two-cc
  poll_interval_ms: 250
  max_runtime_seconds: 180

roles:
  - role_id: impl
    role_type: worker
    backend: claude
    model: claude-sonnet-4-20250514
    count: 2
    write_access: true
    workspace_mode: worktree
    task_kinds: [implement]

  - role_id: merger
    role_type: merger
    backend: claude
    model: claude-sonnet-4-20250514
    count: 1
    write_access: true
    workspace_mode: worktree
    task_kinds: [merge]

budget:
  max_tokens: 500000
  max_cost_usd: 10

merge:
  authority_role: merger
  judge_roles: []
  quality_threshold: 0.5

watchdog:
  heartbeat_timeout_seconds: 45

retries:
  max_task_attempts: 2
```

### B. One Claude + one Codex

```yaml
version: 1
run:
  working_dir: .
  run_dir: .agent/hybrid-swarm/cc-codex
  poll_interval_ms: 250
  max_runtime_seconds: 180

roles:
  - role_id: impl
    role_type: worker
    backend: claude
    model: claude-sonnet-4-20250514
    count: 1
    write_access: true
    workspace_mode: worktree
    task_kinds: [implement]

  - role_id: merger
    role_type: merger
    backend: codex
    model: o3
    count: 1
    write_access: true
    workspace_mode: worktree
    task_kinds: [merge]

budget:
  max_tokens: 500000
  max_cost_usd: 10

merge:
  authority_role: merger
  judge_roles: []
  quality_threshold: 0.5
```

## 5. Test Matrix You Can Run Today

Deterministic local smoke tests (no real model calls):

```bash
pytest -q tests/integration/test_attoswarm_smoke.py
```

Opt-in live smoke tests (real CLIs):

```bash
ATTO_LIVE_SWARM=1 pytest -q -m live_swarm tests/integration/test_attoswarm_live_smoke.py
```

Notes:

- Live tests only require `ATTO_LIVE_SWARM=1` and backend binaries in `PATH`.
- They rely on existing CLI authentication state.

## 6. TUI Operations

From the dashboard:

- `p`: pause/resume
- `r`: manual refresh
- `i`: inject control message into first active agent inbox
- `q`: quit dashboard

For deeper debugging, inspect inbox/outbox files in parallel while TUI is running.

## 7. Common Failure Modes

- `Unsupported backend`: typo in `roles[].backend`.
- Immediate `failed` phase: budget cap too low or `max_runtime_seconds` too low.
- Task stuck as `ready`: no matching role (`role_hint` / `task_kinds` mismatch).
- Frequent restarts: watchdog timeout too aggressive for chosen backend.

## 8. Recommended First Real Task

Use a small, deterministic repository task first:

```text
Create a file `swarm_smoke/hello.txt` with one line `hello from swarm` and report completion.
```

Then scale to multi-file implementation tasks once telemetry and merge behavior look healthy.
