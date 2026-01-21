# Lesson 10: Hook & Event System

> Building extensible architecture through events and hooks

## What You'll Learn

1. **Event-Driven Architecture**: How components communicate through events instead of direct calls
2. **Hook System**: Intercepting and modifying behavior without changing core code
3. **Priority Ordering**: Ensuring predictable hook execution order
4. **Error Isolation**: Preventing one hook from breaking others
5. **Performance Tracking**: Monitoring hook execution times

## Why This Matters

As your agent grows, you'll need to add features like:
- Logging all tool calls
- Blocking dangerous operations
- Collecting metrics
- Custom validation

Without hooks, you'd have to modify the core agent code for each feature. Hooks let you add these capabilities externally, keeping the core clean and maintainable.

## Key Concepts

### Events vs Hooks

| Aspect | Events | Hooks |
|--------|--------|-------|
| Purpose | Observation | Interception |
| Can modify? | No | Yes (with `canModify: true`) |
| Timing | After the fact | Before/after |
| Use case | Logging, metrics | Security, validation |

### Event Types

```typescript
type AgentEvent =
  | { type: 'tool.before'; tool: string; args: unknown }
  | { type: 'tool.after'; tool: string; result: unknown; durationMs: number }
  | { type: 'tool.error'; tool: string; error: Error }
  | { type: 'session.start'; sessionId: string }
  | { type: 'session.end'; sessionId: string; reason: string }
  | { type: 'message.created'; role: string; content: string }
  | { type: 'file.edited'; path: string; operation: string }
  | { type: 'error'; error: Error; recoverable: boolean };
```

### Hook Definition

```typescript
interface Hook<T extends AgentEventType> {
  id: string;           // Unique identifier
  event: T;             // Event type to listen for
  handler: Function;    // Callback function
  priority?: number;    // Execution order (lower = earlier)
  canModify?: boolean;  // Can this hook modify the event?
}
```

### Priority Ranges

| Range | Who Uses It | Example |
|-------|-------------|---------|
| 0-50 | System hooks | Logging (always runs first) |
| 50-150 | Plugin hooks | Metrics, validation |
| 150+ | User hooks | Custom business logic |

## Files in This Lesson

| File | Purpose |
|------|---------|
| `types.ts` | Event and hook type definitions |
| `event-bus.ts` | Typed EventEmitter for observation |
| `hook-registry.ts` | Hook registration and execution |
| `built-in-hooks.ts` | Logging, metrics, security hooks |
| `main.ts` | Demonstration of all concepts |

## Running This Lesson

```bash
npm run lesson:10
```

## Code Examples

### Basic Event Subscription

```typescript
import { EventBus, createEvent } from './event-bus.js';

const bus = new EventBus();

// Subscribe to tool events
const subscription = bus.on('tool.before', (event) => {
  console.log(`Tool ${event.tool} called with:`, event.args);
});

// Emit an event
await bus.emit(createEvent('tool.before', {
  tool: 'bash',
  args: { command: 'ls -la' }
}));

// Cleanup
subscription.unsubscribe();
```

### Intercepting Hook

```typescript
import { HookRegistry } from './hook-registry.js';

const registry = new HookRegistry();

// Block dangerous operations
registry.register({
  id: 'security-block',
  event: 'tool.before',
  priority: 10,
  canModify: true,
  handler: (event) => {
    if (event.tool === 'bash' && event.args.command.includes('rm -rf')) {
      console.warn('Blocked dangerous command!');
      event.preventDefault = true;  // Stop execution
    }
  }
});
```

### Collecting Metrics

```typescript
import { registerMetricsHooks } from './built-in-hooks.js';

const metrics: Metric[] = [];

registerMetricsHooks(registry, {
  prefix: 'myagent',
  onMetric: (metric) => {
    metrics.push(metric);
    // Send to monitoring system
  }
});
```

### Complete Tool Wrapper

```typescript
async function executeWithHooks(tool: string, args: unknown) {
  // Before hook
  const beforeEvent = { type: 'tool.before', tool, args };
  await registry.execute(beforeEvent);

  if (beforeEvent.preventDefault) {
    return { blocked: true };
  }

  // Execute
  const start = performance.now();
  const result = await actualExecute(tool, args);
  const durationMs = performance.now() - start;

  // After hook
  await registry.execute({
    type: 'tool.after',
    tool,
    result,
    durationMs
  });

  return result;
}
```

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                        Agent Core                            │
│  ┌──────────┐     ┌──────────┐     ┌──────────┐            │
│  │  Tools   │────▶│  Events  │────▶│  Hooks   │            │
│  └──────────┘     └──────────┘     └──────────┘            │
│       │                │                │                    │
└───────┼────────────────┼────────────────┼────────────────────┘
        │                │                │
        │                ▼                ▼
        │         ┌──────────┐    ┌──────────────┐
        │         │ EventBus │    │ HookRegistry │
        │         └──────────┘    └──────────────┘
        │                │                │
        ▼                ▼                ▼
┌─────────────────────────────────────────────────────────────┐
│                     Plugin Layer                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ Logging  │  │ Metrics  │  │ Security │  │ Custom   │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
└─────────────────────────────────────────────────────────────┘
```

## Error Handling Strategies

The hook registry supports three error strategies:

```typescript
type ErrorStrategy = 'continue' | 'stop' | 'collect';
```

| Strategy | Behavior |
|----------|----------|
| `continue` | Log error, continue to next hook |
| `stop` | Stop execution on first error |
| `collect` | Collect all errors, return in result |

## Design Decisions

### Why Typed Events?
TypeScript's discriminated unions ensure you can only emit valid events and get proper type inference in handlers.

### Why Priority Numbers?
Explicit priorities (vs. registration order) make behavior predictable and allow plugins to position themselves appropriately.

### Why Error Isolation?
One buggy hook shouldn't crash the entire agent. Errors are caught and logged, but execution continues.

## Common Patterns

### Async Hooks
```typescript
registry.register({
  id: 'async-hook',
  event: 'tool.after',
  handler: async (event) => {
    await sendToAnalytics(event);  // Async is supported
  }
});
```

### Conditional Hooks
```typescript
registry.register({
  id: 'conditional',
  event: 'tool.before',
  handler: (event) => {
    if (shouldSkip(event)) return;  // Early return
    // ... processing
  }
});
```

### Transforming Args
```typescript
registry.register({
  id: 'transform-args',
  event: 'tool.before',
  canModify: true,
  handler: (event) => {
    // Sanitize command before execution
    event.modifiedArgs = {
      ...event.args,
      command: sanitize(event.args.command)
    };
  }
});
```

## Testing Hooks

```typescript
import { describe, it, expect } from 'vitest';
import { HookRegistry } from './hook-registry.js';

describe('HookRegistry', () => {
  it('executes hooks in priority order', async () => {
    const registry = new HookRegistry();
    const order: string[] = [];

    registry.register({
      id: 'second',
      event: 'tool.before',
      priority: 100,
      handler: () => order.push('second')
    });

    registry.register({
      id: 'first',
      event: 'tool.before',
      priority: 50,
      handler: () => order.push('first')
    });

    await registry.execute({ type: 'tool.before', tool: 'test', args: {} });

    expect(order).toEqual(['first', 'second']);
  });
});
```

## Next Steps

In **Lesson 11: Plugin Architecture**, we'll build on the hook system to create a full plugin system that can:
- Discover and load plugins dynamically
- Provide isolated contexts for plugins
- Manage plugin lifecycle (init, cleanup)
- Handle plugin dependencies

The hook system you learned here becomes the foundation for plugin communication!
