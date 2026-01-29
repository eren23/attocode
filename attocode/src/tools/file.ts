/**
 * Lesson 3: File Tools
 *
 * Tools for file system operations.
 */

import { z } from 'zod';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import { defineTool } from './registry.js';
import type { ToolResult } from './types.js';
import { FileOperationError, ErrorCategory } from '../errors/index.js';

// =============================================================================
// READ FILE
// =============================================================================

const readFileSchema = z.object({
  path: z.string().describe('Path to the file to read'),
});

export const readFileTool = defineTool(
  'read_file',
  'Read the contents of a file at the given path',
  readFileSchema,
  async (input): Promise<ToolResult> => {
    try {
      const content = await fs.readFile(input.path, 'utf-8');
      const lines = content.split('\n').length;
      return {
        success: true,
        output: content,
        metadata: { lines, bytes: content.length },
      };
    } catch (error) {
      const err = error as NodeJS.ErrnoException;
      if (err.code === 'ENOENT') {
        throw FileOperationError.notFound(input.path, 'read');
      }
      if (err.code === 'EACCES') {
        throw FileOperationError.permissionDenied(input.path, 'read');
      }
      if (err.code === 'EBUSY') {
        throw FileOperationError.busy(input.path, 'read');
      }
      // For other errors, wrap with generic file operation error
      throw new FileOperationError(
        `Error reading file: ${err.message}`,
        err.code === 'ETIMEDOUT' ? ErrorCategory.TRANSIENT : ErrorCategory.INTERNAL,
        err.code === 'ETIMEDOUT',
        input.path,
        'read',
        { code: err.code },
        err
      );
    }
  },
  'safe'
);

// =============================================================================
// WRITE FILE
// =============================================================================

/**
 * Atomic file write helper.
 * Writes to a temp file first, then renames to target path.
 * This prevents partial writes from corrupting files on disk full or crash.
 */
async function writeFileAtomic(filePath: string, content: string): Promise<void> {
  const tempPath = `${filePath}.tmp.${Date.now()}.${Math.random().toString(36).slice(2, 8)}`;

  try {
    // Write to temp file
    await fs.writeFile(tempPath, content, 'utf-8');

    // Atomic rename (on same filesystem)
    await fs.rename(tempPath, filePath);
  } catch (err) {
    // Clean up temp file on failure
    try {
      await fs.unlink(tempPath);
    } catch {
      // Ignore cleanup errors - temp file may not exist
    }

    // Re-throw with specific error for disk full
    const nodeErr = err as NodeJS.ErrnoException;
    if (nodeErr.code === 'ENOSPC') {
      throw new Error(`Disk full - cannot write file: ${filePath}`);
    }
    throw err;
  }
}

const writeFileSchema = z.object({
  path: z.string().describe('Path to the file to write'),
  content: z.string().describe('Content to write to the file'),
});

export const writeFileTool = defineTool(
  'write_file',
  'Write content to a file (creates or overwrites)',
  writeFileSchema,
  async (input): Promise<ToolResult> => {
    try {
      // Ensure directory exists
      const dir = path.dirname(input.path);
      await fs.mkdir(dir, { recursive: true });

      // Check if file exists
      let action = 'created';
      try {
        await fs.access(input.path);
        action = 'overwrote';
      } catch {
        // File doesn't exist, that's fine
      }

      // Use atomic write to prevent corruption
      await writeFileAtomic(input.path, input.content);
      const lines = input.content.split('\n').length;

      return {
        success: true,
        output: `Successfully ${action} ${input.path} (${lines} lines, ${input.content.length} bytes)`,
        metadata: { action, lines, bytes: input.content.length },
      };
    } catch (error) {
      const err = error as NodeJS.ErrnoException;
      if (err.code === 'ENOSPC' || err.message.includes('Disk full')) {
        throw new FileOperationError(
          `Disk full - cannot write file: ${input.path}`,
          ErrorCategory.RESOURCE,
          false, // Not recoverable without human intervention
          input.path,
          'write',
          { code: err.code }
        );
      }
      if (err.code === 'EACCES') {
        throw FileOperationError.permissionDenied(input.path, 'write');
      }
      if (err.code === 'EBUSY') {
        throw FileOperationError.busy(input.path, 'write');
      }
      throw new FileOperationError(
        `Error writing file: ${err.message}`,
        ErrorCategory.INTERNAL,
        false,
        input.path,
        'write',
        { code: err.code },
        err
      );
    }
  },
  'moderate'
);

// =============================================================================
// EDIT FILE (str_replace style)
// =============================================================================

const editFileSchema = z.object({
  path: z.string().describe('Path to the file to edit'),
  old_string: z.string().describe('Exact string to find (must be unique in file)'),
  new_string: z.string().describe('String to replace it with'),
});

export const editFileTool = defineTool(
  'edit_file',
  'Make a surgical edit by replacing a unique string in a file',
  editFileSchema,
  async (input): Promise<ToolResult> => {
    try {
      // Read file
      const content = await fs.readFile(input.path, 'utf-8');
      
      // Count occurrences
      const regex = new RegExp(escapeRegExp(input.old_string), 'g');
      const matches = content.match(regex);
      const count = matches?.length ?? 0;
      
      if (count === 0) {
        return {
          success: false,
          output: `String not found in ${input.path}. Make sure old_string exactly matches the file content, including whitespace.`,
        };
      }
      
      if (count > 1) {
        return {
          success: false,
          output: `String found ${count} times in ${input.path}. The old_string must be unique. Include more surrounding context.`,
        };
      }
      
      // Replace and write atomically
      const newContent = content.replace(input.old_string, input.new_string);
      await writeFileAtomic(input.path, newContent);

      const linesDiff = input.new_string.split('\n').length - input.old_string.split('\n').length;

      return {
        success: true,
        output: `Successfully edited ${input.path} (${linesDiff >= 0 ? '+' : ''}${linesDiff} lines)`,
        metadata: { linesDiff },
      };
    } catch (error) {
      const err = error as NodeJS.ErrnoException;
      if (err.code === 'ENOENT') {
        throw FileOperationError.notFound(input.path, 'edit');
      }
      if (err.code === 'ENOSPC' || err.message.includes('Disk full')) {
        throw new FileOperationError(
          `Disk full - cannot edit file: ${input.path}`,
          ErrorCategory.RESOURCE,
          false,
          input.path,
          'edit',
          { code: err.code }
        );
      }
      if (err.code === 'EACCES') {
        throw FileOperationError.permissionDenied(input.path, 'edit');
      }
      if (err.code === 'EBUSY') {
        throw FileOperationError.busy(input.path, 'edit');
      }
      throw new FileOperationError(
        `Error editing file: ${err.message}`,
        ErrorCategory.INTERNAL,
        false,
        input.path,
        'edit',
        { code: err.code },
        err
      );
    }
  },
  'moderate'
);

// =============================================================================
// LIST FILES
// =============================================================================

const listFilesSchema = z.object({
  path: z.string().optional().default('.').describe('Directory path to list'),
  recursive: z.boolean().optional().default(false).describe('List recursively'),
});

export const listFilesTool = defineTool(
  'list_files',
  'List files and directories at the given path',
  listFilesSchema,
  async (input): Promise<ToolResult> => {
    try {
      if (input.recursive) {
        const files = await listRecursive(input.path);
        return {
          success: true,
          output: files.length > 0 ? files.join('\n') : '(empty directory)',
          metadata: { count: files.length },
        };
      }
      
      const entries = await fs.readdir(input.path, { withFileTypes: true });
      const formatted = entries
        .sort((a, b) => {
          // Directories first, then files
          if (a.isDirectory() && !b.isDirectory()) return -1;
          if (!a.isDirectory() && b.isDirectory()) return 1;
          return a.name.localeCompare(b.name);
        })
        .map(e => `${e.isDirectory() ? '📁' : '📄'} ${e.name}`);
      
      return {
        success: true,
        output: formatted.length > 0 ? formatted.join('\n') : '(empty directory)',
        metadata: { count: entries.length },
      };
    } catch (error) {
      const err = error as NodeJS.ErrnoException;
      if (err.code === 'ENOENT') {
        throw FileOperationError.notFound(input.path, 'list');
      }
      if (err.code === 'EACCES') {
        throw FileOperationError.permissionDenied(input.path, 'list');
      }
      throw new FileOperationError(
        `Error listing directory: ${err.message}`,
        ErrorCategory.INTERNAL,
        false,
        input.path,
        'list',
        { code: err.code },
        err
      );
    }
  },
  'safe'
);

// =============================================================================
// HELPERS
// =============================================================================

function escapeRegExp(string: string): string {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Directories to always skip (huge/binary/irrelevant)
const SKIP_DIRS = new Set([
  'node_modules',
  '.git',
  '.next',
  '.nuxt',
  'dist',
  'build',
  '.cache',
  '.parcel-cache',
  '__pycache__',
  '.pytest_cache',
  'venv',
  '.venv',
  'env',
  '.env',
  'vendor',
  'target',
  '.idea',
  '.vscode',
  'coverage',
  '.nyc_output',
  '.turbo',
  '.svelte-kit',
  'out',
  '.output',
]);

// Max files to return (prevents massive outputs)
const MAX_RECURSIVE_FILES = 500;

async function listRecursive(dir: string, prefix = '', count = { value: 0 }): Promise<string[]> {
  const results: string[] = [];

  // Stop if we've hit the limit
  if (count.value >= MAX_RECURSIVE_FILES) {
    return results;
  }

  const entries = await fs.readdir(dir, { withFileTypes: true });

  for (const entry of entries) {
    // Skip hidden files and excluded directories
    if (entry.name.startsWith('.') && entry.isDirectory()) continue;
    if (entry.isDirectory() && SKIP_DIRS.has(entry.name)) continue;

    const fullPath = path.join(prefix, entry.name);

    if (entry.isDirectory()) {
      results.push(`📁 ${fullPath}/`);
      count.value++;

      if (count.value < MAX_RECURSIVE_FILES) {
        const subEntries = await listRecursive(path.join(dir, entry.name), fullPath, count);
        results.push(...subEntries);
      }
    } else {
      results.push(`📄 ${fullPath}`);
      count.value++;
    }

    if (count.value >= MAX_RECURSIVE_FILES) {
      results.push(`\n... [Limit reached: ${MAX_RECURSIVE_FILES} files shown. Use specific paths to see more.]`);
      break;
    }
  }

  return results;
}
