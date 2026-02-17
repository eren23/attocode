---
sidebar_position: 1
title: Tracing
---

# Tracing

Attocode produces structured JSONL trace files that capture every LLM request, tool execution, phase transition, and swarm event. Traces are the foundation for the [dashboard](./trace-dashboard), [session comparison](./session-comparison), and [automated issue detection](./issue-detection).

## Enabling Tracing

```bash
# Via CLI flag
attocode --trace "Fix the login bug"

# Via slash command during a session
/trace on
```

Traces are written to `.traces/{sessionId}-{timestamp}.jsonl` (or `.agent/traces/` if configured).

## Trace Collector

The `TraceCollector` class in `src/tracing/trace-collector.ts` is the central hub. It subscribes to agent events and produces buffered JSONL output.

```typescript
const collector = new TraceCollector({
  outputDir: '.traces',
  captureMessageContent: true,
  captureToolResults: true,
  maxMessageLength: 10000,
  bufferSize: 50,
});

collector.startSession('session-id', 'Fix the login bug', 'claude-sonnet-4');

// During execution
collector.recordLLMRequest(requestData);
collector.recordLLMResponse(responseData);
collector.recordToolExecution(toolData);

// When done
const trace = await collector.endSession({ success: true });
```

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `false` | Whether tracing is active |
| `outputDir` | `.traces` | Directory for JSONL output |
| `captureMessageContent` | `true` | Include full message text |
| `captureToolResults` | `true` | Include tool execution output |
| `maxMessageLength` | `10000` | Truncation limit per message |
| `bufferSize` | `50` | Entries buffered before flush |

Enhanced tracing options control capture of thinking blocks, memory retrieval, plan evolution, and decision points.

## JSONL Entry Types

Each line in the trace file is a JSON object with a `_type` discriminator and a `_ts` timestamp. There are 30+ entry types organized into categories:

### Session and Task Lifecycle

| Type | Description |
|------|-------------|
| `session.start` | Session begins -- model, metadata, configuration |
| `session.end` | Session ends -- status, duration, final metrics |
| `task.start` | Individual task within a terminal session |
| `task.end` | Task completion -- status, metrics, result summary |

### LLM Interactions

| Type | Description |
|------|-------------|
| `llm.request` | Request sent to provider -- model, message count, estimated tokens |
| `llm.response` | Response received -- actual tokens, cache stats, cost, stop reason |

### Tool Execution

| Type | Description |
|------|-------------|
| `tool.execution` | Tool call with timing, status, arguments, and result |

### Enhanced Tracing

| Type | Description |
|------|-------------|
| `thinking` | Extended thinking blocks with estimated token counts |
| `memory.retrieval` | Memory/context retrieval events |
| `plan.evolution` | Plan created, updated, or completed |
| `subagent.link` | Parent-child agent relationship with budget and result |
| `decision` | Decision points with type, outcome, and reasoning |
| `context.compaction` | Context window compaction events |
| `iteration.wrapper` | Iteration start/end markers |

### Swarm Events

| Type | Description |
|------|-------------|
| `swarm.start` | Swarm orchestration begins -- task count, config |
| `swarm.decomposition` | Task decomposition -- tasks, waves, dependencies |
| `swarm.wave` | Execution wave started or completed |
| `swarm.task` | Individual task dispatched, completed, failed, or skipped |
| `swarm.quality` | Quality gate evaluation -- score, feedback |
| `swarm.budget` | Budget pool state -- tokens/cost used vs total |
| `swarm.verification` | Integration verification step or completion |
| `swarm.complete` | Swarm orchestration finished |
| `swarm.orchestrator.llm` | Orchestrator's own LLM calls |
| `swarm.wave.allFailed` | All tasks in a wave failed |
| `swarm.phase.progress` | Phase progress update |

### Observability Visualization

| Type | Description |
|------|-------------|
| `codebase.map` | File and symbol mapping of agent interactions |
| `blackboard.event` | Shared blackboard read/write/subscribe events |
| `budget.pool` | Budget pool allocation/consume/release events |
| `filecache.event` | File cache hit/miss/eviction events |
| `context.injection` | Context injection slot accepted/dropped |

## Cache Boundary Tracker

The `CacheBoundaryTracker` in `src/tracing/cache-boundary-tracker.ts` analyzes KV-cache invalidation points within each LLM request. It identifies where cache breaks occur (role changes, content changes, dynamic content) and reports:

- **hitRate** -- fraction of input tokens served from cache
- **estimatedSavings** -- cost reduction from caching
- **breakpoints** -- positions and types of cache invalidations

This data feeds into the dashboard's token flow charts and the [issue detector's](./issue-detection) cache inefficiency rules.

## Source Files

| File | Purpose |
|------|---------|
| `src/tracing/trace-collector.ts` | `TraceCollector`, event recording, buffered JSONL output |
| `src/tracing/types.ts` | All trace type definitions (50+ interfaces) |
| `src/tracing/cache-boundary-tracker.ts` | KV-cache analysis and breakpoint tracking |
