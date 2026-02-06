/**
 * Command History Manager
 *
 * Provides persistent command history storage and retrieval.
 * History is stored in a simple line-delimited text file at
 * ~/.local/state/attocode/history
 *
 * Features:
 * - Persistent storage across sessions
 * - Configurable max history size
 * - Deduplication of consecutive commands
 * - History search
 */

import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

// =============================================================================
// TYPES
// =============================================================================

export interface HistoryManagerConfig {
  /** Max number of history entries to keep (default: 1000) */
  maxEntries?: number;
  /** Path to history file (default: ~/.local/state/attocode/history) */
  historyFile?: string;
  /** Whether to deduplicate consecutive identical commands (default: true) */
  deduplicateConsecutive?: boolean;
}

// =============================================================================
// HISTORY MANAGER
// =============================================================================

export class HistoryManager {
  private config: Required<HistoryManagerConfig>;
  private history: string[] = [];
  private loaded = false;

  constructor(config: HistoryManagerConfig = {}) {
    // Default path: ~/.local/state/attocode/history
    const defaultHistoryDir = path.join(os.homedir(), '.local', 'state', 'attocode');
    const defaultHistoryFile = path.join(defaultHistoryDir, 'history');

    this.config = {
      maxEntries: config.maxEntries ?? 1000,
      historyFile: config.historyFile ?? defaultHistoryFile,
      deduplicateConsecutive: config.deduplicateConsecutive ?? true,
    };
  }

  /**
   * Load history from file (lazy loading).
   */
  private ensureLoaded(): void {
    if (this.loaded) return;

    try {
      // Ensure directory exists
      const dir = path.dirname(this.config.historyFile);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }

      // Load history if file exists
      if (fs.existsSync(this.config.historyFile)) {
        const content = fs.readFileSync(this.config.historyFile, 'utf8');
        this.history = content
          .split('\n')
          .filter(line => line.trim().length > 0)
          .slice(-this.config.maxEntries); // Only keep most recent
      }
    } catch {
      // Silently ignore load errors - start with empty history
      this.history = [];
    }

    this.loaded = true;
  }

  /**
   * Get all history entries (oldest first).
   */
  getHistory(): string[] {
    this.ensureLoaded();
    return [...this.history];
  }

  /**
   * Get number of history entries.
   */
  get length(): number {
    this.ensureLoaded();
    return this.history.length;
  }

  /**
   * Get a specific history entry by index.
   * Index 0 is the oldest, index length-1 is the most recent.
   * Negative indices count from the end (-1 is most recent).
   */
  getEntry(index: number): string | undefined {
    this.ensureLoaded();

    // Handle negative indices
    if (index < 0) {
      index = this.history.length + index;
    }

    return this.history[index];
  }

  /**
   * Add a new entry to history.
   * Optionally deduplicates consecutive identical commands.
   */
  addEntry(command: string): void {
    this.ensureLoaded();

    const trimmed = command.trim();
    if (!trimmed) return; // Don't add empty commands

    // Deduplicate consecutive commands if enabled
    if (this.config.deduplicateConsecutive) {
      const lastEntry = this.history[this.history.length - 1];
      if (lastEntry === trimmed) return;
    }

    // Add entry
    this.history.push(trimmed);

    // Trim if over max
    if (this.history.length > this.config.maxEntries) {
      this.history = this.history.slice(-this.config.maxEntries);
    }

    // Save immediately
    this.save();
  }

  /**
   * Search history for entries matching a query.
   * Returns matches in reverse order (most recent first).
   */
  search(query: string): string[] {
    this.ensureLoaded();

    if (!query.trim()) return [];

    const lowerQuery = query.toLowerCase();
    return this.history
      .filter(entry => entry.toLowerCase().includes(lowerQuery))
      .reverse(); // Most recent first
  }

  /**
   * Save history to file.
   */
  save(): void {
    try {
      // Ensure directory exists
      const dir = path.dirname(this.config.historyFile);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }

      // Write history
      fs.writeFileSync(this.config.historyFile, this.history.join('\n') + '\n', 'utf8');
    } catch {
      // Silently ignore save errors
    }
  }

  /**
   * Clear all history.
   */
  clear(): void {
    this.history = [];
    this.save();
  }

  /**
   * Get the path to the history file.
   */
  getHistoryPath(): string {
    return this.config.historyFile;
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create a new history manager.
 */
export function createHistoryManager(config: HistoryManagerConfig = {}): HistoryManager {
  return new HistoryManager(config);
}
