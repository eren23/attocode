# /swarm-verify — Post-Run Trace Verification

Verify the integrity of a hybrid swarm run by analysing its trace data.

## Usage

```
/swarm-verify <run_dir>
```

Where `<run_dir>` is the path to a swarm run directory (e.g. `.agent/hybrid-swarm/run_abc123`).

## Verification Procedure

When invoked, follow these steps exactly:

### Step 1 — Load Trace Data

```python
from tests.helpers.trace_verifier import TraceVerifier

v = TraceVerifier("<run_dir>")
```

Report file counts:
- Number of events in `swarm.events.jsonl`
- Number of task files in `tasks/`
- Current phase from `swarm.state.json`

### Step 2 — Check for Poisoned Prompts

```python
result = v.assert_no_poisoned_prompts()
```

Poisoned markers: `[TASK_DONE]`, `[TASK_FAILED]`, `[HEARTBEAT]`, `[CONTROL]`, `[EXIT]`

These should never appear in raw `agent.event` messages — they indicate the agent is echoing or injecting control signals.

### Step 3 — Validate Task State Machine

```python
result = v.assert_correct_task_transitions()
```

Every `task.transition` event must follow the canonical FSM defined in `attoswarm.coordinator.loop.TRANSITIONS`. Report any illegal transitions.

### Step 4 — Check Terminal Events

```python
result = v.assert_all_tasks_have_terminal_events()
```

Every task that reached `done` should have matching `agent.task.exit` and `agent.task.classified` events.

### Step 5 — Check for Stuck Agents

```python
result = v.assert_no_stuck_agents()
```

No heartbeat gap > 30s between consecutive `agent.event` entries for the same agent.

### Step 6 — Verify Budget Limits

```python
result = v.assert_budget_within_limits()
```

`tokens_used <= tokens_max` and `cost_used <= cost_max`.

### Step 7 — Check Exit Code Propagation

```python
result = v.assert_exit_codes_propagated()
```

No tasks left in `running` status when the assigned agent has a non-null exit code.

### Step 8 — Verify Coding Task Output

```python
result = v.assert_coding_tasks_produced_output()
```

Implement/test/integrate tasks that reached `done` should show evidence of file operations.

### Step 9 — Run Screenshot Comparison (Optional)

If baselines exist in `tests/snapshots/test_attoswarm_snapshots/`, optionally run:

```bash
.venv/bin/python -m pytest tests/unit/tui/test_attoswarm_snapshots.py -v
```

### Step 10 — Print Summary

```python
print(v.summary())
```

Format as a table showing each check with PASS/FAIL status and details.

## Quick Run-All

For a one-shot summary:

```python
from tests.helpers.trace_verifier import TraceVerifier
print(TraceVerifier("<run_dir>").summary())
```

## Exit Criteria

- All 7 checks pass: run is verified clean
- Any check fails: report violations and suggest remediation
