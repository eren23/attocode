/**
 * Lesson 14: Memory Store
 *
 * Persistence layer for memory entries.
 * Provides in-memory and file-based storage options.
 */

import { writeFile, readFile, mkdir } from 'fs/promises';
import { existsSync } from 'fs';
import { dirname } from 'path';
import type {
  MemoryStore,
  MemoryEntry,
  QueryOptions,
  MemoryEvent,
  MemoryEventListener,
} from './types.js';

// =============================================================================
// IN-MEMORY STORE
// =============================================================================

/**
 * In-memory implementation of MemoryStore.
 * Fast but non-persistent.
 */
export class InMemoryStore implements MemoryStore {
  private memories: Map<string, MemoryEntry> = new Map();
  private listeners: Set<MemoryEventListener> = new Set();

  /**
   * Store a memory entry.
   */
  async store(entry: MemoryEntry): Promise<void> {
    this.memories.set(entry.id, { ...entry });
    this.emit({ type: 'memory.stored', entry });
  }

  /**
   * Get a memory by ID.
   */
  async get(id: string): Promise<MemoryEntry | null> {
    const entry = this.memories.get(id);
    if (entry) {
      // Update access tracking
      entry.lastAccessed = new Date();
      entry.accessCount++;
      this.emit({ type: 'memory.accessed', id });
      return { ...entry };
    }
    return null;
  }

  /**
   * Update a memory entry.
   */
  async update(id: string, updates: Partial<MemoryEntry>): Promise<void> {
    const existing = this.memories.get(id);
    if (existing) {
      Object.assign(existing, updates);
      this.emit({ type: 'memory.updated', id, changes: updates });
    }
  }

  /**
   * Delete a memory.
   */
  async delete(id: string): Promise<void> {
    if (this.memories.delete(id)) {
      this.emit({ type: 'memory.deleted', id });
    }
  }

  /**
   * Query memories with filters.
   */
  async query(options: QueryOptions): Promise<MemoryEntry[]> {
    let results = Array.from(this.memories.values());

    // Apply filters
    if (options.type) {
      results = results.filter((m) => m.type === options.type);
    }

    if (options.tags && options.tags.length > 0) {
      results = results.filter((m) =>
        options.tags!.some((tag) => m.tags.includes(tag))
      );
    }

    if (options.minImportance !== undefined) {
      results = results.filter((m) => m.importance >= options.minImportance!);
    }

    if (options.after) {
      results = results.filter((m) => m.createdAt >= options.after!);
    }

    if (options.before) {
      results = results.filter((m) => m.createdAt <= options.before!);
    }

    // Apply sorting
    if (options.sortBy) {
      const sortKey = options.sortBy;
      const sortOrder = options.sortOrder === 'asc' ? 1 : -1;

      results.sort((a, b) => {
        const aVal = a[sortKey];
        const bVal = b[sortKey];

        if (aVal instanceof Date && bVal instanceof Date) {
          return (aVal.getTime() - bVal.getTime()) * sortOrder;
        }
        if (typeof aVal === 'number' && typeof bVal === 'number') {
          return (aVal - bVal) * sortOrder;
        }
        return 0;
      });
    }

    // Apply pagination
    if (options.offset) {
      results = results.slice(options.offset);
    }

    if (options.limit) {
      results = results.slice(0, options.limit);
    }

    return results.map((m) => ({ ...m }));
  }

  /**
   * Get all memories.
   */
  async getAll(): Promise<MemoryEntry[]> {
    return Array.from(this.memories.values()).map((m) => ({ ...m }));
  }

  /**
   * Clear all memories.
   */
  async clear(): Promise<void> {
    this.memories.clear();
  }

  /**
   * Get memory count.
   */
  async count(): Promise<number> {
    return this.memories.size;
  }

  /**
   * Subscribe to events.
   */
  on(listener: MemoryEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * Emit an event.
   */
  private emit(event: MemoryEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch (err) {
        console.error('Error in memory event listener:', err);
      }
    }
  }
}

// =============================================================================
// FILE-BASED STORE
// =============================================================================

/**
 * File-based implementation of MemoryStore.
 * Persists memories to JSON file.
 */
export class FileStore implements MemoryStore {
  private filePath: string;
  private memories: Map<string, MemoryEntry> = new Map();
  private listeners: Set<MemoryEventListener> = new Set();
  private dirty = false;
  private saveTimer: ReturnType<typeof setTimeout> | null = null;
  private saveDelayMs: number;

  constructor(filePath: string, saveDelayMs = 1000) {
    this.filePath = filePath;
    this.saveDelayMs = saveDelayMs;
  }

  /**
   * Initialize the store (load from file).
   */
  async initialize(): Promise<void> {
    if (existsSync(this.filePath)) {
      try {
        const data = await readFile(this.filePath, 'utf-8');
        const parsed = JSON.parse(data);

        for (const entry of parsed.memories || []) {
          // Reconstruct Date objects
          entry.createdAt = new Date(entry.createdAt);
          entry.lastAccessed = new Date(entry.lastAccessed);
          this.memories.set(entry.id, entry);
        }
      } catch (err) {
        console.error('Failed to load memories from file:', err);
      }
    }
  }

  /**
   * Store a memory entry.
   */
  async store(entry: MemoryEntry): Promise<void> {
    this.memories.set(entry.id, { ...entry });
    this.scheduleSave();
    this.emit({ type: 'memory.stored', entry });
  }

  /**
   * Get a memory by ID.
   */
  async get(id: string): Promise<MemoryEntry | null> {
    const entry = this.memories.get(id);
    if (entry) {
      entry.lastAccessed = new Date();
      entry.accessCount++;
      this.scheduleSave();
      this.emit({ type: 'memory.accessed', id });
      return { ...entry };
    }
    return null;
  }

  /**
   * Update a memory entry.
   */
  async update(id: string, updates: Partial<MemoryEntry>): Promise<void> {
    const existing = this.memories.get(id);
    if (existing) {
      Object.assign(existing, updates);
      this.scheduleSave();
      this.emit({ type: 'memory.updated', id, changes: updates });
    }
  }

  /**
   * Delete a memory.
   */
  async delete(id: string): Promise<void> {
    if (this.memories.delete(id)) {
      this.scheduleSave();
      this.emit({ type: 'memory.deleted', id });
    }
  }

  /**
   * Query memories with filters.
   */
  async query(options: QueryOptions): Promise<MemoryEntry[]> {
    // Reuse in-memory query logic
    const inMemory = new InMemoryStore();
    for (const [id, entry] of this.memories) {
      await inMemory.store(entry);
    }
    return inMemory.query(options);
  }

  /**
   * Get all memories.
   */
  async getAll(): Promise<MemoryEntry[]> {
    return Array.from(this.memories.values()).map((m) => ({ ...m }));
  }

  /**
   * Clear all memories.
   */
  async clear(): Promise<void> {
    this.memories.clear();
    this.scheduleSave();
  }

  /**
   * Get memory count.
   */
  async count(): Promise<number> {
    return this.memories.size;
  }

  /**
   * Subscribe to events.
   */
  on(listener: MemoryEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * Schedule a save operation (debounced).
   */
  private scheduleSave(): void {
    this.dirty = true;

    if (this.saveTimer) {
      clearTimeout(this.saveTimer);
    }

    this.saveTimer = setTimeout(() => {
      this.save();
    }, this.saveDelayMs);
  }

  /**
   * Save memories to file.
   */
  private async save(): Promise<void> {
    if (!this.dirty) return;

    try {
      const dir = dirname(this.filePath);
      if (!existsSync(dir)) {
        await mkdir(dir, { recursive: true });
      }

      const data = {
        version: 1,
        savedAt: new Date().toISOString(),
        memories: Array.from(this.memories.values()),
      };

      await writeFile(this.filePath, JSON.stringify(data, null, 2));
      this.dirty = false;
    } catch (err) {
      console.error('Failed to save memories:', err);
    }
  }

  /**
   * Force immediate save.
   */
  async flush(): Promise<void> {
    if (this.saveTimer) {
      clearTimeout(this.saveTimer);
      this.saveTimer = null;
    }
    await this.save();
  }

  /**
   * Emit an event.
   */
  private emit(event: MemoryEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch (err) {
        console.error('Error in memory event listener:', err);
      }
    }
  }
}

// =============================================================================
// MEMORY ID GENERATOR
// =============================================================================

/**
 * Generate a unique memory ID.
 */
export function generateMemoryId(prefix = 'mem'): string {
  const timestamp = Date.now().toString(36);
  const random = Math.random().toString(36).substring(2, 8);
  return `${prefix}-${timestamp}-${random}`;
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create an in-memory store.
 */
export function createInMemoryStore(): InMemoryStore {
  return new InMemoryStore();
}

/**
 * Create a file-based store.
 */
export async function createFileStore(filePath: string): Promise<FileStore> {
  const store = new FileStore(filePath);
  await store.initialize();
  return store;
}

// =============================================================================
// EXPORTS
// =============================================================================

export const defaultStore = new InMemoryStore();
