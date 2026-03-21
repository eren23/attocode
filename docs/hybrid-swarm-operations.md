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

The shipped `.attocode/swarm.hybrid.yaml.example` uses `claude`, `codex`, and
`attocode` only so `doctor` passes on a default install more often. If you
prefer `aider` for judge/review roles, swap that backend explicitly in your
project config.

## 2. Command Selection

Use `attocode swarm` as the user-facing wrapper. `attoswarm` is the engine
CLI underneath; both support the same run flows.

Initialize interactively (minimal or demo):

```bash
attocode swarm init .
# or
attoswarm init .
```

Preflight backend checks:

```bash
attocode swarm doctor .attocode/swarm.hybrid.yaml
```

### Scenario Matrix

| Scenario | Command | Use this when |
|----------|---------|---------------|
| New standalone swarm | `attocode swarm start .attocode/swarm.hybrid.yaml "Implement a tiny feature and tests"` | Fresh run, fresh goal, no parent swarm lineage |
| New standalone swarm from a goal file | `attocode swarm start .attocode/swarm.hybrid.yaml "$(cat tasks/goal.md)"` | Your high-level swarm goal lives in a Markdown file |
| New child swarm from previous output | `attocode swarm continue .agent/hybrid-swarm/demo-1 --config .attocode/swarm.hybrid.yaml "$(cat tasks/goal-phase2.md)"` | Phase 2 / follow-up work should build on a previous swarm branch/output |
| Resume the same run | `attoswarm resume .agent/hybrid-swarm/demo-1` | Continue the exact same run directory after stop/interruption |
| Open dashboard only | `attocode swarm monitor .agent/hybrid-swarm/demo-1` | Inspect or reattach to an existing run without starting a new one |
| Quick no-config run | `attoswarm quick "Implement a tiny feature and tests"` | Fast ad hoc swarm without a YAML config |

### Start vs Continue vs Resume

- `start`: creates a new standalone run. Use it for a new goal.
- `continue`: creates a new child run from a previous swarm's preserved branch or result ref. Use it for follow-up or phase-2 work.
- `resume`: keeps the same run directory and persisted goal. Use it only when you want to continue the exact same swarm.

If you changed the goal text or wrote a new `goal-*.md`, that is a new swarm.
Use `start` or `continue`, not `resume`.

### Goal Files vs `--tasks-file`

There are two different inputs:

- High-level swarm goal file: pass the file contents as the positional goal text.

```bash
attocode swarm start .attocode/swarm.hybrid.yaml "$(cat tasks/goal.md)"
```

- Pre-defined decomposition file: use `--tasks-file` with `tasks.yaml`, `tasks.yml`, or `tasks.md`.

```bash
attocode swarm start .attocode/swarm.hybrid.yaml \
  --tasks-file tasks/tasks.yaml \
  "Implement the planned work"
```

`--tasks-file` is not for `goal.md` or `goal-phase2.md`. It is for
structured task decomposition files only.

### Monitor, Detach, and Reattach

Single launcher (run + monitor in one command):

```bash
attocode swarm start .attocode/swarm.hybrid.yaml "$(cat tasks/goal.md)"
```

Start coordinator in background and return immediately:

```bash
attocode swarm start .attocode/swarm.hybrid.yaml --detach "$(cat tasks/goal.md)"
```

Open the dashboard later:

```bash
attoswarm tui .agent/hybrid-swarm/demo-1
# or
attocode swarm monitor .agent/hybrid-swarm/demo-1
```

Closing the dashboard detaches from the run. It does not stop the coordinator.

### Terminal States and Finalization

You should interpret the final swarm phase based on what actually happened:

- `completed`: execution finished normally and there is no pending work left in the saved DAG.
- `shutdown`: the swarm was intentionally stopped and can be resumed with `attoswarm resume <run-dir>` if pending tasks remain.
- `planning_failed`: task decomposition or planning failed before runnable shared-workspace execution could start. This is not the same as a worker-task failure.

When a run ends in `shutdown` or `planning_failed`, inspect the run before launching a fresh swarm:

```bash
attocode swarm monitor .agent/hybrid-swarm/demo-1
attoswarm inspect .agent/hybrid-swarm/demo-1
```

Git finalization from the completion screen or CLI now routes through the same
git safety path. Runtime bookkeeping under the swarm run directory is excluded
from finalization so merge/keep actions only preserve product-code changes.

## 3. What Gets Written (Observability)

Run directory layout:

```text
.agent/hybrid-swarm/<run>/
  swarm.manifest.json
  swarm.state.json
  git_safety.json
  index.snapshot.json
  control.jsonl
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
- `swarm.manifest.json`: task definitions for resume support (updated when tasks are added dynamically).
- `git_safety.json`: git branch/stash state for TUI completion screen merge/keep actions.
- `control.jsonl`: append-only control messages from TUI (approve, reject, skip, retry, add_task, edit_task).
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
    model: gpt-5.3-codex
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

> **Tip:** Replace `backend: codex` with `backend: codex-mcp` to use the
> MCP server mode for multi-turn worker support (requires Codex v0.115+).

### C. Claude + Codex MCP (multi-turn)

```yaml
version: 1
run:
  working_dir: .
  run_dir: .agent/hybrid-swarm/cc-codex-mcp
  poll_interval_ms: 250
  max_runtime_seconds: 300

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
    backend: codex-mcp
    model: gpt-5.3-codex
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

The `codex-mcp` backend spawns a `codex mcp-server` process and uses
JSON-RPC over stdio.  The first task message creates a new Codex thread;
subsequent messages reuse the thread ID for multi-turn conversation.
This is useful for merger and reviewer roles that need iterative
dialogue with the model.

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
- `s`: stop swarm (confirmation required)
- `r`: manual refresh
- `i`: inject control message into first active agent inbox
- `n`: add a new task dynamically
- `a`: approve task plan (when in `--preview` mode)
- `x`: reject task plan (when in `--preview` mode)
- `q`: quit dashboard / detach

If a run was interrupted or stopped with pending work left, resume it with:

```bash
attoswarm resume <run_dir>
```

On completion, a summary screen appears with options:

- `[m]` Merge: merge the swarm branch into the original branch
- `[k]` Keep: keep the swarm branch for manual review
- `[q]` Quit: exit without git changes

For deeper debugging, inspect inbox/outbox files in parallel while TUI is running.

### Approval Mode (`--preview`)

Use `--preview` to review the decomposed task plan before execution starts:

```bash
attocode swarm start .attocode/swarm.hybrid.yaml --preview "Implement feature X"
attoswarm quick --preview "Refactor module Y"
```

The TUI shows the task plan and waits for approval (`a`) or rejection (`x`). On resume, a previously-approved run skips the approval gate automatically.

Note: `--preview` requires `--monitor` (the TUI). Using `--preview --no-monitor` automatically falls back to `--dry-run` since there is no TUI to approve.

### Common Mistakes

- New goal file + old run dir: use `start` or `continue`, not `resume`.
- `goal.md` with `--tasks-file`: wrong input type. Pass goal docs as positional text with `$(cat ...)`.
- `tasks.yaml` / `tasks.md` without `--tasks-file`: the orchestrator will only auto-detect those after they are copied into the run dir.
- Expecting `q` in the dashboard to stop the swarm: it only detaches. Use `s` for an explicit stop.
- Expecting `--preview --no-monitor` to wait for approval: it degrades to `--dry-run`.

### Dynamic Task Addition

Press `n` in the TUI to add a new task during execution. Added tasks:

- Are validated for dependency correctness (no cycles)
- Get code-intel enrichment (if enabled)
- Are persisted to the manifest (survive resume)

### Git Safety

By default, swarm runs create a dedicated branch (`attoswarm/<run-id>`) and stash uncommitted changes. Disable with `--no-git-safety`:

```bash
attoswarm quick --no-git-safety "test task"
attocode swarm start config.yaml --no-git-safety "test task"
```

Git safety state is persisted to `git_safety.json` in the run directory for the TUI completion screen.

## 7. Common Failure Modes

- `Unsupported backend`: typo in `roles[].backend`.
- Immediate `failed` phase: budget cap too low or `max_runtime_seconds` too low.
- Task stuck as `ready`: no matching role (`role_hint` / `task_kinds` mismatch).
- Frequent restarts: watchdog timeout too aggressive for chosen backend.
- Run says `completed` but work is still conceptually unfinished: the swarm only knows the persisted run goal and task graph. Check `swarm.state.json` and `swarm.manifest.json` first to see what that run was actually executing.
- Run says `completed` even though tasks remain pending: inspect `swarm.state.json` for pending nodes before trusting the phase alone. Treat that as a status bug / edge case, not proof that the product goal is fully satisfied.

## 8. Recommended First Real Task

Use a small, deterministic repository task first:

```text
Create a file `swarm_smoke/hello.txt` with one line `hello from swarm` and report completion.
```

Then scale to multi-file implementation tasks once telemetry and merge behavior look healthy.

## 9. Agent Quality Features (v0.2.2+)

### Shutdown Reason Tracking

When a run ends in `shutdown`, the state file now records *why*:

```bash
jq '.shutdown_reason' .agent/hybrid-swarm/demo-1/swarm.state.json
```

Possible values: `signal:SIGTERM`, `signal:SIGINT`, `control:shutdown`, `control:reject`, `approval_timeout`, `budget_exhausted`, `unknown`.

The events file also contains a diagnostic event:
```bash
grep "Shutdown requested" .agent/hybrid-swarm/demo-1/swarm.events.jsonl
```

### Context Injection

Worker agents now receive enriched prompts containing:

- **Symbol scope**: relevant AST symbols from code-intel impact analysis (up to 15)
- **Test map**: related test files discovered by naming convention (e.g., `test_<module>.py`)
- **Test command**: auto-detected test command (pytest, npm test, cargo test, go test)
- **Learning context**: patterns and antipatterns from previous runs

Inspect the full prompt an agent received:
```bash
cat .agent/hybrid-swarm/demo-1/agents/agent-task-1.prompt.txt
```

### Syntax Verification Gate

After a worker completes, modified Python and JSON files are parsed to catch syntax errors before the task is marked done. If a file doesn't parse:

- The task is marked failed
- A `warning` event is emitted with the specific syntax errors
- The task enters the retry pipeline

This runs concurrently with test verification in the result pipeline.

### PID Lockfile

A `.orchestrator.pid` file prevents concurrent orchestrators from corrupting the same run directory. Stale lockfiles are cleaned automatically by `ensure_clean_slate` on the next run.

### Diagnostic Events

Every loop exit now emits a diagnostic event explaining *why* execution stopped:

- No ready tasks (with pending task list)
- Preflight blocked all tasks
- Budget gate blocked all tasks
- Batch safety bound reached
- Shutdown requested (with reason)
