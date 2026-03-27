# Research Campaigns Guide

Research campaigns automate iterative experimentation: the orchestrator
generates hypotheses, spawns agent experiments in isolated git worktrees,
evaluates each result against a metric, and promotes winners -- all in a
loop you can steer while it runs.

## Overview

A research campaign is a structured search over code changes. You define:

1. A **goal** (natural language description of what you want to improve).
2. An **eval command** (a shell command that outputs a numeric metric).
3. Budget limits (max experiments, max cost, wall-clock timeout).

The orchestrator then:

- Measures a **baseline** by running the eval command on the current code.
- Generates **hypotheses** using a mix of strategies (explore, exploit, ablate, compose, reproduce).
- Spawns each experiment in an **isolated git worktree** so the main branch stays clean.
- **Evaluates** each experiment and applies an **accept policy** to decide whether the result improves on the current best.
- Tracks everything in a SQLite database for inspection, comparison, and resume.

Campaigns can run unattended for hours, or you can steer them mid-flight
with injected notes, manual holds, and promotions.

## Quick Start

```bash
# Start a campaign to maximize test pass rate
attoswarm research start \
  "Improve the parser to handle edge cases" \
  --eval-command "python -m pytest tests/ -q --tb=no | tail -1" \
  --metric-name pass_rate \
  --metric-direction maximize \
  --target-files src/parser.py \
  --max-experiments 20 \
  --max-cost 10.0

# Check the leaderboard while it runs (from another terminal)
attoswarm research leaderboard --run-id <run-id>

# Inject a steering note to guide future hypotheses
attoswarm research inject <run-id> "Focus on unicode edge cases, not performance"

# View the full feed (leaderboard + findings + steering notes)
attoswarm research feed --run-id <run-id>
```

The run ID is printed at startup and is also stored in
`.agent/research/research.db`.

## How It Works

### Worktree Isolation

Every experiment runs in its own git worktree under
`.agent/research/experiments/<experiment-id>/worktree`. The worktree is
branched from the current best commit (or HEAD for the first experiment).

```text
.agent/research/
  research.db                          # SQLite experiment database
  experiments/
    <run-id>-e001-abcd/
      worktree/                        # isolated git worktree
    <run-id>-e002-ef01/
      worktree/
```

This means:

- The main branch is never modified during a campaign.
- Multiple experiments can run in parallel without conflicts.
- Each experiment's worktree can be inspected after the run.
- Set `preserve_worktrees: false` in config to clean up worktrees for
  rejected experiments automatically.

### Evaluation

After an agent modifies code in a worktree, the orchestrator:

1. Commits all changes in the worktree.
2. Captures the diff.
3. Runs the eval command (with optional retries and repeats).
4. Parses the metric from stdout (last numeric line, or structured JSON).
5. Checks constraint checks (if the evaluator returns them).
6. Applies the accept policy against the current best value.

### Accept / Reject / Promote

The accept policy decides whether an experiment's metric is good enough:

- If accepted and `promotion_repeats > 1`, the experiment enters
  `candidate` status and queues reproduction runs for validation.
- If accepted and `promotion_repeats == 1`, the experiment is immediately
  `accepted` and becomes the new best.
- If rejected, the experiment is stored with its reason but does not
  affect the best value.

You can manually promote, hold, kill, or resume experiments at any time
using CLI commands.

### Campaign Lifecycle

```text
1. Measure baseline
2. While budget remains:
   a. Plan a batch of experiments (strategy mix + promotion queue)
   b. Execute experiments in parallel (up to max_parallel)
   c. Evaluate each result
   d. Accept/reject via policy
   e. Reconcile candidates awaiting validation
   f. Record findings
   g. Checkpoint state to SQLite
3. Print final scoreboard
```

The campaign stops when any of these conditions is met:

- `total_max_experiments` reached.
- `total_max_cost_usd` exceeded.
- `total_max_wall_seconds` elapsed.
- No more experiments can be planned.

## Experiment State Machine

Each experiment transitions through these states:

```text
              +---> candidate --+--> validated --+--> accepted
              |                 |                |
running ------+---> accepted    +--> held -------+--> killed
              |                 |                |
              +---> rejected    +--> resumed ----+
              |                      (back to candidate)
              +---> invalid
              |
              +---> error
```

| State | Meaning |
|-------|---------|
| `running` | Agent is executing in the worktree |
| `candidate` | Passed accept policy, awaiting validation repeats (`promotion_repeats > 1`) |
| `validated` | A reproduction run confirmed the candidate's result |
| `accepted` | Fully accepted as the new best (after validation or immediately) |
| `rejected` | Did not meet the accept policy threshold |
| `invalid` | Evaluation failed or constraint checks failed |
| `error` | Agent or infrastructure error before evaluation |
| `held` | Manually paused by operator via `research hold` |
| `killed` | Manually terminated by operator via `research kill` |

Manual transitions:

- `promote`: `candidate` or `held` -> `accepted`
- `hold`: `candidate` or `held` -> `held`
- `kill`: `candidate`, `held`, or `killed` -> `killed`
- `resume`: `held` or `killed` -> `candidate`

## Strategy Types

The orchestrator uses a configurable mix of strategies. The default
`strategy_mix` is:

```python
{
    "explore": 2,
    "exploit": 1,
    "ablate": 1,
    "compose": 1,
    "reproduce": 1,
}
```

The numbers are relative weights in a round-robin sequence. With the
defaults above, the sequence is:
`explore, explore, exploit, ablate, compose, reproduce, explore, ...`

### explore

Generate a fresh hypothesis from scratch. The agent starts from the
current best (or HEAD) and tries something new. Best for early
diversification when the search space is wide.

### exploit

Refine the current best experiment. The agent starts from the best
branch and tries to improve it further. Use this to squeeze more
performance out of a known-good approach.

### ablate

Remove or simplify one mechanism from the current best and check whether
the gain survives. This tests whether each component of a winning
approach is actually contributing. The agent receives explicit
instructions to remove rather than add.

### compose

Combine two successful approaches. The orchestrator picks the best
experiment and a "partner" (another accepted experiment with minimal
file overlap and high metric value), applies the partner's diff to the
worktree, and asks the agent to integrate both approaches. Falls back to
`exploit` if no suitable partner exists.

### reproduce

Re-run the evaluation on an existing experiment's commit without agent
changes. Used automatically for promotion validation
(`promotion_repeats > 1`) and available manually via `research reproduce`.

## Configuration Reference

All fields on `ResearchConfig` with their defaults:

| Field | Default | Description |
|-------|---------|-------------|
| `metric_name` | `"score"` | Display name for the metric being optimized |
| `metric_direction` | `"maximize"` | `"maximize"` or `"minimize"` |
| `experiment_timeout_seconds` | `300.0` | Timeout per experiment (agent execution) |
| `experiment_max_tokens` | `500_000` | Max tokens per experiment agent call |
| `experiment_max_cost_usd` | `2.0` | Max cost per single experiment |
| `total_max_experiments` | `100` | Stop after this many experiments |
| `total_max_cost_usd` | `50.0` | Stop when total cost exceeds this |
| `total_max_wall_seconds` | `28800.0` | Stop after this many seconds (default: 8 hours) |
| `min_improvement_threshold` | `0.0` | Minimum improvement to accept (used by ThresholdPolicy) |
| `eval_command` | `""` | Shell command that outputs the metric |
| `eval_repeat` | `1` | How many times to run eval per experiment (results are averaged) |
| `baseline_repeats` | `1` | How many times to evaluate the initial baseline |
| `promotion_repeats` | `1` | Reproduction passes required before promoting a candidate to accepted |
| `target_files` | `[]` | Files the agent should focus on modifying |
| `use_git_stash` | `true` | Whether to stash uncommitted changes before starting |
| `model` | `""` | LLM model for agent experiments |
| `backend` | `"claude"` | Agent backend (`claude`, `codex`, `aider`, `attocode`) |
| `max_parallel_experiments` | `1` | Max experiments to run concurrently per batch |
| `search_policy` | `"round_robin"` | Strategy scheduling policy |
| `experiment_workspace_mode` | `"worktree"` | Isolation mode (currently only `worktree` is supported) |
| `strategy_mix` | `{"explore": 2, "exploit": 1, "ablate": 1, "compose": 1, "reproduce": 1}` | Relative weights for each strategy in the round-robin |
| `steering_enabled` | `true` | Whether to apply injected steering notes to hypothesis generation |
| `preserve_worktrees` | `true` | Keep worktrees for rejected/invalid experiments (useful for debugging) |
| `working_dir` | `"."` | Repository root |
| `run_dir` | `".agent/research"` | Directory for run artifacts and the SQLite database |

## CLI Commands Reference

All commands live under `attoswarm research`. The database is resolved
from `--db` (explicit path) or `--run-dir` (directory containing
`research.db`). When neither is given, the default is
`.agent/research/research.db`.

### `research start`

Start a new research campaign (or resume an existing one).

```bash
attoswarm research start <GOAL> \
  --eval-command <cmd> \
  [--target-files <file>]... \
  [--max-experiments <n>] \
  [--max-parallel <n>] \
  [--experiment-timeout <seconds>] \
  [--metric-direction maximize|minimize] \
  [--metric-name <name>] \
  [--max-cost <usd>] \
  [--baseline-repeats <n>] \
  [--promotion-repeats <n>] \
  [--resume <run-id>] \
  [--config <path>] \
  [--db <path>] \
  [--working-dir <path>]
```

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `GOAL` | | (required) | Natural language goal for the campaign |
| `--eval-command` | `-e` | (required) | Shell command that outputs the metric |
| `--target-files` | `-t` | `[]` | Files the agent should modify (repeatable) |
| `--max-experiments` | | `100` | Maximum total experiments |
| `--max-parallel` | | `1` | Experiments per batch |
| `--experiment-timeout` | | `300.0` | Seconds before an experiment is killed |
| `--metric-direction` | | `maximize` | `maximize` or `minimize` |
| `--metric-name` | | `score` | Name of the metric |
| `--max-cost` | | `50.0` | Total cost budget in USD |
| `--baseline-repeats` | | `1` | Eval repeats for the baseline measurement |
| `--promotion-repeats` | | `1` | Reproduction passes before accepting a candidate |
| `--resume` | | `""` | Resume a previous run by ID |
| `--config` | | | Path to a swarm YAML config (provides spawn function) |
| `--db` | | | Path to experiment database |
| `--working-dir` | `-w` | `.` | Repository root |

Example:

```bash
attoswarm research start \
  "Reduce average response latency in the API handler" \
  -e "python bench/latency.py" \
  -t src/api/handler.py \
  --metric-direction minimize \
  --metric-name latency_ms \
  --max-experiments 30 \
  --max-parallel 2 \
  --promotion-repeats 3
```

### `research leaderboard`

Show the scoreboard for a research run.

```bash
attoswarm research leaderboard --run-id <id> [--db <path>] [--run-dir <path>] [--limit <n>]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--run-id` | (required) | Research run ID |
| `--limit` | `10` | Maximum leaderboard rows |

### `research inject`

Inject a steering note into a running campaign. Active notes are included
in hypothesis generation for subsequent experiments.

```bash
attoswarm research inject <RUN_ID> <NOTE> \
  [--scope global|strategy|experiment] \
  [--target <target>] \
  [--db <path>] [--run-dir <path>]
```

| Flag | Default | Description |
|------|---------|-------------|
| `RUN_ID` | (required) | Research run ID |
| `NOTE` | (required) | Steering note text |
| `--scope` | `global` | `global`, `strategy`, or `experiment` |
| `--target` | `""` | Optional target (strategy name or experiment ID) |

Example:

```bash
attoswarm research inject abc12345 "Avoid modifying the database schema" --scope global
attoswarm research inject abc12345 "Try caching" --scope strategy --target exploit
```

### `research feed`

Unified view: leaderboard + findings + active steering notes.

```bash
attoswarm research feed --run-id <id> \
  [--db <path>] [--run-dir <path>] \
  [--leaderboard-limit <n>] \
  [--findings-limit <n>] \
  [--notes-limit <n>]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--run-id` | (required) | Research run ID |
| `--leaderboard-limit` | `5` | Max leaderboard rows |
| `--findings-limit` | `10` | Max findings to show |
| `--notes-limit` | `10` | Max steering notes to show |

### `research monitor`

Detailed view: summary + pending candidates + findings + steering notes.

```bash
attoswarm research monitor --run-id <id> \
  [--db <path>] [--run-dir <path>] \
  [--candidate-limit <n>] \
  [--findings-limit <n>] \
  [--notes-limit <n>]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--run-id` | (required) | Research run ID |
| `--candidate-limit` | `10` | Max pending candidates to show |
| `--findings-limit` | `10` | Max findings to show |
| `--notes-limit` | `10` | Max steering notes to show |

### `research promote`

Manually promote a candidate or held experiment to accepted.

```bash
attoswarm research promote <RUN_ID> <EXPERIMENT_ID> \
  [--db <path>] [--run-dir <path>]
```

Only experiments in `candidate` or `held` status can be promoted.
Already-accepted experiments are skipped with a message. A finding
record is created automatically.

### `research hold`

Pause a candidate experiment (prevents it from being validated or
promoted by the orchestrator).

```bash
attoswarm research hold <RUN_ID> <EXPERIMENT_ID> \
  [--reason <text>] \
  [--db <path>] [--run-dir <path>]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--reason` | `"held by operator"` | Reason for holding |

### `research resume`

Resume a held or killed experiment back to candidate status.

```bash
attoswarm research resume <RUN_ID> <EXPERIMENT_ID> \
  [--db <path>] [--run-dir <path>]
```

Only experiments in `held` or `killed` status can be resumed.

### `research kill`

Permanently reject a candidate, held, or killed experiment.

```bash
attoswarm research kill <RUN_ID> <EXPERIMENT_ID> \
  [--reason <text>] \
  [--db <path>] [--run-dir <path>]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--reason` | `"killed by operator"` | Reason for killing |

### `research compare`

Side-by-side comparison of two experiments.

```bash
attoswarm research compare <RUN_ID> <EXPERIMENT_A> <EXPERIMENT_B> \
  [--db <path>] [--run-dir <path>]
```

Prints each experiment's status, strategy, branch, hypothesis, metric
value, and the delta between them (raw and quality-adjusted).

### `research reproduce`

Manually reproduce an experiment or import a git ref into the campaign.

```bash
attoswarm research reproduce <RUN_ID> \
  [--experiment-id <id>] \
  [--ref <git-ref>] \
  [--eval-command <cmd>] \
  [--working-dir <path>] \
  [--db <path>] [--run-dir <path>]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--experiment-id` | `""` | Existing experiment to reproduce |
| `--ref` | `""` | Git ref to import and score |
| `--eval-command` | `""` | Override eval command (falls back to run config) |

Pass exactly one of `--experiment-id` or `--ref`. The command creates a
worktree at the specified commit, runs the evaluator, and stores the
result. If the result improves on the current best, it is accepted.

Example:

```bash
# Reproduce an existing experiment
attoswarm research reproduce abc12345 --experiment-id abc12345-e003-beef

# Import a branch from outside the campaign
attoswarm research reproduce abc12345 --ref feature/manual-fix
```

### `research import-patch`

Apply a patch file to the campaign and evaluate it.

```bash
attoswarm research import-patch <RUN_ID> <PATCH_PATH> \
  [--base-experiment-id <id>] \
  [--base-ref <git-ref>] \
  [--eval-command <cmd>] \
  [--working-dir <path>] \
  [--db <path>] [--run-dir <path>]
```

| Flag | Default | Description |
|------|---------|-------------|
| `PATCH_PATH` | (required) | Path to a patch/diff file |
| `--base-experiment-id` | `""` | Experiment to apply patch on top of |
| `--base-ref` | `""` | Git ref to apply patch on top of |
| `--eval-command` | `""` | Override eval command |

The patch is applied with `git apply --3way`. If it applies cleanly, the
result is evaluated and stored. If it improves the current best, it is
accepted. Pass at most one of `--base-experiment-id` or `--base-ref`.

Example:

```bash
# Import a colleague's patch on top of the current best
attoswarm research import-patch abc12345 fixes/parser-edge-case.patch

# Import on top of a specific experiment
attoswarm research import-patch abc12345 fixes/cleanup.patch \
  --base-experiment-id abc12345-e007-1234
```

## Evaluation

The evaluator protocol is a single async method:

```python
async def evaluate(self, working_dir: str) -> EvalResult
```

Four built-in evaluators are provided.

### CommandEvaluator

Runs a shell command and parses the metric from stdout. This is the
default evaluator used by `research start --eval-command`.

**Metric parsing** (in order of priority):

1. **Structured JSON**: if stdout is valid JSON (or the last non-empty
   line is JSON) with a `primary_metric` or `metric` key, the full
   structure is used:

   ```json
   {
     "primary_metric": 0.87,
     "secondary_metrics": {"precision": 0.91, "recall": 0.83},
     "constraint_checks": {"no_regressions": true},
     "artifacts": ["report.html"],
     "seed": 42
   }
   ```

2. **Last numeric line**: the last line of stdout that contains a
   number. Supports integers, floats, and scientific notation.

**Non-zero exit codes** produce a failed `EvalResult` with the stderr
captured.

### ScriptEvaluator

Runs a Python script and expects JSON output with a `"metric"` key.
Falls back to structured JSON parsing (same as CommandEvaluator). Useful
when the evaluation logic is complex enough to warrant a script.

### TestPassRateEvaluator

Runs `pytest --tb=no -q` and returns the pass rate (passed / total) as
the metric. Optionally scoped to a specific test path.

```python
evaluator = TestPassRateEvaluator(test_path="tests/unit/")
```

The metadata includes `passed`, `failed`, and `total` counts.

### CompositeEvaluator

Weighted average of multiple evaluators. Useful for multi-objective
optimization where you want a single scalar metric.

```python
evaluator = CompositeEvaluator([
    (TestPassRateEvaluator("tests/"), 0.6),
    (CommandEvaluator("python bench/speed.py"), 0.4),
])
```

If some sub-evaluators fail, the composite uses only the successful
ones (re-normalizing weights). If all fail, the result is a failure.

### Constraint Checks

Evaluators can return `constraint_checks` in their result. These are
hard gates: if any constraint fails, the experiment is marked `invalid`
regardless of the metric value.

```json
{
  "primary_metric": 0.95,
  "constraint_checks": {
    "no_new_warnings": true,
    "type_check": {"passed": true},
    "memory_limit": {"passed": false, "detail": "exceeded 512MB"}
  }
}
```

A constraint fails if its value is `false`, or if it is a dict with
`"passed": false`.

## Accept Policies

Accept policies decide whether an experiment's metric is good enough to
be accepted. Three built-in policies are available.

### NeverRegressPolicy (default)

Accept any improvement over the current best, reject any regression or
tie. This is the simplest and most conservative policy.

- Direction `maximize`: accept if `candidate > baseline`.
- Direction `minimize`: accept if `candidate < baseline`.
- Ties are rejected.

### ThresholdPolicy

Accept only if the improvement exceeds a minimum threshold.

```python
policy = ThresholdPolicy(threshold=0.01)
```

- Direction `maximize`: accept if `candidate - baseline > threshold`.
- Direction `minimize`: accept if `baseline - candidate > threshold`.

Useful when small fluctuations in the metric are noise and you only want
to accept meaningful improvements.

### StatisticalPolicy

Accept based on a z-test against the metric history. Requires at least
`min_samples` (default: 5) historical values before applying the test.
Falls back to simple comparison with fewer samples.

```python
policy = StatisticalPolicy(confidence=0.95, min_samples=5)
```

The z-score is computed against the mean and standard deviation of all
accepted metric values. Supported confidence levels: 0.90 (z=1.645),
0.95 (z=1.960), 0.99 (z=2.576).

Use this when your eval command has high variance and you want to avoid
accepting lucky outliers.

## Tips & Troubleshooting

### Writing Good Eval Commands

The eval command is the most important part of a research campaign. Keep
these guidelines in mind:

- **Deterministic**: minimize randomness. If your eval has variance, use
  `--eval-repeat 3` or `--baseline-repeats 3` to average results.
- **Fast**: the eval runs once per experiment (or more with repeats). A
  60-second eval with 50 experiments is nearly an hour of eval time
  alone.
- **Informative**: use structured JSON output to capture secondary
  metrics and constraint checks alongside the primary metric.
- **Exit code**: a non-zero exit code means evaluation failure, not a
  low metric. Make sure your script exits 0 even when the metric is bad.

### Structured JSON Eval Script Template

```python
#!/usr/bin/env python
import json
import subprocess
import sys

# Run tests
result = subprocess.run(
    ["python", "-m", "pytest", "tests/", "-q", "--tb=no"],
    capture_output=True, text=True
)

passed = failed = 0
for line in result.stdout.splitlines():
    if "passed" in line:
        import re
        m = re.search(r"(\d+) passed", line)
        if m: passed = int(m.group(1))
    if "failed" in line:
        m = re.search(r"(\d+) failed", line)
        if m: failed = int(m.group(1))

total = passed + failed
pass_rate = passed / total if total > 0 else 0.0

print(json.dumps({
    "primary_metric": pass_rate,
    "secondary_metrics": {"passed": passed, "failed": failed},
    "constraint_checks": {"no_syntax_errors": result.returncode != 2},
}))
sys.exit(0)
```

### Resuming a Campaign

Pass `--resume <run-id>` to `research start` to continue a previous
run. The orchestrator loads the checkpoint from SQLite and continues
from where it left off, preserving all experiment history and the
current best.

### Steering a Running Campaign

Steering notes are injected into hypothesis generation. Use them to
redirect the search without restarting the campaign:

```bash
# Focus on a specific approach
attoswarm research inject <run-id> "Try memoization in the hot path"

# Avoid a dead end
attoswarm research inject <run-id> "Do not modify the database layer"

# Scope to a specific strategy
attoswarm research inject <run-id> "Use async IO" --scope strategy --target exploit
```

### Promotion Repeats

Set `--promotion-repeats 3` to require three successful reproduction
runs before accepting a candidate. This guards against lucky eval
results. The orchestrator automatically queues reproduce experiments for
the top candidate until the required count is reached.

### Parallel Experiments

Set `--max-parallel 4` to run up to four experiments per batch. Each
experiment gets its own worktree and agent process. The strategy mix
determines which strategies are used in each batch slot.

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Baseline evaluation fails | Eval command exits non-zero on current code | Fix the eval script or the code first |
| All experiments are `invalid` | Eval command parsing fails | Ensure the command prints a number or valid JSON |
| All experiments are `rejected` | Metric does not improve | Lower the threshold, inject steering notes, or increase experiment count |
| Campaign stops immediately | Budget too low | Increase `--max-experiments` or `--max-cost` |
| Worktree creation fails | Dirty working tree | Commit or stash changes, or set `use_git_stash: true` |
| `No spawn function configured` | Missing `--config` | Pass a swarm YAML config with `--config` to provide the agent backend |
| Compose strategy falls back to exploit | No second accepted experiment | Normal early in a campaign -- compose needs two accepted experiments with different file sets |

### Inspecting the Database

The SQLite database at `.agent/research/research.db` contains all
experiment data. You can query it directly:

```bash
sqlite3 .agent/research/research.db \
  "SELECT experiment_id, status, metric_value, strategy FROM experiments WHERE run_id='<id>' ORDER BY iteration"
```

### Cleaning Up Worktrees

If `preserve_worktrees` is `true` (the default), worktrees accumulate in
`.agent/research/experiments/`. To clean them up:

```bash
# Remove all experiment worktrees
rm -rf .agent/research/experiments/
git worktree prune
```

Or set `preserve_worktrees: false` in your config to auto-clean
worktrees for non-accepted experiments.
