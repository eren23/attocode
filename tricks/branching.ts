/**
 * Trick H: Conversation Branching
 *
 * Create, navigate, and merge conversation branches.
 * Enables exploring different conversation paths.
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * Message in conversation.
 */
export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  timestamp: Date;
  metadata?: Record<string, unknown>;
}

/**
 * Conversation branch.
 */
export interface Branch {
  id: string;
  name?: string;
  parentId: string | null;
  forkPointId: string | null; // Message ID where branch was created
  createdAt: Date;
  messageIds: string[];
}

/**
 * Merge strategy.
 */
export type MergeStrategy = 'keep-source' | 'keep-target' | 'interleave' | 'combine';

/**
 * Branch info for display.
 */
export interface BranchInfo {
  id: string;
  name?: string;
  messageCount: number;
  createdAt: Date;
  isCurrent: boolean;
  parent?: string;
}

// =============================================================================
// CONVERSATION TREE
// =============================================================================

/**
 * Manages conversation branches.
 */
export class ConversationTree {
  private messages: Map<string, Message> = new Map();
  private branches: Map<string, Branch> = new Map();
  private currentBranchId: string;

  constructor() {
    // Create main branch
    const mainBranch: Branch = {
      id: 'main',
      name: 'main',
      parentId: null,
      forkPointId: null,
      createdAt: new Date(),
      messageIds: [],
    };
    this.branches.set('main', mainBranch);
    this.currentBranchId = 'main';
  }

  /**
   * Add a message to current branch.
   */
  addMessage(role: Message['role'], content: string, metadata?: Record<string, unknown>): Message {
    const message: Message = {
      id: generateId(),
      role,
      content,
      timestamp: new Date(),
      metadata,
    };

    this.messages.set(message.id, message);
    this.getCurrentBranch().messageIds.push(message.id);

    return message;
  }

  /**
   * Fork a new branch from a specific message.
   */
  fork(messageId: string, name?: string): string {
    const currentBranch = this.getCurrentBranch();
    const messageIndex = currentBranch.messageIds.indexOf(messageId);

    if (messageIndex === -1) {
      throw new Error(`Message ${messageId} not found in current branch`);
    }

    // Create new branch
    const newBranch: Branch = {
      id: generateId(),
      name,
      parentId: this.currentBranchId,
      forkPointId: messageId,
      createdAt: new Date(),
      // Copy messages up to and including fork point
      messageIds: currentBranch.messageIds.slice(0, messageIndex + 1),
    };

    this.branches.set(newBranch.id, newBranch);
    this.currentBranchId = newBranch.id;

    return newBranch.id;
  }

  /**
   * Fork from current position (creates branch with all current messages).
   */
  forkFromCurrent(name?: string): string {
    const currentBranch = this.getCurrentBranch();
    const lastMessageId = currentBranch.messageIds[currentBranch.messageIds.length - 1];

    if (!lastMessageId) {
      // Empty branch, create child with no messages
      const newBranch: Branch = {
        id: generateId(),
        name,
        parentId: this.currentBranchId,
        forkPointId: null,
        createdAt: new Date(),
        messageIds: [],
      };
      this.branches.set(newBranch.id, newBranch);
      this.currentBranchId = newBranch.id;
      return newBranch.id;
    }

    return this.fork(lastMessageId, name);
  }

  /**
   * Switch to a different branch.
   */
  checkout(branchId: string): Message[] {
    const branch = this.branches.get(branchId);
    if (!branch) {
      throw new Error(`Branch ${branchId} not found`);
    }

    this.currentBranchId = branchId;
    return this.getMessages();
  }

  /**
   * Merge a branch into current branch.
   */
  merge(sourceBranchId: string, strategy: MergeStrategy = 'keep-source'): void {
    const sourceBranch = this.branches.get(sourceBranchId);
    if (!sourceBranch) {
      throw new Error(`Branch ${sourceBranchId} not found`);
    }

    const targetBranch = this.getCurrentBranch();

    switch (strategy) {
      case 'keep-source':
        // Replace target with source messages after fork point
        this.mergeKeepSource(sourceBranch, targetBranch);
        break;

      case 'keep-target':
        // Keep target messages, ignore source
        // Just delete the source branch
        break;

      case 'interleave':
        // Interleave messages by timestamp
        this.mergeInterleave(sourceBranch, targetBranch);
        break;

      case 'combine':
        // Append source messages after target
        this.mergeCombine(sourceBranch, targetBranch);
        break;
    }

    // Optionally delete source branch
    // this.branches.delete(sourceBranchId);
  }

  /**
   * Get messages for current branch.
   */
  getMessages(): Message[] {
    const branch = this.getCurrentBranch();
    return branch.messageIds
      .map((id) => this.messages.get(id))
      .filter((m): m is Message => m !== undefined);
  }

  /**
   * Get current branch.
   */
  getCurrentBranch(): Branch {
    const branch = this.branches.get(this.currentBranchId);
    if (!branch) {
      throw new Error('Current branch not found');
    }
    return branch;
  }

  /**
   * List all branches.
   */
  listBranches(): BranchInfo[] {
    return Array.from(this.branches.values()).map((branch) => ({
      id: branch.id,
      name: branch.name,
      messageCount: branch.messageIds.length,
      createdAt: branch.createdAt,
      isCurrent: branch.id === this.currentBranchId,
      parent: branch.parentId || undefined,
    }));
  }

  /**
   * Delete a branch.
   */
  deleteBranch(branchId: string): boolean {
    if (branchId === 'main') {
      throw new Error('Cannot delete main branch');
    }

    if (branchId === this.currentBranchId) {
      throw new Error('Cannot delete current branch');
    }

    // Check if any branches depend on this one
    for (const branch of this.branches.values()) {
      if (branch.parentId === branchId) {
        throw new Error(`Cannot delete branch with children`);
      }
    }

    return this.branches.delete(branchId);
  }

  /**
   * Rename a branch.
   */
  renameBranch(branchId: string, name: string): void {
    const branch = this.branches.get(branchId);
    if (!branch) {
      throw new Error(`Branch ${branchId} not found`);
    }
    branch.name = name;
  }

  /**
   * Get branch history (path from root to current).
   */
  getBranchPath(): string[] {
    const path: string[] = [];
    let current: Branch | undefined = this.getCurrentBranch();

    while (current) {
      path.unshift(current.id);
      current = current.parentId ? this.branches.get(current.parentId) : undefined;
    }

    return path;
  }

  /**
   * Compare two branches.
   */
  compareBranches(branchAId: string, branchBId: string): {
    common: Message[];
    onlyA: Message[];
    onlyB: Message[];
  } {
    const branchA = this.branches.get(branchAId);
    const branchB = this.branches.get(branchBId);

    if (!branchA || !branchB) {
      throw new Error('Branch not found');
    }

    const setA = new Set(branchA.messageIds);
    const setB = new Set(branchB.messageIds);

    const common: Message[] = [];
    const onlyA: Message[] = [];
    const onlyB: Message[] = [];

    for (const id of branchA.messageIds) {
      const msg = this.messages.get(id);
      if (msg) {
        if (setB.has(id)) {
          common.push(msg);
        } else {
          onlyA.push(msg);
        }
      }
    }

    for (const id of branchB.messageIds) {
      if (!setA.has(id)) {
        const msg = this.messages.get(id);
        if (msg) {
          onlyB.push(msg);
        }
      }
    }

    return { common, onlyA, onlyB };
  }

  /**
   * Serialize tree to JSON.
   */
  toJSON(): string {
    return JSON.stringify({
      messages: Array.from(this.messages.entries()),
      branches: Array.from(this.branches.entries()),
      currentBranchId: this.currentBranchId,
    });
  }

  /**
   * Load tree from JSON.
   */
  static fromJSON(json: string): ConversationTree {
    const data = JSON.parse(json);
    const tree = new ConversationTree();

    tree.messages = new Map(data.messages);
    tree.branches = new Map(data.branches);
    tree.currentBranchId = data.currentBranchId;

    return tree;
  }

  // ==========================================================================
  // MERGE HELPERS
  // ==========================================================================

  private mergeKeepSource(source: Branch, target: Branch): void {
    // Find common ancestor
    const forkPoint = source.forkPointId;
    if (!forkPoint) {
      // No common point, just append
      target.messageIds.push(
        ...source.messageIds.filter((id) => !target.messageIds.includes(id))
      );
      return;
    }

    const forkIndex = target.messageIds.indexOf(forkPoint);
    if (forkIndex === -1) return;

    // Replace messages after fork point with source messages
    const sourceAfterFork = source.messageIds.slice(
      source.messageIds.indexOf(forkPoint) + 1
    );
    target.messageIds = [...target.messageIds.slice(0, forkIndex + 1), ...sourceAfterFork];
  }

  private mergeInterleave(source: Branch, target: Branch): void {
    // Get messages unique to source
    const targetSet = new Set(target.messageIds);
    const uniqueSource = source.messageIds.filter((id) => !targetSet.has(id));

    // Add to target and sort by timestamp
    target.messageIds.push(...uniqueSource);
    target.messageIds.sort((a, b) => {
      const msgA = this.messages.get(a);
      const msgB = this.messages.get(b);
      if (!msgA || !msgB) return 0;
      return msgA.timestamp.getTime() - msgB.timestamp.getTime();
    });
  }

  private mergeCombine(source: Branch, target: Branch): void {
    // Append source messages that aren't in target
    const targetSet = new Set(target.messageIds);
    for (const id of source.messageIds) {
      if (!targetSet.has(id)) {
        target.messageIds.push(id);
      }
    }
  }
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Generate unique ID.
 */
function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

/**
 * Create a conversation tree.
 */
export function createConversationTree(): ConversationTree {
  return new ConversationTree();
}

// Usage:
// const tree = createConversationTree();
//
// // Add messages
// tree.addMessage('user', 'Hello');
// tree.addMessage('assistant', 'Hi there!');
// const msg = tree.addMessage('user', 'Tell me a joke');
//
// // Fork to try a different response
// const branchId = tree.fork(msg.id, 'alternative');
// tree.addMessage('assistant', 'Why did the chicken cross the road?');
//
// // Switch back to main
// tree.checkout('main');
// tree.addMessage('assistant', 'What kind of joke would you like?');
//
// // Compare branches
// const diff = tree.compareBranches('main', branchId);
// console.log('Unique to alternative:', diff.onlyB);
