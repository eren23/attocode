/**
 * Lesson 25: Session Persistence
 *
 * Saves and loads conversation sessions to/from disk.
 * Uses JSONL format for append-only, crash-safe storage.
 */

import { readFile, writeFile, mkdir, readdir, unlink, stat } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import type { Message, ToolCall } from '../../types.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Session metadata stored in index.
 */
export interface SessionMetadata {
  id: string;
  name?: string;
  workspacePath?: string;
  createdAt: string;
  lastActiveAt: string;
  messageCount: number;
  tokenCount: number;
  summary?: string;
}

/**
 * Entry types that can be stored in a session.
 */
export type SessionEntryType = 'message' | 'tool_call' | 'tool_result' | 'checkpoint' | 'compaction' | 'metadata';

/**
 * A single entry in the session log.
 */
export interface SessionEntry {
  timestamp: string;
  type: SessionEntryType;
  data: unknown;
}

/**
 * Session index file structure.
 */
interface SessionIndex {
  version: number;
  sessions: SessionMetadata[];
}

/**
 * Session store configuration.
 */
export interface SessionStoreConfig {
  /** Base directory for sessions (default: .agent/sessions) */
  baseDir?: string;
  /** Auto-save on each entry (default: true) */
  autoSave?: boolean;
  /** Max sessions to keep (default: 50) */
  maxSessions?: number;
}

/**
 * Session store events.
 */
export type SessionEvent =
  | { type: 'session.created'; sessionId: string }
  | { type: 'session.loaded'; sessionId: string; entryCount: number }
  | { type: 'session.saved'; sessionId: string }
  | { type: 'session.deleted'; sessionId: string }
  | { type: 'entry.appended'; sessionId: string; entryType: SessionEntryType };

export type SessionEventListener = (event: SessionEvent) => void;

// =============================================================================
// SESSION STORE
// =============================================================================

/**
 * Manages session persistence.
 */
export class SessionStore {
  private config: Required<SessionStoreConfig>;
  private currentSessionId: string | null = null;
  private index: SessionIndex = { version: 1, sessions: [] };
  private listeners: SessionEventListener[] = [];
  private writeQueue: Promise<void> = Promise.resolve();

  constructor(config: SessionStoreConfig = {}) {
    this.config = {
      baseDir: config.baseDir || '.agent/sessions',
      autoSave: config.autoSave ?? true,
      maxSessions: config.maxSessions || 50,
    };
  }

  /**
   * Initialize the session store.
   */
  async initialize(): Promise<void> {
    // Ensure directory exists
    if (!existsSync(this.config.baseDir)) {
      await mkdir(this.config.baseDir, { recursive: true });
    }

    // Load index
    await this.loadIndex();
  }

  /**
   * Load the session index.
   */
  private async loadIndex(): Promise<void> {
    const indexPath = join(this.config.baseDir, 'index.json');

    if (existsSync(indexPath)) {
      try {
        const content = await readFile(indexPath, 'utf-8');
        this.index = JSON.parse(content);
      } catch {
        // Corrupted index, start fresh
        this.index = { version: 1, sessions: [] };
      }
    }
  }

  /**
   * Save the session index.
   */
  private async saveIndex(): Promise<void> {
    const indexPath = join(this.config.baseDir, 'index.json');
    await writeFile(indexPath, JSON.stringify(this.index, null, 2));
  }

  /**
   * Create a new session.
   */
  async createSession(name?: string): Promise<string> {
    const id = `session-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
    const now = new Date().toISOString();

    const metadata: SessionMetadata = {
      id,
      name,
      workspacePath: process.cwd(),
      createdAt: now,
      lastActiveAt: now,
      messageCount: 0,
      tokenCount: 0,
    };

    this.index.sessions.unshift(metadata);
    this.currentSessionId = id;

    // Prune old sessions if needed
    await this.pruneOldSessions();

    await this.saveIndex();
    this.emit({ type: 'session.created', sessionId: id });

    return id;
  }

  /**
   * Get the current session ID.
   */
  getCurrentSessionId(): string | null {
    return this.currentSessionId;
  }

  /**
   * Set the current session ID.
   */
  setCurrentSessionId(sessionId: string): void {
    this.currentSessionId = sessionId;
  }

  /**
   * Append an entry to the current session.
   */
  async appendEntry(entry: Omit<SessionEntry, 'timestamp'>): Promise<void> {
    if (!this.currentSessionId) {
      await this.createSession();
    }

    const fullEntry: SessionEntry = {
      ...entry,
      timestamp: new Date().toISOString(),
    };

    // Queue writes to prevent race conditions
    this.writeQueue = this.writeQueue.then(async () => {
      const sessionPath = join(this.config.baseDir, `${this.currentSessionId}.jsonl`);
      await writeFile(sessionPath, JSON.stringify(fullEntry) + '\n', { flag: 'a' });
    });

    await this.writeQueue;

    // Update metadata
    const meta = this.index.sessions.find(s => s.id === this.currentSessionId);
    if (meta) {
      meta.lastActiveAt = fullEntry.timestamp;
      if (entry.type === 'message') {
        meta.messageCount++;
      } else if (entry.type === 'checkpoint') {
        // Update message count from checkpoint data
        const checkpointData = entry.data as { messages?: unknown[] } | undefined;
        if (checkpointData?.messages) {
          meta.messageCount = checkpointData.messages.length;
        }
      }
      if (this.config.autoSave) {
        await this.saveIndex();
      }
    }

    this.emit({ type: 'entry.appended', sessionId: this.currentSessionId!, entryType: entry.type });
  }

  /**
   * Append a message to the current session.
   */
  async appendMessage(message: Message): Promise<void> {
    await this.appendEntry({ type: 'message', data: message });
  }

  /**
   * Append a tool call to the current session.
   */
  async appendToolCall(toolCall: ToolCall): Promise<void> {
    await this.appendEntry({ type: 'tool_call', data: toolCall });
  }

  /**
   * Append a tool result to the current session.
   */
  async appendToolResult(callId: string, result: unknown): Promise<void> {
    await this.appendEntry({ type: 'tool_result', data: { callId, result } });
  }

  /**
   * Append a compaction summary.
   */
  async appendCompaction(summary: string, compactedCount: number): Promise<void> {
    await this.appendEntry({
      type: 'compaction',
      data: { summary, compactedCount, compactedAt: new Date().toISOString() },
    });
  }

  /**
   * Append a checkpoint for session restoration.
   * Checkpoints store the full conversation state at a point in time.
   */
  async appendCheckpoint(checkpoint: {
    id: string;
    label?: string;
    messages: Message[];
    iteration: number;
    metrics?: unknown;
  }): Promise<void> {
    await this.appendEntry({
      type: 'checkpoint',
      data: {
        id: checkpoint.id,
        label: checkpoint.label,
        messages: checkpoint.messages,
        iteration: checkpoint.iteration,
        metrics: checkpoint.metrics,
        createdAt: new Date().toISOString(),
      },
    });
  }

  /**
   * Load a session by ID.
   */
  async loadSession(sessionId: string): Promise<SessionEntry[]> {
    const sessionPath = join(this.config.baseDir, `${sessionId}.jsonl`);

    if (!existsSync(sessionPath)) {
      throw new Error(`Session not found: ${sessionId}`);
    }

    const content = await readFile(sessionPath, 'utf-8');
    const entries: SessionEntry[] = [];

    for (const line of content.split('\n')) {
      if (line.trim()) {
        try {
          entries.push(JSON.parse(line));
        } catch {
          // Skip corrupted lines
        }
      }
    }

    this.currentSessionId = sessionId;
    this.emit({ type: 'session.loaded', sessionId, entryCount: entries.length });

    return entries;
  }

  /**
   * Reconstruct messages from session entries.
   */
  async loadSessionMessages(sessionId: string): Promise<Message[]> {
    const entries = await this.loadSession(sessionId);
    const messages: Message[] = [];

    for (const entry of entries) {
      if (entry.type === 'message') {
        messages.push(entry.data as Message);
      } else if (entry.type === 'compaction') {
        // Insert compaction summary as a system message
        const compaction = entry.data as { summary: string };
        messages.push({
          role: 'system',
          content: `[Previous conversation summary]\n${compaction.summary}`,
        });
      }
    }

    return messages;
  }

  /**
   * Delete a session.
   */
  async deleteSession(sessionId: string): Promise<void> {
    const sessionPath = join(this.config.baseDir, `${sessionId}.jsonl`);

    if (existsSync(sessionPath)) {
      await unlink(sessionPath);
    }

    this.index.sessions = this.index.sessions.filter(s => s.id !== sessionId);
    await this.saveIndex();

    if (this.currentSessionId === sessionId) {
      this.currentSessionId = null;
    }

    this.emit({ type: 'session.deleted', sessionId });
  }

  /**
   * List all sessions.
   */
  listSessions(): SessionMetadata[] {
    return [...this.index.sessions];
  }

  /**
   * Get the most recent session.
   */
  getRecentSession(): SessionMetadata | null {
    return this.index.sessions[0] || null;
  }

  /**
   * Get session metadata by ID.
   */
  getSessionMetadata(sessionId: string): SessionMetadata | undefined {
    return this.index.sessions.find(s => s.id === sessionId);
  }

  /**
   * Update session metadata.
   */
  async updateSessionMetadata(
    sessionId: string,
    updates: Partial<Pick<SessionMetadata, 'name' | 'summary' | 'tokenCount'>>
  ): Promise<void> {
    const meta = this.index.sessions.find(s => s.id === sessionId);
    if (meta) {
      Object.assign(meta, updates);
      await this.saveIndex();
    }
  }

  /**
   * Prune old sessions if over limit.
   */
  private async pruneOldSessions(): Promise<void> {
    while (this.index.sessions.length > this.config.maxSessions) {
      const oldest = this.index.sessions.pop();
      if (oldest) {
        const sessionPath = join(this.config.baseDir, `${oldest.id}.jsonl`);
        if (existsSync(sessionPath)) {
          await unlink(sessionPath);
        }
      }
    }
  }

  /**
   * Subscribe to events.
   */
  on(listener: SessionEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  /**
   * Emit an event.
   */
  private emit(event: SessionEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }

  /**
   * Cleanup - save index on exit.
   */
  async cleanup(): Promise<void> {
    await this.writeQueue;
    await this.saveIndex();
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create and initialize a session store.
 */
export async function createSessionStore(config?: SessionStoreConfig): Promise<SessionStore> {
  const store = new SessionStore(config);
  await store.initialize();
  return store;
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Format session metadata for display.
 */
export function formatSessionList(sessions: SessionMetadata[]): string {
  if (sessions.length === 0) {
    return 'No saved sessions.';
  }

  const lines: string[] = ['Sessions:'];

  for (const session of sessions.slice(0, 10)) {
    const date = new Date(session.lastActiveAt).toLocaleDateString();
    const time = new Date(session.lastActiveAt).toLocaleTimeString();
    const name = session.name || session.id;
    lines.push(`  ${name} - ${session.messageCount} msgs - ${date} ${time}`);
  }

  if (sessions.length > 10) {
    lines.push(`  ... and ${sessions.length - 10} more`);
  }

  return lines.join('\n');
}
