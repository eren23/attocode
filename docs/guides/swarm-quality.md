# Swarm Quality Improvements

Attocode's swarm mode includes multiple quality layers that catch errors early, enrich thin task descriptions, verify worker outputs, and pause for human input when needed. These features work together to reduce wasted LLM calls and improve first-attempt success rates.

---

## Mandatory Compilation Checks

Every action task's output is checked for syntax and compilation errors **before** reaching the LLM quality gate. This saves quality gate costs by rejecting obviously broken code immediately.

### What It Catches

| Language | Check Method | Catches |
|----------|-------------|---------|
| Python (`.py`) | `compile(source, file, 'exec')` + import resolution | Syntax errors, indentation errors, unresolved imports |
| TypeScript (`.ts`, `.tsx`) | `npx tsc --noEmit --isolatedModules` | Type errors, syntax errors, missing imports |
| JavaScript (`.js`, `.jsx`, `.mjs`, `.cjs`) | `node --check` | Syntax errors, parse failures |
| JSON (`.json`) | `json.loads()` | Malformed JSON, trailing commas, encoding issues |

### How It Works

1. After a worker completes a task, modified files are grouped by extension
2. Each group runs through its language-specific checker
3. If any file has errors with `severity == "error"`, the check fails
4. Structured error data (file, line number, message) is attached to the task's `RetryContext`
5. The worker sees exact error locations on its next attempt

### Structured Error Feedback

Workers receive precise error locations in their retry context, not vague "something failed" messages:

```
## Compilation Errors (from previous attempt)

- src/auth/middleware.py:42 — SyntaxError: unexpected indent
- src/models/user.py:15 — SyntaxError: invalid syntax
```

### Configuration

Compilation checks are **always on** for action tasks. There is no flag to disable them. They run before the quality gate in the execution pipeline.

!!! note "Performance"
    Python and JSON checks run in-process (<10ms/file). JavaScript checks use `node --check` (~100ms/file). TypeScript checks batch files through a single `tsc` invocation.

---

## Task Enrichment Pipeline

### Problem

The decomposer sometimes produces subtasks with thin descriptions: a single sentence, no acceptance criteria, no file references. Workers receiving these descriptions produce vague or incorrect output.

### Solution

A post-decomposition enrichment pipeline runs after task decomposition and before scheduling. It adds acceptance criteria, code context, technical constraints, and modification instructions to each subtask.

### Pipeline Steps

1. **Quality check** --- Flag tasks with short descriptions (<80 chars), missing actionable verbs, or no target/relevant files
2. **Code context gathering** --- Read target and relevant files, extract key structures (classes, functions) via AST service
3. **Rule-based criteria** --- Generate acceptance criteria based on task type (implement, test, refactor, document, deploy)
4. **LLM enrichment** --- For tasks still flagged as thin after steps 1--3, call the LLM to flesh out descriptions

If more than 50% of enrichable tasks remain thin after LLM enrichment, the pipeline requests a re-decomposition.

### Example

**BEFORE** (thin task from decomposer):

```yaml
- id: task-3
  type: implement
  description: "Add validation"
  target_files: []
  acceptance_criteria: []
```

**AFTER** (enriched task):

```yaml
- id: task-3
  type: implement
  description: >
    Add input validation to the UserCreateRequest model in
    src/models/user.py. Validate email format using a regex pattern,
    enforce password minimum length of 8 characters, and ensure
    username contains only alphanumeric characters. Raise
    ValidationError with descriptive messages for each field.
  target_files:
    - src/models/user.py
  acceptance_criteria:
    - "File 'src/models/user.py' exists and is non-empty"
    - "Contains described functions/classes"
    - "Imports resolve without errors"
    - "No syntax errors in modified files"
  technical_constraints:
    - "Use stdlib re module, not third-party validators"
    - "ValidationError must include field name in message"
  modification_instructions: >
    1. Open src/models/user.py
    2. Add validate_email(), validate_password(), validate_username()
    3. Call validators in UserCreateRequest.__post_init__()
  test_expectations:
    - "test_valid_email passes"
    - "test_invalid_email raises ValidationError"
```

### Configuration

```yaml
# .attocode/swarm.yaml
swarm:
  enable_task_enrichment: true          # default: true
  enrichment_min_description_chars: 80  # default: 80
```

Set `enable_task_enrichment: false` to skip enrichment entirely (useful for well-structured decomposers that already produce rich descriptions).

---

## Verification Gate

The verification gate runs automated checks on worker outputs after task completion. It is **decoupled** from the `quality_gates` flag --- verification runs independently.

### Checks Performed

| Check | Tool | When |
|-------|------|------|
| Tests | `pytest --tb=short -q` or `npm test` | Python project with `pyproject.toml` or `tests/` directory; Node project with `package.json` |
| Type checking | `mypy .` or `npx tsc --noEmit` | Python with `pyproject.toml`; TypeScript with `tsconfig.json` |
| Linting | `ruff check .` or `npx eslint .` | Python with `pyproject.toml`; Node with `package.json` |
| LLM review | Prompt-based evaluation | When an LLM provider is configured |

### Structured Failure Feedback

When verification fails, the gate produces structured suggestions that are attached to the task's retry context:

```
[tests] FAILED: 2 tests failed
  - test_user_validation::test_empty_email
  - test_user_validation::test_password_too_short

[type_check] FAILED: src/models/user.py:42: error: Argument 1 has incompatible type "str"

[lint] PASSED
```

Workers see these structured failures on retry, with actionable fix suggestions.

### Configuration

```yaml
swarm:
  enable_verification: true   # default: true (independent of quality_gates)
  quality_gates: true          # default: true (LLM-based quality scoring)
  quality_threshold: 3         # default: 3 (1-5 scale)
  max_verification_retries: 2  # default: 2
```

!!! info "Verification vs Quality Gates"
    `enable_verification` controls automated filesystem checks (tests, types, lint). `quality_gates` controls LLM-based scoring of task output. Both can be enabled independently. Verification catches objective errors; quality gates catch subjective quality issues.

---

## User Intervention Hook

When a task fails repeatedly, the swarm can pause and request human intervention instead of immediately cascade-skipping the task and its dependents.

### How It Works

1. A task fails and exhausts its retry budget (`worker_retries`)
2. If `enable_user_intervention` is `true` and `task.attempts >= user_intervention_threshold`, the swarm emits a `swarm.task.intervention_needed` event
3. The TUI/dashboard displays an intervention prompt with error details
4. **Cascade skip is deferred** --- dependent tasks are not skipped yet
5. The user can provide guidance, fix the issue, or allow the cascade skip to proceed

### Event Payload

The `swarm.task.intervention_needed` event includes:

```python
{
    "task_id": "task-3",
    "description": "Add input validation to UserCreateRequest",
    "attempts": 3,
    "last_error": "SyntaxError: unexpected indent at line 42",
    "compilation_errors": [
        {"file": "src/models/user.py", "line": 42, "message": "SyntaxError: unexpected indent"}
    ],
    "failure_mode": "error",
    "model": "claude-sonnet-4-20250514",
}
```

### Configuration

```yaml
swarm:
  enable_user_intervention: false  # default: false (opt-in)
  user_intervention_threshold: 3   # default: 3 (pause after N failed attempts)
```

!!! warning "Opt-in Feature"
    User intervention is disabled by default. Enable it for supervised swarm runs where a human is available to review failures. For unattended runs, leave it disabled so the swarm can cascade-skip and continue.

---

## Structured Retry Context

When a task is retried, the worker receives a `RetryContext` containing structured error data from the previous attempt. This replaces the older pattern of passing raw error text.

### RetryContext Fields

| Field | Type | Description |
|-------|------|-------------|
| `previous_feedback` | `str` | Quality gate feedback text |
| `previous_score` | `int` | Quality gate score (1--5) |
| `attempt` | `int` | Current attempt number |
| `previous_model` | `str | None` | Model used in previous attempt |
| `previous_files` | `list[str] | None` | Files modified in previous attempt |
| `swarm_progress` | `str | None` | Summary of overall swarm progress |
| `compilation_errors` | `list[dict] | None` | Structured `[{file, line, message}]` from compilation checks |
| `test_failures` | `list[str] | None` | Test names that failed |
| `verification_suggestions` | `list[str] | None` | Actionable fix suggestions from verification gate |

### What Workers See

On retry, the worker's prompt includes structured error context:

```
## Previous Attempt (attempt 2/3, score: 2/5)

### Compilation Errors
- src/models/user.py:42 — SyntaxError: unexpected indent
- src/models/user.py:15 — ImportError: cannot import 'Validator' from 'pydantic'

### Test Failures
- test_user_validation::test_empty_email
- test_user_validation::test_password_too_short

### Fix Suggestions
- [type_check] Fix indentation at line 42 in user.py
- [tests] Ensure validate_email handles empty string input

### Quality Gate Feedback
"Validation logic is incomplete. Missing email format check and
password length enforcement."
```

---

## New SwarmConfig Fields Reference

All quality-related configuration fields added to `SwarmConfig`:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enable_task_enrichment` | `bool` | `true` | Run post-decomposition enrichment pipeline |
| `enrichment_min_description_chars` | `int` | `80` | Minimum description length before flagging as thin |
| `enable_verification` | `bool` | `true` | Run automated checks (tests, types, lint) on worker outputs |
| `enable_user_intervention` | `bool` | `false` | Pause tasks for user review after repeated failures |
| `user_intervention_threshold` | `int` | `3` | Number of failed attempts before requesting intervention |
| `quality_gates` | `bool` | `true` | Enable LLM-based quality scoring |
| `quality_threshold` | `int` | `3` | Minimum quality score (1--5) to accept task output |
| `quality_gate_model` | `str` | `""` | Model override for quality gate LLM calls |
| `enable_concrete_validation` | `bool` | `true` | Validate task outputs against concrete criteria |
| `max_verification_retries` | `int` | `2` | Maximum verification retry attempts |
| `worker_retries` | `int` | `2` | Base retry limit for failed tasks |
| `max_dispatches_per_task` | `int` | `5` | Hard cap on total dispatches per task |

### Full Example Configuration

```yaml
# .attocode/swarm.yaml
swarm:
  # Quality pipeline
  quality_gates: true
  quality_threshold: 3
  enable_concrete_validation: true
  enable_task_enrichment: true
  enrichment_min_description_chars: 80
  enable_verification: true
  max_verification_retries: 2

  # Retry & intervention
  worker_retries: 2
  max_dispatches_per_task: 5
  enable_user_intervention: false
  user_intervention_threshold: 3
```
