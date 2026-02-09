/**
 * Tests for basePath propagation through tool wrappers.
 *
 * Verifies that createStandardRegistry with basePath correctly:
 * - Resolves relative paths against basePath for file tools
 * - Sets default cwd for bash tool
 * - Leaves absolute paths untouched
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { createStandardRegistry } from '../../src/tools/standard.js';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';

describe('createStandardRegistry with basePath', () => {
  let testDir: string;

  beforeEach(async () => {
    testDir = mkdtempSync(path.join(tmpdir(), 'attocode-test-'));
    // Create a test file
    await fs.writeFile(path.join(testDir, 'hello.txt'), 'Hello, World!');
  });

  afterEach(async () => {
    await fs.rm(testDir, { recursive: true, force: true });
  });

  describe('without basePath (default behavior)', () => {
    it('creates a registry with standard tools', () => {
      const registry = createStandardRegistry('yolo');
      expect(registry.has('bash')).toBe(true);
      expect(registry.has('read_file')).toBe(true);
      expect(registry.has('write_file')).toBe(true);
      expect(registry.has('edit_file')).toBe(true);
      expect(registry.has('list_files')).toBe(true);
      expect(registry.has('grep')).toBe(true);
      expect(registry.has('glob')).toBe(true);
    });
  });

  describe('with basePath', () => {
    it('resolves relative paths for read_file', async () => {
      const registry = createStandardRegistry('yolo', { basePath: testDir });

      const result = await registry.execute('read_file', { path: 'hello.txt' });
      expect(result.success).toBe(true);
      expect(result.output).toBe('Hello, World!');
    });

    it('leaves absolute paths untouched for read_file', async () => {
      const registry = createStandardRegistry('yolo', { basePath: testDir });
      const absPath = path.join(testDir, 'hello.txt');

      const result = await registry.execute('read_file', { path: absPath });
      expect(result.success).toBe(true);
      expect(result.output).toBe('Hello, World!');
    });

    it('resolves relative paths for write_file', async () => {
      const registry = createStandardRegistry('yolo', { basePath: testDir });

      const result = await registry.execute('write_file', {
        path: 'output.txt',
        content: 'test content',
      });
      expect(result.success).toBe(true);

      // Verify file was written to basePath
      const content = await fs.readFile(path.join(testDir, 'output.txt'), 'utf-8');
      expect(content).toBe('test content');
    });

    it('sets default cwd for bash tool', async () => {
      const registry = createStandardRegistry('yolo', { basePath: testDir });

      const result = await registry.execute('bash', { command: 'pwd' });
      expect(result.success).toBe(true);
      // macOS resolves /var -> /private/var, so compare real paths
      const realTestDir = await fs.realpath(testDir);
      expect(result.output.trim()).toBe(realTestDir);
    });

    it('does not override explicit cwd for bash tool', async () => {
      const registry = createStandardRegistry('yolo', { basePath: testDir });
      const otherDir = mkdtempSync(path.join(tmpdir(), 'attocode-other-'));

      try {
        const result = await registry.execute('bash', { command: 'pwd', cwd: otherDir });
        expect(result.success).toBe(true);
        const realOtherDir = await fs.realpath(otherDir);
        expect(result.output.trim()).toBe(realOtherDir);
      } finally {
        await fs.rm(otherDir, { recursive: true, force: true });
      }
    });

    it('resolves relative paths for list_files', async () => {
      const registry = createStandardRegistry('yolo', { basePath: testDir });

      const result = await registry.execute('list_files', { path: '.' });
      expect(result.success).toBe(true);
      expect(result.output).toContain('hello.txt');
    });

    it('resolves relative paths for edit_file', async () => {
      const registry = createStandardRegistry('yolo', { basePath: testDir });

      const result = await registry.execute('edit_file', {
        path: 'hello.txt',
        old_string: 'Hello',
        new_string: 'Goodbye',
      });
      expect(result.success).toBe(true);

      // Verify the edit was applied
      const content = await fs.readFile(path.join(testDir, 'hello.txt'), 'utf-8');
      expect(content).toBe('Goodbye, World!');
    });

    it('provides isolation - different basePaths see different files', async () => {
      const dir2 = mkdtempSync(path.join(tmpdir(), 'attocode-test2-'));
      await fs.writeFile(path.join(dir2, 'hello.txt'), 'Different content');

      try {
        const registry1 = createStandardRegistry('yolo', { basePath: testDir });
        const registry2 = createStandardRegistry('yolo', { basePath: dir2 });

        const result1 = await registry1.execute('read_file', { path: 'hello.txt' });
        const result2 = await registry2.execute('read_file', { path: 'hello.txt' });

        expect(result1.output).toBe('Hello, World!');
        expect(result2.output).toBe('Different content');
      } finally {
        await fs.rm(dir2, { recursive: true, force: true });
      }
    });
  });
});
