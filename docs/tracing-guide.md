# Tracing & Observability

Attocode records detailed execution traces in JSONL format, capturing every LLM call, tool execution, budget check, and more. Traces enable post-hoc analysis, debugging, and performance optimization.

## Enabling Tracing

```bash
# Enable tracing for a session
attocode --trace "Build a REST API"

# Or toggle during a session
/trace
```

Traces are saved to `.attocode/traces/` (or `.traces/`) as JSONL files, one event per line.

## Trace Events

The tracing system defines **42 event kinds** across **16 categories**:

| Category | Events | Description |
|----------|--------|-------------|
| **SESSION** | `session_start`, `session_end` | Session lifecycle boundaries |
| **ITERATION** | `iteration_start`, `iteration_end` | ReAct loop iteration boundaries |
| **LLM** | `llm_request`, `llm_response`, `llm_error`, `llm_retry` | LLM API interactions |
| **TOOL** | `tool_start`, `tool_end`, `tool_error`, `tool_approval` | Tool execution lifecycle |
| **BUDGET** | `budget_check`, `budget_warning`, `budget_exhausted` | Budget monitoring |
| **COMPACTION** | `compaction_start`, `compaction_end`, `context_overflow` | Context management |
| **SUBAGENT** | `subagent_spawn`, `subagent_complete`, `subagent_error`, `subagent_timeout` | Subagent lifecycle |
| **SWARM** | `swarm_start`, `swarm_complete`, `swarm_wave_start`, `swarm_wave_complete`, `swarm_task_start`, `swarm_task_complete`, `swarm_task_failed` | Swarm orchestration |
| **PLAN** | `plan_created`, `plan_step_start`, `plan_step_complete` | Plan execution |
| **QUALITY** | `quality_check`, `learning_proposed` | Quality assurance |
| **ERROR** | `error`, `recovery` | Error handling |
| **MODE** | `mode_change` | Agent mode transitions |
| **MCP** | `mcp_connect`, `mcp_disconnect` | MCP server lifecycle |
| **FILE** | `file_change` | File modifications |
| **CHECKPOINT** | `checkpoint` | Session checkpoints |
| **CUSTOM** | `custom` | User-defined events |

## JSONL Format

Each line in a trace file is a JSON object with these fields:

```json
{
  "event_id": "a1b2c3d4",
  "kind": "llm_response",
  "timestamp": 1709123456.789,
  "session_id": "session-xyz",
  "iteration": 5,
  "data": {
    "model": "claude-sonnet-4-20250514",
    "input_tokens": 15000,
    "output_tokens": 500,
    "cache_read_tokens": 12000,
    "cost": 0.003,
    "duration_ms": 1200
  },
  "parent_event_id": "e5f6g7h8",
  "duration_ms": 1200.5
}
```

### Key Fields

| Field | Type | Description |
|-------|------|-------------|
| `event_id` | string | Unique event identifier |
| `kind` | string | One of the 42 event kinds |
| `timestamp` | float | Unix epoch seconds |
| `session_id` | string | Parent session |
| `iteration` | int \| null | Current ReAct iteration |
| `data` | dict | Kind-specific payload |
| `parent_event_id` | string \| null | Hierarchical parent link |
| `duration_ms` | float \| null | Operation duration |

## Trace Collector

The `TraceCollector` is the core recording engine:

- **Buffered writes** — Events are buffered (default: 100 events) and flushed to disk periodically
- **Crash-safe** — An atexit handler ensures no data loss on interpreter shutdown
- **O(1) summaries** — Running counters track tokens, cost, iterations, tool calls without re-scanning
- **Safe serialization** — Long strings are truncated, exotic types fall back to `str()`, tracing errors never crash the agent

### Specialized Recording Methods

The collector provides typed helpers for common events:

```python
collector.record_llm_request(iteration, messages_count, model)
collector.record_llm_response(tokens, cost, duration_ms)
collector.record_tool_call(tool, args, result, duration)
collector.record_budget_check(status, usage_fraction)
collector.record_compaction(messages_before, messages_after, tokens_saved)
collector.record_subagent(agent_id, event_type, data)
collector.record_error(error, context, iteration)
```

## Analysis Tools

The `tracing/analysis/` module provides tools for post-hoc trace analysis.

### Session Analyzer

Computes aggregate metrics and efficiency scores:

```python
from attocode.tracing.analysis import SessionAnalyzer

analyzer = SessionAnalyzer(trace_session)

# Aggregate metrics with 0-100 efficiency score
summary = analyzer.summary()
print(f"Efficiency: {summary.efficiency_score}/100")
print(f"Cache hit rate: {summary.cache_hit_rate:.1%}")

# Chronological event timeline
timeline = analyzer.timeline()

# Hierarchical iteration → event tree
tree = analyzer.tree()

# Per-iteration token flow
flow = analyzer.token_flow()
```

**Efficiency Score** (0–100) is a weighted composite:

| Component | Weight | Measures |
|-----------|--------|----------|
| Cache hit rate | 30% | `cache_read / (input + cache_read)` |
| Error rate | 25% | `1 - errors / tool_calls` |
| Compaction frequency | 15% | Lower is better |
| Tool success rate | 20% | Successful / total tool calls |
| Token efficiency | 10% | Output / input ratio |

### Token Analyzer

Detailed token usage and cost tracking:

```python
from attocode.tracing.analysis import TokenAnalyzer

tokens = TokenAnalyzer(trace_session)

# Per-iteration token snapshots
flow = tokens.token_flow()

# Total session cost
cost = tokens.total_cost()

# Cache efficiency (0.0–1.0)
cache_eff = tokens.cache_efficiency()

# Breakdown by category
breakdown = tokens.token_breakdown()
# → {"input": 150000, "output": 5000, "cache_read": 120000, "cache_write": 30000}
```

### Inefficiency Detector

Scans traces for **11 categories** of performance issues:

| Category | Trigger | Severity |
|----------|---------|----------|
| Excessive iterations | >15 iterations without tool calls | High |
| Repeated tool calls | Identical tool+args 3+ times | High |
| Cache drops | >50% drop in hit rate | Medium |
| Token spikes | >2x average tokens | Medium |
| Compaction frequency | >3 in 20 iterations | Medium |
| Empty responses | 0 output tokens | High |
| Tool error rate | >30% failure rate | High |
| Long tool execution | >30 seconds | Low |
| Context overflow | Emergency truncation triggered | Critical |
| Budget warnings ignored | Budget signals without action | Medium |
| Subagent timeouts | Delegated task failures | Medium |

```python
from attocode.tracing.analysis import InefficiencyDetector

detector = InefficiencyDetector(trace_session)
issues = detector.detect()

for issue in issues:
    print(f"[{issue.severity}] {issue.title}")
    print(f"  {issue.description}")
    print(f"  Suggestion: {issue.suggestion}")
```

## Cache Boundary Tracking

The `CacheBoundaryTracker` monitors KV-cache hit/miss patterns:

```python
from attocode.tracing import CacheBoundaryTracker

tracker = CacheBoundaryTracker()
tracker.record_request(input_tokens=15000, cache_read_tokens=12000)

print(f"Hit rate: {tracker.get_cache_hit_rate():.1%}")
print(f"Boundary: ~{tracker.get_boundary_position()} tokens")
```

Maintains a sliding window of 50 recent requests for moving-average calculations.

## Debugging with Traces

### Finding Stuck Agents

Look for repeated tool calls in the trace:

```bash
# Find repeated tool calls
grep "tool_start" .attocode/traces/session-*.jsonl | \
  python -c "import sys,json; [print(json.loads(l)['data']['tool_name']) for l in sys.stdin]" | \
  sort | uniq -c | sort -rn | head
```

### Analyzing Token Usage

```bash
# Sum tokens per iteration
grep "llm_response" .attocode/traces/session-*.jsonl | \
  python -c "
import sys, json
for line in sys.stdin:
    e = json.loads(line)
    d = e.get('data', {})
    print(f\"iter {e.get('iteration', '?')}: in={d.get('input_tokens',0)} out={d.get('output_tokens',0)} cache={d.get('cache_read_tokens',0)}\")
"
```

### Using Debug Mode

For real-time debugging without trace files:

```bash
attocode --debug "Fix the bug"
```

Debug mode enables verbose logging to stderr.

## Dashboard

The TUI includes a built-in trace dashboard accessible via `Ctrl+D`. See the [TUI Guide](tui-guide.md#dashboard-screen-ctrld) for details.

## Related Pages

- [TUI Interface](tui-guide.md) — Dashboard and monitoring panels
- [Budget System](BUDGET.md) — Budget events and doom loop detection
- [Context Engineering](context-engineering.md) — Compaction events
