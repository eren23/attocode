---
sidebar_position: 6
title: Type System
---

# Type System

The shared type definitions in `src/types.ts` (~1,500 lines) form the contract between all system components. This file defines message types, configuration, state, events, LLM interfaces, and tool types.

## Message Types

The core conversation types model the LLM interaction protocol:

```typescript
interface Message {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  toolCalls?: ToolCall[];
  toolResults?: ToolResult[];
  toolCallId?: string;            // For tool role, references the call
  metadata?: Record<string, unknown>;  // Compaction hints, provenance
}

interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  parseError?: string;   // Set when JSON parsing partially fails
}

interface ToolResult {
  callId: string;
  result: unknown;
  error?: string;
}
```

### Structured Content Messages

For prompt caching, messages can carry structured content blocks instead of plain strings:

```typescript
interface ContentBlock {
  type: 'text';
  text: string;
  cache_control?: { type: 'ephemeral' };
}

interface MessageWithStructuredContent {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string | ContentBlock[];
  toolCalls?: ToolCall[];
  toolResults?: ToolResult[];
  toolCallId?: string;
  metadata?: Record<string, unknown>;
}
```

The `cache_control` marker tells the Anthropic API to cache this content block across requests, enabling significant cost savings for static system prompt portions.

## Configuration

`ProductionAgentConfig` contains ~50 feature flags, each following the `FeatureConfig | false` pattern:

```typescript
interface ProductionAgentConfig {
  // Required
  provider: LLMProvider;
  tools: ToolDefinition[];

  // Optional core settings
  systemPrompt?: string;
  model?: string;
  maxTokens?: number;
  temperature?: number;
  maxContextTokens?: number;
  maxIterations?: number;
  timeout?: number;
  workingDirectory?: string;

  // Feature configs (each can be disabled with `false`)
  hooks?: HooksConfig | false;
  plugins?: PluginsConfig | false;
  rules?: RulesConfig | false;
  memory?: MemoryConfig | false;
  planning?: PlanningConfig | false;
  reflection?: ReflectionConfig | false;
  observability?: ObservabilityConfig | false;
  routing?: RoutingConfig | false;
  sandbox?: SandboxConfig | false;
  humanInLoop?: HumanInLoopConfig | false;
  multiAgent?: MultiAgentConfig | false;
  react?: ReActPatternConfig | false;
  executionPolicy?: ExecutionPolicyConfig | false;
  policyEngine?: PolicyEngineConfig | false;
  threads?: ThreadsConfig | false;
  cancellation?: CancellationConfig | false;
  resources?: ResourceConfig | false;
  lsp?: LSPAgentConfig | false;
  semanticCache?: SemanticCacheAgentConfig | false;
  skills?: SkillsAgentConfig | false;
  codebaseContext?: CodebaseContextAgentConfig | false;
  interactivePlanning?: InteractivePlanningAgentConfig | false;
  recursiveContext?: RecursiveContextAgentConfig | false;
  compaction?: CompactionAgentConfig | false;
  learningStore?: LearningStoreAgentConfig | false;
  resilience?: LLMResilienceAgentConfig | false;
  fileChangeTracker?: FileChangeTrackerAgentConfig | false;
  subagent?: SubagentConfig | false;
  swarm?: SwarmConfig | false;
  providerResilience?: ProviderResilienceConfig | false;
  verificationCriteria?: { ... };

  // Internal fields (for subagent coordination)
  toolResolver?: (toolName: string) => ToolDefinition | null;
  mcpToolSummaries?: Array<{ name: string; description: string }>;
  agentId?: string;
  blackboard?: unknown;
  fileCache?: unknown;
  budget?: { maxTokens?: number; softTokenLimit?: number; ... };
  sharedContextState?: unknown;
  sharedEconomicsState?: unknown;
}
```

The `isFeatureEnabled()` helper returns `false` when the config value is `false` or `undefined`, and `true` otherwise. This drives the nullable manager pattern throughout the codebase.

## State Types

### AgentState

```typescript
interface AgentState {
  status: 'idle' | 'running' | 'completed' | 'error';
  messages: Message[];
  plan?: AgentPlan;
  memoryContext: string[];
  metrics: AgentMetrics;
  iteration: number;
}
```

### AgentResult

```typescript
interface AgentResult {
  success: boolean;
  response: string;
  metrics: AgentMetrics;
  completionStatus: AgentCompletionStatus;
  modifiedFiles?: string[];
}
```

### AgentCompletionStatus

```typescript
interface AgentCompletionStatus {
  reason: 'completed' | 'max_iterations' | 'budget_exceeded'
    | 'cancelled' | 'error' | 'resource_limit'
    | 'verification_failed' | 'hard_context_limit';
  details?: string;
}
```

### AgentMetrics

```typescript
interface AgentMetrics {
  totalTokens: number;
  inputTokens: number;
  outputTokens: number;
  estimatedCost: number;
  llmCalls: number;
  toolCalls: number;
  duration: number;
  successCount: number;
  failureCount: number;
  retryCount?: number;
  cacheHitRate?: number;
}
```

## Event System

`AgentEvent` is a discriminated union of 80+ event types, grouped by category:

| Category | Event Types | Examples |
|----------|------------|---------|
| **Lifecycle** | 8 types | `run.before`, `run.after`, `iteration.before`, `iteration.after`, `completion.before`, `completion.after`, `recovery.before`, `recovery.after` |
| **Core** | 12 types | `start`, `planning`, `llm.start`, `llm.chunk`, `llm.complete`, `tool.start`, `tool.complete`, `tool.blocked`, `approval.required`, `error`, `complete` |
| **ReAct** | 4 types | `react.thought`, `react.action`, `react.observation`, `react.answer` |
| **Multi-agent** | 8 types | `multiagent.spawn`, `agent.spawn`, `agent.complete`, `agent.error`, `agent.pending_plan` |
| **Policy** | 6 types | `policy.evaluated`, `policy.profile.resolved`, `policy.tool.blocked`, `policy.bash.blocked` |
| **Thread** | 4 types | `thread.forked`, `thread.switched`, `checkpoint.created`, `rollback` |
| **Resilience** | 6 types | `resilience.retry`, `resilience.recovered`, `resilience.continue`, `resilience.completed`, `resilience.truncated_tool_call` |
| **Compaction** | 2 types | `compaction.auto`, `compaction.warning` |
| **Cache** | 3 types | `cache.hit`, `cache.miss`, `cache.set` |
| **Insight** | 4 types | `insight.tokens`, `insight.context`, `insight.tool`, `insight.routing` |
| **Mode/Plan** | 5 types | `mode.changed`, `plan.change.queued`, `plan.approved`, `plan.rejected`, `plan.executing` |
| **Cancellation** | 2 types | `cancellation.requested`, `cancellation.completed` |
| **Diagnostics** | various | `swarm.*`, `subagent.*`, `verification.*` |

Events are consumed by:
- **TUI**: Renders messages, tool calls, agent status, and token metrics
- **ObservabilityManager**: Logs and traces
- **TraceCollector**: Records to JSONL for post-hoc analysis

## LLM Types

```typescript
interface LLMProvider {
  name?: string;
  chat(messages: (Message | MessageWithStructuredContent)[], options?: ChatOptions): Promise<ChatResponse>;
  stream?(messages: Message[], options?: ChatOptions): AsyncIterable<StreamChunk>;
}

interface ChatOptions {
  model?: string;
  maxTokens?: number;
  temperature?: number;
  tools?: ToolDefinition[];
}

interface ChatResponse {
  content: string;
  toolCalls?: ToolCall[];
  usage?: TokenUsage;
  model?: string;
  stopReason?: 'end_turn' | 'tool_use' | 'max_tokens' | 'stop_sequence';
  thinking?: string;  // Extended thinking from supporting models
}

interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  cacheReadTokens?: number;
  cacheWriteTokens?: number;
  cost?: number;
}
```

## Tool Types

```typescript
interface ToolDefinition {
  name: string;
  description: string;
  parameters: Record<string, unknown>;  // JSON Schema
  execute: (args: Record<string, unknown>) => Promise<unknown>;
  dangerLevel?: 'safe' | 'moderate' | 'dangerous';
  getDangerLevel?: (args: Record<string, unknown>) => DangerLevel;
}

type DangerLevel = 'safe' | 'moderate' | 'dangerous';

type PermissionMode = 'always_allow' | 'always_deny' | 'ask';
```

Permission requests and responses flow through a typed protocol:

```typescript
interface PermissionRequest {
  tool: string;
  args: Record<string, unknown>;
  dangerLevel: DangerLevel;
  reason: string;
}

interface PermissionResponse {
  granted: boolean;
  scope?: 'once' | 'session' | 'always';
  reason?: string;
}
```
