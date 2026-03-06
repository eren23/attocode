---
sidebar_position: 5
title: "Integration Modules"
---

# Integration Modules

Attocode's features are organized as integration modules under `src/integrations/`. Each module is a self-contained unit that plugs into the agent through a consistent pattern.

## Directory Structure

There are 13 subdirectories, each with its own `index.ts` barrel:

```
src/integrations/
├── budget/        # Economics, budget pools, doom loop detection
├── context/       # Context engineering, compaction, codebase analysis
├── safety/        # Sandboxing, policy engine, edit validation
├── persistence/   # SQLite store, session management, history
├── agents/        # Agent registry, blackboard, delegation protocol
├── tasks/         # Task management, planning, decomposition
├── skills/        # Skill loading and execution
├── mcp/           # MCP client, tool search, custom tools
├── quality/       # Learning store, self-improvement, checkpoints
├── utilities/     # Hooks, rules, routing, logger, retry, etc.
├── swarm/         # Swarm orchestration, worker pools, task queues
├── streaming/     # Streaming output, PTY shell
├── lsp/           # Language Server Protocol integration
└── index.ts       # Root barrel re-exporting from all subdirectories
```

## Adding a New Module

### 1. Choose the Right Subdirectory

Pick the subdirectory that best matches your module's domain. If none fit, you can create a new subdirectory.

### 2. Create the Module File

```typescript
// src/integrations/quality/my-feature.ts

export interface MyFeatureConfig {
  enabled?: boolean;
  threshold?: number;
}

export class MyFeatureManager {
  private config: MyFeatureConfig;

  constructor(config: MyFeatureConfig) {
    this.config = config;
  }

  async initialize(): Promise<void> {
    // Setup logic
  }

  async cleanup(): Promise<void> {
    // Teardown logic
  }
}
```

### 3. Export from the Subdirectory Barrel

```typescript
// src/integrations/quality/index.ts
export { MyFeatureManager, type MyFeatureConfig } from './my-feature.js';
```

The root `src/integrations/index.ts` re-exports from all subdirectory barrels automatically.

### 4. Add a Config Flag

Add a configuration option in `src/types.ts` inside `ProductionAgentConfig`:

```typescript
export interface ProductionAgentConfig {
  // ... existing config ...

  /** My feature configuration */
  myFeature?: MyFeatureConfig | false;
}
```

Setting the value to `false` explicitly disables the feature. Leaving it `undefined` uses the default behavior.

### 5. Initialize in Feature Initializer

Wire the module into the agent in `src/agent/feature-initializer.ts`:

```typescript
// In initializeFeatures()
if (config.myFeature !== false) {
  const myFeature = new MyFeatureManager(config.myFeature ?? {});
  await myFeature.initialize();
  agent.myFeatureManager = myFeature;
}
```

## Integration Pattern

The standard pattern for integration modules:

1. **Nullable manager**: The agent holds a nullable reference (`myFeatureManager: MyFeatureManager | null = null`)
2. **Feature flag**: Controlled by `ProductionAgentConfig` with `false` to disable
3. **Lazy initialization**: Created in `feature-initializer.ts` during agent setup
4. **Cleanup**: Implement `cleanup()` for resource release during agent shutdown

## Events

Modules can emit typed events through the agent's event system:

```typescript
// Emit from within the agent
this.emit({
  type: 'myfeature.activated',
  threshold: this.config.threshold,
});
```

Add your event types to the `AgentEvent` union in `src/types.ts`:

```typescript
export type AgentEvent =
  // ... existing events ...
  | { type: 'myfeature.activated'; threshold: number }
  | { type: 'myfeature.result'; success: boolean };
```

## Testing

Write tests in the `tests/` directory following existing patterns:

```typescript
// tests/my-feature.test.ts
import { describe, it, expect, beforeEach } from 'vitest';
import { MyFeatureManager } from '../src/integrations/quality/my-feature.js';

describe('MyFeatureManager', () => {
  let manager: MyFeatureManager;

  beforeEach(() => {
    manager = new MyFeatureManager({ enabled: true, threshold: 5 });
  });

  it('should initialize without errors', async () => {
    await expect(manager.initialize()).resolves.not.toThrow();
  });
});
```

Run tests with:

```bash
npm test                    # All tests
npm run test:watch          # Watch mode
npm run test:coverage       # Coverage report
```

## Checklist

When adding a new integration module:

- [ ] Module file in the appropriate subdirectory
- [ ] Exported from the subdirectory's `index.ts`
- [ ] Config type added to `ProductionAgentConfig` in `src/types.ts`
- [ ] Initialization wired in `src/agent/feature-initializer.ts`
- [ ] Cleanup implemented and called during agent shutdown
- [ ] Events added to `AgentEvent` union if needed
- [ ] Tests written in `tests/`
