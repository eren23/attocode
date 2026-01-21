/**
 * Lesson 24: Thread Manager
 *
 * Manages conversation threads with support for:
 * - Forking (create branches to explore alternatives)
 * - Merging (combine branches back together)
 * - Rollback (return to earlier state)
 *
 * Inspired by git-like version control for conversations.
 */

import type {
  Thread,
  ThreadState,
  Message,
  ForkOptions,
  MergeOptions,
  MergeStrategy,
  ThreadOperationResult,
  AdvancedPatternEvent,
  AdvancedPatternEventListener,
} from './types.js';
import { DEFAULT_FORK_OPTIONS, DEFAULT_MERGE_OPTIONS } from './types.js';

// =============================================================================
// THREAD MANAGER
// =============================================================================

/**
 * Manages conversation threads with branching capabilities.
 */
export class ThreadManager {
  private threads: Map<string, Thread> = new Map();
  private activeThreadId: string | null = null;
  private threadCounter = 0;
  private messageCounter = 0;
  private eventListeners: Set<AdvancedPatternEventListener> = new Set();

  constructor() {
    // Create default main thread
    this.createThread('main');
  }

  // ===========================================================================
  // THREAD LIFECYCLE
  // ===========================================================================

  /**
   * Create a new thread.
   */
  createThread(name?: string): Thread {
    const id = `thread_${++this.threadCounter}_${Date.now()}`;
    const thread: Thread = {
      id,
      name: name || `Thread ${this.threadCounter}`,
      messages: [],
      state: 'active',
      createdAt: new Date(),
      updatedAt: new Date(),
    };

    this.threads.set(id, thread);

    if (!this.activeThreadId) {
      this.activeThreadId = id;
    }

    this.emit({ type: 'thread.created', thread });
    return thread;
  }

  /**
   * Get a thread by ID.
   */
  getThread(threadId: string): Thread | undefined {
    return this.threads.get(threadId);
  }

  /**
   * Get the currently active thread.
   */
  getActiveThread(): Thread | undefined {
    return this.activeThreadId
      ? this.threads.get(this.activeThreadId)
      : undefined;
  }

  /**
   * Switch to a different thread.
   */
  switchThread(threadId: string): boolean {
    const thread = this.threads.get(threadId);
    if (!thread || thread.state === 'merged' || thread.state === 'abandoned') {
      return false;
    }

    this.activeThreadId = threadId;
    return true;
  }

  /**
   * Get all threads.
   */
  getAllThreads(): Thread[] {
    return Array.from(this.threads.values());
  }

  /**
   * Get threads by state.
   */
  getThreadsByState(state: ThreadState): Thread[] {
    return this.getAllThreads().filter(t => t.state === state);
  }

  /**
   * Update thread state.
   */
  setThreadState(threadId: string, state: ThreadState): boolean {
    const thread = this.threads.get(threadId);
    if (!thread) return false;

    thread.state = state;
    thread.updatedAt = new Date();

    this.emit({ type: 'thread.state_changed', threadId, state });
    return true;
  }

  // ===========================================================================
  // MESSAGE MANAGEMENT
  // ===========================================================================

  /**
   * Add a message to the active thread.
   */
  addMessage(
    role: Message['role'],
    content: string,
    options: {
      toolCalls?: Message['toolCalls'];
      toolCallId?: string;
      metadata?: Record<string, unknown>;
    } = {}
  ): Message {
    const thread = this.getActiveThread();
    if (!thread) {
      throw new Error('No active thread');
    }

    const message: Message = {
      id: `msg_${++this.messageCounter}_${Date.now()}`,
      role,
      content,
      toolCalls: options.toolCalls,
      toolCallId: options.toolCallId,
      timestamp: new Date(),
      metadata: options.metadata,
    };

    thread.messages.push(message);
    thread.updatedAt = new Date();

    return message;
  }

  /**
   * Add a message to a specific thread.
   */
  addMessageToThread(
    threadId: string,
    role: Message['role'],
    content: string,
    options: {
      toolCalls?: Message['toolCalls'];
      toolCallId?: string;
      metadata?: Record<string, unknown>;
    } = {}
  ): Message | null {
    const thread = this.threads.get(threadId);
    if (!thread) return null;

    const message: Message = {
      id: `msg_${++this.messageCounter}_${Date.now()}`,
      role,
      content,
      toolCalls: options.toolCalls,
      toolCallId: options.toolCallId,
      timestamp: new Date(),
      metadata: options.metadata,
    };

    thread.messages.push(message);
    thread.updatedAt = new Date();

    return message;
  }

  /**
   * Get messages from active thread.
   */
  getMessages(): Message[] {
    const thread = this.getActiveThread();
    return thread ? [...thread.messages] : [];
  }

  /**
   * Get messages from a specific thread.
   */
  getThreadMessages(threadId: string): Message[] {
    const thread = this.threads.get(threadId);
    return thread ? [...thread.messages] : [];
  }

  /**
   * Find a message by ID across all threads.
   */
  findMessage(messageId: string): { thread: Thread; message: Message } | null {
    for (const thread of this.threads.values()) {
      const message = thread.messages.find(m => m.id === messageId);
      if (message) {
        return { thread, message };
      }
    }
    return null;
  }

  // ===========================================================================
  // FORKING
  // ===========================================================================

  /**
   * Fork the current thread to explore an alternative.
   */
  fork(options: ForkOptions = {}): Thread {
    const opts = { ...DEFAULT_FORK_OPTIONS, ...options };
    const sourceThread = this.getActiveThread();

    if (!sourceThread) {
      throw new Error('No active thread to fork');
    }

    // Determine fork point
    let forkIndex = sourceThread.messages.length;
    let forkPointId: string | undefined;

    if (opts.fromMessageId) {
      const msgIndex = sourceThread.messages.findIndex(
        m => m.id === opts.fromMessageId
      );
      if (msgIndex === -1) {
        throw new Error(`Message ${opts.fromMessageId} not found in thread`);
      }
      forkIndex = msgIndex + 1;
      forkPointId = opts.fromMessageId;
    } else if (sourceThread.messages.length > 0) {
      forkPointId = sourceThread.messages[sourceThread.messages.length - 1].id;
    }

    // Create the forked thread
    const fork: Thread = {
      id: `thread_${++this.threadCounter}_${Date.now()}`,
      name: opts.name || `Fork of ${sourceThread.name}`,
      parentId: sourceThread.id,
      forkPointId,
      messages: sourceThread.messages.slice(0, forkIndex).map(m => ({ ...m })),
      state: 'active',
      createdAt: new Date(),
      updatedAt: new Date(),
      metadata: opts.copyMetadata
        ? { ...sourceThread.metadata, ...opts.metadata }
        : opts.metadata,
    };

    this.threads.set(fork.id, fork);
    this.activeThreadId = fork.id;

    this.emit({
      type: 'thread.forked',
      parentId: sourceThread.id,
      forkId: fork.id,
    });

    return fork;
  }

  /**
   * Fork from a specific thread (not necessarily active).
   */
  forkFrom(threadId: string, options: ForkOptions = {}): Thread | null {
    const oldActive = this.activeThreadId;
    if (!this.switchThread(threadId)) {
      return null;
    }

    const fork = this.fork(options);

    // Optionally restore previous active thread
    // this.activeThreadId = oldActive;

    return fork;
  }

  // ===========================================================================
  // MERGING
  // ===========================================================================

  /**
   * Merge a branch thread into the main thread.
   */
  merge(
    branchId: string,
    mainId?: string,
    options: MergeOptions = {}
  ): ThreadOperationResult {
    const opts = { ...DEFAULT_MERGE_OPTIONS, ...options };

    const branch = this.threads.get(branchId);
    if (!branch) {
      return { success: false, threadId: branchId, error: 'Branch not found' };
    }

    // Determine main thread
    const targetId = mainId || branch.parentId || this.activeThreadId;
    if (!targetId) {
      return {
        success: false,
        threadId: branchId,
        error: 'No target thread for merge',
      };
    }

    const main = this.threads.get(targetId);
    if (!main) {
      return { success: false, threadId: branchId, error: 'Main thread not found' };
    }

    // Find divergence point
    let divergeIndex = 0;
    if (branch.forkPointId) {
      const forkIdx = main.messages.findIndex(m => m.id === branch.forkPointId);
      if (forkIdx !== -1) {
        divergeIndex = forkIdx + 1;
      }
    }

    // Get the new messages from the branch
    const branchNewMessages = branch.messages.slice(divergeIndex);

    // Apply merge strategy
    switch (opts.strategy) {
      case 'append':
        main.messages.push(...branchNewMessages.map(m => ({ ...m })));
        break;

      case 'interleave':
        const mainNewMessages = main.messages.slice(divergeIndex);
        const merged = this.interleaveMessages(mainNewMessages, branchNewMessages);
        main.messages = [...main.messages.slice(0, divergeIndex), ...merged];
        break;

      case 'replace':
        main.messages = [...main.messages.slice(0, divergeIndex), ...branchNewMessages];
        break;

      case 'summarize':
        const summary = this.summarizeBranch(branch, branchNewMessages);
        main.messages.push(summary);
        break;

      case 'custom':
        if (opts.conflictResolver) {
          const mainNew = main.messages.slice(divergeIndex);
          const resolved = opts.conflictResolver(mainNew, branchNewMessages);
          main.messages = [...main.messages.slice(0, divergeIndex), ...resolved];
        }
        break;
    }

    main.updatedAt = new Date();

    // Update branch state
    if (!opts.keepSource) {
      branch.state = 'merged';
    }

    // Switch to main thread
    this.activeThreadId = main.id;

    this.emit({ type: 'thread.merged', mainId: main.id, branchId: branch.id });

    return {
      success: true,
      threadId: main.id,
      message: `Merged ${branch.name} into ${main.name}`,
    };
  }

  /**
   * Interleave messages by timestamp.
   */
  private interleaveMessages(a: Message[], b: Message[]): Message[] {
    const all = [...a.map(m => ({ ...m })), ...b.map(m => ({ ...m }))];
    return all.sort((x, y) => x.timestamp.getTime() - y.timestamp.getTime());
  }

  /**
   * Create a summary message for a branch.
   */
  private summarizeBranch(branch: Thread, messages: Message[]): Message {
    const userMessages = messages.filter(m => m.role === 'user');
    const assistantMessages = messages.filter(m => m.role === 'assistant');

    const summary = [
      `[Merged from branch: ${branch.name}]`,
      `User messages: ${userMessages.length}`,
      `Assistant messages: ${assistantMessages.length}`,
      '',
      'Key points:',
      ...assistantMessages.slice(-3).map(m =>
        `- ${m.content.substring(0, 100)}${m.content.length > 100 ? '...' : ''}`
      ),
    ].join('\n');

    return {
      id: `msg_${++this.messageCounter}_${Date.now()}`,
      role: 'assistant',
      content: summary,
      timestamp: new Date(),
      metadata: { mergedFrom: branch.id, messageCount: messages.length },
    };
  }

  // ===========================================================================
  // ROLLBACK
  // ===========================================================================

  /**
   * Rollback to a specific message in the current thread.
   */
  rollbackToMessage(messageId: string): ThreadOperationResult {
    const thread = this.getActiveThread();
    if (!thread) {
      return { success: false, threadId: '', error: 'No active thread' };
    }

    const messageIndex = thread.messages.findIndex(m => m.id === messageId);
    if (messageIndex === -1) {
      return {
        success: false,
        threadId: thread.id,
        error: `Message ${messageId} not found`,
      };
    }

    // Keep messages up to and including the target
    thread.messages = thread.messages.slice(0, messageIndex + 1);
    thread.updatedAt = new Date();

    this.emit({
      type: 'thread.rolled_back',
      threadId: thread.id,
      checkpointId: messageId,
    });

    return {
      success: true,
      threadId: thread.id,
      message: `Rolled back to message ${messageId}`,
    };
  }

  /**
   * Rollback to a specific number of messages ago.
   */
  rollbackBy(count: number): ThreadOperationResult {
    const thread = this.getActiveThread();
    if (!thread) {
      return { success: false, threadId: '', error: 'No active thread' };
    }

    if (count <= 0 || count >= thread.messages.length) {
      return {
        success: false,
        threadId: thread.id,
        error: `Invalid rollback count: ${count}`,
      };
    }

    const targetIndex = thread.messages.length - count - 1;
    const targetMessage = thread.messages[targetIndex];

    return this.rollbackToMessage(targetMessage.id);
  }

  /**
   * Rollback thread to its fork point (if it's a forked thread).
   */
  rollbackToForkPoint(): ThreadOperationResult {
    const thread = this.getActiveThread();
    if (!thread) {
      return { success: false, threadId: '', error: 'No active thread' };
    }

    if (!thread.forkPointId) {
      return {
        success: false,
        threadId: thread.id,
        error: 'Thread has no fork point',
      };
    }

    return this.rollbackToMessage(thread.forkPointId);
  }

  // ===========================================================================
  // CLEANUP
  // ===========================================================================

  /**
   * Delete a thread.
   */
  deleteThread(threadId: string): boolean {
    if (threadId === this.activeThreadId) {
      // Find another thread to switch to
      const other = this.getAllThreads().find(
        t => t.id !== threadId && t.state === 'active'
      );
      if (other) {
        this.activeThreadId = other.id;
      } else {
        this.activeThreadId = null;
      }
    }

    return this.threads.delete(threadId);
  }

  /**
   * Archive old threads.
   */
  archiveOldThreads(maxAge: number): number {
    const cutoff = Date.now() - maxAge;
    let archived = 0;

    for (const thread of this.threads.values()) {
      if (
        thread.state !== 'archived' &&
        thread.updatedAt.getTime() < cutoff
      ) {
        thread.state = 'archived';
        archived++;
      }
    }

    return archived;
  }

  /**
   * Clear all threads and start fresh.
   */
  reset(): void {
    this.threads.clear();
    this.activeThreadId = null;
    this.createThread('main');
  }

  // ===========================================================================
  // THREAD INFO
  // ===========================================================================

  /**
   * Get thread tree structure.
   */
  getThreadTree(): ThreadTreeNode {
    const roots = this.getAllThreads().filter(t => !t.parentId);
    if (roots.length === 0) {
      throw new Error('No root thread found');
    }

    const buildNode = (thread: Thread): ThreadTreeNode => {
      const children = this.getAllThreads().filter(t => t.parentId === thread.id);
      return {
        thread,
        children: children.map(buildNode),
      };
    };

    return buildNode(roots[0]);
  }

  /**
   * Get thread ancestry (parent chain).
   */
  getAncestry(threadId: string): Thread[] {
    const ancestry: Thread[] = [];
    let current = this.threads.get(threadId);

    while (current) {
      ancestry.unshift(current);
      current = current.parentId
        ? this.threads.get(current.parentId)
        : undefined;
    }

    return ancestry;
  }

  /**
   * Get thread descendants (children and their children).
   */
  getDescendants(threadId: string): Thread[] {
    const descendants: Thread[] = [];
    const visit = (id: string) => {
      const children = this.getAllThreads().filter(t => t.parentId === id);
      for (const child of children) {
        descendants.push(child);
        visit(child.id);
      }
    };
    visit(threadId);
    return descendants;
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
   * Export all threads to JSON.
   */
  exportThreads(): string {
    const data = {
      activeThreadId: this.activeThreadId,
      threads: Array.from(this.threads.entries()),
    };
    return JSON.stringify(data, null, 2);
  }

  /**
   * Import threads from JSON.
   */
  importThreads(json: string): void {
    const data = JSON.parse(json);
    this.threads.clear();

    for (const [id, thread] of data.threads) {
      // Restore dates
      thread.createdAt = new Date(thread.createdAt);
      thread.updatedAt = new Date(thread.updatedAt);
      for (const msg of thread.messages) {
        msg.timestamp = new Date(msg.timestamp);
      }
      this.threads.set(id, thread);
    }

    this.activeThreadId = data.activeThreadId;
  }
}

/**
 * Thread tree node for visualization.
 */
export interface ThreadTreeNode {
  thread: Thread;
  children: ThreadTreeNode[];
}

// =============================================================================
// FACTORY FUNCTIONS
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
export function createThreadManagerWithHistory(
  messages: Array<{ role: Message['role']; content: string }>
): ThreadManager {
  const manager = new ThreadManager();
  for (const msg of messages) {
    manager.addMessage(msg.role, msg.content);
  }
  return manager;
}
