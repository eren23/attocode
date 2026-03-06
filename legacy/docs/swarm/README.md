# Swarm Mode Guide

Swarm mode lets one orchestrator model coordinate multiple cheap specialist worker models in parallel. Instead of a single expensive model doing everything sequentially, the orchestrator decomposes your task into a DAG of subtasks, dispatches them across waves of parallel workers, reviews outputs through quality gates, and synthesizes a final result.

## Start Here

New to swarm mode? Read the **[Getting Started](getting-started.md)** tutorial to run your first swarm task in under 5 minutes.

## Guides

| Guide | Description |
|-------|-------------|
| [How It Works](how-it-works.md) | Deep dive into normal mode vs swarm, the 8-phase pipeline, wave execution, and the hierarchy |
| [Getting Started](getting-started.md) | Tutorial: your first swarm run, understanding the output, and when to use swarm mode |
| [Configuration Guide](configuration-guide.md) | Every config option explained with defaults and examples |

## Examples

Pre-built config files in [`examples/`](examples/):

| Config | Use Case |
|--------|----------|
| [`minimal.yaml`](examples/minimal.yaml) | Simplest possible config — auto-detect everything |
| [`free-tier.yaml`](examples/free-tier.yaml) | All free models with conservative throttling |
| [`paid-fast.yaml`](examples/paid-fast.yaml) | Paid models with max parallelism for speed |
| [`quality-focused.yaml`](examples/quality-focused.yaml) | Strict quality gates with manager + judge hierarchy |
| [`resume-friendly.yaml`](examples/resume-friendly.yaml) | Persistence and checkpointing for long-running tasks |

## Advanced Topics

| Guide | Description |
|-------|-------------|
| [Architecture Deep Dive](advanced/architecture-deep-dive.md) | Internals: events, budget pool, circuit breaker, throttling, persistence |
| [Model Selection](advanced/model-selection.md) | How models are auto-detected, filtered, and assigned to workers |
| [Dashboard](advanced/dashboard.md) | Using the live web dashboard to visualize swarm execution |

## Quick Reference

```bash
# Basic swarm run
attocode --swarm "Build a REST API with tests"

# With custom config
attocode --swarm .attocode/swarm.yaml "Refactor auth module"

# Paid models only (higher rate limits)
attocode --swarm --paid-only "Implement login"

# Safe permission mode (recommended)
attocode --swarm --permission auto-safe "Add unit tests"

# Resume a previous session
attocode --swarm-resume <session-id>
```

See also: [Quick reference doc](../swarm-mode.md) for the config schema and troubleshooting.
