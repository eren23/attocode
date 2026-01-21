/**
 * Lesson 6: Tool Tests
 * 
 * Example tests for tools in isolation.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { createTestSandbox } from './helpers.js';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';

// =============================================================================
// SIMPLIFIED TOOLS FOR TESTING
// =============================================================================

interface ToolResult {
  success: boolean;
  output: string;
}

async function readFile(filePath: string): Promise<ToolResult> {
  try {
    const content = await fs.readFile(filePath, 'utf-8');
    return { success: true, output: content };
  } catch (error) {
    return { success: false, output: `Error: ${(error as Error).message}` };
  }
}

async function writeFile(filePath: string, content: string): Promise<ToolResult> {
  try {
    await fs.mkdir(path.dirname(filePath), { recursive: true });
    await fs.writeFile(filePath, content, 'utf-8');
    return { success: true, output: `Wrote ${content.length} bytes to ${filePath}` };
  } catch (error) {
    return { success: false, output: `Error: ${(error as Error).message}` };
  }
}

async function editFile(filePath: string, oldString: string, newString: string): Promise<ToolResult> {
  try {
    const content = await fs.readFile(filePath, 'utf-8');
    
    const count = (content.match(new RegExp(escapeRegExp(oldString), 'g')) || []).length;
    
    if (count === 0) {
      return { success: false, output: 'String not found in file' };
    }
    
    if (count > 1) {
      return { success: false, output: `String found ${count} times, must be unique` };
    }
    
    const newContent = content.replace(oldString, newString);
    await fs.writeFile(filePath, newContent, 'utf-8');
    
    return { success: true, output: 'File edited successfully' };
  } catch (error) {
    return { success: false, output: `Error: ${(error as Error).message}` };
  }
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// =============================================================================
// TESTS
// =============================================================================

describe('readFile', () => {
  let sandbox: Awaited<ReturnType<typeof createTestSandbox>>;

  beforeEach(async () => {
    sandbox = await createTestSandbox();
  });

  afterEach(async () => {
    await sandbox.cleanup();
  });

  it('should read an existing file', async () => {
    await sandbox.writeFile('test.txt', 'Hello, World!');
    
    const result = await readFile(path.join(sandbox.path, 'test.txt'));
    
    expect(result.success).toBe(true);
    expect(result.output).toBe('Hello, World!');
  });

  it('should return error for missing file', async () => {
    const result = await readFile(path.join(sandbox.path, 'nonexistent.txt'));
    
    expect(result.success).toBe(false);
    expect(result.output).toContain('ENOENT');
  });

  it('should handle files with unicode content', async () => {
    await sandbox.writeFile('unicode.txt', '你好世界 🌍');
    
    const result = await readFile(path.join(sandbox.path, 'unicode.txt'));
    
    expect(result.success).toBe(true);
    expect(result.output).toBe('你好世界 🌍');
  });
});

describe('writeFile', () => {
  let sandbox: Awaited<ReturnType<typeof createTestSandbox>>;

  beforeEach(async () => {
    sandbox = await createTestSandbox();
  });

  afterEach(async () => {
    await sandbox.cleanup();
  });

  it('should create a new file', async () => {
    const result = await writeFile(
      path.join(sandbox.path, 'new.txt'),
      'New content'
    );
    
    expect(result.success).toBe(true);
    expect(await sandbox.readFile('new.txt')).toBe('New content');
  });

  it('should create nested directories', async () => {
    const result = await writeFile(
      path.join(sandbox.path, 'deep/nested/dir/file.txt'),
      'Nested content'
    );
    
    expect(result.success).toBe(true);
    expect(await sandbox.exists('deep/nested/dir/file.txt')).toBe(true);
  });

  it('should overwrite existing files', async () => {
    await sandbox.writeFile('existing.txt', 'Old content');
    
    const result = await writeFile(
      path.join(sandbox.path, 'existing.txt'),
      'New content'
    );
    
    expect(result.success).toBe(true);
    expect(await sandbox.readFile('existing.txt')).toBe('New content');
  });
});

describe('editFile', () => {
  let sandbox: Awaited<ReturnType<typeof createTestSandbox>>;

  beforeEach(async () => {
    sandbox = await createTestSandbox();
  });

  afterEach(async () => {
    await sandbox.cleanup();
  });

  it('should replace a unique string', async () => {
    await sandbox.writeFile('code.ts', 'const x = 1;\nconst y = 2;');
    
    const result = await editFile(
      path.join(sandbox.path, 'code.ts'),
      'const x = 1;',
      'const x = 10;'
    );
    
    expect(result.success).toBe(true);
    expect(await sandbox.readFile('code.ts')).toBe('const x = 10;\nconst y = 2;');
  });

  it('should fail if string not found', async () => {
    await sandbox.writeFile('code.ts', 'const x = 1;');
    
    const result = await editFile(
      path.join(sandbox.path, 'code.ts'),
      'const y = 2;',
      'const y = 20;'
    );
    
    expect(result.success).toBe(false);
    expect(result.output).toContain('not found');
  });

  it('should fail if string is not unique', async () => {
    await sandbox.writeFile('code.ts', 'const x = 1;\nconst x = 1;');
    
    const result = await editFile(
      path.join(sandbox.path, 'code.ts'),
      'const x = 1;',
      'const x = 10;'
    );
    
    expect(result.success).toBe(false);
    expect(result.output).toContain('2 times');
  });

  it('should handle multiline replacements', async () => {
    const original = `function add(a, b) {
  return a + b;
}`;
    
    const replacement = `function add(a: number, b: number): number {
  return a + b;
}`;

    await sandbox.writeFile('code.ts', original);
    
    const result = await editFile(
      path.join(sandbox.path, 'code.ts'),
      'function add(a, b) {',
      'function add(a: number, b: number): number {'
    );
    
    expect(result.success).toBe(true);
    const content = await sandbox.readFile('code.ts');
    expect(content).toContain('a: number');
  });

  it('should handle special regex characters', async () => {
    await sandbox.writeFile('code.ts', 'const pattern = /\\d+/;');
    
    const result = await editFile(
      path.join(sandbox.path, 'code.ts'),
      '/\\d+/',
      '/\\w+/'
    );
    
    expect(result.success).toBe(true);
    expect(await sandbox.readFile('code.ts')).toBe('const pattern = /\\w+/;');
  });
});

describe('Integration: File Operations', () => {
  let sandbox: Awaited<ReturnType<typeof createTestSandbox>>;

  beforeEach(async () => {
    sandbox = await createTestSandbox();
  });

  afterEach(async () => {
    await sandbox.cleanup();
  });

  it('should handle a complete read-edit-verify cycle', async () => {
    // Setup: Create a file with a bug
    await sandbox.writeFile('main.ts', `
function greet(name: string) {
  console.log("Hello, " + nme);  // Bug: typo 'nme'
}
`.trim());

    // Read the file
    const readResult = await readFile(path.join(sandbox.path, 'main.ts'));
    expect(readResult.success).toBe(true);
    expect(readResult.output).toContain('nme');

    // Fix the bug
    const editResult = await editFile(
      path.join(sandbox.path, 'main.ts'),
      'console.log("Hello, " + nme);',
      'console.log("Hello, " + name);'
    );
    expect(editResult.success).toBe(true);

    // Verify the fix
    const verifyResult = await readFile(path.join(sandbox.path, 'main.ts'));
    expect(verifyResult.output).toContain('+ name);');
    expect(verifyResult.output).not.toContain('+ nme);');
  });
});
