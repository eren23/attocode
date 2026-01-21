/**
 * Filesystem Context Storage
 *
 * Stores conversation context on the filesystem for persistence.
 * Uses JSONL format for message history (append-friendly, easy to tail).
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import type {
  ContextStorage,
  StoredMessage,
  SessionMetadata,
} from './context-manager.js';

// =============================================================================
// FILESYSTEM STORAGE
// =============================================================================

/**
 * Filesystem-based context storage.
 *
 * Directory structure:
 * ```
 * baseDir/
 *   sessions/
 *     session-123/
 *       metadata.json    # Session metadata
 *       history.jsonl    # Message history (one message per line)
 *     session-456/
 *       ...
 * ```
 *
 * @example
 * ```typescript
 * const storage = new FilesystemContextStorage('./.agent-sessions');
 *
 * const contextManager = new ContextManager({
 *   storage,
 *   maxMessages: 50,
 * });
 * ```
 */
export class FilesystemContextStorage implements ContextStorage {
  private sessionsDir: string;

  constructor(baseDir: string = './.agent-sessions') {
    this.sessionsDir = path.join(baseDir, 'sessions');
  }

  /**
   * Ensure storage directories exist.
   */
  async initialize(): Promise<void> {
    await fs.mkdir(this.sessionsDir, { recursive: true });
  }

  // ===========================================================================
  // STORAGE INTERFACE IMPLEMENTATION
  // ===========================================================================

  async saveMessages(sessionId: string, messages: StoredMessage[]): Promise<void> {
    await this.initialize();
    const sessionDir = this.getSessionDir(sessionId);
    await fs.mkdir(sessionDir, { recursive: true });

    const historyPath = path.join(sessionDir, 'history.jsonl');

    // Write as JSONL (one JSON object per line)
    const jsonl = messages
      .map(msg => JSON.stringify(msg))
      .join('\n');

    await fs.writeFile(historyPath, jsonl + '\n', 'utf-8');
  }

  async loadMessages(sessionId: string): Promise<StoredMessage[]> {
    const historyPath = path.join(this.getSessionDir(sessionId), 'history.jsonl');

    try {
      const content = await fs.readFile(historyPath, 'utf-8');
      const lines = content.trim().split('\n').filter(line => line.trim());

      return lines.map(line => JSON.parse(line) as StoredMessage);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
        return [];
      }
      throw error;
    }
  }

  async saveMetadata(sessionId: string, metadata: SessionMetadata): Promise<void> {
    await this.initialize();
    const sessionDir = this.getSessionDir(sessionId);
    await fs.mkdir(sessionDir, { recursive: true });

    const metadataPath = path.join(sessionDir, 'metadata.json');
    await fs.writeFile(metadataPath, JSON.stringify(metadata, null, 2), 'utf-8');
  }

  async loadMetadata(sessionId: string): Promise<SessionMetadata | null> {
    const metadataPath = path.join(this.getSessionDir(sessionId), 'metadata.json');

    try {
      const content = await fs.readFile(metadataPath, 'utf-8');
      return JSON.parse(content) as SessionMetadata;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
        return null;
      }
      throw error;
    }
  }

  async listSessions(): Promise<SessionMetadata[]> {
    await this.initialize();

    try {
      const entries = await fs.readdir(this.sessionsDir, { withFileTypes: true });
      const sessions: SessionMetadata[] = [];

      for (const entry of entries) {
        if (entry.isDirectory()) {
          const metadata = await this.loadMetadata(entry.name);
          if (metadata) {
            sessions.push(metadata);
          }
        }
      }

      // Sort by most recent first
      sessions.sort((a, b) => b.updatedAt - a.updatedAt);
      return sessions;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
        return [];
      }
      throw error;
    }
  }

  async deleteSession(sessionId: string): Promise<void> {
    const sessionDir = this.getSessionDir(sessionId);

    try {
      await fs.rm(sessionDir, { recursive: true, force: true });
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') {
        throw error;
      }
    }
  }

  // ===========================================================================
  // ADDITIONAL METHODS
  // ===========================================================================

  /**
   * Append a single message to history.
   * More efficient than rewriting the entire file.
   */
  async appendMessage(sessionId: string, message: StoredMessage): Promise<void> {
    await this.initialize();
    const sessionDir = this.getSessionDir(sessionId);
    await fs.mkdir(sessionDir, { recursive: true });

    const historyPath = path.join(sessionDir, 'history.jsonl');
    await fs.appendFile(historyPath, JSON.stringify(message) + '\n', 'utf-8');
  }

  /**
   * Get the last N messages (useful for quick context loading).
   */
  async getRecentMessages(
    sessionId: string,
    count: number
  ): Promise<StoredMessage[]> {
    const messages = await this.loadMessages(sessionId);
    return messages.slice(-count);
  }

  /**
   * Get session directory path.
   */
  getSessionDir(sessionId: string): string {
    // Sanitize session ID to prevent directory traversal
    const safeId = sessionId.replace(/[^a-zA-Z0-9_-]/g, '_');
    return path.join(this.sessionsDir, safeId);
  }

  /**
   * Check if a session exists.
   */
  async sessionExists(sessionId: string): Promise<boolean> {
    const metadata = await this.loadMetadata(sessionId);
    return metadata !== null;
  }

  /**
   * Clean up old sessions.
   *
   * @param maxAgeDays - Delete sessions older than this
   * @param keepMinimum - Always keep at least this many sessions
   */
  async cleanup(maxAgeDays: number = 30, keepMinimum: number = 5): Promise<number> {
    const sessions = await this.listSessions();
    const now = Date.now();
    const maxAgeMs = maxAgeDays * 24 * 60 * 60 * 1000;
    let deletedCount = 0;

    // Keep at least keepMinimum sessions
    if (sessions.length <= keepMinimum) {
      return 0;
    }

    for (let i = keepMinimum; i < sessions.length; i++) {
      const session = sessions[i];
      const age = now - session.updatedAt;

      if (age > maxAgeMs) {
        await this.deleteSession(session.id);
        deletedCount++;
      }
    }

    return deletedCount;
  }

  /**
   * Get total storage size for all sessions.
   */
  async getStorageSize(): Promise<{ totalBytes: number; sessionCount: number }> {
    const sessions = await this.listSessions();
    let totalBytes = 0;

    for (const session of sessions) {
      const sessionDir = this.getSessionDir(session.id);
      try {
        const files = await fs.readdir(sessionDir);
        for (const file of files) {
          const stat = await fs.stat(path.join(sessionDir, file));
          totalBytes += stat.size;
        }
      } catch {
        // Ignore errors for individual sessions
      }
    }

    return { totalBytes, sessionCount: sessions.length };
  }
}

// =============================================================================
// IN-MEMORY STORAGE (for testing)
// =============================================================================

/**
 * In-memory context storage for testing.
 */
export class InMemoryContextStorage implements ContextStorage {
  private sessions = new Map<string, {
    messages: StoredMessage[];
    metadata: SessionMetadata;
  }>();

  async saveMessages(sessionId: string, messages: StoredMessage[]): Promise<void> {
    const existing = this.sessions.get(sessionId);
    if (existing) {
      existing.messages = [...messages];
    } else {
      this.sessions.set(sessionId, {
        messages: [...messages],
        metadata: {
          id: sessionId,
          createdAt: Date.now(),
          updatedAt: Date.now(),
          messageCount: messages.length,
          state: {
            filesRead: [],
            filesModified: [],
            commandsExecuted: [],
            currentTask: '',
            metadata: {},
          },
        },
      });
    }
  }

  async loadMessages(sessionId: string): Promise<StoredMessage[]> {
    const session = this.sessions.get(sessionId);
    return session ? [...session.messages] : [];
  }

  async saveMetadata(sessionId: string, metadata: SessionMetadata): Promise<void> {
    const existing = this.sessions.get(sessionId);
    if (existing) {
      existing.metadata = { ...metadata };
    } else {
      this.sessions.set(sessionId, {
        messages: [],
        metadata: { ...metadata },
      });
    }
  }

  async loadMetadata(sessionId: string): Promise<SessionMetadata | null> {
    const session = this.sessions.get(sessionId);
    return session ? { ...session.metadata } : null;
  }

  async listSessions(): Promise<SessionMetadata[]> {
    return Array.from(this.sessions.values())
      .map(s => ({ ...s.metadata }))
      .sort((a, b) => b.updatedAt - a.updatedAt);
  }

  async deleteSession(sessionId: string): Promise<void> {
    this.sessions.delete(sessionId);
  }

  /**
   * Clear all sessions (for testing).
   */
  clear(): void {
    this.sessions.clear();
  }
}
