# Swarm Mode

> **For an in-depth guide with examples, see [docs/swarm/](swarm/README.md).**

## Overview

Swarm mode lets one orchestrator coordinate multiple specialist worker models in parallel. Instead of a single large model doing everything sequentially, the orchestrator decomposes a task into subtasks, dispatches them to smaller/cheaper models, reviews results, and synthesizes a final output.

Use swarm mode when:
- Your task can be decomposed into independent subtasks (feature implementation, refactoring, multi-file changes)
- You want to leverage cheap/free models for most of the work while a smarter model orchestrates
- You want parallel execution for speed

## Quick Start

```bash
# Auto-detect worker models from OpenRouter
attocode --swarm "Build a recursive descent parser"

# Use a custom config file
attocode --swarm .attocode/swarm.yaml "Refactor auth module"

# Paid models only (skip free tier)
attocode --swarm --paid-only "Implement login"

# Safe permission mode (recommended for non-yolo testing)
attocode --swarm --permission auto-safe "Add unit tests"

# Resume a previous swarm session
attocode --swarm-resume <session-id>
```

Run `attocode init` to scaffold a `.attocode/swarm.yaml` with all options commented out.

## Configuration

The swarm config file (`.attocode/swarm.yaml`) controls every aspect of swarm execution. All sections are optional — sensible defaults are used when omitted.

### Full Schema

```yaml
# Development philosophy injected into ALL worker system prompts.
# Use this to enforce coding standards across all workers.
philosophy: |
  Write clean, tested TypeScript. Prefer simplicity over cleverness.
  Always run tests after changes. Follow existing patterns.

# Model assignments
models:
  orchestrator: google/gemini-2.0-flash-001
  paid_only: false    # Set true to exclude free-tier models

# Worker definitions
workers:
  - name: coder
    model: google/gemini-2.0-flash-001
    capabilities: [code, refactor]
    persona: "You are a senior TypeScript developer."
  - name: researcher
    model: google/gemini-2.0-flash-001
    capabilities: [research, analysis]
  - name: tester
    model: qwen/qwen-2.5-coder-32b-instruct
    capabilities: [test]

# Hierarchical roles (see "Hierarchy" section below)
hierarchy:
  manager:
    model: anthropic/claude-sonnet-4
    persona: "You are a strict code reviewer focused on correctness."
  judge:
    model: google/gemini-2.0-flash-001
    persona: "You are a quality assurance expert."

# Token and cost budgets
budget:
  total_tokens: 2000000
  max_cost: 1.00
  max_tokens_per_worker: 20000

# Quality gates
quality:
  gates: true
  gate_model: google/gemini-2.0-flash-001

# Inter-worker communication
communication:
  blackboard: true                      # Shared state between workers
  dependency_context_max_length: 2000   # Max chars of dependency output to include
  include_file_list: true               # Include workspace file listing

# Resilience and rate limiting
resilience:
  max_concurrency: 5
  worker_retries: 2
  rate_limit_retries: 3
  dispatch_stagger_ms: 500

# Permission settings (see "Permission Modes" section below)
# permissions:
#   mode: auto-safe
#   auto_approve: [read_file, glob, grep, list_files, search]
#   scoped_approve:
#     write_file: { paths: ["src/", "tests/"] }
#     bash: { paths: ["src/", "tests/"] }
#   require_approval: [bash_dangerous]
```

## Hierarchy

Swarm uses three hierarchical roles with separated authority:

### Executor (default)
Regular workers that perform the actual subtasks (coding, testing, research). All workers are executors unless promoted.

### Manager
Reviews wave outputs and makes re-dispatch decisions. The manager sees all completed work after each wave and decides:
- Whether outputs meet acceptance criteria
- Which tasks need retrying
- What follow-up tasks to create

Configure via `hierarchy.manager` in `swarm.yaml`.

### Judge
Runs quality gates on individual worker outputs. Scores each output and provides feedback. Failed quality gates trigger worker retries.

Configure via `hierarchy.judge` in `swarm.yaml`. If no judge model is specified, the orchestrator model is used.

### How They Interact

```
Orchestrator (plans & dispatches)
  └─► Executor workers (parallel subtasks)
        └─► Judge (quality gate per output)
              └─► Manager (wave review)
                    └─► Orchestrator (next wave or synthesis)
```

## Worker Personas & Philosophy

### Philosophy
The `philosophy` field is injected into every worker's system prompt. Use it to enforce team-wide standards:

```yaml
philosophy: |
  Always write tests first. Use dependency injection.
  Never commit secrets. Follow the project's existing patterns.
```

### Per-Worker Personas
Each worker can have a `persona` that tailors its behavior:

```yaml
workers:
  - name: security-reviewer
    model: google/gemini-2.0-flash-001
    capabilities: [review]
    persona: "You are a security expert. Focus on OWASP Top 10 vulnerabilities."
```

Personas are appended after the philosophy in the system prompt, so they layer on top of team-wide standards.

## Permission Modes

Swarm workers inherit the permission mode from the CLI. Available modes:

| Mode | Behavior |
|------|----------|
| `strict` | Ask for every tool call |
| `interactive` | Ask for dangerous ops (default) |
| `auto-safe` | Auto-approve safe/moderate ops, ask for dangerous |
| `yolo` | Auto-approve everything |

### Recommended: `auto-safe`

For testing swarm mode without constant approval prompts but with safety for destructive operations:

```bash
attocode --swarm --permission auto-safe "Implement feature X"
```

This auto-approves read operations (file reads, glob, grep, search) and moderate writes, while still requiring approval for dangerous operations like destructive bash commands.

### Scoped Approvals in Config

You can also configure path-scoped approvals in `swarm.yaml`:

```yaml
permissions:
  mode: auto-safe
  auto_approve: [read_file, glob, grep, list_files, search]
  scoped_approve:
    write_file: { paths: ["src/", "tests/"] }
    bash: { paths: ["src/", "tests/"] }
  require_approval: [bash_dangerous]
```

This restricts file writes and bash execution to specific directories.

## Rate Limit Awareness

Swarm mode includes proactive rate limit handling:

1. **Request throttling** — Configurable delays between API calls. Default: free-tier throttle (20 req/min, 200 req/day). Set `--paid-only` for paid-tier limits.

2. **Dispatch staggering** — Workers are dispatched with configurable delays (`dispatch_stagger_ms`, default: 500ms) to avoid bursting.

3. **Automatic retries** — Rate-limited requests (429/402) are retried with exponential backoff up to `rate_limit_retries` times (default: 3).

4. **Model failover** — When a model is rate-limited, the orchestrator can switch to an alternative model (`enableModelFailover: true`, default).

```yaml
resilience:
  dispatch_stagger_ms: 1000   # 1s between dispatches
  rate_limit_retries: 5       # More retries for rate limits
```

## Dashboard

Swarm execution can be visualized in the trace dashboard when `--trace` is enabled:

```bash
# Run swarm with tracing
attocode --swarm --trace "Build feature X"

# Open the dashboard
npm run dashboard
```

The dashboard shows:
- Task DAG with dependency edges
- Worker timeline (parallel execution visualization)
- Budget consumption (tokens and cost)
- Quality gate scores per task
- Event feed (real-time swarm events)
- Model distribution across workers

## Budget

Swarm budgets control total resource consumption:

```yaml
budget:
  total_tokens: 2000000        # Total tokens across all workers
  max_cost: 1.00               # USD cost cap
  max_tokens_per_worker: 20000 # Per-worker token limit
```

The orchestrator reserves a fraction of the budget for its own planning and synthesis (`orchestratorReserveRatio: 0.15` by default). Workers are terminated if they exceed their individual token limits.

Budget is tracked across waves — if early waves consume less than expected, later waves can use the surplus.

## Troubleshooting

### Workers failing immediately
- Check that your `OPENROUTER_API_KEY` is set and valid
- Run `attocode --swarm --paid-only` to skip free-tier models that may have restrictive limits
- Increase `dispatch_stagger_ms` to reduce rate limit pressure

### Quality gates rejecting everything
- The default quality threshold may be too strict for your use case
- Try setting a specific `gate_model` that's good at evaluation
- Add a judge persona that matches your project's quality standards

### Workers not using tools
- Check `toolAccessMode` — default is `'all'`, which gives workers access to all tools
- If using `'whitelist'` mode, ensure each worker's `allowedTools` includes what they need
- Verify MCP servers are connected if workers need external tools

### Rate limits exhausted
- Add `--paid-only` to use models with higher rate limits
- Increase `dispatch_stagger_ms` and reduce `max_concurrency`
- Set `rate_limit_retries` higher for transient 429 errors

### Resuming failed runs
- Swarm state is checkpointed after each wave (when `enablePersistence: true`)
- Use `--swarm-resume <session-id>` to continue from the last checkpoint
- State is stored in `.agent/swarm-state/` by default
