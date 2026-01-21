# Lesson 24: Advanced Patterns

This lesson teaches advanced agent patterns including thread management, checkpoints, hierarchical configuration, and resource monitoring. Inspired by patterns from OpenCode and Codex.

## Key Concepts

### Thread Management
Git-like version control for conversations:
- **Fork**: Create branches to explore alternatives
- **Merge**: Combine successful explorations back
- **Rollback**: Return to earlier conversation states

### Checkpoints
State snapshots for recovery:
- Save complete agent state at key points
- Restore to previous states when needed
- Enable safe exploration with rollback capability

### Hierarchical Configuration
Cascading settings from global to local:
- **Default**: Built-in sensible defaults
- **Global**: User preferences (~/.agent/config)
- **Workspace**: Project settings (.agent/config)
- **Session**: Runtime overrides

### Configuration-Driven Agents
Define agents in markdown files:
- YAML frontmatter for settings
- Markdown body for system prompt
- Easy to version control and share

### Cancellation Tokens
Graceful operation cancellation:
- Cooperative cancellation pattern
- Timeout support
- Clean resource cleanup

### Resource Monitoring
Prevent runaway operations:
- Memory and CPU tracking
- Concurrent operation limits
- Warning and critical thresholds

## Files

| File | Purpose |
|------|---------|
| `types.ts` | Type definitions for all patterns |
| `thread-manager.ts` | Thread forking, merging, rollback |
| `checkpoint-store.ts` | State snapshots and recovery |
| `hierarchical-state.ts` | Configuration cascading |
| `agent-loader.ts` | Load agents from markdown files |
| `cancellation.ts` | Cancellation token implementation |
| `resource-monitor.ts` | Resource usage tracking and limits |
| `agents/*.md` | Example agent definitions |
| `main.ts` | Interactive demo |

## Usage

### Thread Management

```typescript
import { createThreadManager } from './thread-manager.js';

const tm = createThreadManager();

// Build conversation
tm.addMessage('user', 'Help me with this problem');
tm.addMessage('assistant', 'I can help two ways...');

// Fork to explore option A
const branchA = tm.fork({ name: 'option-a' });
tm.addMessage('user', 'Let\'s try option A');
tm.addMessage('assistant', 'Here\'s option A...');

// Go back and try option B
tm.switchThread(branchA.parentId!);
const branchB = tm.fork({ name: 'option-b' });
tm.addMessage('user', 'Let\'s try option B');

// Merge successful branch
tm.merge(branchA.id, branchB.parentId!, { strategy: 'append' });

// Rollback if needed
tm.rollbackBy(2); // Go back 2 messages
```

### Checkpoints

```typescript
import { createCheckpointStore } from './checkpoint-store.js';

const store = createCheckpointStore(threadManager);

// Create checkpoint at key moment
const checkpoint = store.createCheckpoint(thread, {
  label: 'before-risky-operation'
});

// ... do risky things ...

// Restore if things went wrong
store.restore(checkpoint.id, threadManager);
```

### Hierarchical Configuration

```typescript
import { createStateManager } from './hierarchical-state.js';

const manager = createStateManager({
  model: 'claude-3-5-sonnet',
  maxTokens: 4096,
});

// Load from files
manager.loadGlobal();    // ~/.agent/config.json
manager.loadWorkspace(); // .agent/config.json

// Session override
manager.setSessionOverride('model', 'claude-3-opus');

// Get resolved config
const config = manager.resolve();
console.log(config.config.model); // 'claude-3-opus'
console.log(config.sources.model); // 'session'
```

### Agent Definitions

```markdown
<!-- agents/coder.md -->
---
name: coder
model: claude-3-5-sonnet
tools: [read_file, write_file, bash]
authority: 5
---

# Code Writer Agent

You are an expert developer focused on clean code...
```

```typescript
import { createAgentLoader } from './agent-loader.js';

const loader = createAgentLoader();
loader.loadFromDirectory('./agents');

const coder = loader.getAgent('coder');
console.log(coder.systemPrompt);
```

### Cancellation Tokens

```typescript
import {
  createCancellationTokenSource,
  withCancellation,
  CancellationError
} from './cancellation.js';

const cts = createCancellationTokenSource();

// Run cancellable operation
const operation = withCancellation(
  async () => {
    // Check cancellation periodically
    cts.token.throwIfCancellationRequested();
    await longOperation();
  },
  { cancellationToken: cts.token }
);

// Cancel from elsewhere (e.g., user interrupt)
process.on('SIGINT', () => cts.cancel());

// Or use timeout
const cts2 = createCancellationTokenSource();
cts2.cancelAfter(30000); // 30 seconds
```

### Resource Monitoring

```typescript
import { createResourceMonitor } from './resource-monitor.js';

const monitor = createResourceMonitor({
  maxMemoryBytes: 512 * 1024 * 1024,
  maxOperations: 10,
  warningThreshold: 0.7,
});

// Check before starting work
if (!monitor.canStartOperation()) {
  await monitor.waitForSlot();
}

// Track operations
await monitor.runOperation(async () => {
  await doWork();
});

// React to warnings
monitor.subscribe(event => {
  if (event.type === 'resource.warning') {
    console.log('Approaching limits, consider cleanup');
  }
});
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Agent Runtime                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │   Thread    │  │ Checkpoint  │  │    Hierarchical     │ │
│  │   Manager   │──│   Store     │  │   State Manager     │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
│         │                                     │             │
│         ▼                                     ▼             │
│  ┌─────────────┐                    ┌─────────────────┐    │
│  │   Agent     │                    │   Agent Config  │    │
│  │   Loader    │                    │    (merged)     │    │
│  └─────────────┘                    └─────────────────┘    │
│         │                                                   │
│  ┌──────┴──────┐                                           │
│  │ agents/*.md │                                           │
│  └─────────────┘                                           │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐                         │
│  │Cancellation │  │  Resource   │                         │
│  │   Tokens    │  │  Monitor    │                         │
│  └─────────────┘  └─────────────┘                         │
└─────────────────────────────────────────────────────────────┘
```

## Merge Strategies

| Strategy | Behavior |
|----------|----------|
| `append` | Add branch messages to end of main |
| `interleave` | Sort all messages by timestamp |
| `replace` | Replace main with branch messages |
| `summarize` | Create summary of branch changes |
| `custom` | Use custom resolver function |

## Configuration Levels

| Level | Priority | Source |
|-------|----------|--------|
| `default` | 1 (lowest) | Built-in |
| `global` | 2 | ~/.agent/config |
| `workspace` | 3 | .agent/config |
| `session` | 4 | Runtime |
| `override` | 5 (highest) | Explicit |

## Running the Demo

```bash
npx tsx 24-advanced-patterns/main.ts
```

## Best Practices

1. **Checkpoint strategically**: Before risky operations, after major milestones
2. **Fork for exploration**: Don't modify main thread when unsure
3. **Use session overrides**: Don't modify workspace config at runtime
4. **Register cleanup handlers**: Always handle cancellation gracefully
5. **Monitor resources**: Set appropriate limits for your environment
6. **Define agents declaratively**: Use markdown files for easy management

## Integration with Production Agent

In Lesson 25, these patterns integrate with the production agent:

```typescript
const agent = buildAgent()
  .provider(myProvider)
  .threads({ enabled: true, autoCheckpoint: true })
  .hierarchicalConfig({
    defaults: { model: 'claude-3-5-sonnet' },
    loadGlobal: true,
    loadWorkspace: true,
  })
  .cancellation({ timeout: 60000 })
  .resourceLimits({
    maxMemoryBytes: 512 * 1024 * 1024,
    maxOperations: 10,
  })
  .build();

// Create checkpoint before risky operation
agent.createCheckpoint('before-deploy');

// Fork for exploration
const branch = agent.fork('try-alternative');

// Rollback if needed
agent.rollbackTo('before-deploy');
```

## Next Steps

- **Lesson 25**: Production Agent - Capstone with ALL features integrated
