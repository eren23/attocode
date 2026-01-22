/**
 * Lesson 8: Tool Re-exports and Schema Conversion
 *
 * Re-exports tools from Lesson 3 and provides conversion utilities
 * for OpenRouter's native tool use format.
 */

import { ToolRegistry, defineTool } from './registry.js';
import { readFileTool, writeFileTool, editFileTool, listFilesTool } from './file.js';
import { bashTool, grepTool, globTool } from './bash.js';
import type { ToolDefinitionSchema } from '../providers/types.js';
import type { ToolDescription, PermissionMode } from './types.js';

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
// PRESET REGISTRY
// =============================================================================

/**
 * Create a pre-configured tool registry with all standard tools.
 *
 * @param permissionMode - How to handle dangerous operations
 * @returns Configured ToolRegistry with all tools registered
 *
 * @example
 * ```typescript
 * const registry = createStandardRegistry('interactive');
 * const result = await registry.execute('read_file', { path: 'README.md' });
 * ```
 */
export function createStandardRegistry(permissionMode: PermissionMode = 'interactive'): ToolRegistry {
  const registry = new ToolRegistry(permissionMode);

  // File operations
  registry.register(readFileTool);
  registry.register(writeFileTool);
  registry.register(editFileTool);
  registry.register(listFilesTool);

  // Bash operations
  registry.register(bashTool);
  registry.register(grepTool);
  registry.register(globTool);

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
  ];

  return tools
    .map(t => `  • ${t.name}: ${t.desc}${t.safe ? '' : ' ⚠️'}`)
    .join('\n');
}
