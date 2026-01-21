/**
 * Lesson 24: Advanced Patterns Types
 *
 * Type definitions for advanced agent patterns including:
 * - Thread management (fork, merge, rollback)
 * - Checkpoints and state snapshots
 * - Hierarchical configuration
 * - Configuration-driven agents
 * - Cancellation tokens
 * - Resource monitoring
 *
 * Inspired by patterns from OpenCode and Codex.
 */

// =============================================================================
// MESSAGE TYPES
// =============================================================================

/**
 * A message in a conversation thread.
 */
export interface Message {
  /** Unique message ID */
  id: string;

  /** Message role */
  role: 'system' | 'user' | 'assistant' | 'tool';

  /** Message content */
  content: string;

  /** Tool calls (for assistant messages) */
  toolCalls?: ToolCall[];

  /** Tool call ID this message responds to */
  toolCallId?: string;

  /** Timestamp */
  timestamp: Date;

  /** Metadata */
  metadata?: Record<string, unknown>;
}

/**
 * A tool call in a message.
 */
export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
}

// =============================================================================
// THREAD TYPES
// =============================================================================

/**
 * A conversation thread that can be forked and merged.
 */
export interface Thread {
  /** Unique thread ID */
  id: string;

  /** Human-readable name */
  name?: string;

  /** Parent thread ID (if forked) */
  parentId?: string;

  /** Fork point message ID (if forked) */
  forkPointId?: string;

  /** Messages in this thread */
  messages: Message[];

  /** Thread state */
  state: ThreadState;

  /** Creation timestamp */
  createdAt: Date;

  /** Last update timestamp */
  updatedAt: Date;

  /** Thread metadata */
  metadata?: Record<string, unknown>;
}

/**
 * Thread state.
 */
export type ThreadState =
  | 'active'      // Currently being used
  | 'paused'      // Temporarily paused
  | 'completed'   // Finished successfully
  | 'merged'      // Merged into another thread
  | 'abandoned'   // Rolled back or discarded
  | 'archived';   // Kept for reference

/**
 * Options for forking a thread.
 */
export interface ForkOptions {
  /** Name for the new branch */
  name?: string;

  /** Message ID to fork from (default: latest) */
  fromMessageId?: string;

  /** Copy metadata to fork */
  copyMetadata?: boolean;

  /** Additional metadata for fork */
  metadata?: Record<string, unknown>;
}

/**
 * Options for merging threads.
 */
export interface MergeOptions {
  /** Strategy for handling conflicts (defaults to 'concat') */
  strategy?: MergeStrategy;

  /** Keep the source branch after merge */
  keepSource?: boolean;

  /** Custom conflict resolver */
  conflictResolver?: (main: Message[], branch: Message[]) => Message[];
}

/**
 * Strategy for merging threads.
 */
export type MergeStrategy =
  | 'append'      // Append branch messages to main
  | 'interleave'  // Interleave by timestamp
  | 'replace'     // Replace main messages with branch
  | 'summarize'   // Summarize branch and add as single message
  | 'custom';     // Use custom resolver

/**
 * Result of a thread operation.
 */
export interface ThreadOperationResult {
  success: boolean;
  threadId: string;
  message?: string;
  error?: string;
}

// =============================================================================
// CHECKPOINT TYPES
// =============================================================================

/**
 * A checkpoint capturing agent state at a point in time.
 */
export interface Checkpoint {
  /** Unique checkpoint ID */
  id: string;

  /** Human-readable label */
  label?: string;

  /** Thread ID this checkpoint belongs to */
  threadId: string;

  /** Message ID at checkpoint time */
  messageId: string;

  /** Message index in thread */
  messageIndex: number;

  /** Serialized agent state */
  state: SerializedState;

  /** Creation timestamp */
  createdAt: Date;

  /** Checkpoint metadata */
  metadata?: Record<string, unknown>;
}

/**
 * Serialized agent state for checkpoints.
 */
export interface SerializedState {
  /** Messages up to checkpoint */
  messages: Message[];

  /** Memory state (if applicable) */
  memory?: unknown;

  /** Plan state (if applicable) */
  plan?: unknown;

  /** Tool state (pending calls, etc.) */
  tools?: unknown;

  /** Custom state */
  custom?: Record<string, unknown>;
}

/**
 * Options for creating a checkpoint.
 */
export interface CheckpointOptions {
  /** Label for the checkpoint */
  label?: string;

  /** Include full state (memory, plan, etc.) */
  includeFullState?: boolean;

  /** Custom state to include */
  customState?: Record<string, unknown>;

  /** Metadata */
  metadata?: Record<string, unknown>;
}

/**
 * Options for restoring from checkpoint.
 */
export interface RestoreOptions {
  /** Create a new thread instead of modifying current */
  createNewThread?: boolean;

  /** Restore memory state */
  restoreMemory?: boolean;

  /** Restore plan state */
  restorePlan?: boolean;
}

// =============================================================================
// HIERARCHICAL STATE TYPES
// =============================================================================

/**
 * Configuration at a specific level.
 */
export interface LevelConfig {
  /** Configuration level */
  level: ConfigLevel;

  /** The configuration values */
  values: Record<string, unknown>;

  /** Source of this configuration */
  source?: string;

  /** Load timestamp */
  loadedAt: Date;
}

/**
 * Configuration levels (lower = higher priority).
 */
export type ConfigLevel =
  | 'default'     // Built-in defaults (lowest priority)
  | 'global'      // User global config (~/.agent/config)
  | 'workspace'   // Project config (.agent/config)
  | 'session'     // Runtime overrides (highest priority)
  | 'override';   // Explicit overrides

/**
 * Resolved configuration after merging all levels.
 */
export interface ResolvedConfig<T = Record<string, unknown>> {
  /** The merged configuration */
  config: T;

  /** Which level each key came from */
  sources: Record<string, ConfigLevel>;

  /** Levels that contributed */
  levels: ConfigLevel[];

  /** Resolution timestamp */
  resolvedAt: Date;
}

/**
 * Configuration schema for validation.
 */
export interface ConfigSchema {
  /** Schema version */
  version: string;

  /** Field definitions */
  fields: Record<string, ConfigFieldDef>;

  /** Required fields */
  required?: string[];
}

/**
 * Definition for a configuration field.
 */
export interface ConfigFieldDef {
  /** Field type */
  type: 'string' | 'number' | 'boolean' | 'array' | 'object';

  /** Description */
  description?: string;

  /** Default value */
  default?: unknown;

  /** Allowed values (for enums) */
  enum?: unknown[];

  /** Minimum value (for numbers) */
  min?: number;

  /** Maximum value (for numbers) */
  max?: number;

  /** Can be overridden at lower levels */
  overridable?: boolean;
}

// =============================================================================
// AGENT DEFINITION TYPES
// =============================================================================

/**
 * Agent definition loaded from markdown/config file.
 */
export interface AgentDefinition {
  /** Agent name */
  name: string;

  /** Display name */
  displayName?: string;

  /** Description */
  description?: string;

  /** Model to use */
  model?: string;

  /** Available tools */
  tools?: string[];

  /** System prompt */
  systemPrompt: string;

  /** Authority level (for multi-agent) */
  authority?: number;

  /** Maximum concurrent tasks */
  maxConcurrentTasks?: number;

  /** Custom settings */
  settings?: Record<string, unknown>;

  /** Source file */
  sourceFile?: string;

  /** Load timestamp */
  loadedAt?: Date;
}

/**
 * Frontmatter from agent markdown file.
 */
export interface AgentFrontmatter {
  name: string;
  displayName?: string;
  model?: string;
  tools?: string[];
  authority?: number;
  maxConcurrentTasks?: number;
  [key: string]: unknown;
}

// =============================================================================
// CANCELLATION TYPES
// =============================================================================

/**
 * Token that can be used to cancel an operation.
 */
export interface CancellationToken {
  /** Whether cancellation has been requested */
  isCancellationRequested: boolean;

  /** Promise that resolves when cancelled */
  onCancellationRequested: Promise<void>;

  /** Register a callback for cancellation */
  register(callback: () => void): Disposable;

  /** Throw if cancelled */
  throwIfCancellationRequested(): void;
}

/**
 * Source that creates cancellation tokens.
 */
export interface CancellationTokenSource {
  /** The token */
  token: CancellationToken;

  /** Request cancellation with optional reason */
  cancel(reason?: string): void;

  /** Dispose the source */
  dispose(): void;
}

/**
 * A disposable resource.
 */
export interface Disposable {
  dispose(): void;
}

/**
 * Options for cancellable operations.
 */
export interface CancellableOptions {
  /** Cancellation token */
  cancellationToken?: CancellationToken;

  /** Timeout in milliseconds */
  timeout?: number;

  /** Callback on cancellation */
  onCancel?: () => void;
}

/**
 * Error thrown when operation is cancelled.
 */
export class CancellationError extends Error {
  readonly isCancellation = true;

  constructor(message = 'Operation was cancelled') {
    super(message);
    this.name = 'CancellationError';
  }
}

// =============================================================================
// RESOURCE MONITORING TYPES
// =============================================================================

/**
 * Current resource usage.
 */
export interface ResourceUsage {
  /** Memory usage in bytes */
  memoryBytes: number;

  /** Memory usage as percentage of limit */
  memoryPercent: number;

  /** CPU time in milliseconds */
  cpuTimeMs: number;

  /** Number of active operations */
  activeOperations: number;

  /** Timestamp */
  timestamp: Date;
}

/**
 * Resource limits.
 */
export interface ResourceLimits {
  /** Maximum memory in bytes */
  maxMemoryBytes?: number;

  /** Maximum CPU time in milliseconds */
  maxCpuTimeMs?: number;

  /** Maximum concurrent operations */
  maxOperations?: number;

  /** Warning threshold (0-1) */
  warningThreshold?: number;

  /** Critical threshold (0-1) */
  criticalThreshold?: number;
}

/**
 * Resource status.
 */
export type ResourceStatus =
  | 'healthy'   // Below warning threshold
  | 'warning'   // Above warning, below critical
  | 'critical'  // Above critical threshold
  | 'exceeded'; // Limits exceeded

/**
 * Resource check result.
 */
export interface ResourceCheck {
  /** Current status */
  status: ResourceStatus;

  /** Current usage */
  usage: ResourceUsage;

  /** Configured limits */
  limits: ResourceLimits;

  /** Recommendations */
  recommendations?: string[];
}

// =============================================================================
// EVENTS
// =============================================================================

/**
 * Events from advanced pattern operations.
 */
export type AdvancedPatternEvent =
  // Thread events
  | { type: 'thread.created'; thread: Thread }
  | { type: 'thread.forked'; parentId: string; forkId: string }
  | { type: 'thread.merged'; mainId: string; branchId: string }
  | { type: 'thread.rolled_back'; threadId: string; checkpointId: string }
  | { type: 'thread.state_changed'; threadId: string; state: ThreadState }
  // Checkpoint events
  | { type: 'checkpoint.created'; checkpoint: Checkpoint }
  | { type: 'checkpoint.restored'; checkpointId: string; threadId: string }
  | { type: 'checkpoint.deleted'; checkpointId: string }
  // Config events
  | { type: 'config.loaded'; level: ConfigLevel; source: string }
  | { type: 'config.resolved'; config: ResolvedConfig }
  | { type: 'config.changed'; key: string; oldValue: unknown; newValue: unknown }
  // Agent loader events
  | { type: 'agent.loaded'; agent: AgentDefinition }
  | { type: 'agent.reloaded'; agent: AgentDefinition }
  | { type: 'agent.error'; name: string; error: string }
  // Cancellation events
  | { type: 'cancellation.requested'; reason?: string }
  | { type: 'cancellation.completed'; cleanedUp: boolean }
  // Resource events
  | { type: 'resource.warning'; usage: ResourceUsage; limit: string }
  | { type: 'resource.critical'; usage: ResourceUsage; limit: string }
  | { type: 'resource.exceeded'; usage: ResourceUsage; limit: string };

/**
 * Event listener.
 */
export type AdvancedPatternEventListener = (event: AdvancedPatternEvent) => void;

// =============================================================================
// DEFAULT VALUES
// =============================================================================

/**
 * Default resource limits.
 */
export const DEFAULT_RESOURCE_LIMITS: ResourceLimits = {
  maxMemoryBytes: 512 * 1024 * 1024, // 512 MB
  maxCpuTimeMs: 300000, // 5 minutes
  maxOperations: 10,
  warningThreshold: 0.7,
  criticalThreshold: 0.9,
};

/**
 * Default merge options.
 */
export const DEFAULT_MERGE_OPTIONS: MergeOptions = {
  strategy: 'append',
  keepSource: false,
};

/**
 * Default fork options.
 */
export const DEFAULT_FORK_OPTIONS: ForkOptions = {
  copyMetadata: true,
};

/**
 * Default checkpoint options.
 */
export const DEFAULT_CHECKPOINT_OPTIONS: CheckpointOptions = {
  includeFullState: true,
};
