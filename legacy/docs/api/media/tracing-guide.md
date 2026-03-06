# Tracing & Performance Analysis Guide

Attocode provides comprehensive tracing capabilities for understanding agent behavior, debugging issues, and optimizing performance. This guide covers all tracing features.

## Overview

The tracing system captures:
- **LLM requests/responses** - Full message history, token counts, cache metrics
- **Tool executions** - Arguments, results, timing, errors
- **Session metrics** - Aggregated costs, cache efficiency, iteration counts
- **Anomaly detection** - Automatic identification of inefficiencies

## Enabling Tracing

### Command Line Flag

```bash
attocode --trace
```

When enabled, traces are written to `.traces/` as JSONL files:
```
.traces/
├── trace-session-1234567890-abc123-1234567890.jsonl
├── trace-session-1234567891-def456-1234567891.jsonl
└── ...
```

### Trace Output Format

Each trace file contains JSONL entries:

```json
{"_type":"session.start","_ts":"2026-01-30T12:00:00Z","sessionId":"...","task":"...","model":"..."}
{"_type":"llm.request","_ts":"...","requestId":"...","messageCount":5,"toolCount":12}
{"_type":"llm.response","_ts":"...","requestId":"...","tokens":{...},"cache":{...}}
{"_type":"tool.execution","_ts":"...","toolName":"read_file","durationMs":45,"status":"success"}
{"_type":"session.end","_ts":"...","status":"completed","metrics":{...}}
```

## In-Session Commands

### `/trace` - Session Summary

Shows current session metrics:

```
Trace Summary:
  Session ID:    session-1769788273260-c4o82v
  Status:        completed
  Iterations:    3
  Duration:      45s

Metrics:
  Input tokens:  8,542
  Output tokens: 1,234
  Cache hit:     72%
  Tool calls:    12
  Errors:        0
  Est. Cost:     $0.0284
```

### `/trace --analyze` - Efficiency Analysis

Runs detailed analysis and identifies issues:

```
=== Trace Analysis ===

Meta:
  Session: session-xxx
  Task: Implement feature X
  Model: claude-sonnet-4
  Duration: 45s

Metrics:
  Iterations: 3
  Total tokens: 9,776
  Cache hit rate: 72%
  Cost: $0.0284

Anomalies Detected:
  [HIGH] redundant_tool_calls: Tool "read_file" called 5 times
         Evidence: May indicate repetitive behavior

Tool Patterns:
  read_file: 5 calls
  bash: 3 calls
  write_file: 2 calls
```

### `/trace issues` - List Issues

Shows all detected inefficiencies:

```
Detected Issues:
  [HIGH] excessive_iterations: Session used 12 iterations
  [MEDIUM] cache_inefficiency: Below-average cache hit rate: 42%
```

### `/trace fixes` - Suggested Fixes

Lists actionable improvements:

```
Suggested Improvements:
  1. Consider batch reading files to reduce iterations
  2. Use more specific prompts to reduce back-and-forth
```

### `/trace export [file]` - Export for Analysis

Exports trace data as JSON for external analysis:

```bash
/trace export                     # Outputs to stdout
/trace export my-trace.json       # Saves to file
```

The exported JSON is optimized for LLM analysis (~4000 tokens).

## Trace Viewer CLI Tool

For offline analysis of trace files, use the standalone trace viewer.

### Setup

```bash
cd tools/trace-viewer
npm install
npm run build
```

### Basic Usage

```bash
# View most recent trace
npx tsx bin/trace-viewer.ts .traces/

# View specific trace file
npx tsx bin/trace-viewer.ts .traces/trace-session-xxx.jsonl

# View all traces in directory
npx tsx bin/trace-viewer.ts .traces/ --verbose
```

### View Modes

#### Summary View (default)

```bash
npx tsx bin/trace-viewer.ts .traces/ --view summary
```

Shows:
- Session metadata
- Aggregated metrics
- Detected anomalies
- Tool usage patterns

#### Timeline View

```bash
npx tsx bin/trace-viewer.ts .traces/ --view timeline
```

Shows chronological sequence:
```
00:00.000  SESSION START
00:00.050  LLM REQUEST  → claude-sonnet-4
00:02.341  LLM RESPONSE ← 245 tokens, cache: 65%
00:02.400  TOOL START   read_file(src/main.ts)
00:02.445  TOOL END     success (45ms)
...
```

#### Tree View

```bash
npx tsx bin/trace-viewer.ts .traces/ --view tree
```

Shows hierarchical structure:
```
Session: session-xxx
├── Iteration 1
│   ├── LLM Request (2,542 tokens in)
│   ├── LLM Response (119 tokens out)
│   └── Tools
│       ├── read_file: success (45ms)
│       └── bash: success (1,234ms)
├── Iteration 2
│   └── ...
```

#### Token Flow View

```bash
npx tsx bin/trace-viewer.ts .traces/ --view tokens
```

Shows token usage over time:
```
Token Flow Analysis:

Iteration  In      Out     Cache   Hit%    Cost
1          2,542   119     0       0%      $0.0094
2          3,891   234     2,100   54%     $0.0078
3          4,567   456     3,200   70%     $0.0065
─────────────────────────────────────────────────
Total      10,999  809     5,300   48%     $0.0237

Cache Efficiency: GOOD
Recommendation: Cache warming effective after iteration 1
```

#### All Views

```bash
npx tsx bin/trace-viewer.ts .traces/ --view all
```

### Output Formats

#### HTML Report

```bash
npx tsx bin/trace-viewer.ts .traces/ --output html --out report.html
```

Generates an interactive HTML report with:
- Collapsible iteration details
- Token charts
- Tool timing visualization
- Anomaly highlighting

#### JSON Export

```bash
npx tsx bin/trace-viewer.ts .traces/ --output json --out analysis.json
```

Exports structured JSON optimized for:
- LLM-based analysis
- Custom tooling
- CI/CD integration

### Filtering Options

```bash
# Filter by session ID
npx tsx bin/trace-viewer.ts .traces/ --session session-xxx

# Filter by date range
npx tsx bin/trace-viewer.ts .traces/ --since 2026-01-01
npx tsx bin/trace-viewer.ts .traces/ --until 2026-01-31

# Combine filters
npx tsx bin/trace-viewer.ts .traces/ --since 2026-01-30 --analyze
```

### Comparing Sessions

Compare two trace sessions to identify improvements or regressions:

```bash
npx tsx bin/trace-viewer.ts compare baseline.jsonl comparison.jsonl
```

Output:
```
Session Comparison
==================

Baseline:   session-abc123
Comparison: session-def456

Metric Comparison:
--------------------------------------------------
Iterations               5 →          3  ↓ -2 (better)
Total Tokens         15000 →      12000  ↓ -3000 (better)
Cache Hit Rate          45% →        72%  ↑ +27pp (better)
Total Cost          $0.0450 →    $0.0284  ↓ $0.0166 (better)
Errors                   2 →          0  ↓ -2 (better)

--------------------------------------------------
Overall: 5/5 metrics improved
```

## Understanding Anomaly Detection

The tracing system automatically detects common issues:

### Excessive Iterations

**Trigger:** >7 iterations (medium), >10 iterations (high)

**Indicates:** Agent may be stuck in a loop or task is too complex

**Solutions:**
- Break task into smaller subtasks
- Provide clearer requirements
- Check for error recovery loops

### Cache Inefficiency

**Trigger:** <50% cache hit with 3+ iterations (medium), <30% with 2+ (high)

**Indicates:** System prompts or context changing too frequently

**Solutions:**
- Stabilize system prompt between calls
- Order messages consistently
- Use structured tool definitions

### Redundant Tool Calls

**Trigger:** Same tool called 5+ times

**Indicates:** Agent re-reading same files or repeating operations

**Solutions:**
- Agent should cache file contents in context
- Use batch operations where possible
- Review loop detection in agent logic

### Error Loops

**Trigger:** 3+ errors in session

**Indicates:** Agent encountering repeated failures

**Solutions:**
- Check tool error messages for patterns
- Review permission configuration
- Investigate external service issues

## Best Practices

### When to Use Tracing

1. **Debugging** - Enable when investigating unexpected behavior
2. **Optimization** - Profile long-running sessions for inefficiencies
3. **Cost Analysis** - Track token usage and spending patterns
4. **Benchmarking** - Compare performance across model changes

### Performance Impact

Tracing adds minimal overhead:
- ~1-2ms per event recording
- ~50-100KB per session (typical)
- Async file writes (non-blocking)

### Trace File Management

```bash
# Clean old traces (keep last 7 days)
find .traces/ -name "*.jsonl" -mtime +7 -delete

# Compress for archival
tar -czf traces-$(date +%Y%m).tar.gz .traces/*.jsonl

# Add to .gitignore (recommended)
echo ".traces/" >> .gitignore
```

## Programmatic Access

Access trace data from code:

```typescript
import { TraceCollector, createTraceCollector } from './tracing/trace-collector.js';

// Create collector
const collector = createTraceCollector({
  enabled: true,
  outputDir: '.traces',
  captureMessageContent: true,
  captureToolResults: true,
});

// Start session
await collector.startSession(sessionId, task, model);

// Record events (usually done automatically by ProductionAgent)
await collector.record({ type: 'llm.request', data: {...} });

// Get current trace without ending session
const trace = collector.getSessionTrace();

// End session
const finalTrace = await collector.endSession({ success: true });
```

### Accessing from ProductionAgent

```typescript
const agent = new ProductionAgent(config);

// Get trace collector
const collector = agent.getTraceCollector();

// Check if tracing is enabled
if (collector?.isSessionActive()) {
  const trace = collector.getSessionTrace();
  console.log('Iterations:', trace.iterations.length);
}
```

## Troubleshooting

### "No trace data collected yet"

**Cause:** Session hasn't started or already ended

**Solutions:**
1. Ensure `--trace` flag is enabled
2. Run at least one LLM call first
3. The trace remains available after session ends (since v0.1.4)

### Empty trace files

**Cause:** Session ended without LLM calls

**Solution:** Traces require at least one LLM request/response cycle

### Missing tool results

**Cause:** `captureToolResults: false` in config

**Solution:** Enable in trace collector config (may increase file size)

### High disk usage

**Cause:** Long sessions with verbose tracing

**Solutions:**
1. Set `maxResultSize` to limit tool result capture
2. Disable `captureMessageContent` for production
3. Implement trace rotation/cleanup
