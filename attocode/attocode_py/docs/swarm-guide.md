# Swarm Mode Guide: 2 Claude Codes Working Together

This guide walks through using Attocode's swarm mode to decompose a task and run it with two parallel Claude workers.

## Scenario

You want to build a REST API for a todo app with tests. Instead of one agent doing everything sequentially, swarm mode decomposes the work, then dispatches it to two workers that run in parallel --- one focused on implementation, the other on testing.

## Setup

### 1. Copy the example config

```bash
cp .attocode/swarm.yaml.example .attocode/swarm.yaml
```

### 2. Set your API key

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

### 3. Review the config

The default config sets up two Claude Sonnet workers:

```yaml
models:
  orchestrator: anthropic/claude-sonnet-4-20250514

workers:
  - name: coder
    model: anthropic/claude-sonnet-4-20250514
    capabilities: [code, test, refactor]
    count: 1
  - name: reviewer
    model: anthropic/claude-sonnet-4-20250514
    capabilities: [review, research]
    count: 1

budget:
  totalTokens: 5000000      # 5M tokens total
  maxCost: 10.0              # $10 max spend
  maxConcurrency: 2          # 2 workers at a time

quality:
  enabled: true              # Quality gates check each output

features:
  planning: true             # LLM-assisted decomposition
  verification: true         # Integration verification at the end
```

**Key decisions:**

- `maxConcurrency: 2` means at most two workers run in parallel at any time
- The `coder` worker handles implementation tasks; the `reviewer` handles review/research
- Quality gates score each task output 1--5 and reject below threshold (default 3)

## Running It

```bash
attocode --swarm "Build a REST API for a todo app with tests"
```

Or with an explicit config path:

```bash
attocode --swarm .attocode/swarm.yaml "Build a REST API for a todo app with tests"
```

## What Happens

### Phase 1: Decomposition

The orchestrator uses the LLM to break the prompt into subtasks with dependencies:

```
Subtask 1: [design]     Design API schema and routes        (no deps)
Subtask 2: [implement]  Implement the API server            (depends on 1)
Subtask 3: [test]       Write API tests                     (depends on 1)
Subtask 4: [implement]  Implement database models           (depends on 1)
Subtask 5: [integrate]  Integration and final wiring        (depends on 2, 3, 4)
```

### Phase 2: Wave scheduling

Tasks are grouped into dependency-aware waves:

```
Wave 1:  [design]     Design API schema        -> runs alone
Wave 2:  [implement]  Implement API server  \
         [test]       Write API tests        > run in parallel
         [implement]  Database models        /
Wave 3:  [integrate]  Integration             -> runs alone
```

### Phase 3: Execution

Workers are dispatched per wave. In wave 2, both workers run simultaneously:

```
coder-0   -> "Implement the API server"     (claude-sonnet)
reviewer-0 -> "Write API tests"             (claude-sonnet)
```

When both finish, the remaining wave-2 task (database models) dispatches to whichever worker is free first.

### Phase 4: Quality gating

Each completed task is scored by the quality gate (1--5). If a task scores below threshold:

- The worker retries with feedback from the quality gate
- After max retries, the task is marked failed and dependents may cascade-skip

### Phase 5: Verification

If `features.verification` is enabled, the orchestrator runs integration checks against the produced artifacts.

### Phase 6: Synthesis

The orchestrator merges all task outputs into a final summary.

## TUI Display

When running in the interactive TUI, the SwarmPanel (toggle with `Ctrl+W`) shows live status:

```
+-- SWARM -- Executing -----------------------------------------------+
|  Wave 2/3  [████████░░░░] 67%                                       |
|                                                                      |
|  Queue: Ready: 1  Running: 2  Done: 2  Failed: 0                    |
|                                                                      |
|  Workers (2 active):                                                 |
|   * coder-0      (claude-sonnet)  Implement API server     [45s]    |
|   * reviewer-0   (claude-sonnet)  Write API tests           [32s]    |
|                                                                      |
|  Budget: 125k/5.0M tokens [##........] 3%  $0.12/$10.00             |
+----------------------------------------------------------------------+
```

Each section:

- **Header** --- current phase (Decomposing, Executing, Verifying, etc.)
- **Wave** --- which wave is active and overall progress
- **Queue** --- task counts by status
- **Workers** --- each active worker's name, model, current task, and elapsed time
- **Budget** --- token and cost usage with progress bar

## Monitoring Files

During execution, the swarm writes state to `.agent/swarm-state/`:

```
.agent/swarm-state/
  state.json          # Full snapshot (updated every ~2s)
  events.jsonl        # Append-only event log
  task-t1.json        # Per-task detail file
  task-t2.json
  ...
```

You can watch state live:

```bash
# Follow the event log
tail -f .agent/swarm-state/events.jsonl | jq .

# Check current state
cat .agent/swarm-state/state.json | jq '.status'
```

## Resuming a Session

If the process is interrupted, you can resume:

```bash
attocode --swarm-resume SESSION_ID
```

The orchestrator reloads the checkpoint (tasks, wave position, budget) and continues from where it left off. Completed tasks are not re-run.

## Troubleshooting

### Rate limits

If a worker hits a rate limit, the swarm automatically:
1. Backs off with exponential delay
2. Retries up to `rate_limit_retries` times (default 3)
3. If the model is consistently rate-limited, tries a failover model

### Hollow completions

A "hollow" completion is when a worker returns a generic response without doing real work. The quality gate detects these and retries with stronger instructions. If `enable_hollow_termination` is on, the swarm aborts after too many hollows.

### Budget exhaustion

When the token budget runs low:
1. The orchestrator reserves 15% for synthesis and verification
2. Remaining tasks get proportionally reduced budgets
3. If a budget extension handler is wired (TUI mode), the user is prompted to extend

### Task failures

When a task fails:
- The swarm retries up to `worker_retries` times (default 2)
- On retry, the worker receives failure feedback and previous attempt context
- After max retries, the task is marked failed
- Dependent tasks may be cascade-skipped or run with partial context (if >50% of deps succeeded)

## Example Configs

See `.attocode/swarm.yaml.example` for the default 2-worker setup.

### Minimal (1 worker, no quality gates)

```yaml
workers:
  - name: worker
    model: anthropic/claude-sonnet-4-20250514
    capabilities: [code, test, review, research]
    count: 1
budget:
  maxConcurrency: 1
quality:
  enabled: false
```

### High throughput (4 workers)

```yaml
workers:
  - name: coder
    model: anthropic/claude-sonnet-4-20250514
    capabilities: [code, refactor]
    count: 2
  - name: tester
    model: anthropic/claude-sonnet-4-20250514
    capabilities: [test, review]
    count: 2
budget:
  totalTokens: 10000000
  maxCost: 25.0
  maxConcurrency: 4
```
