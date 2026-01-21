/**
 * Lesson 24: Checkpoint Store
 *
 * Manages state snapshots for agent recovery and rollback.
 * Checkpoints capture the full agent state at a point in time,
 * enabling:
 * - Recovery from failures
 * - Exploration with safe rollback points
 * - Session persistence
 */

import type {
  Checkpoint,
  SerializedState,
  CheckpointOptions,
  RestoreOptions,
  Thread,
  Message,
  AdvancedPatternEvent,
  AdvancedPatternEventListener,
} from './types.js';
import { DEFAULT_CHECKPOINT_OPTIONS } from './types.js';
import { ThreadManager } from './thread-manager.js';

// =============================================================================
// CHECKPOINT STORE
// =============================================================================

/**
 * Stores and manages agent checkpoints.
 */
export class CheckpointStore {
  private checkpoints: Map<string, Checkpoint> = new Map();
  private checkpointCounter = 0;
  private eventListeners: Set<AdvancedPatternEventListener> = new Set();

  // Reference to thread manager for automatic checkpointing
  private threadManager?: ThreadManager;

  constructor(threadManager?: ThreadManager) {
    this.threadManager = threadManager;
  }

  // ===========================================================================
  // CHECKPOINT CREATION
  // ===========================================================================

  /**
   * Create a checkpoint from the current thread state.
   */
  createCheckpoint(
    thread: Thread,
    options: CheckpointOptions = {}
  ): Checkpoint {
    const opts = { ...DEFAULT_CHECKPOINT_OPTIONS, ...options };

    const lastMessage = thread.messages[thread.messages.length - 1];
    if (!lastMessage) {
      throw new Error('Cannot checkpoint empty thread');
    }

    const checkpoint: Checkpoint = {
      id: `ckpt_${++this.checkpointCounter}_${Date.now()}`,
      label: opts.label,
      threadId: thread.id,
      messageId: lastMessage.id,
      messageIndex: thread.messages.length - 1,
      state: this.serializeState(thread, opts),
      createdAt: new Date(),
      metadata: opts.metadata,
    };

    this.checkpoints.set(checkpoint.id, checkpoint);
    this.emit({ type: 'checkpoint.created', checkpoint });

    return checkpoint;
  }

  /**
   * Create a checkpoint at a specific message.
   */
  createCheckpointAt(
    thread: Thread,
    messageId: string,
    options: CheckpointOptions = {}
  ): Checkpoint | null {
    const messageIndex = thread.messages.findIndex(m => m.id === messageId);
    if (messageIndex === -1) {
      return null;
    }

    const opts = { ...DEFAULT_CHECKPOINT_OPTIONS, ...options };

    // Create a partial thread up to this message
    const partialThread: Thread = {
      ...thread,
      messages: thread.messages.slice(0, messageIndex + 1),
    };

    const checkpoint: Checkpoint = {
      id: `ckpt_${++this.checkpointCounter}_${Date.now()}`,
      label: opts.label,
      threadId: thread.id,
      messageId,
      messageIndex,
      state: this.serializeState(partialThread, opts),
      createdAt: new Date(),
      metadata: opts.metadata,
    };

    this.checkpoints.set(checkpoint.id, checkpoint);
    this.emit({ type: 'checkpoint.created', checkpoint });

    return checkpoint;
  }

  /**
   * Create a labeled checkpoint (shorthand).
   */
  label(thread: Thread, label: string): Checkpoint {
    return this.createCheckpoint(thread, { label });
  }

  // ===========================================================================
  // STATE SERIALIZATION
  // ===========================================================================

  /**
   * Serialize thread state for checkpoint.
   */
  private serializeState(
    thread: Thread,
    options: CheckpointOptions
  ): SerializedState {
    const state: SerializedState = {
      messages: thread.messages.map(m => ({ ...m })),
    };

    if (options.includeFullState) {
      // Include additional state if available
      // These would be populated by the agent when creating checkpoints
      state.memory = undefined;
      state.plan = undefined;
      state.tools = undefined;
    }

    if (options.customState) {
      state.custom = { ...options.customState };
    }

    return state;
  }

  /**
   * Create checkpoint with full agent state.
   */
  createFullCheckpoint(
    thread: Thread,
    agentState: {
      memory?: unknown;
      plan?: unknown;
      tools?: unknown;
      custom?: Record<string, unknown>;
    },
    options: CheckpointOptions = {}
  ): Checkpoint {
    const checkpoint = this.createCheckpoint(thread, options);

    // Enhance state with agent data
    checkpoint.state.memory = agentState.memory;
    checkpoint.state.plan = agentState.plan;
    checkpoint.state.tools = agentState.tools;
    if (agentState.custom) {
      checkpoint.state.custom = {
        ...checkpoint.state.custom,
        ...agentState.custom,
      };
    }

    return checkpoint;
  }

  // ===========================================================================
  // CHECKPOINT RETRIEVAL
  // ===========================================================================

  /**
   * Get a checkpoint by ID.
   */
  getCheckpoint(checkpointId: string): Checkpoint | undefined {
    return this.checkpoints.get(checkpointId);
  }

  /**
   * Get all checkpoints for a thread.
   */
  getThreadCheckpoints(threadId: string): Checkpoint[] {
    return Array.from(this.checkpoints.values())
      .filter(c => c.threadId === threadId)
      .sort((a, b) => a.createdAt.getTime() - b.createdAt.getTime());
  }

  /**
   * Get the latest checkpoint for a thread.
   */
  getLatestCheckpoint(threadId: string): Checkpoint | undefined {
    const checkpoints = this.getThreadCheckpoints(threadId);
    return checkpoints[checkpoints.length - 1];
  }

  /**
   * Get checkpoint by label.
   */
  getByLabel(label: string, threadId?: string): Checkpoint | undefined {
    for (const checkpoint of this.checkpoints.values()) {
      if (checkpoint.label === label) {
        if (!threadId || checkpoint.threadId === threadId) {
          return checkpoint;
        }
      }
    }
    return undefined;
  }

  /**
   * Get all checkpoints.
   */
  getAllCheckpoints(): Checkpoint[] {
    return Array.from(this.checkpoints.values());
  }

  /**
   * Find checkpoints by criteria.
   */
  findCheckpoints(criteria: {
    threadId?: string;
    label?: string;
    since?: Date;
    until?: Date;
  }): Checkpoint[] {
    return Array.from(this.checkpoints.values()).filter(c => {
      if (criteria.threadId && c.threadId !== criteria.threadId) return false;
      if (criteria.label && c.label !== criteria.label) return false;
      if (criteria.since && c.createdAt < criteria.since) return false;
      if (criteria.until && c.createdAt > criteria.until) return false;
      return true;
    });
  }

  // ===========================================================================
  // RESTORATION
  // ===========================================================================

  /**
   * Restore a thread from a checkpoint.
   */
  restore(
    checkpointId: string,
    threadManager: ThreadManager,
    options: RestoreOptions = {}
  ): Thread | null {
    const checkpoint = this.checkpoints.get(checkpointId);
    if (!checkpoint) {
      return null;
    }

    if (options.createNewThread) {
      // Create a new thread with the checkpoint state
      const newThread = threadManager.createThread(
        `Restored from ${checkpoint.label || checkpoint.id}`
      );

      // Copy messages to the new thread
      for (const msg of checkpoint.state.messages) {
        threadManager.addMessageToThread(
          newThread.id,
          msg.role,
          msg.content,
          {
            toolCalls: msg.toolCalls,
            toolCallId: msg.toolCallId,
            metadata: msg.metadata,
          }
        );
      }

      this.emit({
        type: 'checkpoint.restored',
        checkpointId,
        threadId: newThread.id,
      });

      return newThread;
    } else {
      // Restore to existing thread
      const thread = threadManager.getThread(checkpoint.threadId);
      if (!thread) {
        return null;
      }

      // Rollback to the checkpoint message
      const result = threadManager.switchThread(thread.id);
      if (!result) {
        return null;
      }

      // Truncate to checkpoint point
      thread.messages = checkpoint.state.messages.map(m => ({ ...m }));
      thread.updatedAt = new Date();

      this.emit({
        type: 'checkpoint.restored',
        checkpointId,
        threadId: thread.id,
      });

      return thread;
    }
  }

  /**
   * Get the restoration data without applying it.
   */
  getRestoreData(checkpointId: string): SerializedState | null {
    const checkpoint = this.checkpoints.get(checkpointId);
    return checkpoint ? { ...checkpoint.state } : null;
  }

  // ===========================================================================
  // CHECKPOINT MANAGEMENT
  // ===========================================================================

  /**
   * Delete a checkpoint.
   */
  deleteCheckpoint(checkpointId: string): boolean {
    const deleted = this.checkpoints.delete(checkpointId);
    if (deleted) {
      this.emit({ type: 'checkpoint.deleted', checkpointId });
    }
    return deleted;
  }

  /**
   * Delete all checkpoints for a thread.
   */
  deleteThreadCheckpoints(threadId: string): number {
    let deleted = 0;
    for (const [id, checkpoint] of this.checkpoints) {
      if (checkpoint.threadId === threadId) {
        this.checkpoints.delete(id);
        deleted++;
      }
    }
    return deleted;
  }

  /**
   * Keep only the N most recent checkpoints per thread.
   */
  pruneOldCheckpoints(keepPerThread: number): number {
    const byThread = new Map<string, Checkpoint[]>();

    // Group by thread
    for (const checkpoint of this.checkpoints.values()) {
      const list = byThread.get(checkpoint.threadId) || [];
      list.push(checkpoint);
      byThread.set(checkpoint.threadId, list);
    }

    let pruned = 0;

    // Prune each thread
    for (const [threadId, checkpoints] of byThread) {
      // Sort by creation time (newest first)
      checkpoints.sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime());

      // Delete old ones
      for (let i = keepPerThread; i < checkpoints.length; i++) {
        this.checkpoints.delete(checkpoints[i].id);
        pruned++;
      }
    }

    return pruned;
  }

  /**
   * Delete checkpoints older than a certain age.
   */
  deleteOlderThan(maxAge: number): number {
    const cutoff = Date.now() - maxAge;
    let deleted = 0;

    for (const [id, checkpoint] of this.checkpoints) {
      if (checkpoint.createdAt.getTime() < cutoff) {
        this.checkpoints.delete(id);
        deleted++;
      }
    }

    return deleted;
  }

  /**
   * Clear all checkpoints.
   */
  clear(): void {
    this.checkpoints.clear();
  }

  // ===========================================================================
  // AUTO-CHECKPOINTING
  // ===========================================================================

  /**
   * Enable auto-checkpointing on the thread manager.
   */
  enableAutoCheckpoint(
    threadManager: ThreadManager,
    options: {
      /** Checkpoint every N messages */
      interval?: number;
      /** Maximum checkpoints per thread */
      maxPerThread?: number;
      /** Auto-label format */
      labelFormat?: (index: number) => string;
    } = {}
  ): () => void {
    const interval = options.interval || 5;
    const maxPerThread = options.maxPerThread || 10;
    const labelFormat = options.labelFormat || ((i: number) => `auto_${i}`);

    let messageCount = 0;
    let checkpointCount = 0;

    const unsubscribe = threadManager.subscribe(event => {
      if (event.type === 'thread.created') {
        // Reset counter for new threads
        messageCount = 0;
      }
    });

    // Store the thread manager reference
    this.threadManager = threadManager;

    // Return cleanup function
    return () => {
      unsubscribe();
      this.threadManager = undefined;
    };
  }

  /**
   * Manually trigger auto-checkpoint check.
   */
  checkAutoCheckpoint(thread: Thread, interval: number): boolean {
    if (thread.messages.length % interval === 0 && thread.messages.length > 0) {
      this.createCheckpoint(thread, {
        label: `auto_${thread.messages.length}`,
      });
      return true;
    }
    return false;
  }

  // ===========================================================================
  // EVENTS
  // ===========================================================================

  /**
   * Subscribe to events.
   */
  subscribe(listener: AdvancedPatternEventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  /**
   * Emit an event.
   */
  private emit(event: AdvancedPatternEvent): void {
    for (const listener of this.eventListeners) {
      try {
        listener(event);
      } catch (error) {
        console.error('Event listener error:', error);
      }
    }
  }

  // ===========================================================================
  // SERIALIZATION
  // ===========================================================================

  /**
   * Export all checkpoints to JSON.
   */
  exportCheckpoints(): string {
    return JSON.stringify(
      Array.from(this.checkpoints.values()),
      null,
      2
    );
  }

  /**
   * Import checkpoints from JSON.
   */
  importCheckpoints(json: string): number {
    const checkpoints = JSON.parse(json) as Checkpoint[];
    let imported = 0;

    for (const checkpoint of checkpoints) {
      // Restore dates
      checkpoint.createdAt = new Date(checkpoint.createdAt);
      for (const msg of checkpoint.state.messages) {
        msg.timestamp = new Date(msg.timestamp);
      }

      this.checkpoints.set(checkpoint.id, checkpoint);
      imported++;
    }

    return imported;
  }

  // ===========================================================================
  // STATISTICS
  // ===========================================================================

  /**
   * Get checkpoint statistics.
   */
  getStats(): CheckpointStats {
    const checkpoints = Array.from(this.checkpoints.values());
    const byThread = new Map<string, number>();

    for (const c of checkpoints) {
      byThread.set(c.threadId, (byThread.get(c.threadId) || 0) + 1);
    }

    let totalMessages = 0;
    for (const c of checkpoints) {
      totalMessages += c.state.messages.length;
    }

    return {
      totalCheckpoints: checkpoints.length,
      checkpointsByThread: Object.fromEntries(byThread),
      averageMessagesPerCheckpoint:
        checkpoints.length > 0 ? totalMessages / checkpoints.length : 0,
      oldestCheckpoint: checkpoints.length > 0
        ? checkpoints.reduce((a, b) =>
            a.createdAt < b.createdAt ? a : b
          ).createdAt
        : undefined,
      newestCheckpoint: checkpoints.length > 0
        ? checkpoints.reduce((a, b) =>
            a.createdAt > b.createdAt ? a : b
          ).createdAt
        : undefined,
    };
  }
}

/**
 * Checkpoint statistics.
 */
export interface CheckpointStats {
  totalCheckpoints: number;
  checkpointsByThread: Record<string, number>;
  averageMessagesPerCheckpoint: number;
  oldestCheckpoint?: Date;
  newestCheckpoint?: Date;
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a checkpoint store.
 */
export function createCheckpointStore(
  threadManager?: ThreadManager
): CheckpointStore {
  return new CheckpointStore(threadManager);
}

/**
 * Create a checkpoint store with auto-checkpointing enabled.
 */
export function createAutoCheckpointStore(
  threadManager: ThreadManager,
  interval: number = 5
): { store: CheckpointStore; cleanup: () => void } {
  const store = new CheckpointStore(threadManager);
  const cleanup = store.enableAutoCheckpoint(threadManager, { interval });
  return { store, cleanup };
}
