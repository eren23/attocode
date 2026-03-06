---
title: "Lesson 26: Tracing & Evaluation"
---

!!! info "Source Code"
    The runnable TypeScript source for this lesson is in
    [`lessons/26-tracing-and-evaluation/`](https://github.com/eren23/attocode/tree/main/lessons/26-tracing-and-evaluation/)

!!! warning "Work in Progress"
    This lesson is still under development and has not been fully tested.

# Lesson 26: Tracing & Evaluation

> Comprehensive trace collection, performance analysis, and evaluation frameworks for AI agents

## What You'll Learn

1. **Trace Collection**: Capturing detailed execution traces from agent runs
2. **Trace Export**: Exporting traces in multiple formats for analysis
3. **Trace Visualization**: Rendering traces for human inspection
4. **Evaluation Frameworks**: Measuring and benchmarking agent performance
5. **Agent Integration**: Wiring tracing into the production agent pipeline
6. **Cache Boundary Tracking**: Monitoring cache effectiveness across operations

## Why This Matters

Building an agent is only half the battle. To improve it, you need to:

- **Measure performance**: How long do operations take? What are the bottlenecks?
- **Track costs**: How many tokens are consumed per task? Where can you optimize?
- **Evaluate quality**: Are the agent's outputs correct? How do they compare across runs?
- **Debug failures**: When something goes wrong, can you trace exactly what happened?
- **Benchmark changes**: Does a new prompt or tool configuration improve results?

## Key Concepts

### Trace Collection

Traces capture the full execution history of an agent run, including:
- LLM calls with input/output tokens and latency
- Tool invocations with arguments and results
- Decision points and branching logic
- Error events and recovery actions

### Trace Export

Traces can be exported in multiple formats:
- **JSON**: For programmatic analysis
- **JSONL**: For streaming and log aggregation
- **Console**: For human-readable debugging
- **OTLP**: For integration with observability platforms

### Evaluation

Evaluation frameworks allow you to:
- Define test cases with expected outcomes
- Run agents against benchmarks
- Score outputs on multiple dimensions (correctness, completeness, efficiency)
- Compare performance across configurations

## Files in This Lesson

| File | Purpose |
|------|---------|
| `types.ts` | Type definitions for traces and evaluations |
| `trace-collector.ts` | Core trace collection infrastructure |
| `trace-exporter.ts` | Multi-format trace export |
| `trace-visualizer.ts` | Human-readable trace rendering |
| `cache-boundary-tracker.ts` | Cache effectiveness monitoring |
| `agent-integration.ts` | Wiring traces into the agent pipeline |
| `evaluation/` | Evaluation framework and benchmarks |
| `main.ts` | Demonstration of all concepts |

## Running This Lesson

```bash
npm run lesson:26
```

## Architecture

```
+---------------------------------------------------------------+
|                    Trace Collection Layer                        |
|                                                                 |
|  +------------------+  +------------------+  +---------------+  |
|  | Trace Collector  |  | Cache Boundary   |  |    Agent      |  |
|  |  (spans, events) |  |    Tracker       |  | Integration   |  |
|  +------------------+  +------------------+  +---------------+  |
|           |                     |                    |          |
|           v                     v                    v          |
|  +----------------------------------------------------------+  |
|  |                    Trace Store                              |  |
|  +----------------------------------------------------------+  |
|           |                                                     |
|           v                                                     |
|  +------------------+  +------------------+  +---------------+  |
|  | Trace Exporter   |  | Trace Visualizer |  |  Evaluation   |  |
|  | (JSON/JSONL/OTLP)|  | (Console render) |  |  Framework    |  |
|  +------------------+  +------------------+  +---------------+  |
+---------------------------------------------------------------+
```

## Integration with Production Agent

This lesson builds on the observability foundation from Lesson 19 and extends it with:

- **End-to-end tracing**: Full trace from user input to final output
- **Evaluation pipelines**: Automated quality assessment
- **Regression detection**: Catch performance regressions before deployment
- **Cost attribution**: Per-feature cost breakdowns

## Best Practices

1. **Trace everything in development**: Full tracing helps catch issues early
2. **Sample in production**: Use sampling to reduce overhead while maintaining visibility
3. **Define clear metrics**: Know what "good" looks like before measuring
4. **Automate evaluation**: Run benchmarks as part of CI/CD
5. **Version your traces**: Link traces to code versions for meaningful comparisons
6. **Monitor cache boundaries**: Track cache hit rates to optimize token usage

## Next Steps

With all 26 lessons complete, you have a comprehensive understanding of AI agent architecture. Consider:

1. **Building your own agent** using these patterns
2. **Contributing improvements** back to the course
3. **Exploring the atomic tricks** for additional utilities
4. **Deploying the production agent** for real coding tasks
