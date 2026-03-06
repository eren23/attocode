/**
 * Lesson 8: Tool Re-exports and Schema Conversion
 *
 * Re-exports tools from Lesson 3 and provides conversion utilities
 * for OpenRouter's native tool use format.
 */

import { ToolRegistry, defineTool } from './registry.js';
import { readFileTool, writeFileTool, editFileTool, listFilesTool } from './file.js';
import { bashTool, grepTool, globTool } from './bash.js';
import { undoToolsAsStandard } from './undo.js';
import type { ToolDefinitionSchema } from '../providers/types.js';
import type { ToolDescription, PermissionMode, ToolDefinition } from './types.js';
import * as path from 'node:path';

// =============================================================================
// RE-EXPORTS
// =============================================================================

export {
  // Registry
  ToolRegistry,
  defineTool,

  // File tools
  readFileTool,
  writeFileTool,
  editFileTool,
  listFilesTool,

  // Bash tools
  bashTool,
  grepTool,
  globTool,
};

// =============================================================================
// SCHEMA CONVERSION
// =============================================================================

/**
 * ═══════════════════════════════════════════════════════════════════════════
 * Converting Tool Schemas: Anthropic vs OpenAI Format
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Anthropic format (what Lesson 3 uses):
 *   { name, description, input_schema: { type: 'object', properties, required } }
 *
 * OpenAI/OpenRouter format (what native tool use needs):
 *   { type: 'function', function: { name, description, parameters: {...} } }
 *
 * The actual schema structure is similar - it's just wrapped differently.
 * This conversion enables native tool calling instead of JSON text parsing.
 * ═══════════════════════════════════════════════════════════════════════════
 */

/**
 * Convert a single ToolDescription to OpenRouter format.
 */
export function toOpenRouterSchema(tool: ToolDescription): ToolDefinitionSchema {
  return {
    type: 'function',
    function: {
      name: tool.name,
      description: tool.description,
      // Type assertion needed because JSONSchema is a stricter type
      parameters: tool.input_schema as unknown as Record<string, unknown>,
    },
  };
}

/**
 * Convert multiple tool descriptions to OpenRouter format.
 */
export function toOpenRouterSchemas(tools: ToolDescription[]): ToolDefinitionSchema[] {
  return tools.map(toOpenRouterSchema);
}

// =============================================================================
// BASE PATH WRAPPING
// =============================================================================

/**
 * Resolve a path relative to a base directory.
 * Absolute paths are returned as-is. Relative paths are resolved against basePath.
 */
function resolveAgainstBase(basePath: string, filePath: string): string {
  if (path.isAbsolute(filePath)) return filePath;
  return path.resolve(basePath, filePath);
}

/**
 * Wrap a tool so that path-like inputs are resolved against a basePath.
 * The wrapper preserves the original tool's schema, description, and danger level.
 *
 * Uses 'any' cast internally because Zod's generic type parameters are invariant,
 * making it impossible to express "same type in, same type out" without it.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function wrapToolWithBasePath<T extends ToolDefinition<any>>(
  tool: T,
  basePath: string,
  pathFields: string[],
  cwdField?: string,
): T {
  return {
    ...tool,
    execute: async (input: Record<string, unknown>) => {
      const resolved = { ...input };

      // Resolve path fields
      for (const field of pathFields) {
        if (typeof resolved[field] === 'string') {
          resolved[field] = resolveAgainstBase(basePath, resolved[field] as string);
        }
      }

      // Set default cwd if not provided
      if (cwdField && !resolved[cwdField]) {
        resolved[cwdField] = basePath;
      }

      return tool.execute(resolved);
    },
  } as T;
}

// =============================================================================
// PRESET REGISTRY
// =============================================================================

/**
 * Options for creating a standard tool registry.
 */
export interface StandardRegistryOptions {
  /**
   * Base path for all tool operations.
   * When set, relative paths in file/bash tools are resolved against this directory,
   * and bash commands default to this as their cwd.
   * Falls back to process.cwd() behavior when not set.
   */
  basePath?: string;
}

/**
 * Create a pre-configured tool registry with all standard tools.
 *
 * @param permissionMode - How to handle dangerous operations
 * @param options - Optional configuration including basePath for path resolution
 * @returns Configured ToolRegistry with all tools registered
 *
 * @example
 * ```typescript
 * const registry = createStandardRegistry('interactive');
 * const result = await registry.execute('read_file', { path: 'README.md' });
 *
 * // With basePath for isolated execution
 * const isolated = createStandardRegistry('yolo', { basePath: '/tmp/workspace' });
 * ```
 */
export function createStandardRegistry(
  permissionMode: PermissionMode = 'interactive',
  options?: StandardRegistryOptions,
): ToolRegistry {
  const registry = new ToolRegistry(permissionMode);
  const basePath = options?.basePath;

  if (basePath) {
    // Wrap tools to resolve paths against basePath
    registry.register(wrapToolWithBasePath(readFileTool, basePath, ['path']));
    registry.register(wrapToolWithBasePath(writeFileTool, basePath, ['path']));
    registry.register(wrapToolWithBasePath(editFileTool, basePath, ['path']));
    registry.register(wrapToolWithBasePath(listFilesTool, basePath, ['path']));
    registry.register(wrapToolWithBasePath(bashTool, basePath, [], 'cwd'));
    registry.register(wrapToolWithBasePath(grepTool, basePath, ['path']));
    registry.register(wrapToolWithBasePath(globTool, basePath, ['path']));
  } else {
    // Register tools as-is (original behavior)
    registry.register(readFileTool);
    registry.register(writeFileTool);
    registry.register(editFileTool);
    registry.register(listFilesTool);
    registry.register(bashTool);
    registry.register(grepTool);
    registry.register(globTool);
  }

  // Undo/history operations (gracefully handle missing tracker context)
  for (const tool of undoToolsAsStandard) {
    registry.register(tool);
  }

  return registry;
}

/**
 * Get OpenRouter-compatible tool schemas for all standard tools.
 */
export function getStandardToolSchemas(): ToolDefinitionSchema[] {
  const registry = createStandardRegistry('yolo'); // Mode doesn't matter for schemas
  return toOpenRouterSchemas(registry.getDescriptions());
}

// =============================================================================
// TOOL SUMMARY (for documentation/logging)
// =============================================================================

/**
 * Get a human-readable summary of available tools.
 */
export function getToolsSummary(): string {
  const tools = [
    { name: 'read_file', desc: 'Read file contents', safe: true },
    { name: 'write_file', desc: 'Create/overwrite files', safe: false },
    { name: 'edit_file', desc: 'Make surgical edits (find & replace)', safe: false },
    { name: 'list_files', desc: 'List directory contents', safe: true },
    { name: 'bash', desc: 'Execute shell commands', safe: false },
    { name: 'grep', desc: 'Search for patterns in files', safe: true },
    { name: 'glob', desc: 'Find files by pattern', safe: true },
    { name: 'undo_file_change', desc: 'Undo last change to a file', safe: false },
    { name: 'show_file_history', desc: 'Show change history for a file', safe: true },
    { name: 'show_session_changes', desc: 'Show all session changes', safe: true },
  ];

  return tools.map((t) => `  • ${t.name}: ${t.desc}${t.safe ? '' : ' ⚠️'}`).join('\n');
}
