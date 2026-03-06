/**
 * Tests for Unified Persistence Adapters
 *
 * Tests both JSONFilePersistenceAdapter and SQLitePersistenceAdapter
 * against the PersistenceAdapter interface.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {
  JSONFilePersistenceAdapter,
  SQLitePersistenceAdapter,
  createPersistenceAdapter,
} from '../../src/shared/persistence.js';

// =============================================================================
// JSON FILE ADAPTER
// =============================================================================

describe('JSONFilePersistenceAdapter', () => {
  let tmpDir: string;
  let adapter: JSONFilePersistenceAdapter;

  beforeEach(async () => {
    tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'persist-json-'));
    adapter = new JSONFilePersistenceAdapter(tmpDir);
  });

  afterEach(async () => {
    await fs.rm(tmpDir, { recursive: true, force: true });
  });

  it('save and load roundtrip', async () => {
    await adapter.save('ns1', 'key1', { hello: 'world', count: 42 });
    const loaded = await adapter.load('ns1', 'key1');
    expect(loaded).toEqual({ hello: 'world', count: 42 });
  });

  it('load returns null for nonexistent key', async () => {
    const result = await adapter.load('ns1', 'nonexistent');
    expect(result).toBeNull();
  });

  it('list returns keys in namespace', async () => {
    await adapter.save('ns1', 'alpha', 1);
    await adapter.save('ns1', 'beta', 2);
    await adapter.save('ns2', 'gamma', 3);

    const keys = await adapter.list('ns1');
    expect(keys.sort()).toEqual(['alpha', 'beta']);
  });

  it('list returns empty for nonexistent namespace', async () => {
    const keys = await adapter.list('nonexistent');
    expect(keys).toEqual([]);
  });

  it('delete removes key', async () => {
    await adapter.save('ns1', 'key1', 'data');
    const deleted = await adapter.delete('ns1', 'key1');
    expect(deleted).toBe(true);
    const loaded = await adapter.load('ns1', 'key1');
    expect(loaded).toBeNull();
  });

  it('delete returns false for nonexistent key', async () => {
    const deleted = await adapter.delete('ns1', 'nonexistent');
    expect(deleted).toBe(false);
  });

  it('exists returns true for existing key', async () => {
    await adapter.save('ns1', 'key1', 'data');
    expect(await adapter.exists('ns1', 'key1')).toBe(true);
  });

  it('exists returns false for nonexistent key', async () => {
    expect(await adapter.exists('ns1', 'nonexistent')).toBe(false);
  });

  it('save overwrites existing key', async () => {
    await adapter.save('ns1', 'key1', 'old');
    await adapter.save('ns1', 'key1', 'new');
    const loaded = await adapter.load('ns1', 'key1');
    expect(loaded).toBe('new');
  });

  it('roundtrips Maps via mapReplacer/mapReviver', async () => {
    const data = {
      name: 'test',
      lookup: new Map([
        ['a', 1],
        ['b', 2],
      ]),
    };
    await adapter.save('ns1', 'with-map', data);
    const loaded = (await adapter.load('ns1', 'with-map')) as typeof data;
    expect(loaded.lookup).toBeInstanceOf(Map);
    expect(loaded.lookup.get('a')).toBe(1);
    expect(loaded.lookup.get('b')).toBe(2);
  });
});

// =============================================================================
// SQLITE ADAPTER
// =============================================================================

describe('SQLitePersistenceAdapter', () => {
  let adapter: SQLitePersistenceAdapter;

  beforeEach(() => {
    adapter = new SQLitePersistenceAdapter(':memory:');
  });

  afterEach(() => {
    adapter.close();
  });

  it('save and load roundtrip', async () => {
    await adapter.save('ns1', 'key1', { hello: 'world', count: 42 });
    const loaded = await adapter.load('ns1', 'key1');
    expect(loaded).toEqual({ hello: 'world', count: 42 });
  });

  it('load returns null for nonexistent key', async () => {
    const result = await adapter.load('ns1', 'nonexistent');
    expect(result).toBeNull();
  });

  it('list returns keys in namespace ordered', async () => {
    await adapter.save('ns1', 'beta', 2);
    await adapter.save('ns1', 'alpha', 1);
    await adapter.save('ns2', 'gamma', 3);

    const keys = await adapter.list('ns1');
    expect(keys).toEqual(['alpha', 'beta']);
  });

  it('list returns empty for nonexistent namespace', async () => {
    const keys = await adapter.list('nonexistent');
    expect(keys).toEqual([]);
  });

  it('delete removes key', async () => {
    await adapter.save('ns1', 'key1', 'data');
    const deleted = await adapter.delete('ns1', 'key1');
    expect(deleted).toBe(true);
    const loaded = await adapter.load('ns1', 'key1');
    expect(loaded).toBeNull();
  });

  it('delete returns false for nonexistent key', async () => {
    const deleted = await adapter.delete('ns1', 'nonexistent');
    expect(deleted).toBe(false);
  });

  it('exists returns true for existing key', async () => {
    await adapter.save('ns1', 'key1', 'data');
    expect(await adapter.exists('ns1', 'key1')).toBe(true);
  });

  it('exists returns false for nonexistent key', async () => {
    expect(await adapter.exists('ns1', 'nonexistent')).toBe(false);
  });

  it('save overwrites existing key', async () => {
    await adapter.save('ns1', 'key1', 'old');
    await adapter.save('ns1', 'key1', 'new');
    const loaded = await adapter.load('ns1', 'key1');
    expect(loaded).toBe('new');
  });

  it('roundtrips Maps via mapReplacer/mapReviver', async () => {
    const data = {
      name: 'test',
      lookup: new Map([
        ['a', 1],
        ['b', 2],
      ]),
    };
    await adapter.save('ns1', 'with-map', data);
    const loaded = (await adapter.load('ns1', 'with-map')) as typeof data;
    expect(loaded.lookup).toBeInstanceOf(Map);
    expect(loaded.lookup.get('a')).toBe(1);
    expect(loaded.lookup.get('b')).toBe(2);
  });
});

// =============================================================================
// FACTORY
// =============================================================================

describe('createPersistenceAdapter', () => {
  it('creates JSON adapter', async () => {
    const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'persist-factory-'));
    try {
      const adapter = createPersistenceAdapter('json', { baseDir: tmpDir });
      expect(adapter).toBeInstanceOf(JSONFilePersistenceAdapter);
    } finally {
      await fs.rm(tmpDir, { recursive: true, force: true });
    }
  });

  it('creates SQLite adapter', () => {
    const adapter = createPersistenceAdapter('sqlite', { dbPath: ':memory:' });
    expect(adapter).toBeInstanceOf(SQLitePersistenceAdapter);
    (adapter as SQLitePersistenceAdapter).close();
  });

  it('throws for JSON without baseDir', () => {
    expect(() => createPersistenceAdapter('json', {})).toThrow('baseDir');
  });

  it('throws for SQLite without dbPath', () => {
    expect(() => createPersistenceAdapter('sqlite', {})).toThrow('dbPath');
  });
});
