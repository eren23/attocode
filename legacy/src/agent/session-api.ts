/**
 * Session, checkpoint, and file-change tracking API.
 *
 * Extracted from ProductionAgent to keep agent.ts focused on orchestration.
 * Each function takes a `SessionApiDeps` object that exposes the private
 * fields it needs, plus explicit parameters that mirror the original
 * method signatures.
 */

import type { Message, AgentMetrics, AgentPlan, AgentState } from '../types.js';

import type { FileChangeTracker, UndoResult } from '../integrations/index.js';

import type {
  ObservabilityManager,
  PlanningManager,
  ThreadManager,
  MemoryManager,
} from '../integrations/index.js';

import { createComponentLogger } from '../integrations/utilities/logger.js';

const log = createComponentLogger('SessionApi');

// =============================================================================
// DEPENDENCY INTERFACE
// =============================================================================

/**
 * The subset of ProductionAgent fields that the session/checkpoint/file-change
 * functions need. Kept intentionally narrow — only what these functions touch.
 */
export interface SessionApiDeps {
  // Agent state (read/write)
  state: AgentState;

  // Integration managers (read)
  fileChangeTracker: FileChangeTracker | null;
  observability: ObservabilityManager | null;
  memory: MemoryManager | null;
  planning: PlanningManager | null;
  threadManager: ThreadManager | null;
}

// =============================================================================
// FILE CHANGE TRACKING
// =============================================================================

/**
 * Record a file change for potential undo.
 * No-op if file change tracking is not enabled.
 *
 * @returns Change ID if tracked, -1 otherwise
 */
export async function trackFileChange(
  deps: SessionApiDeps,
  params: {
    filePath: string;
    operation: 'create' | 'write' | 'edit' | 'delete';
    contentBefore?: string;
    contentAfter?: string;
    toolCallId?: string;
  },
): Promise<number> {
  if (!deps.fileChangeTracker) {
    return -1;
  }

  return deps.fileChangeTracker.recordChange({
    filePath: params.filePath,
    operation: params.operation,
    contentBefore: params.contentBefore,
    contentAfter: params.contentAfter,
    turnNumber: deps.state.iteration,
    toolCallId: params.toolCallId,
  });
}

/**
 * Undo the last change to a specific file.
 * Returns null if file change tracking is not enabled.
 */
export async function undoLastFileChange(
  deps: SessionApiDeps,
  filePath: string,
): Promise<UndoResult | null> {
  if (!deps.fileChangeTracker) {
    return null;
  }
  return deps.fileChangeTracker.undoLastChange(filePath);
}

/**
 * Undo all changes in the current turn.
 * Returns null if file change tracking is not enabled.
 */
export async function undoCurrentTurn(deps: SessionApiDeps): Promise<UndoResult[] | null> {
  if (!deps.fileChangeTracker) {
    return null;
  }
  return deps.fileChangeTracker.undoTurn(deps.state.iteration);
}

// =============================================================================
// STATE RESET
// =============================================================================

/**
 * Reset agent state to initial values.
 */
export function reset(deps: SessionApiDeps): void {
  deps.state.status = 'idle';
  deps.state.messages = [];
  deps.state.plan = undefined;
  deps.state.memoryContext = [];
  deps.state.metrics = {
    totalTokens: 0,
    inputTokens: 0,
    outputTokens: 0,
    estimatedCost: 0,
    llmCalls: 0,
    toolCalls: 0,
    duration: 0,
    successCount: 0,
    failureCount: 0,
    cancelCount: 0,
    retryCount: 0,
  };
  deps.state.iteration = 0;

  deps.memory?.clear();
  deps.observability?.metrics?.reset();
  deps.planning?.clearPlan();

  deps.observability?.logger?.info('Agent state reset');
}

// =============================================================================
// MESSAGE LOADING (deprecated)
// =============================================================================

/**
 * Load messages from a previous session.
 * @deprecated Use loadState() for full state restoration
 */
export function loadMessages(deps: SessionApiDeps, messages: Message[]): void {
  deps.state.messages = [...messages];

  // Sync to threadManager if enabled
  if (deps.threadManager) {
    const thread = deps.threadManager.getActiveThread();
    thread.messages = [...messages];
  }

  deps.observability?.logger?.info('Messages loaded', { count: messages.length });
}

// =============================================================================
// SERIALIZABLE STATE
// =============================================================================

/**
 * Serializable state for checkpoints (excludes non-serializable fields).
 */
export function getSerializableState(deps: SessionApiDeps): {
  messages: Message[];
  iteration: number;
  metrics: AgentMetrics;
  plan?: AgentPlan;
  memoryContext?: string[];
} {
  return {
    messages: deps.state.messages,
    iteration: deps.state.iteration,
    metrics: { ...deps.state.metrics },
    plan: deps.state.plan ? { ...deps.state.plan } : undefined,
    memoryContext: deps.state.memoryContext ? [...deps.state.memoryContext] : undefined,
  };
}

// =============================================================================
// CHECKPOINT VALIDATION
// =============================================================================

/**
 * Validate checkpoint data before loading.
 * Returns validation result with errors and warnings.
 */
export function validateCheckpoint(data: unknown): {
  valid: boolean;
  errors: string[];
  warnings: string[];
  sanitized: {
    messages: Message[];
    iteration: number;
    metrics?: Partial<AgentMetrics>;
    plan?: AgentPlan;
    memoryContext?: string[];
  } | null;
} {
  const errors: string[] = [];
  const warnings: string[] = [];

  // Check if data is an object
  if (!data || typeof data !== 'object') {
    errors.push('Checkpoint data must be an object');
    return { valid: false, errors, warnings, sanitized: null };
  }

  const checkpoint = data as Record<string, unknown>;

  // Validate messages array (required)
  if (!checkpoint.messages) {
    errors.push('Checkpoint missing required "messages" field');
  } else if (!Array.isArray(checkpoint.messages)) {
    errors.push('Checkpoint "messages" must be an array');
  } else {
    // Validate each message has required fields
    for (let i = 0; i < checkpoint.messages.length; i++) {
      const msg = checkpoint.messages[i] as Record<string, unknown>;
      if (!msg || typeof msg !== 'object') {
        errors.push(`Message at index ${i} is not an object`);
        continue;
      }
      if (!msg.role || typeof msg.role !== 'string') {
        errors.push(`Message at index ${i} missing valid "role" field`);
      }
      if (msg.content !== undefined && msg.content !== null && typeof msg.content !== 'string') {
        // Content can be undefined for tool call messages
        warnings.push(`Message at index ${i} has non-string content (type: ${typeof msg.content})`);
      }
    }
  }

  // Validate iteration (optional but should be non-negative number)
  if (checkpoint.iteration !== undefined) {
    if (typeof checkpoint.iteration !== 'number' || checkpoint.iteration < 0) {
      warnings.push(`Invalid iteration value: ${checkpoint.iteration}, will use default`);
    }
  }

  // Validate metrics (optional)
  if (checkpoint.metrics !== undefined && checkpoint.metrics !== null) {
    if (typeof checkpoint.metrics !== 'object') {
      warnings.push('Metrics field is not an object, will be ignored');
    }
  }

  // Validate memoryContext (optional)
  if (checkpoint.memoryContext !== undefined && checkpoint.memoryContext !== null) {
    if (!Array.isArray(checkpoint.memoryContext)) {
      warnings.push('memoryContext is not an array, will be ignored');
    }
  }

  // If we have critical errors, fail validation
  if (errors.length > 0) {
    return { valid: false, errors, warnings, sanitized: null };
  }

  // Build sanitized checkpoint
  const messages = (checkpoint.messages as Message[]).filter(
    (msg): msg is Message => msg && typeof msg === 'object' && typeof msg.role === 'string',
  );

  const sanitized = {
    messages,
    iteration:
      typeof checkpoint.iteration === 'number' && checkpoint.iteration >= 0
        ? checkpoint.iteration
        : Math.floor(messages.length / 2),
    metrics:
      typeof checkpoint.metrics === 'object' && checkpoint.metrics !== null
        ? (checkpoint.metrics as Partial<AgentMetrics>)
        : undefined,
    plan: checkpoint.plan as AgentPlan | undefined,
    memoryContext: Array.isArray(checkpoint.memoryContext)
      ? (checkpoint.memoryContext as string[])
      : undefined,
  };

  return { valid: true, errors, warnings, sanitized };
}

// =============================================================================
// STATE LOADING
// =============================================================================

/**
 * Load full state from a checkpoint.
 * Restores messages, iteration, metrics, plan, and memory context.
 * Validates checkpoint data before loading to prevent corrupted state.
 */
export function loadState(
  deps: SessionApiDeps,
  savedState: {
    messages: Message[];
    iteration?: number;
    metrics?: Partial<AgentMetrics>;
    plan?: AgentPlan;
    memoryContext?: string[];
  },
): void {
  // Validate checkpoint data
  const validation = validateCheckpoint(savedState);

  // Log warnings
  for (const warning of validation.warnings) {
    log.warn('Checkpoint validation warning', { warning });
    deps.observability?.logger?.warn('Checkpoint validation warning', { warning });
  }

  // Fail on validation errors
  if (!validation.valid || !validation.sanitized) {
    const errorMsg = `Invalid checkpoint: ${validation.errors.join('; ')}`;
    deps.observability?.logger?.error('Checkpoint validation failed', {
      errors: validation.errors,
    });
    throw new Error(errorMsg);
  }

  // Use sanitized data
  const sanitized = validation.sanitized;

  // Restore messages
  deps.state.messages = [...sanitized.messages];

  // Restore iteration (already validated/defaulted in sanitized)
  deps.state.iteration = sanitized.iteration;

  // Restore metrics (merge with defaults)
  if (sanitized.metrics) {
    deps.state.metrics = {
      totalTokens: sanitized.metrics.totalTokens ?? 0,
      inputTokens: sanitized.metrics.inputTokens ?? 0,
      outputTokens: sanitized.metrics.outputTokens ?? 0,
      estimatedCost: sanitized.metrics.estimatedCost ?? 0,
      llmCalls: sanitized.metrics.llmCalls ?? 0,
      toolCalls: sanitized.metrics.toolCalls ?? 0,
      duration: sanitized.metrics.duration ?? 0,
      reflectionAttempts: sanitized.metrics.reflectionAttempts,
      successCount: sanitized.metrics.successCount ?? 0,
      failureCount: sanitized.metrics.failureCount ?? 0,
      cancelCount: sanitized.metrics.cancelCount ?? 0,
      retryCount: sanitized.metrics.retryCount ?? 0,
    };
  }

  // Restore plan if present
  if (sanitized.plan) {
    deps.state.plan = { ...sanitized.plan };
    // Sync with planning manager if enabled
    if (deps.planning) {
      deps.planning.loadPlan(sanitized.plan);
    }
  }

  // Restore memory context if present
  if (sanitized.memoryContext) {
    deps.state.memoryContext = [...sanitized.memoryContext];
  }

  // Sync to threadManager if enabled
  if (deps.threadManager) {
    const thread = deps.threadManager.getActiveThread();
    thread.messages = [...sanitized.messages];
  }

  deps.observability?.logger?.info('State loaded', {
    messageCount: sanitized.messages.length,
    iteration: deps.state.iteration,
    hasPlan: !!sanitized.plan,
    hasMemoryContext: !!sanitized.memoryContext,
  });
}
