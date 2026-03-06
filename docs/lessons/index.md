---
title: "Attocode Lessons"
---

# Attocode

A comprehensive course that teaches you to build production-ready AI coding agents from scratch, using TypeScript and modern patterns that go beyond typical tutorials.

> **26 lessons** covering foundations through production deployment, with hands-on exercises and a complete working agent at the end of each major section.

!!! note "TypeScript Lessons, Python Agent"
    These lessons use TypeScript throughout and teach the patterns that were used to build the Python version of the agent. The concepts and architecture transfer directly.

## Prerequisites

- **Node.js 18+**
- Basic **TypeScript** knowledge
- Understanding of async/await and Promises
- (Optional) API key from Anthropic, OpenAI, or Azure

## Quick Start

```bash
# Clone and install
git clone https://github.com/eren23/attocode.git
cd attocode
npm install

# Set up your API key
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY or OPENAI_API_KEY

# Run your first lesson
npm run lesson:1
```

For the runnable TypeScript source code, see the [`lessons/`](https://github.com/eren23/attocode/tree/main/lessons/) directory.

## Inspiration

This course was heavily inspired by the article **["You Could've Invented Claude Code"](https://erikschluntz.com/software/2025/05/09/you-couldve-invented-claude-code.html)** by Erik Schluntz.

That article demonstrates a powerful insight: the core of Claude Code is just a loop that lets an AI read files, run commands, and iterate until a task is done. Starting from a 50-line bash script, it builds up to a ~150-line Python agent that captures the essence of how AI coding agents work.

**Attocode takes this first-principles approach and expands it into a full curriculum:**

| "You Could've Invented Claude Code" | Attocode |
|-------------------------------------|----------|
| Single tutorial | 26 progressive lessons |
| Python + bash | TypeScript throughout |
| ~150 lines of code | Production-ready patterns |
| Core concepts only | Memory, planning, reflection, multi-agent |
| Read and run | Hands-on exercises with tests |
| One provider | Multi-provider abstraction |
| Basic safety | Sandboxing, human-in-loop, observability |

## All Lessons

### Part 1: Foundations (Lessons 1-9)

| Lesson | Title | Key Concepts |
|--------|-------|-------------|
| [01](01-core-loop.md) | The Core Loop | Agent loop, tool parsing, conversation history |
| [02](02-provider-abstraction.md) | Provider Abstraction | Adapter pattern, environment detection, provider registry |
| [03](03-tool-system.md) | Tool System | Zod validation, permission modes, danger classification |
| [04](04-streaming.md) | Streaming Responses | Async generators, SSE parsing, terminal UI |
| [05](05-error-recovery.md) | Error Recovery | Error classification, retry strategies, circuit breaker pattern |
| [06](06-testing-agents.md) | Testing Agents | Mock providers, fixtures, behavioral assertions |
| [07](07-mcp-integration.md) | MCP Integration | MCP protocol, stdio transport, tool aggregation |
| [08](08-cache-hitting.md) | Cache Hitting | Prompt caching, cache invalidation, cost optimization |
| [09](09-complete-agent.md) | Complete Agent | Integration, REPL interface, production patterns |

### Part 2: Production Infrastructure (Lessons 10-13)

| Lesson | Title | Key Concepts |
|--------|-------|-------------|
| [10](10-hook-system.md) | Hook & Event System | Event bus, hook priorities, sync/async hooks |
| [11](11-plugin-system.md) | Plugin Architecture | Plugin lifecycle, sandboxed context, hot-reloading |
| [12](12-rules-system.md) | Rules & Instructions System | Hierarchical config, rule merging, glob patterns |
| [13](13-client-server.md) | Client/Server Separation | Session management, protocol design, event streaming |

### Part 3: AI Reasoning (Lessons 14-18)

| Lesson | Title | Key Concepts |
|--------|-------|-------------|
| [14](14-memory-systems.md) | Memory Systems | Memory types, importance scoring, retrieval strategies |
| [15](15-planning.md) | Planning & Decomposition | Task decomposition, dependency graphs, re-planning |
| [16](16-reflection.md) | Self-Reflection & Critique | Critique prompts, confidence scoring, iteration limits |
| [17](17-multi-agent.md) | Multi-Agent Coordination | Role specialization, orchestration, consensus |
| [18](18-react-pattern.md) | ReAct Pattern | Thought parsing, observation formatting, trace logging |

### Part 4: Operations (Lessons 19-22)

| Lesson | Title | Key Concepts |
|--------|-------|-------------|
| [19](19-observability.md) | Observability & Tracing | Spans, metrics, cost attribution |
| [20](20-sandboxing.md) | Sandboxing & Isolation | Process isolation, resource limits, security policies |
| [21](21-human-in-loop.md) | Human-in-the-Loop Patterns | Risk assessment, approval workflows, audit logging |
| [22](22-model-routing.md) | Model Routing & Fallbacks | Capability matching, cost optimization, circuit breakers |

### Part 5: Advanced Patterns (Lessons 23-26)

| Lesson | Title | Key Concepts |
|--------|-------|-------------|
| [23](23-execution-policies.md) | Execution Policies & Intent Classification | Policy composition, execution control, conditional logic |
| [24](24-advanced-patterns.md) | Advanced Patterns | Thread management, checkpoints, hierarchical configuration |
| [25](25-production-agent.md) | Production Agent (Capstone) | Production deployment, system integration, configuration management |
| [26](26-tracing-and-evaluation.md) | Tracing & Evaluation | Trace collection, performance metrics, evaluation frameworks |

## Learning Path

**Beginners** (new to AI agents):

1. Lessons 1-9 (Foundations)
2. Lesson 18 (ReAct Pattern)
3. Lessons 10-11 (Extensibility)

**Intermediate** (building production systems):

1. Lessons 10-13 (Infrastructure)
2. Lessons 19-22 (Operations)
3. Lessons 23-26 (Advanced Patterns)

**Advanced** (AI reasoning systems):

1. Lessons 14-17 (Memory, Planning, Reflection, Multi-Agent)
2. Integrate with production infrastructure
