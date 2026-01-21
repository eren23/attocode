# Atomic Tricks

Standalone utility modules for common AI agent patterns. Each trick is self-contained and can be used independently or integrated into larger systems.

## Overview

| Trick | Name | Description |
|-------|------|-------------|
| A | [Structured Output](#a-structured-output) | Parse LLM outputs into typed structures |
| B | [Token Counting](#b-token-counting) | Estimate tokens and costs |
| C | [Prompt Templates](#c-prompt-templates) | Compile and render templates |
| D | [Tool Batching](#d-tool-batching) | Execute tools with concurrency control |
| E | [Context Sliding](#e-context-sliding) | Manage context window limits |
| F | [Semantic Cache](#f-semantic-cache) | Cache based on semantic similarity |
| G | [Rate Limiter](#g-rate-limiter) | Handle API rate limits |
| H | [Branching](#h-branching) | Conversation tree management |
| I | [File Watcher](#i-file-watcher) | Watch files for changes |
| J | [LSP Client](#j-lsp-client) | Language Server Protocol integration |
| P | [KV-Cache Aware Context](#p-kv-cache-aware-context) | Optimize context for LLM caching (~10x cost reduction) |
| Q | [Recitation](#q-recitation--goal-reinforcement) | Combat "lost in middle" with goal injection |
| R | [Reversible Compaction](#r-reversible-compaction) | Preserve retrieval keys during summarization |
| S | [Failure Evidence](#s-failure-evidence-preservation) | Track failures to prevent loops |
| T | [Serialization Diversity](#t-serialization-diversity) | Prevent few-shot pattern collapse |

---

## A: Structured Output

Parse LLM outputs into strongly-typed structures with retry logic.

```typescript
import { parseStructured, objectSchema } from './tricks';

// Define schema
interface Task {
  title: string;
  priority: 'low' | 'medium' | 'high';
}

function isTask(v: unknown): v is Task {
  const obj = v as Record<string, unknown>;
  return typeof obj.title === 'string' && ['low', 'medium', 'high'].includes(obj.priority as string);
}

const taskSchema = objectSchema(isTask);

// Parse with retries
const task = await parseStructured(llm, 'Extract: "Submit report by Friday"', taskSchema);
// { title: "Submit report", priority: "high" }
```

**Key Features:**
- Schema validation with retries
- JSON extraction from markdown code blocks
- Error feedback for self-correction

---

## B: Token Counting

Estimate token counts and API costs.

```typescript
import { countTokens, estimateCost, createBudgetTracker } from './tricks';

// Count tokens
const tokens = countTokens('Hello, how are you?', 'gpt-4');

// Estimate cost
const cost = estimateCost({ inputTokens: 1000, outputTokens: 500, totalTokens: 1500 }, 'gpt-4');
console.log(cost); // { inputCost: 0.03, outputCost: 0.03, totalCost: 0.06 }

// Track budget
const budget = createBudgetTracker(10); // $10 limit
budget.record(0.05, 'gpt-4');
console.log(budget.remaining()); // 9.95
```

**Key Features:**
- Character-based estimation
- Model-specific pricing
- Budget tracking with history

---

## C: Prompt Templates

Compile templates with variables, conditionals, and loops.

```typescript
import { compileTemplate, PROMPT_TEMPLATES } from './tricks';

// Simple template
const greet = compileTemplate('Hello, {{name}}!');
console.log(greet({ name: 'Alice' })); // "Hello, Alice!"

// With conditionals and loops
const template = compileTemplate(`
{{#if examples}}
Examples:
{{#each examples}}
- {{this}}
{{/each}}
{{/if}}
`);

// Use built-in templates
const prompt = PROMPT_TEMPLATES.fewShot({
  task: 'Translate to French',
  examples: [{ input: 'Hello', output: 'Bonjour' }],
  input: 'Goodbye',
});
```

**Key Features:**
- Variable substitution
- Conditionals (`{{#if}}`), loops (`{{#each}}`)
- Nested property access

---

## D: Tool Batching

Execute multiple tool calls with controlled concurrency.

```typescript
import { executeBatch, createToolRegistry, executeWithDependencies } from './tricks';

const registry = createToolRegistry([
  { name: 'read_file', execute: async (args) => readFile(args.path) },
  { name: 'list_dir', execute: async (args) => readdir(args.path) },
]);

// Parallel with concurrency limit
const results = await executeBatch(calls, registry, {
  concurrency: 3,
  timeout: 5000,
  continueOnError: true,
});

// With dependencies
const dependentCalls = [
  { id: '1', name: 'list_dir', arguments: { path: '.' } },
  { id: '2', name: 'read_file', arguments: { path: 'a.txt' }, dependsOn: ['1'] },
];
await executeWithDependencies(dependentCalls, registry);
```

**Key Features:**
- Concurrency control
- Timeout handling
- Dependency resolution

---

## E: Context Sliding

Manage conversation history to fit within token limits.

```typescript
import { slideWindow, createContextWindow } from './tricks';

// One-time sliding
const result = await slideWindow(messages, {
  maxTokens: 4096,
  strategy: 'hybrid', // truncate, summarize, hybrid, priority
  reserveTokens: 1000,
  summarize: async (msgs) => `Summary of ${msgs.length} messages`,
});

// Managed window
const window = createContextWindow({ maxTokens: 4096, strategy: 'truncate' });
window.add({ id: '1', role: 'user', content: 'Hello' });
const { messages, summarized } = await window.getContext();
```

**Key Features:**
- Multiple strategies (truncate, summarize, hybrid, priority)
- Pinned messages support
- Token counting integration

---

## F: Semantic Cache

Cache responses based on semantic similarity.

```typescript
import { createSemanticCache, withCache } from './tricks';

const cache = createSemanticCache({
  threshold: 0.9, // Similarity threshold
  maxSize: 1000,
  ttl: 3600000, // 1 hour
});

// Manual cache check
const hit = await cache.get('What is the capital of France?');
if (hit) {
  console.log(`Cache hit (${hit.similarity}): ${hit.entry.response}`);
}

// Wrap LLM function
const cachedLLM = withCache(llm.generate.bind(llm), cache);
const response = await cachedLLM('What is the capital of France?');
```

**Key Features:**
- Cosine similarity matching
- LRU eviction
- Function wrapper

---

## G: Rate Limiter

Handle API rate limits with backpressure.

```typescript
import { createRateLimiter, PROVIDER_LIMITS } from './tricks';

const limiter = createRateLimiter({
  maxRequests: 100,
  windowMs: 60000,
  maxConcurrent: 5,
  retryStrategy: 'exponential',
});

// Manual acquire/release
await limiter.acquire();
try {
  await fetch('/api/...');
} finally {
  limiter.release();
}

// With retry logic
const response = await limiter.withRetry(() => fetch('/api/...'));

// Pre-configured providers
const openaiLimiter = PROVIDER_LIMITS.openai();
```

**Key Features:**
- Token bucket algorithm
- Retry-after header handling
- Exponential backoff

---

## H: Branching

Manage conversation branches for exploring alternatives.

```typescript
import { createConversationTree } from './tricks';

const tree = createConversationTree();

// Add messages
tree.addMessage('user', 'Hello');
const msg = tree.addMessage('assistant', 'Hi!');

// Fork to try alternative
const branchId = tree.fork(msg.id, 'alternative');
tree.addMessage('assistant', 'Hey there!');

// Switch branches
tree.checkout('main');

// Compare branches
const diff = tree.compareBranches('main', branchId);
console.log('Unique to alternative:', diff.onlyB);

// Merge branches
tree.merge(branchId, 'interleave');
```

**Key Features:**
- Fork/checkout/merge operations
- Multiple merge strategies
- Branch comparison

---

## I: File Watcher

Watch for file changes with debouncing.

```typescript
import { watchProject, watchProjectBatched } from './tricks';

// Watch with callback
const watcher = watchProject('.', ['**/*.ts'], (path, event) => {
  console.log(`${event}: ${path}`);
}, {
  ignore: ['node_modules'],
  debounce: 100,
});

// Batched events
const batchedWatcher = watchProjectBatched('.', ['**/*.ts'], (changes) => {
  console.log(`${changes.size} files changed`);
});

// Cleanup
watcher.dispose();
```

**Key Features:**
- Glob pattern matching
- Debouncing
- Batched events

---

## J: LSP Client

Language Server Protocol integration for code intelligence.

```typescript
import { createLSPClient } from './tricks';

const client = createLSPClient({
  serverPath: 'typescript-language-server',
  serverArgs: ['--stdio'],
  rootUri: 'file:///path/to/project',
});

await client.start();

// Get definition
const definition = await client.getDefinition('file:///path/file.ts', 10, 5);

// Get completions
const completions = await client.getCompletions('file:///path/file.ts', 10, 5);

// Get hover info
const hover = await client.getHover('file:///path/file.ts', 10, 5);

await client.stop();
```

**Key Features:**
- Definition lookup
- Completions
- Hover information
- References search

---

## P: KV-Cache Aware Context

Optimize context structure for LLM KV-cache efficiency. Cached input tokens cost ~10x less than uncached ones.

```typescript
import { createCacheAwareContext, stableStringify, analyzeCacheEfficiency } from './tricks';

// Create cache-aware context manager
const context = createCacheAwareContext({
  staticPrefix: 'You are a helpful coding assistant.',
  cacheBreakpoints: ['system_end', 'tools_end'],
  deterministicJson: true,
});

// Build system prompt with stable prefix
// Dynamic content (session ID, timestamp) goes at END, not beginning
const systemPrompt = context.buildSystemPrompt({
  rules: rulesContent,
  tools: toolDescriptions,
  dynamic: { sessionId: 'abc123', mode: 'build' },
});

// Serialize tool arguments deterministically (same object = same string)
const args = stableStringify({ path: '/src', recursive: true });

// Check for cache-unfriendly patterns
const analysis = analyzeCacheEfficiency(systemPrompt);
if (analysis.warnings.length > 0) {
  console.warn('Cache warnings:', analysis.warnings);
}
```

**Key Principles:**
1. **Stable prefix** - Keep static content at the START of system prompt
2. **Deterministic JSON** - Sorted keys ensure same object = same string
3. **Dynamic content at END** - Timestamps, session IDs go last
4. **Append-only history** - Never modify past messages

**Key Features:**
- 10x cost reduction on cached tokens
- Cache breakpoint tracking
- Append-only validation
- Cache statistics calculation

---

## Q: Recitation / Goal Reinforcement

Periodically inject task summaries (plans, todos, goals) into the END of context to combat "lost in the middle" attention issues.

```typescript
import { createRecitationManager, calculateOptimalFrequency } from './tricks';

const recitation = createRecitationManager({
  frequency: 5,  // Every 5 iterations
  sources: ['goal', 'plan', 'todo'],
  maxTokens: 500,
});

// In agent loop
const enrichedMessages = recitation.injectIfNeeded(messages, {
  iteration: currentIteration,
  goal: 'Implement user authentication',
  plan: {
    description: 'Add OAuth login',
    tasks: [
      { id: '1', description: 'Create login endpoint', status: 'completed' },
      { id: '2', description: 'Add JWT tokens', status: 'in_progress' },
      { id: '3', description: 'Write tests', status: 'pending' },
    ],
    currentTaskIndex: 1,
  },
  todos: [
    { content: 'Fix session timeout', status: 'pending' },
  ],
});

// Calculate optimal frequency based on context size
const frequency = calculateOptimalFrequency(contextTokens);
recitation.updateConfig({ frequency });
```

**Problem Solved:**
In long conversations (50+ tool calls), the original goal gets "buried" in the middle of context. The model's attention favors recent content, causing it to lose track of the original task.

**Key Features:**
- Automatic frequency calculation based on context size
- Multiple content sources (goal, plan, todo, memory)
- Injection at context END (where attention is highest)
- Active file and recent error tracking

---

## R: Reversible Compaction

Preserve "reconstruction recipes" during context compaction. Instead of discarding information, store retrieval keys so the model can fetch details when needed.

```typescript
import { createReversibleCompactor, createReconstructionPrompt } from './tricks';

const compactor = createReversibleCompactor({
  preserveTypes: ['file', 'url', 'function', 'error'],
  maxReferences: 50,
  deduplicate: true,
});

// Compact messages while preserving references
const result = await compactor.compact(messages, {
  summarize: async (msgs) => summarizeLLM(msgs),
});

console.log(result.summary);       // Condensed summary
console.log(result.references);    // Preserved retrieval keys
console.log(result.stats);         // Compression statistics

// Create prompt that enables retrieval
const reconstructionPrompt = createReconstructionPrompt(result.references);
// Output:
// "Files (can be read with read_file tool):
//   - /src/auth/login.ts
//   - /src/utils/jwt.ts
// URLs (can be fetched for details):
//   - https://docs.example.com/oauth [Documentation]"

// Later, search references
const authFiles = compactor.searchReferences('auth');
const errors = compactor.getReferencesByType('error');
```

**Reference Types:**
- `file` - File paths that can be re-read
- `url` - URLs that can be re-fetched
- `function` - Function names that can be searched
- `error` - Error messages for debugging context
- `command` - Shell commands that were executed

**Key Features:**
- Extract references during compaction
- Deduplication and relevance scoring
- Reconstruction prompts for retrieval
- Search preserved references

---

## S: Failure Evidence Preservation

Track failed actions, error traces, and unsuccessful attempts so the model can learn from mistakes and avoid repeating them.

```typescript
import { createFailureTracker, formatFailureContext, extractInsights } from './tricks';

const tracker = createFailureTracker({
  maxFailures: 30,
  preserveStackTraces: true,
  detectRepeats: true,
  repeatWarningThreshold: 3,
});

// Record failures during agent loop
try {
  await tool.execute(args);
} catch (error) {
  tracker.recordFailure({
    action: tool.name,
    args,
    error,
    iteration: currentIteration,
    intent: 'Read configuration file',
  });
}

// Include failure context in prompts
const failureContext = tracker.getFailureContext({ maxFailures: 10 });
if (failureContext) {
  messages.push({
    role: 'system',
    content: failureContext,
  });
}

// Check for patterns
tracker.on((event) => {
  if (event.type === 'failure.repeated' && event.count >= 3) {
    console.warn(`Action "${event.failure.action}" has failed ${event.count} times!`);
  }
  if (event.type === 'pattern.detected') {
    console.warn(`Pattern detected: ${event.pattern.description}`);
    console.warn(`Suggestion: ${event.pattern.suggestion}`);
  }
});

// Get actionable insights
const insights = extractInsights(tracker.getUnresolvedFailures());
// ["Multiple permission errors - check if running with sufficient privileges"]
```

**Auto-categorization:**
- `permission` - Access denied errors
- `not_found` - File/resource not found
- `syntax` - Parsing/syntax errors
- `type` - Type errors
- `network` - Connection errors
- `timeout` - Timeout errors

**Key Features:**
- Automatic error categorization
- Repeat failure detection
- Pattern recognition (escalating failures, category clusters)
- Auto-generated suggestions

---

## T: Serialization Diversity

Introduce controlled variation in serialization to prevent few-shot pattern collapse and over-fitting to specific formats.

```typescript
import { createDiverseSerializer, generateVariations, areSemanticEquivalent } from './tricks';

const serializer = createDiverseSerializer({
  variationLevel: 0.3,  // 30% variation
  preserveSemantics: true,
  varyKeyOrder: true,
  varyIndentation: true,
});

// Each call may produce slightly different (but equivalent) output
const json1 = serializer.serialize({ name: 'Alice', age: 30 });
const json2 = serializer.serialize({ name: 'Alice', age: 30 });
// json1: {"age": 30, "name": "Alice"}
// json2: {"name": "Alice", "age": 30}

// Both are semantically equivalent
console.log(areSemanticEquivalent(json1, json2)); // true

// Generate multiple variations (useful for training data)
const variations = generateVariations(data, 5, 0.5);
// [
//   '{"count":2,"files":["a.ts","b.ts"]}',
//   '{\n  "files": ["a.ts", "b.ts"],\n  "count": 2\n}',
//   '{"files": ["a.ts", "b.ts"], "count": 2}',
//   ...
// ]

// Track diversity statistics
const stats = serializer.getStats();
console.log(`Average variation: ${(stats.averageVariation * 100).toFixed(1)}%`);
```

**Variation Types:**
- **Key ordering** - Randomize or reverse object key order
- **Indentation** - Vary between compact, 2-space, 4-space, tab
- **Spacing** - Vary space after colons, inside brackets
- **Array format** - Compact vs expanded for arrays
- **Null handling** - Sometimes omit null values

**Problem Solved:**
When tool results are always serialized identically, the model may develop rigid patterns - expecting certain fields in certain orders. This causes brittle behavior when encountering slight variations from external sources.

**Key Features:**
- Controlled variation (0-1 level)
- Semantic equivalence guarantee
- Statistics tracking
- Deterministic mode with seed

---

## Usage

Import from the index:

```typescript
import {
  parseStructured,
  countTokens,
  compileTemplate,
  executeBatch,
  slideWindow,
  createSemanticCache,
  createRateLimiter,
  createConversationTree,
  watchProject,
  createLSPClient,
} from './tricks';
```

Or import individual modules:

```typescript
import { parseStructured } from './tricks/structured-output.js';
import { countTokens } from './tricks/token-counter.js';
```

## Integration Examples

### With Agent Loop

```typescript
import { createRateLimiter, createSemanticCache, countTokens } from './tricks';

const limiter = createRateLimiter({ maxRequests: 60, windowMs: 60000 });
const cache = createSemanticCache({ threshold: 0.95 });

async function agentLoop(prompt: string) {
  // Check cache
  const cached = await cache.get(prompt);
  if (cached) return cached.entry.response;

  // Rate limit
  await limiter.acquire();
  try {
    const response = await llm.generate(prompt);
    await cache.set(prompt, response);
    return response;
  } finally {
    limiter.release();
  }
}
```

### With Tool Execution

```typescript
import { executeBatch, createToolRegistry, parseStructured } from './tricks';

// Parse tool calls from LLM output
const calls = await parseStructured(llm, prompt, toolCallsSchema);

// Execute with batching
const results = await executeBatch(calls, registry, { concurrency: 3 });
```

### With Context Management

```typescript
import { createContextWindow, countTokens } from './tricks';

const window = createContextWindow({
  maxTokens: 8192,
  strategy: 'hybrid',
  countTokens: (text) => countTokens(text, 'gpt-4'),
  summarize: async (msgs) => summarizeLLM(msgs),
});

// Add messages as conversation progresses
window.add({ id: '1', role: 'user', content: userMessage });

// Get context that fits
const { messages } = await window.getContext();
```

---

## Production Agent Integration

The following table shows which tricks are used in the Lesson 25 Production Agent:

| Trick | Used in Production | Notes |
|-------|-------------------|-------|
| A: Structured Output | ✓ Inline | Tool call parsing uses inline JSON extraction |
| B: Token Counter | ✓ Enhanced | `economics.ts` - budget tracking, cost estimation |
| C: Prompt Templates | ✓ Inline | `rules.ts` - simplified inline templates |
| D: Tool Batching | ✓ Enhanced | `agent.ts` - parallel tool execution |
| E: Context Sliding | ✓ Enhanced | `compaction.ts` - context summarization |
| F: Semantic Cache | ✓ Enhanced | `semantic-cache.ts` - manager version |
| G: Rate Limiter | ✓ Embedded | Error handling, retry logic in providers |
| H: Branching | ✓ Enhanced | `thread-manager.ts` - full thread management |
| **I: File Watcher** | **❌ Not Used** | Available for extension (see below) |
| J: LSP Client | ✓ Enhanced | `lsp.ts` - manager version |
| **P: KV-Cache Context** | **🆕 Ready** | Integration ready - see performance tests |
| **Q: Recitation** | **🆕 Ready** | Integration ready - see performance tests |
| **R: Reversible Compaction** | **🆕 Ready** | Enhances E (Context Sliding) |
| **S: Failure Evidence** | **🆕 Ready** | Integration ready - see performance tests |
| **T: Serialization Diversity** | **🆕 Ready** | Integration ready - see performance tests |

### Trick I: File Watcher (Extension Point)

The File Watcher trick is **not currently used** in the production agent but is available for extension. Potential uses:

1. **Auto-reload configuration** - Watch `.agent/`, `.rules/`, `.skills/` for changes
2. **Live test runner** - Re-run tests when source files change
3. **Code analysis triggers** - Re-analyze when relevant files change
4. **Session auto-save** - Trigger saves when watched files are modified

Example integration:

```typescript
import { watchProject } from './tricks/file-watcher.js';

// Watch for rule changes and reload
const watcher = watchProject('.agent', ['**/*.md'], async (path, event) => {
  if (event === 'change' || event === 'add') {
    await rulesManager.reload();
    console.log('Rules reloaded');
  }
}, { debounce: 500 });

// Cleanup on shutdown
agent.on('shutdown', () => watcher.dispose());
```

The trick is fully implemented and tested - it just wasn't needed for the current production agent workflow.
