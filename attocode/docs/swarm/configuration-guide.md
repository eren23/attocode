# Swarm Configuration Guide

The swarm config file (`.attocode/swarm.yaml`) controls every aspect of swarm execution. All sections are optional — sensible defaults are used when omitted.

Config files are searched in this order:
1. `{project}/.attocode/swarm.yaml`
2. `{project}/.attocode/swarm.yml`
3. `{project}/.attocode/swarm.json`
4. `~/.attocode/swarm.yaml` (user-level default)

Merge order: **built-in defaults < yaml config < CLI flags**.

## Philosophy

**What it does**: A multiline string injected into every worker's system prompt. Use it to enforce coding standards across all workers.

**Default**: None.

```yaml
philosophy: |
  Write clean, tested TypeScript. Prefer simplicity over cleverness.
  Always run tests after changes. Follow existing patterns.
  Never commit secrets. Use dependency injection.
```

Workers receive the philosophy before their individual persona, so team-wide standards come first.

## Facts

**What it does**: Injects temporal and project facts into all worker system prompts. Prevents LLM training data staleness (e.g., writing "as of 2024" when it's 2026).

**Default**: Auto-detected (current date, Node version, OS).

```yaml
facts:
  custom:
    - "Today is February 2026. ALL research must target 2025-2026 data."
    - "Claude model family is now 4.x. GPT is 4.5/o3/o4-mini."
    - "Report files go in report/ directory."
```

Custom facts appear before the worker persona in the system prompt. Use this for:
- **Temporal grounding** — "The current date is..." prevents workers from citing outdated information
- **Project conventions** — "Files go in X directory" keeps outputs organized
- **Domain knowledge** — Facts the LLM's training data may lack or get wrong

| Field | Type | Description |
|-------|------|-------------|
| `currentDate` | `string` | Override auto-detected date (rarely needed) |
| `currentYear` | `number` | Override auto-detected year (rarely needed) |
| `custom` | `string[]` | List of fact strings injected into every worker prompt |

## Models

**What it does**: Controls model assignments for the orchestrator and worker auto-detection.

```yaml
models:
  orchestrator: google/gemini-2.0-flash-001   # Orchestrator model (default: --model flag)
  paid_only: false                             # Exclude free-tier models (default: false)
  planner: anthropic/claude-sonnet-4           # Model for planning phase (default: orchestrator)
  qualityGate: google/gemini-2.0-flash-001    # Model for quality gates (default: orchestrator)
```

| Field | Default | When to change |
|-------|---------|----------------|
| `orchestrator` | `--model` flag | When you want a different model for orchestration vs normal mode |
| `paid_only` | `false` | When free models are too unreliable or rate-limited |
| `planner` | orchestrator model | When you want a smarter model for planning/review |
| `qualityGate` | orchestrator model | When you want a specific model for evaluation |

## Workers

**What it does**: Defines the worker models, their capabilities, and behavioral instructions. If omitted, workers are auto-detected from OpenRouter.

```yaml
workers:
  - name: coder
    model: google/gemini-2.0-flash-001
    capabilities: [code, refactor]
    policyProfile: code-strict-bash
    persona: "You are a senior TypeScript developer."
    maxTokens: 30000
  - name: researcher
    model: google/gemini-2.0-flash-001
    capabilities: [research, analysis]
  - name: tester
    model: qwen/qwen-2.5-coder-32b-instruct
    capabilities: [test]
    persona: "You are a testing expert. Write comprehensive tests."
  - name: documenter
    model: mistralai/ministral-14b-2512
    capabilities: [document]
```

### Policy Profiles (Recommended)

Use `policyProfile` for worker behavior and tool constraints instead of hardcoding `allowedTools`/`deniedTools` on each worker.

```yaml
policyProfiles:
  code-strict-bash:
    toolAccessMode: whitelist
    allowedTools: [read_file, write_file, edit_file, list_files, glob, grep, bash]
    bashMode: strict
    bashWriteProtection: block_file_mutation
  research-safe:
    toolAccessMode: whitelist
    allowedTools: [read_file, list_files, glob, grep]
    deniedTools: [bash, write_file, edit_file, delete_file]

workers:
  - name: coder
    model: anthropic/claude-sonnet-4
    capabilities: [code]
    policyProfile: code-strict-bash
  - name: researcher
    model: google/gemini-2.0-flash-001
    capabilities: [research]
    policyProfile: research-safe
```

### Worker Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Human-readable name (e.g., `coder`, `researcher`) |
| `model` | Yes | OpenRouter model ID |
| `capabilities` | Yes | What this worker can do: `code`, `research`, `review`, `test`, `document`, `write` |
| `persona` | No | Per-worker behavioral instructions appended to system prompt |
| `contextWindow` | No | Context window size for compaction tuning |
| `maxTokens` | No | Per-worker token limit override |
| `policyProfile` | No | Named profile from `policyProfiles` or built-in defaults (`code-strict-bash`, `code-full`, `research-safe`) |
| `allowedTools` | No | Legacy compatibility whitelist (prefer `policyProfile`) |
| `deniedTools` | No | Legacy compatibility denylist (prefer `policyProfile`) |
| `role` | No | Hierarchical role: `executor` (default), `manager`, or `judge` |

### Capability Normalization

Capabilities are normalized automatically: aliases like `refactor`→`code`, `implement`→`code`, `coding`→`code`, `writing`/`synthesis`/`synthesize`/`merge`→`write`, `docs`/`documentation`→`document`, `testing`→`test` are resolved. Unknown values are silently dropped. If all capabilities are dropped, the worker falls back to `['code']`.

### Capability Mapping

Tasks are matched to workers by capability:

| Task Type | Required Capability |
|-----------|-------------------|
| `implement`, `refactor`, `integrate`, `deploy` | `code` |
| `merge` | `write` (falls back to `code` if no `write`-capable worker) |
| `research`, `analysis`, `design` | `research` |
| `test` | `test` |
| `review` | `review` |
| `document` | `document` |

## Hierarchy

**What it does**: Configures manager and judge roles for quality control. Without hierarchy, the orchestrator handles both review and quality gating.

```yaml
hierarchy:
  manager:
    model: anthropic/claude-sonnet-4
    persona: "You are a strict code reviewer focused on correctness."
  judge:
    model: google/gemini-2.0-flash-001
    persona: "You are a quality assurance expert."
```

| Role | Purpose | When it runs |
|------|---------|-------------|
| `manager` | Reviews wave outputs, spawns fix-up tasks | After each wave completes |
| `judge` | Scores individual outputs (1-5), rejects poor quality | After each task completes |

If no model is specified for a role, the orchestrator model is used.

## Budget

**What it does**: Controls token and cost limits for the entire swarm execution.

```yaml
budget:
  total_tokens: 2000000        # Total token budget across all workers
  max_cost: 1.00               # USD cost cap
  max_tokens_per_worker: 20000 # Per-worker token limit
  max_concurrency: 5           # Maximum parallel workers
  worker_timeout: 120000       # Worker timeout in ms
  dispatch_stagger_ms: 500     # Delay between dispatching workers (ms)
```

| Field | Default | When to change |
|-------|---------|----------------|
| `total_tokens` | `5,000,000` | Increase for larger tasks, decrease to save costs |
| `max_cost` | `$10.00` | Set a hard dollar limit |
| `max_tokens_per_worker` | `50,000` | Increase for complex subtasks, decrease for simple ones |
| `max_concurrency` | `3` | Increase for paid models with high rate limits |
| `worker_timeout` | `120,000` (2 min) | Increase for complex subtasks |
| `dispatch_stagger_ms` | `1,500` | Decrease for paid models, increase for free tier |

> **Note:** The `budget:` section accepts both camelCase and snake_case (e.g., `dispatch_stagger_ms` or `dispatchStaggerMs`). All other sections (communication, resilience) require camelCase.

### Budget Split

The orchestrator reserves a fraction of the total budget (default: 15%) for its own work (decomposition, planning, quality gates, synthesis). The remaining 85% is shared among workers.

```yaml
# Advanced: tune the orchestrator reserve
# (not exposed in yaml, set in SwarmConfig programmatically)
# orchestratorReserveRatio: 0.15
```

## Quality

**What it does**: Controls quality gates that validate worker outputs before they're accepted.

```yaml
quality:
  enabled: true                            # Run quality gates (default: true)
```

| Field | Default | When to change |
|-------|---------|----------------|
| `enabled` | `true` | Set `false` to skip quality gates entirely (faster but less reliable) |

Quality gates automatically skip when under rate limit pressure (to avoid compounding 429 errors) and on retried tasks (they already failed once, let them through).

## Communication

**What it does**: Controls how workers share information and context.

```yaml
communication:
  blackboard: true                      # Shared state between workers
  dependencyContextMaxLength: 2000      # Max chars of dependency output to include
  includeFileList: true                 # Include workspace file listing
```

> **Note:** The `communication:` section requires camelCase field names. Snake_case variants (`dependency_context_max_length`, `include_file_list`) are **not recognized** and will be silently ignored.

| Field | Default | When to change |
|-------|---------|----------------|
| `blackboard` | `true` | Workers post findings to a shared blackboard for others to read |
| `dependencyContextMaxLength` | `2000` | Increase if workers need more context from dependencies |
| `includeFileList` | `true` | Set `false` for large repos where the file list is too long |

## Resilience

**What it does**: Controls retry behavior, rate limit handling, and model failover.

```yaml
resilience:
  workerRetries: 2            # Retries for failed workers
  rateLimitRetries: 3         # Extra retries specifically for 429/402 errors
  modelFailover: true         # Switch models on rate limit errors
```

> **Note:** The `resilience:` section requires camelCase field names. Snake_case variants (`worker_retries`, `rate_limit_retries`, `model_failover`) are **not recognized** and will be silently ignored.

| Field | Default | When to change |
|-------|---------|----------------|
| `workerRetries` | `2` | Increase for unreliable models |
| `rateLimitRetries` | `3` | Increase for free models with strict limits |
| `modelFailover` | `true` | Set `false` if you want to stick with assigned models |

### Circuit Breaker

The circuit breaker is automatic and not configurable via yaml. It activates after 3 rate limit errors within 30 seconds, pausing all dispatch for 15 seconds. This prevents cascading failures.

## Features

**What it does**: Toggle major pipeline phases on or off.

```yaml
features:
  planning: true        # Create acceptance criteria per task
  wave_review: true     # Manager reviews each wave
  verification: true    # Run integration tests at the end
  persistence: true     # Checkpoint after each wave
```

| Field | Default | When to change |
|-------|---------|----------------|
| `planning` | `true` | Set `false` for faster execution without criteria |
| `wave_review` | `true` | Set `false` to skip manager review between waves |
| `verification` | `true` | Set `false` to skip integration testing |
| `persistence` | `true` | Set `false` if you don't need resume capability |

## Throttle

**What it does**: Controls request rate limiting to prevent 429 errors.

```yaml
throttle: free    # 'free' | 'paid' | false
```

| Value | Max Concurrent | Refill Rate | Min Spacing |
|-------|---------------|-------------|-------------|
| `free` (default) | 2 | 0.5 req/s | 1,500ms |
| `paid` | 5 | 2.0 req/s | 200ms |
| `false` | Unlimited | N/A | N/A |

The throttle wraps the LLM provider with a token bucket algorithm. It automatically backs off when rate limits are hit and recovers after sustained success.

## Permissions

**What it does**: Controls what operations workers can perform without human approval.

```yaml
permissions:
  mode: auto-safe
  auto_approve: [read_file, glob, grep, list_files, web_search, task_get, task_list]
  scoped_approve:
    write_file: { paths: ["src/", "tests/"] }
    bash: { paths: ["src/", "tests/"] }
  require_approval: [bash_dangerous]
```

| Mode | Behavior |
|------|----------|
| `strict` | Ask for every tool call |
| `interactive` | Ask for dangerous ops (default) |
| `auto-safe` | Auto-approve safe/moderate ops, ask for dangerous |
| `yolo` | Auto-approve everything |

For swarm mode, `auto-safe` is recommended — it lets workers read freely and write to specified paths without constant approval prompts.

## Tasks

**What it does**: Controls task decomposition behavior.

```yaml
tasks:
  priorities: [test, implement, document]    # Preferred decomposition order
  file_conflict_strategy: claim-based        # How to handle file conflicts
```

| Field | Default | When to change |
|-------|---------|----------------|
| `priorities` | None | Set to influence which subtask types are prioritized |
| `file_conflict_strategy` | `claim-based` | Options: `serialize`, `claim-based`, `orchestrator-merges` |

### File Conflict Strategies

| Strategy | Behavior |
|----------|----------|
| `serialize` | Only one worker can modify a file at a time |
| `claim-based` | Workers claim files before modifying; conflicts are rejected |
| `orchestrator-merges` | The orchestrator resolves file conflicts after each wave |

## Full Example

Here's a complete config using all sections:

```yaml
philosophy: |
  Write clean, tested TypeScript with strict types.
  Follow existing patterns. Run tests after changes.

facts:
  custom:
    - "Today is February 2026. Target 2025-2026 libraries and APIs."

models:
  paid_only: true

workers:
  - name: coder
    model: anthropic/claude-sonnet-4
    capabilities: [code, refactor]
    persona: "Senior TypeScript developer. Write clean, efficient code."
  - name: synthesizer
    model: anthropic/claude-sonnet-4
    capabilities: [write]
    persona: "Integration specialist. Merge research and code into coherent outputs."
  - name: tester
    model: google/gemini-2.0-flash-001
    capabilities: [test]
    persona: "Testing expert. Aim for high coverage."
  - name: researcher
    model: google/gemini-2.0-flash-001
    capabilities: [research, review]

hierarchy:
  manager:
    model: anthropic/claude-sonnet-4
    persona: "Strict code reviewer focused on correctness."
  judge:
    model: google/gemini-2.0-flash-001

budget:
  total_tokens: 3000000
  max_cost: 2.00
  max_tokens_per_worker: 30000
  max_concurrency: 5
  dispatch_stagger_ms: 300

quality:
  enabled: true

communication:
  blackboard: true
  dependencyContextMaxLength: 3000
  includeFileList: true

resilience:
  workerRetries: 2
  rateLimitRetries: 3
  modelFailover: true

features:
  planning: true
  wave_review: true
  verification: true
  persistence: true
```

## See Also

- [Example Configs](examples/) — Pre-built configs for common scenarios
- [How It Works](how-it-works.md) — Understand the pipeline these options control
- [Architecture Deep Dive](advanced/architecture-deep-dive.md) — Internal mechanics
