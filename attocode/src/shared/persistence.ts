/**
 * Unified Persistence Adapters
 *
 * Thin interface over different storage backends (JSON files, SQLite).
 * Provides a common API for save/load/list/delete operations.
 *
 * Existing stores (SQLiteStore, SwarmStateStore) continue unchanged.
 * These adapters are opt-in wrappers for unified access patterns.
 */

import fs from 'node:fs/promises';
import path from 'node:path';
import Database from 'better-sqlite3';

// =============================================================================
// MAP SERIALIZATION (reused from swarm-state-store pattern)
// =============================================================================

/** JSON replacer that serializes Maps as { __type: 'Map', entries: [...] } */
function mapReplacer(_key: string, value: unknown): unknown {
  if (value instanceof Map) {
    return { __type: 'Map', entries: [...value.entries()] };
  }
  return value;
}

/** JSON reviver that deserializes Maps from { __type: 'Map', entries: [...] } */
function mapReviver(_key: string, value: unknown): unknown {
  if (
    value &&
    typeof value === 'object' &&
    (value as Record<string, unknown>).__type === 'Map'
  ) {
    return new Map((value as { entries: [unknown, unknown][] }).entries);
  }
  return value;
}

// =============================================================================
// INTERFACE
// =============================================================================

export interface PersistenceAdapter {
  /** Save data under a key within a namespace */
  save(namespace: string, key: string, data: unknown): Promise<void>;
  /** Load data by namespace + key */
  load(namespace: string, key: string): Promise<unknown | null>;
  /** List all keys in a namespace */
  list(namespace: string): Promise<string[]>;
  /** Delete a key */
  delete(namespace: string, key: string): Promise<boolean>;
  /** Check if a key exists */
  exists(namespace: string, key: string): Promise<boolean>;
}

// =============================================================================
// JSON FILE ADAPTER
// =============================================================================

/**
 * JSON file-based persistence.
 * Each namespace is a directory, each key is a JSON file.
 */
export class JSONFilePersistenceAdapter implements PersistenceAdapter {
  constructor(private baseDir: string) {}

  private keyPath(namespace: string, key: string): string {
    return path.join(this.baseDir, namespace, `${key}.json`);
  }

  private nsDir(namespace: string): string {
    return path.join(this.baseDir, namespace);
  }

  async save(namespace: string, key: string, data: unknown): Promise<void> {
    const filePath = this.keyPath(namespace, key);
    await fs.mkdir(path.dirname(filePath), { recursive: true });
    await fs.writeFile(filePath, JSON.stringify(data, mapReplacer, 2));
  }

  async load(namespace: string, key: string): Promise<unknown | null> {
    try {
      const content = await fs.readFile(this.keyPath(namespace, key), 'utf-8');
      return JSON.parse(content, mapReviver) as unknown;
    } catch {
      return null;
    }
  }

  async list(namespace: string): Promise<string[]> {
    try {
      const entries = await fs.readdir(this.nsDir(namespace));
      return entries
        .filter((e) => e.endsWith('.json'))
        .map((e) => e.slice(0, -5));
    } catch {
      return [];
    }
  }

  async delete(namespace: string, key: string): Promise<boolean> {
    try {
      await fs.unlink(this.keyPath(namespace, key));
      return true;
    } catch {
      return false;
    }
  }

  async exists(namespace: string, key: string): Promise<boolean> {
    try {
      await fs.access(this.keyPath(namespace, key));
      return true;
    } catch {
      return false;
    }
  }
}

// =============================================================================
// SQLITE ADAPTER
// =============================================================================

const CREATE_TABLE_SQL = `
  CREATE TABLE IF NOT EXISTS kv_store (
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    data TEXT NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (namespace, key)
  )
`;

/**
 * SQLite-based persistence.
 * Uses a generic key-value table with namespace partitioning.
 */
export class SQLitePersistenceAdapter implements PersistenceAdapter {
  private db: InstanceType<typeof Database>;

  constructor(dbPath: string) {
    this.db = new Database(dbPath);
    this.db.pragma('journal_mode = WAL');
    this.db.exec(CREATE_TABLE_SQL);
  }

  async save(namespace: string, key: string, data: unknown): Promise<void> {
    this.db
      .prepare(
        `INSERT OR REPLACE INTO kv_store (namespace, key, data, updated_at)
         VALUES (?, ?, ?, ?)`,
      )
      .run(namespace, key, JSON.stringify(data, mapReplacer), Date.now());
  }

  async load(namespace: string, key: string): Promise<unknown | null> {
    const row = this.db
      .prepare(`SELECT data FROM kv_store WHERE namespace = ? AND key = ?`)
      .get(namespace, key) as { data: string } | undefined;
    if (!row) return null;
    return JSON.parse(row.data, mapReviver) as unknown;
  }

  async list(namespace: string): Promise<string[]> {
    const rows = this.db
      .prepare(`SELECT key FROM kv_store WHERE namespace = ? ORDER BY key`)
      .all(namespace) as { key: string }[];
    return rows.map((r) => r.key);
  }

  async delete(namespace: string, key: string): Promise<boolean> {
    const result = this.db
      .prepare(`DELETE FROM kv_store WHERE namespace = ? AND key = ?`)
      .run(namespace, key);
    return result.changes > 0;
  }

  async exists(namespace: string, key: string): Promise<boolean> {
    const row = this.db
      .prepare(
        `SELECT 1 FROM kv_store WHERE namespace = ? AND key = ? LIMIT 1`,
      )
      .get(namespace, key);
    return row !== undefined;
  }

  /** Close the database connection */
  close(): void {
    this.db.close();
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/** Create a persistence adapter of the given type */
export function createPersistenceAdapter(
  type: 'json' | 'sqlite',
  config: { baseDir?: string; dbPath?: string },
): PersistenceAdapter {
  if (type === 'json') {
    if (!config.baseDir) throw new Error('baseDir is required for json adapter');
    return new JSONFilePersistenceAdapter(config.baseDir);
  }
  if (!config.dbPath) throw new Error('dbPath is required for sqlite adapter');
  return new SQLitePersistenceAdapter(config.dbPath);
}
