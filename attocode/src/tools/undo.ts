/**
 * Undo Tools
 *
 * Tools for undoing file changes and viewing file history.
 * These tools use the FileChangeTracker to provide undo capability
 * for file operations within an agent session.
 *
 * @example
 * ```typescript
 * import { undoTools } from './tools/undo.js';
 *
 * // Register undo tools with agent
 * for (const tool of undoTools) {
 *   registry.register(tool);
 * }
 * ```
 */

import { z } from 'zod';
import type { ToolDefinition, ToolResult, DangerLevel } from './types.js';
import type { FileChangeTracker } from '../integrations/utilities/file-change-tracker.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Context passed to tool execution that provides access to agent features.
 */
export interface ToolExecutionContext {
  /** Reference to the agent (if available) */
  agent?: {
    getFileChangeTracker?: () => FileChangeTracker | null;
  };
}

/**
 * Extended tool definition that accepts execution context.
 */
export interface ContextAwareToolDefinition<TInput extends z.ZodTypeAny = z.ZodTypeAny> {
  /** Unique identifier */
  name: string;
  /** Human-readable description (shown to LLM) */
  description: string;
  /** Input parameter schema */
  parameters: TInput;
  /** Danger level for permission checking */
  dangerLevel: DangerLevel;
  /** Execute the tool with context */
  execute: (input: z.infer<TInput>, context?: ToolExecutionContext) => Promise<ToolResult>;
}

// =============================================================================
// UNDO FILE CHANGE TOOL
// =============================================================================

/**
 * Tool to undo the last change to a specific file.
 */
export const undoFileChangeTool: ContextAwareToolDefinition = {
  name: 'undo_file_change',
  description: 'Undo the last change to a specific file, restoring its previous content',
  parameters: z.object({
    path: z.string().describe('The file path to undo changes for'),
  }),
  dangerLevel: 'moderate',
  execute: async (args: { path: string }, context?: ToolExecutionContext): Promise<ToolResult> => {
    const tracker = context?.agent?.getFileChangeTracker?.();
    if (!tracker) {
      return { success: false, output: 'File change tracking is not enabled' };
    }

    const result = await tracker.undoLastChange(args.path);
    return {
      success: result.success,
      output: result.message,
    };
  },
};

// =============================================================================
// SHOW FILE HISTORY TOOL
// =============================================================================

/**
 * Tool to show change history for a file.
 */
export const showFileHistoryTool: ContextAwareToolDefinition = {
  name: 'show_file_history',
  description: 'Show the change history for a file in this session',
  parameters: z.object({
    path: z.string().describe('The file path to show history for'),
  }),
  dangerLevel: 'safe',
  execute: async (args: { path: string }, context?: ToolExecutionContext): Promise<ToolResult> => {
    const tracker = context?.agent?.getFileChangeTracker?.();
    if (!tracker) {
      return { success: false, output: 'File change tracking is not enabled' };
    }

    const history = tracker.getFileHistory(args.path);
    if (history.length === 0) {
      return { success: true, output: `No changes recorded for ${args.path}` };
    }

    const formatted = history
      .map(
        (change, i) =>
          `${i + 1}. [${change.operation}] Turn ${change.turnNumber} - ${change.createdAt}` +
          `\n   Before: ${change.bytesBefore} bytes, After: ${change.bytesAfter} bytes` +
          (change.isUndone ? ' (UNDONE)' : ''),
      )
      .join('\n');

    return { success: true, output: `File history for ${args.path}:\n${formatted}` };
  },
};

// =============================================================================
// SHOW SESSION CHANGES TOOL
// =============================================================================

/**
 * Tool to show session change summary.
 */
export const showSessionChangesTool: ContextAwareToolDefinition = {
  name: 'show_session_changes',
  description: 'Show a summary of all file changes in this session',
  parameters: z.object({}),
  dangerLevel: 'safe',
  execute: async (
    _args: Record<string, never>,
    context?: ToolExecutionContext,
  ): Promise<ToolResult> => {
    const tracker = context?.agent?.getFileChangeTracker?.();
    if (!tracker) {
      return { success: false, output: 'File change tracking is not enabled' };
    }

    const summary = tracker.getSessionChangeSummary();
    const output = [
      `Session Change Summary:`,
      `  Total changes: ${summary.totalChanges}`,
      `  Files modified: ${summary.filesModified.length}`,
      `  Creates: ${summary.byOperation.create}`,
      `  Writes: ${summary.byOperation.write}`,
      `  Edits: ${summary.byOperation.edit}`,
      `  Deletes: ${summary.byOperation.delete}`,
      `  Undone: ${summary.undoneChanges}`,
    ].join('\n');

    return { success: true, output };
  },
};

// =============================================================================
// EXPORTS
// =============================================================================

/**
 * All undo-related tools.
 *
 * These tools require the agent to pass a ToolExecutionContext
 * that provides access to the FileChangeTracker via
 * context.agent.getFileChangeTracker().
 */
export const undoTools: ContextAwareToolDefinition[] = [
  undoFileChangeTool,
  showFileHistoryTool,
  showSessionChangesTool,
];

/**
 * Cast undo tools to standard ToolDefinition format.
 * Use this when registering with a registry that doesn't support context.
 * Note: The tools will return "tracking not enabled" if context is not passed.
 */
export const undoToolsAsStandard: ToolDefinition[] = undoTools as unknown as ToolDefinition[];
