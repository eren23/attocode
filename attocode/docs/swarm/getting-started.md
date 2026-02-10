# Getting Started with Swarm Mode

This tutorial walks you through your first swarm run, explains the output, and helps you decide when swarm mode is the right choice.

## Prerequisites

- **OpenRouter API key**: Set `OPENROUTER_API_KEY` in your environment. Swarm mode auto-detects cheap worker models from OpenRouter's model catalog.
- **Node.js 20+**: Required for attocode itself.
- Alternatively, use `--model` with an Anthropic key to set the orchestrator model (workers still need OpenRouter for auto-detection).

## Your First Swarm Run

Run a simple task:

```bash
attocode --swarm "Create a simple HTTP server with a GET /health endpoint and tests"
```

### What Happens

1. **Decomposition**: The orchestrator analyzes the task and breaks it into subtasks:
   ```
   Swarm started: 4 tasks in 2 waves (max 3 concurrent)
   ```

2. **Planning**: Acceptance criteria are created for each subtask:
   ```
   Plan created: 4 acceptance criteria, integration test plan ready
   ```

3. **Wave execution**: Workers run in parallel:
   ```
   Wave 1/2: dispatching 2 tasks
     Task st-0 → coder (mistralai/mistral-large-2512): Implement HTTP server with /health endpoint
     Task st-1 → researcher (moonshotai/kimi-k2.5-0127): Research testing patterns for HTTP servers
   Wave 1/2 complete: 2 done, 0 failed, 0 skipped
   ```

4. **Wave review**: The manager checks outputs:
   ```
   Wave 1 review: good
   ```

5. **Next wave**: Dependent tasks run:
   ```
   Wave 2/2: dispatching 2 tasks
     Task st-2 → coder-alt (z-ai/glm-4.7-flash): Write unit tests for /health endpoint
     Task st-3 → coder (mistralai/mistral-large-2512): Add integration tests
   ```

6. **Verification**: Integration tests run:
   ```
   Running 2 verification steps...
   Verify step 1: Check server file exists — PASS
   Verify step 2: Run tests — PASS
   Verification PASSED: 2/2 steps passed
   ```

7. **Summary**:
   ```
   Swarm execution complete:
     Tasks: 4/4 completed, 0 failed, 0 skipped
     Waves: 2
     Tokens: 45k
     Cost: $0.0012
     Duration: 28.3s
   ```

## Understanding the TUI Panel

When running with the TUI (default), you'll see a swarm status panel showing:

- **Phase**: Current pipeline phase (decomposing, planning, executing, reviewing, verifying, synthesizing)
- **Wave progress**: `Wave 2/3 — 5/8 tasks completed`
- **Active workers**: Which models are running which tasks right now
- **Budget**: Tokens and cost consumed vs. total budget

## Watching the Dashboard

For a richer visualization, enable tracing and open the web dashboard:

```bash
# Terminal 1: Run the swarm with tracing
attocode --swarm --trace "Build a parser"

# Terminal 2: Start the dashboard
cd tools/trace-dashboard && npm run dashboard
```

The dashboard shows a task DAG, worker timeline, budget gauges, quality heatmap, model distribution, and a live event feed. See [Dashboard Guide](advanced/dashboard.md) for details.

## Customizing with a Config File

### Scaffold a config

```bash
attocode init
```

This creates `.attocode/swarm.yaml` with all options commented out. Edit it to customize.

### Common first customizations

**Use paid models for higher rate limits:**
```yaml
models:
  paid_only: true
```

**Increase parallelism:**
```yaml
budget:
  max_concurrency: 5
  dispatch_stagger_ms: 200
```

**Add coding standards:**
```yaml
philosophy: |
  Write clean TypeScript with strict types.
  Always write tests. Follow existing patterns.
```

**Set a cost cap:**
```yaml
budget:
  max_cost: 0.50
  total_tokens: 1000000
```

See the [Configuration Guide](configuration-guide.md) for all options.

## When to Use Swarm Mode

### Use swarm mode when:

- **Multi-file tasks**: Implementing a feature that touches 3+ files
- **Parallelizable work**: Tasks that decompose into independent subtasks (e.g., "add tests for all modules")
- **Cost-sensitive**: You want to use cheap/free models for most of the work
- **Large refactors**: Renaming patterns, updating APIs across many files
- **Speed matters**: Parallel execution is faster than sequential for large tasks

### Use normal mode when:

- **Focused tasks**: Single-file changes, bug fixes, conversations
- **Interactive work**: You want to iterate with the agent step by step
- **Simple tasks**: Quick questions, small edits
- **Precision matters**: One smart model is better than many cheap ones for tricky logic

### Decision Flowchart

```
Is the task decomposable into 2+ independent parts?
├─ No  → Normal mode
└─ Yes
    ├─ Is each part simple enough for a cheap model?
    │   ├─ No  → Normal mode (or swarm with paid models)
    │   └─ Yes → Swarm mode
    └─ Do you need interactive iteration?
        ├─ Yes → Normal mode
        └─ No  → Swarm mode
```

### Cost Comparison

For a "build a parser with tests" task:

| Mode | Models | Time | Cost (approx.) |
|------|--------|------|-----------------|
| Normal (Claude Sonnet) | 1 | ~3 min | $0.15 |
| Swarm (free workers) | 5-6 | ~1 min | $0.002 |
| Swarm (paid workers) | 5-6 | ~30s | $0.02 |

Swarm mode trades model intelligence for parallelism and cost savings. The quality gates and manager review help catch issues that cheaper models might miss.

## Common Flags

```bash
# Paid models only (higher rate limits, better quality)
attocode --swarm --paid-only "task"

# Custom config file
attocode --swarm .attocode/swarm.yaml "task"

# Safe permissions (auto-approve reads, ask for writes)
attocode --swarm --permission auto-safe "task"

# Resume from a previous run
attocode --swarm-resume <session-id>

# Enable tracing for dashboard
attocode --swarm --trace "task"
```

## Troubleshooting

### Workers failing immediately
- Verify `OPENROUTER_API_KEY` is set and valid
- Try `--paid-only` to skip free models with restrictive limits
- Increase `dispatch_stagger_ms` in your config

### Rate limit errors
- Add `--paid-only` for higher rate limits
- Reduce `max_concurrency` and increase `dispatch_stagger_ms`
- The circuit breaker will automatically pause dispatch after 3 rate limits in 30 seconds

### Quality gates too strict
- Try setting `models.qualityGate` to a model that's good at evaluation
- Customize the judge persona for your project's standards

See the [troubleshooting section](../swarm-mode.md#troubleshooting) for more.

## Next Steps

- [Configuration Guide](configuration-guide.md) — Fine-tune every aspect of swarm execution
- [How It Works](how-it-works.md) — Understand the full pipeline in depth
- [Example Configs](examples/) — Start from a pre-built configuration
