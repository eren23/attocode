/**
 * Trick M: Thread Manager (Lightweight)
 *
 * Simple conversation thread management with fork/rollback.
 * For full features, see Lesson 24.
 *
 * Usage:
 *   const tm = createThreadManager();
 *   tm.addMessage('user', 'Hello');
 *   const branch = tm.fork('experiment');
 *   tm.rollback(2); // Go back 2 messages
 */

import { generateId } from './sortable-id.js';

// =============================================================================
// TYPES
// =============================================================================

export interface Message {
  id: string;
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  timestamp: Date;
  metadata?: Record<string, unknown>;
}

export interface Thread {
  id: string;
  name: string;
  parentId?: string;
  messages: Message[];
  createdAt: Date;
}

// =============================================================================
// THREAD MANAGER
// =============================================================================

export class SimpleThreadManager {
  private threads = new Map<string, Thread>();
  private activeId: string;

  constructor() {
    const main = this.createThread('main');
    this.activeId = main.id;
  }

  /**
   * Create a new thread.
   */
  createThread(name: string, parentId?: string): Thread {
    const thread: Thread = {
      id: generateId('thd'),
      name,
      parentId,
      messages: [],
      createdAt: new Date(),
    };
    this.threads.set(thread.id, thread);
    return thread;
  }

  /**
   * Get the active thread.
   */
  getActive(): Thread {
    return this.threads.get(this.activeId)!;
  }

  /**
   * Switch to a different thread.
   */
  switchTo(threadId: string): boolean {
    if (!this.threads.has(threadId)) return false;
    this.activeId = threadId;
    return true;
  }

  /**
   * Add a message to the active thread.
   */
  addMessage(
    role: Message['role'],
    content: string,
    metadata?: Record<string, unknown>
  ): Message {
    const message: Message = {
      id: generateId('msg'),
      role,
      content,
      timestamp: new Date(),
      metadata,
    };
    this.getActive().messages.push(message);
    return message;
  }

  /**
   * Get messages from active thread.
   */
  getMessages(): Message[] {
    return [...this.getActive().messages];
  }

  /**
   * Fork the active thread.
   */
  fork(name: string, fromIndex?: number): Thread {
    const current = this.getActive();
    const forkPoint = fromIndex ?? current.messages.length;

    const fork = this.createThread(name, current.id);
    fork.messages = current.messages.slice(0, forkPoint).map(m => ({ ...m }));

    this.activeId = fork.id;
    return fork;
  }

  /**
   * Rollback N messages in active thread.
   */
  rollback(count: number): boolean {
    const thread = this.getActive();
    if (count <= 0 || count > thread.messages.length) return false;

    thread.messages = thread.messages.slice(0, -count);
    return true;
  }

  /**
   * Rollback to a specific message ID.
   */
  rollbackTo(messageId: string): boolean {
    const thread = this.getActive();
    const index = thread.messages.findIndex(m => m.id === messageId);
    if (index === -1) return false;

    thread.messages = thread.messages.slice(0, index + 1);
    return true;
  }

  /**
   * Merge a branch into current thread.
   */
  merge(branchId: string, strategy: 'append' | 'replace' = 'append'): boolean {
    const branch = this.threads.get(branchId);
    const current = this.getActive();

    if (!branch || branch.id === current.id) return false;

    // Find common ancestor point
    let divergePoint = 0;
    if (branch.parentId === current.id) {
      // Branch was forked from current
      divergePoint = this.findDivergePoint(current, branch);
    }

    const branchMessages = branch.messages.slice(divergePoint);

    if (strategy === 'append') {
      current.messages.push(...branchMessages.map(m => ({ ...m })));
    } else {
      current.messages = [
        ...current.messages.slice(0, divergePoint),
        ...branchMessages.map(m => ({ ...m })),
      ];
    }

    return true;
  }

  private findDivergePoint(main: Thread, branch: Thread): number {
    // Find where messages start to differ
    const minLen = Math.min(main.messages.length, branch.messages.length);
    for (let i = 0; i < minLen; i++) {
      if (main.messages[i].id !== branch.messages[i].id) {
        return i;
      }
    }
    return minLen;
  }

  /**
   * Get all threads.
   */
  getAllThreads(): Thread[] {
    return Array.from(this.threads.values());
  }

  /**
   * Delete a thread (can't delete active).
   */
  deleteThread(threadId: string): boolean {
    if (threadId === this.activeId) return false;
    return this.threads.delete(threadId);
  }

  /**
   * Clear all messages in active thread.
   */
  clear(): void {
    this.getActive().messages = [];
  }

  /**
   * Reset to single main thread.
   */
  reset(): void {
    this.threads.clear();
    const main = this.createThread('main');
    this.activeId = main.id;
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create a new thread manager.
 */
export function createThreadManager(): SimpleThreadManager {
  return new SimpleThreadManager();
}

/**
 * Create with initial messages.
 */
export function createWithHistory(
  messages: Array<{ role: Message['role']; content: string }>
): SimpleThreadManager {
  const tm = new SimpleThreadManager();
  for (const msg of messages) {
    tm.addMessage(msg.role, msg.content);
  }
  return tm;
}
