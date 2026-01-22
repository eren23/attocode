/**
 * Lesson 25: Thread Manager Integration
 *
 * Integrates thread management and checkpoints (from Lesson 24)
 * into the production agent. Enables conversation forking,
 * rollback, and state recovery.
 */

import type { Message, AgentState, AgentMetrics } from '../types.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Thread represents a conversation branch.
 */
export interface Thread {
  id: string;
  name: string;
  parentId?: string;
  messages: Message[];
  metadata: ThreadMetadata;
  createdAt: Date;
  updatedAt: Date;
}

export interface ThreadMetadata {
  description?: string;
  tags?: string[];
  isMainThread?: boolean;
  forkPoint?: number;
}

/**
 * Checkpoint captures agent state at a point in time.
 */
export interface Checkpoint {
  id: string;
  threadId: string;
  label?: string;
  state: CheckpointState;
  createdAt: Date;
  metadata?: Record<string, unknown>;
}

export interface CheckpointState {
  messages: Message[];
  metrics: AgentMetrics;
  iteration: number;
  custom?: Record<string, unknown>;
}

/**
 * Thread merge strategy.
 */
export type MergeStrategy = 'append' | 'interleave' | 'replace';

/**
 * Thread manager events.
 */
export type ThreadEvent =
  | { type: 'thread.created'; thread: Thread }
  | { type: 'thread.switched'; fromId: string; toId: string }
  | { type: 'thread.forked'; parent: Thread; child: Thread }
  | { type: 'thread.merged'; source: Thread; target: Thread; strategy: MergeStrategy }
  | { type: 'thread.deleted'; threadId: string }
  | { type: 'checkpoint.created'; checkpoint: Checkpoint }
  | { type: 'checkpoint.restored'; checkpoint: Checkpoint }
  | { type: 'checkpoint.deleted'; checkpointId: string }
  | { type: 'rollback'; threadId: string; steps: number };

export type ThreadEventListener = (event: ThreadEvent) => void;

// =============================================================================
// THREAD MANAGER
// =============================================================================

/**
 * ThreadManager handles conversation threading and checkpoints.
 */
export class ThreadManager {
  private threads = new Map<string, Thread>();
  private checkpoints = new Map<string, Checkpoint>();
  private activeThreadId: string;
  private listeners: ThreadEventListener[] = [];
  private idCounter = 0;

  constructor() {
    // Create default main thread
    const mainThread = this.createThread({ name: 'main', isMain: true });
    this.activeThreadId = mainThread.id;
  }

  // -------------------------------------------------------------------------
  // THREAD OPERATIONS
  // -------------------------------------------------------------------------

  /**
   * Create a new thread.
   */
  createThread(options: {
    name: string;
    parentId?: string;
    messages?: Message[];
    isMain?: boolean;
  }): Thread {
    const thread: Thread = {
      id: this.generateId('thread'),
      name: options.name,
      parentId: options.parentId,
      messages: options.messages ? [...options.messages] : [],
      metadata: {
        isMainThread: options.isMain ?? false,
      },
      createdAt: new Date(),
      updatedAt: new Date(),
    };

    this.threads.set(thread.id, thread);
    this.emit({ type: 'thread.created', thread });

    return thread;
  }

  /**
   * Get the active thread.
   */
  getActiveThread(): Thread {
    return this.threads.get(this.activeThreadId)!;
  }

  /**
   * Switch to a different thread.
   */
  switchThread(threadId: string): boolean {
    if (!this.threads.has(threadId)) {
      return false;
    }

    const fromId = this.activeThreadId;
    this.activeThreadId = threadId;
    this.emit({ type: 'thread.switched', fromId, toId: threadId });

    return true;
  }

  /**
   * Fork the current thread at the current point or a specific index.
   */
  fork(options: {
    name: string;
    atIndex?: number;
    description?: string;
  }): Thread {
    const parent = this.getActiveThread();
    const forkIndex = options.atIndex ?? parent.messages.length;

    const forkedMessages = parent.messages.slice(0, forkIndex);

    const child = this.createThread({
      name: options.name,
      parentId: parent.id,
      messages: forkedMessages,
    });

    child.metadata.forkPoint = forkIndex;
    child.metadata.description = options.description;

    // Switch to the new thread
    this.activeThreadId = child.id;

    this.emit({ type: 'thread.forked', parent, child });

    return child;
  }

  /**
   * Merge a thread into another.
   */
  merge(
    sourceId: string,
    targetId: string,
    strategy: MergeStrategy = 'append'
  ): boolean {
    const source = this.threads.get(sourceId);
    const target = this.threads.get(targetId);

    if (!source || !target) {
      return false;
    }

    switch (strategy) {
      case 'append':
        // Append source messages after target
        target.messages.push(...source.messages.map(m => ({ ...m })));
        break;

      case 'interleave':
        // Interleave by timestamp (if available) or alternate
        const merged = this.interleaveMessages(target.messages, source.messages);
        target.messages = merged;
        break;

      case 'replace':
        // Replace target messages with source
        target.messages = source.messages.map(m => ({ ...m }));
        break;
    }

    target.updatedAt = new Date();
    this.emit({ type: 'thread.merged', source, target, strategy });

    return true;
  }

  /**
   * Delete a thread (cannot delete active thread).
   */
  deleteThread(threadId: string): boolean {
    if (threadId === this.activeThreadId) {
      return false;
    }

    const thread = this.threads.get(threadId);
    if (!thread || thread.metadata.isMainThread) {
      return false;
    }

    // Delete associated checkpoints
    for (const [id, cp] of this.checkpoints) {
      if (cp.threadId === threadId) {
        this.checkpoints.delete(id);
      }
    }

    this.threads.delete(threadId);
    this.emit({ type: 'thread.deleted', threadId });

    return true;
  }

  /**
   * Get all threads.
   */
  getAllThreads(): Thread[] {
    return Array.from(this.threads.values());
  }

  // -------------------------------------------------------------------------
  // MESSAGE OPERATIONS
  // -------------------------------------------------------------------------

  /**
   * Add message to active thread.
   */
  addMessage(message: Message): void {
    const thread = this.getActiveThread();
    thread.messages.push(message);
    thread.updatedAt = new Date();
  }

  /**
   * Get messages from active thread.
   */
  getMessages(): Message[] {
    return [...this.getActiveThread().messages];
  }

  /**
   * Rollback N messages in active thread.
   */
  rollback(steps: number): boolean {
    const thread = this.getActiveThread();

    if (steps <= 0 || steps > thread.messages.length) {
      return false;
    }

    thread.messages = thread.messages.slice(0, -steps);
    thread.updatedAt = new Date();

    this.emit({ type: 'rollback', threadId: thread.id, steps });

    return true;
  }

  /**
   * Rollback to a specific message by ID.
   */
  rollbackToMessage(messageIndex: number): boolean {
    const thread = this.getActiveThread();

    if (messageIndex < 0 || messageIndex >= thread.messages.length) {
      return false;
    }

    const steps = thread.messages.length - messageIndex - 1;
    return this.rollback(steps);
  }

  // -------------------------------------------------------------------------
  // CHECKPOINT OPERATIONS
  // -------------------------------------------------------------------------

  /**
   * Create a checkpoint of current state.
   */
  createCheckpoint(options: {
    label?: string;
    agentState?: Partial<AgentState>;
    metadata?: Record<string, unknown>;
  } = {}): Checkpoint {
    const thread = this.getActiveThread();

    const checkpoint: Checkpoint = {
      id: this.generateId('ckpt'),
      threadId: thread.id,
      label: options.label,
      state: {
        messages: thread.messages.map(m => ({ ...m })),
        metrics: options.agentState?.metrics ?? this.emptyMetrics(),
        iteration: options.agentState?.iteration ?? 0,
        custom: options.metadata,
      },
      createdAt: new Date(),
      metadata: options.metadata,
    };

    this.checkpoints.set(checkpoint.id, checkpoint);
    this.emit({ type: 'checkpoint.created', checkpoint });

    return checkpoint;
  }

  /**
   * Restore from a checkpoint.
   */
  restoreCheckpoint(checkpointId: string): CheckpointState | null {
    const checkpoint = this.checkpoints.get(checkpointId);
    if (!checkpoint) {
      return null;
    }

    // Switch to the thread if different
    if (checkpoint.threadId !== this.activeThreadId) {
      this.switchThread(checkpoint.threadId);
    }

    // Restore messages
    const thread = this.getActiveThread();
    thread.messages = checkpoint.state.messages.map(m => ({ ...m }));
    thread.updatedAt = new Date();

    this.emit({ type: 'checkpoint.restored', checkpoint });

    return { ...checkpoint.state };
  }

  /**
   * Get checkpoint by ID.
   */
  getCheckpoint(checkpointId: string): Checkpoint | undefined {
    return this.checkpoints.get(checkpointId);
  }

  /**
   * Get all checkpoints for active thread.
   */
  getThreadCheckpoints(): Checkpoint[] {
    const threadId = this.activeThreadId;
    return Array.from(this.checkpoints.values())
      .filter(cp => cp.threadId === threadId)
      .sort((a, b) => a.createdAt.getTime() - b.createdAt.getTime());
  }

  /**
   * Delete a checkpoint.
   */
  deleteCheckpoint(checkpointId: string): boolean {
    if (!this.checkpoints.has(checkpointId)) {
      return false;
    }

    this.checkpoints.delete(checkpointId);
    this.emit({ type: 'checkpoint.deleted', checkpointId });

    return true;
  }

  // -------------------------------------------------------------------------
  // EVENT HANDLING
  // -------------------------------------------------------------------------

  /**
   * Subscribe to events.
   */
  on(listener: ThreadEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  // -------------------------------------------------------------------------
  // PRIVATE METHODS
  // -------------------------------------------------------------------------

  private emit(event: ThreadEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }

  private generateId(prefix: string): string {
    const timestamp = Date.now().toString(36);
    const counter = (++this.idCounter).toString(36);
    return `${prefix}_${timestamp}${counter}`;
  }

  private interleaveMessages(a: Message[], b: Message[]): Message[] {
    // Simple alternating merge - could be enhanced with timestamp sorting
    const result: Message[] = [];
    const maxLen = Math.max(a.length, b.length);

    for (let i = 0; i < maxLen; i++) {
      if (i < a.length) result.push({ ...a[i] });
      if (i < b.length) result.push({ ...b[i] });
    }

    return result;
  }

  private emptyMetrics(): AgentMetrics {
    return {
      totalTokens: 0,
      inputTokens: 0,
      outputTokens: 0,
      estimatedCost: 0,
      llmCalls: 0,
      toolCalls: 0,
      duration: 0,
    };
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create a thread manager.
 */
export function createThreadManager(): ThreadManager {
  return new ThreadManager();
}

/**
 * Create a thread manager with initial messages.
 */
export function createWithHistory(messages: Message[]): ThreadManager {
  const tm = new ThreadManager();
  const thread = tm.getActiveThread();
  thread.messages.push(...messages);
  return tm;
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Export thread as a shareable format.
 */
export function exportThread(thread: Thread): string {
  const lines: string[] = [
    `# Thread: ${thread.name}`,
    `Created: ${thread.createdAt.toISOString()}`,
    '',
  ];

  for (const msg of thread.messages) {
    lines.push(`## ${msg.role.toUpperCase()}`);
    lines.push(msg.content);
    lines.push('');
  }

  return lines.join('\n');
}

/**
 * Get thread lineage (parent chain).
 */
export function getThreadLineage(
  threads: Map<string, Thread>,
  threadId: string
): Thread[] {
  const lineage: Thread[] = [];
  let current = threads.get(threadId);

  while (current) {
    lineage.unshift(current);
    current = current.parentId ? threads.get(current.parentId) : undefined;
  }

  return lineage;
}
