# Lesson 19: Observability & Tracing

> Monitoring, debugging, and understanding agent behavior in production

## What You'll Learn

1. **Distributed Tracing**: Track operations through spans
2. **Metrics Collection**: Token/cost/latency tracking
3. **Structured Logging**: Correlated logs for debugging
4. **Export Formats**: Console, JSON, JSONL, OTLP
5. **Cost Attribution**: Per-task cost tracking

## Why This Matters

Without observability, debugging agents is guesswork:

```
Without Observability:
┌─────────────────────────────────────────────────────────┐
│  Agent run fails... but why?                            │
│                                                         │
│  ❓ Which LLM call took so long?                        │
│  ❓ Which tool call failed?                             │
│  ❓ How much did this run cost?                         │
│  ❓ What was the sequence of operations?                │
└─────────────────────────────────────────────────────────┘

With Observability:
┌─────────────────────────────────────────────────────────┐
│  ✓ "LLM call at 2:34:15 took 5.2s (timeout was 5s)"    │
│  ✓ "Tool 'search' returned 0 results"                  │
│  ✓ "Total cost: $0.0023, 450 input + 120 output tokens"│
└─────────────────────────────────────────────────────────┘
```

## Key Concepts

### Traces and Spans

```
Trace (full operation)
└── Span: agent.run (500ms)
    ├── Span: agent.plan (50ms)
    ├── Span: llm.call (150ms)
    │   └── attributes: model=claude-3-sonnet, tokens=200
    ├── Span: tool.search (80ms)
    │   └── attributes: results=5
    └── Span: llm.call (120ms)
```

### Agent Metrics

```typescript
interface AgentMetrics {
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  estimatedCost: number;
  toolCalls: number;
  llmCalls: number;
  duration: number;
  errors: number;
}
```

### Log Correlation

Logs include trace/span IDs for correlation:
```
2024-01-15T10:30:00Z INFO  [abc12345]: Making LLM call {model: "claude-3"}
2024-01-15T10:30:01Z WARN  [abc12345]: Rate limit approaching {remaining: 10}
```

## Files in This Lesson

| File | Purpose |
|------|---------|
| `types.ts` | Span, Metric, Log type definitions |
| `tracer.ts` | OpenTelemetry-style tracing |
| `metrics.ts` | Token/cost/latency tracking |
| `logger.ts` | Structured logging |
| `exporter.ts` | Output formats (console, JSON, OTLP) |
| `main.ts` | Demonstration of all concepts |

## Running This Lesson

```bash
npm run lesson:19
```

## Code Examples

### Basic Tracing

```typescript
import { createTracer } from './tracer.js';

const tracer = createTracer('my-agent');

// Wrap operations with spans
const result = await tracer.withSpan('agent.run', async (span) => {
  tracer.setAttribute(span, 'goal', 'Find tutorials');

  // Nested span for LLM call
  await tracer.withSpan('llm.call', async (llmSpan) => {
    tracer.setAttribute(llmSpan, 'model', 'claude-3-sonnet');
    tracer.setAttribute(llmSpan, 'tokens', 150);
    // ... make LLM call
  }, { kind: 'client' });

  return 'success';
});
```

### Metrics Collection

```typescript
import { createMetricsCollector } from './metrics.js';

const metrics = createMetricsCollector({ service: 'my-agent' });

// Record LLM call
metrics.recordLLMCall(
  'claude-3-sonnet',
  150,  // input tokens
  50,   // output tokens
  120,  // duration ms
  false // cached
);

// Record tool call
metrics.recordToolCall('search', 80, true);

// Get summary
const summary = metrics.getAgentMetrics();
console.log(`Total cost: $${summary.estimatedCost.toFixed(4)}`);
```

### Structured Logging

```typescript
import { createLogger } from './logger.js';

const logger = createLogger('agent', { minLevel: 'info' });

logger.info('Starting task', { goal: 'Find tutorials' });
logger.debug('Configuration loaded', { model: 'claude-3' });
logger.warn('Rate limit approaching', { remaining: 10 });
logger.error('Task failed', new Error('Timeout'), { retries: 3 });
```

### Exporting Data

```typescript
import { ConsoleExporter, JSONLExporter, OTLPExporter } from './exporter.js';

// Console (human-readable)
const console = new ConsoleExporter();

// JSONL (streaming)
const jsonl = new JSONLExporter('/path/to/traces.jsonl');

// OTLP (observability platforms)
const otlp = new OTLPExporter('http://collector:4318');

// Export spans
await exporter.exportSpans(tracer.getAllTraces()[0].spans);
await exporter.flush();
```

## Cost Tracking

Model pricing (per 1K tokens):

| Model | Input | Output |
|-------|-------|--------|
| GPT-4 | $0.030 | $0.060 |
| GPT-4-Turbo | $0.010 | $0.030 |
| Claude-3-Opus | $0.015 | $0.075 |
| Claude-3-Sonnet | $0.003 | $0.015 |
| Claude-3-Haiku | $0.00025 | $0.00125 |

```typescript
const cost = metrics.calculateCost('claude-3-sonnet', 1000, 500);
// $0.003 + $0.0075 = $0.0105
```

## Alerting Patterns

```typescript
// Latency alert
metrics.on((event) => {
  if (event.type === 'metric.recorded' &&
      event.metric.name === 'agent.llm.duration' &&
      event.metric.value > 5000) {
    alert('LLM latency > 5s');
  }
});

// Error rate alert
const errorRate = metrics.getAgentMetrics().errors /
                  metrics.getAgentMetrics().llmCalls;
if (errorRate > 0.05) {
  alert('Error rate > 5%');
}

// Cost alert
if (metrics.getAgentMetrics().estimatedCost > 10) {
  alert('Daily cost exceeded $10');
}
```

## Export Formats

| Format | Use Case |
|--------|----------|
| console | Development, quick debugging |
| json | Analysis, archival |
| jsonl | Streaming, log aggregation |
| otlp | Observability platforms (Jaeger, Datadog) |

## Best Practices

### Span Naming
- Use dot notation: `agent.run`, `llm.call`, `tool.search`
- Include operation type and subject

### Attribute Selection
- Don't log sensitive data (API keys, PII)
- Include enough context for debugging
- Use consistent attribute names

### Sampling
- Sample traces in production (e.g., 10%)
- Always record errors
- Full sampling in development

### Cost Management
- Set daily/monthly budgets
- Alert before hitting limits
- Track cost per task type

## Advanced: Execution Economics

The production agent implements an **ExecutionEconomicsManager** that replaces hard-coded iteration limits with intelligent budget management and progress detection.

### The Problem with Iteration Limits

```
Traditional approach:
  maxIterations = 100  // Arbitrary!

Problems:
- Simple tasks hit the limit unnecessarily
- Complex tasks get cut off prematurely
- No correlation to actual cost or time
- Can't distinguish productive vs. stuck
```

### Multi-Dimensional Budgets

```typescript
interface ExecutionBudget {
  // Hard limits (force stop)
  maxTokens: number;           // e.g., 200000
  maxCost: number;             // e.g., $0.50 USD
  maxDuration: number;         // e.g., 300000ms (5 min)

  // Soft limits (warn/prompt for extension)
  softTokenLimit: number;      // e.g., 150000
  softCostLimit: number;       // e.g., $0.30 USD
  softDurationLimit: number;   // e.g., 180000ms (3 min)

  // Iteration is now soft guidance
  targetIterations: number;    // e.g., 20 (advisory)
  maxIterations: number;       // e.g., 100 (safety cap)
}
```

### Progress Detection

```typescript
interface ProgressState {
  filesRead: Set<string>;       // Files we've read
  filesModified: Set<string>;   // Files we've changed
  commandsRun: string[];        // Commands executed
  recentToolCalls: ToolCall[];  // Last 10 calls for loop detection
  lastMeaningfulProgress: number; // Timestamp
  stuckCount: number;           // Iterations without progress
}

// Detect stuck state
function isStuck(): boolean {
  // Check for repeated identical calls
  if (recentToolCalls.length >= 3) {
    const last3 = recentToolCalls.slice(-3);
    const unique = new Set(last3.map(tc => `${tc.tool}:${tc.args}`));
    if (unique.size === 1) return true; // Same call 3x
  }

  // Check for no progress over time
  const timeSinceProgress = Date.now() - lastMeaningfulProgress;
  if (timeSinceProgress > 60000 && iterations > 5) {
    return true; // No progress for 1 min with 5+ iterations
  }

  return false;
}
```

### Cost Estimation

```typescript
recordLLMUsage(inputTokens: number, outputTokens: number, model?: string): void {
  this.usage.inputTokens += inputTokens;
  this.usage.outputTokens += outputTokens;
  this.usage.tokens += inputTokens + outputTokens;

  // Model-specific cost estimates
  const inputCost = getInputCost(model);  // e.g., $0.003/1k for Sonnet
  const outputCost = getOutputCost(model); // e.g., $0.015/1k for Sonnet

  this.usage.cost += (inputTokens / 1000) * inputCost;
  this.usage.cost += (outputTokens / 1000) * outputCost;
}
```

### Budget Check Flow

```typescript
function checkBudget(): BudgetCheckResult {
  // 1. Check hard limits first
  if (usage.tokens >= budget.maxTokens) {
    return { canContinue: false, suggestedAction: 'stop' };
  }
  if (usage.cost >= budget.maxCost) {
    return { canContinue: false, suggestedAction: 'stop' };
  }

  // 2. Check soft limits (warnings)
  if (usage.tokens >= budget.softTokenLimit) {
    return { canContinue: true, suggestedAction: 'request_extension' };
  }

  // 3. Check if stuck
  if (progressState.stuckCount >= 3) {
    return { canContinue: true, suggestedAction: 'request_extension' };
  }

  // 4. All good
  return { canContinue: true, suggestedAction: 'continue' };
}
```

### Budget Extension Requests

```typescript
interface ExtensionRequest {
  currentUsage: ExecutionUsage;
  budget: ExecutionBudget;
  reason: string;
  suggestedExtension: Partial<ExecutionBudget>;
}

// When approaching soft limit:
async function requestExtension(reason: string): Promise<boolean> {
  const request = {
    currentUsage,
    budget,
    reason,
    suggestedExtension: {
      maxTokens: Math.round(budget.maxTokens * 1.5),
      maxCost: budget.maxCost * 1.5,
    },
  };

  // Ask user for approval
  const approved = await extensionHandler(request);
  if (approved) {
    extendBudget(approved);
    return true;
  }
  return false;
}
```

### Preset Budgets

```typescript
// Quick task - simple queries
const QUICK_BUDGET = {
  maxTokens: 50000,
  maxCost: 0.10,
  maxDuration: 60000, // 1 minute
  targetIterations: 5,
};

// Standard task - typical development
const STANDARD_BUDGET = {
  maxTokens: 200000,
  maxCost: 0.50,
  maxDuration: 300000, // 5 minutes
  targetIterations: 20,
};

// Large task - complex multi-step
const LARGE_BUDGET = {
  maxTokens: 500000,
  maxCost: 2.00,
  maxDuration: 900000, // 15 minutes
  targetIterations: 50,
};
```

### Integration Example

```typescript
const economics = createEconomicsManager(STANDARD_BUDGET);

// Set extension handler (prompts user)
economics.setExtensionHandler(async (request) => {
  const answer = await askUser(
    `Task is using ${request.currentUsage.tokens} tokens. Extend budget?`
  );
  return answer ? request.suggestedExtension : null;
});

// In agent loop
while (true) {
  // Record LLM usage
  const response = await llm.chat(messages);
  economics.recordLLMUsage(response.inputTokens, response.outputTokens, model);

  // Record tool calls
  for (const call of response.toolCalls) {
    const result = await executeTool(call);
    economics.recordToolCall(call.name, call.args, result);
  }

  // Check budget
  const check = economics.checkBudget();
  if (!check.canContinue) {
    console.log(`Stopping: ${check.reason}`);
    break;
  }
  if (check.suggestedAction === 'request_extension') {
    const extended = await economics.requestExtension(check.reason);
    if (!extended) break;
  }
}
```

### Events

```typescript
economics.on((event) => {
  switch (event.type) {
    case 'budget.warning':
      console.log(`Budget warning: ${event.budgetType} at ${event.percentUsed}%`);
      break;
    case 'budget.exceeded':
      console.log(`Budget exceeded: ${event.budgetType}`);
      break;
    case 'progress.stuck':
      console.log(`Agent stuck for ${event.stuckCount} iterations`);
      break;
    case 'progress.made':
      console.log(`Progress: ${event.filesModified} files modified`);
      break;
  }
});
```

## Next Steps

In **Lesson 20: Sandboxing & Isolation**, we'll learn how to:
- Run untrusted code safely
- Limit resource usage
- Isolate agent execution environments
