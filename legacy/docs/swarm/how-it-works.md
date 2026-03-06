# How Swarm Mode Works

This guide explains the difference between attocode's normal single-agent mode and swarm mode, then walks through the full swarm pipeline in detail.

## Normal Mode (Single Agent)

In normal mode, attocode runs one model in a sequential loop:

```
User → Agent → LLM → Tools → LLM → Tools → ... → Result
```

The agent:
1. Reads the user's prompt
2. Sends it to one LLM (e.g., Claude, GPT-4)
3. The LLM decides which tool to call (read a file, edit code, run a command)
4. The agent executes the tool and feeds the result back to the LLM
5. Repeat until the LLM produces a final response

All reasoning, planning, and execution happen in a single conversation with one model. This works well for focused tasks, conversations, and small changes.

## Swarm Mode

Swarm mode introduces parallelism and role separation:

```
User → Orchestrator → Decompose → Plan → Schedule
                                            │
                                    ┌───────┼───────┐
                                    ▼       ▼       ▼
                                Worker   Worker   Worker   (Wave 1)
                                    │       │       │
                                    └───────┼───────┘
                                            ▼
                                    Judge (quality gate)
                                            ▼
                                    Manager (wave review)
                                            ▼
                                    ┌───────┼───────┐
                                    ▼       ▼       ▼
                                Worker   Worker   Worker   (Wave 2)
                                    │       │       │
                                    └───────┼───────┘
                                            ▼
                                    Verification
                                            ▼
                                    Synthesis → Result
```

Instead of one model doing everything:
- An **orchestrator** decomposes the task into subtasks with dependencies
- Multiple **workers** execute subtasks in parallel waves
- A **judge** validates each output through quality gates
- A **manager** reviews each wave and can spawn fix-up tasks
- An **integration verifier** checks the combined result
- A **synthesizer** merges all outputs into a final response

## Side-by-Side Comparison

| Aspect | Normal Mode | Swarm Mode |
|--------|------------|------------|
| **Models** | 1 (usually expensive) | N (mix of cheap specialists) |
| **Execution** | Sequential tool calls | Parallel waves of workers |
| **Planning** | Implicit (agent decides as it goes) | Explicit (LLM decomposes into subtask DAG) |
| **Cost** | Higher per-task (one expensive model) | Lower via cheap/free workers |
| **Speed** | Linear in task complexity | Sub-linear (parallelization) |
| **Quality checks** | Self-review only | Separate judge + manager roles |
| **Resume** | Session restore | Wave-level checkpoints |
| **Best for** | Focused tasks, conversations | Large multi-file features, refactors |

## The 8-Phase Pipeline

Every swarm execution follows this pipeline:

### Phase 1: Decompose

The orchestrator model analyzes your task and breaks it into subtasks. Each subtask has:
- A clear description
- A type (implement, test, research, refactor, review, document, etc.)
- Dependencies on other subtasks
- A complexity rating (1-10)
- Target files it will modify or read

```
"Build a parser with tests" →
  st-0: Research existing parser patterns (research, complexity: 3)
  st-1: Implement lexer module (implement, complexity: 6, depends: st-0)
  st-2: Implement parser module (implement, complexity: 7, depends: st-0)
  st-3: Write lexer tests (test, complexity: 4, depends: st-1)
  st-4: Write parser tests (test, complexity: 5, depends: st-2)
```

### Phase 2: Plan

The orchestrator (or manager, if configured) creates:
- **Acceptance criteria** for each subtask — what "done" looks like
- **Integration test plan** — bash commands to verify the combined result works

This phase is optional (`enablePlanning: true` by default) and gracefully degrades if it fails.

### Phase 3: Schedule

Subtasks are organized into waves based on their dependencies:

```
Wave 0: [st-0]           ← no dependencies, runs first
Wave 1: [st-1, st-2]     ← both depend on st-0, run in parallel
Wave 2: [st-3, st-4]     ← depend on st-1 and st-2 respectively
```

Tasks within a wave run in parallel. Waves execute sequentially (wave N+1 waits for wave N).

### Phase 4: Execute

For each wave, the orchestrator:
1. Selects a worker model for each task based on capability matching
2. Dispatches workers with staggered timing to avoid rate limit bursts
3. Each worker runs as a full agent — it can read files, write code, run tests
4. Workers execute in parallel up to `maxConcurrency` (default: 3)

Workers receive:
- The task description and acceptance criteria
- The project's `philosophy` (coding standards)
- Their `persona` (role-specific instructions)
- Context from completed dependencies
- A file listing of the workspace (if `includeFileList` is enabled)

### Phase 5: Review (Quality Gate)

After each task completes, the judge model evaluates the output:
- Scores from 1-5 on correctness, completeness, and quality
- Failed outputs are retried with the quality feedback
- Quality gates are automatically skipped when under rate limit pressure

### Phase 6: Wave Review

After each wave completes, the manager model reviews all outputs:
- Checks if outputs meet acceptance criteria
- Assesses the wave as "good", "needs-fixes", or "critical-issues"
- Can spawn **fix-up tasks** that run immediately before the next wave

### Phase 7: Verify

After all waves complete, integration verification runs:
- Executes the bash commands from the integration test plan
- Failed verification triggers fix-up tasks (up to `maxVerificationRetries` attempts)
- This catches issues that individual task reviews might miss

### Phase 8: Synthesize

All completed task outputs are merged into a final result using the result synthesizer. The orchestrator produces a summary of what was accomplished, including statistics on tasks completed, tokens used, and cost.

## Wave-Based Execution

### What Waves Are

Waves are dependency layers. Tasks in the same wave have no dependencies on each other and can run in parallel. A wave only starts after all tasks in the previous wave have completed (or failed/skipped).

### Task Lifecycle

Each task moves through these states:

```
pending → ready → dispatched → completed
                            └→ failed → (retry) → dispatched
                            └→ skipped (dependency failed)
```

- **pending**: Waiting for dependencies to complete
- **ready**: Dependencies satisfied, eligible for dispatch
- **dispatched**: Assigned to a worker, executing
- **completed**: Worker finished successfully, passed quality gate
- **failed**: Worker failed or quality gate rejected — may retry
- **skipped**: A dependency failed permanently, so this task can't run

### Concrete Example

Task: "Build a recursive descent parser with lexer, parser, and tests"

```
Wave 0 (1 task):
  ├─ st-0: Research parser patterns          → researcher model

Wave 1 (2 tasks, parallel):
  ├─ st-1: Implement lexer (tokenizer.ts)    → coder model
  └─ st-2: Implement parser (parser.ts)      → coder-alt model

Wave 2 (2 tasks, parallel):
  ├─ st-3: Write lexer tests                 → coder model
  └─ st-4: Write parser tests                → coder-alt2 model
```

Wave 0 runs first (research). Once it completes, wave 1 dispatches both implementation tasks to different models in parallel. When both finish, wave 2 dispatches both test tasks.

Total: 5 tasks, 3 waves, but only ~3x the wall-clock time of the slowest individual task (rather than 5x sequential).

## The Hierarchy

Swarm mode uses four distinct roles with separated authority:

### Orchestrator
- Plans the overall execution
- Decomposes the task into subtasks
- Handles the synthesis of final results
- Uses the model specified by `--model` or `models.orchestrator`

### Workers (Executors)
- Perform the actual subtasks (write code, run tests, do research)
- Each worker is a full agent with access to tools
- Assigned models based on capability matching
- Can be customized with `persona` for role-specific behavior

### Judge
- Runs quality gates on individual worker outputs
- Scores each output on a 1-5 scale
- Failed quality gates trigger worker retries
- Configured via `hierarchy.judge` in swarm.yaml

### Manager
- Reviews all outputs after each wave completes
- Makes accept/reject decisions against acceptance criteria
- Can spawn fix-up tasks for issues found
- Configured via `hierarchy.manager` in swarm.yaml

### How They Interact

```
Orchestrator (decomposes & plans)
  └─► Workers (parallel subtask execution)
        └─► Judge (quality gate per output, score 1-5)
              └─► Manager (wave-level review, fix-up tasks)
                    └─► Orchestrator (next wave or synthesis)
```

The hierarchy is optional. Without a configured manager or judge, the orchestrator handles review and quality gating directly.

## Budget Management

The total token budget is split:
- **Orchestrator reserve** (15% by default): For decomposition, planning, quality gates, synthesis
- **Worker pool** (85%): Shared among all workers with per-worker caps

Budget is tracked across waves. If early waves consume less than expected, later waves can use the surplus. Workers are terminated if they exceed their individual token limits (`maxTokensPerWorker`).

## Next Steps

- [Getting Started](getting-started.md) — Run your first swarm task
- [Configuration Guide](configuration-guide.md) — Customize every aspect of swarm execution
- [Architecture Deep Dive](advanced/architecture-deep-dive.md) — Understand the internals
