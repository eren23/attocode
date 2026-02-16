/**
 * Tests for remembered permissions feature.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { createSQLiteStore, SQLiteStore } from '../../src/integrations/persistence/sqlite-store.js';
import { join } from 'node:path';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';

describe('Remembered Permissions', () => {
  let store: SQLiteStore;
  let tempDir: string;

  beforeEach(async () => {
    tempDir = await mkdtemp(join(tmpdir(), 'perm-test-'));
    store = await createSQLiteStore({
      dbPath: join(tempDir, 'test.db'),
    });
  });

  afterEach(async () => {
    store.close();
    await rm(tempDir, { recursive: true, force: true });
  });

  describe('hasRememberedPermissionsFeature', () => {
    it('should return true after migration', () => {
      expect(store.hasRememberedPermissionsFeature()).toBe(true);
    });
  });

  describe('rememberPermission', () => {
    it('should store a permission decision', () => {
      store.rememberPermission('bash', 'always');

      const result = store.getRememberedPermission('bash');
      expect(result).toBeDefined();
      expect(result?.decision).toBe('always');
    });

    it('should store a permission with pattern', () => {
      store.rememberPermission('bash', 'always', 'git status');

      const result = store.getRememberedPermission('bash', 'git status');
      expect(result).toBeDefined();
      expect(result?.decision).toBe('always');
      expect(result?.pattern).toBe('git status');
    });

    it('should replace existing decision', () => {
      store.rememberPermission('bash', 'always', 'rm -rf');
      store.rememberPermission('bash', 'never', 'rm -rf');

      const result = store.getRememberedPermission('bash', 'rm -rf');
      expect(result?.decision).toBe('never');
    });
  });

  describe('getRememberedPermission', () => {
    it('should return undefined for unknown tool', () => {
      const result = store.getRememberedPermission('unknown-tool');
      expect(result).toBeUndefined();
    });

    it('should match tool without pattern', () => {
      store.rememberPermission('write_file', 'always');

      const result = store.getRememberedPermission('write_file');
      expect(result?.decision).toBe('always');
    });
  });

  describe('listRememberedPermissions', () => {
    it('should list all permissions', () => {
      store.rememberPermission('bash', 'always', 'git status');
      store.rememberPermission('bash', 'never', 'rm -rf');
      store.rememberPermission('write_file', 'always');

      const list = store.listRememberedPermissions();
      expect(list.length).toBe(3);
    });

    it('should return empty array when no permissions', () => {
      const list = store.listRememberedPermissions();
      expect(list).toEqual([]);
    });
  });

  describe('forgetPermission', () => {
    it('should remove a permission', () => {
      store.rememberPermission('bash', 'always', 'git status');
      store.forgetPermission('bash', 'git status');

      const result = store.getRememberedPermission('bash', 'git status');
      expect(result).toBeUndefined();
    });
  });

  describe('clearRememberedPermissions', () => {
    it('should clear all permissions for a tool', () => {
      store.rememberPermission('bash', 'always', 'git status');
      store.rememberPermission('bash', 'never', 'rm -rf');
      store.rememberPermission('write_file', 'always');

      store.clearRememberedPermissions('bash');

      const list = store.listRememberedPermissions();
      expect(list.length).toBe(1);
      expect(list[0].toolName).toBe('write_file');
    });

    it('should clear all permissions when no tool specified', () => {
      store.rememberPermission('bash', 'always');
      store.rememberPermission('write_file', 'always');

      store.clearRememberedPermissions();

      const list = store.listRememberedPermissions();
      expect(list).toEqual([]);
    });
  });
});
