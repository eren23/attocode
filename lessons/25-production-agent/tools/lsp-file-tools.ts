/**
 * LSP-Aware File Tools
 *
 * Enhanced file editing tools that leverage Language Server Protocol
 * to provide real-time diagnostic feedback after modifications.
 */

import { z } from 'zod';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import type { ToolDefinition } from '../types.js';
import type { LSPManager, LSPDiagnostic } from '../integrations/lsp.js';

// =============================================================================
// TYPES
// =============================================================================

export interface LSPFileToolsConfig {
  /** LSPManager instance for diagnostics */
  lspManager: LSPManager;
  /** Wait time for diagnostics after edit (ms) */
  diagnosticDelay?: number;
  /** Include warnings in output */
  includeWarnings?: boolean;
}

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

function escapeRegExp(string: string): string {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function formatDiagnostics(diagnostics: LSPDiagnostic[], filePath: string): string {
  if (diagnostics.length === 0) {
    return '';
  }

  const errors = diagnostics.filter(d => d.severity === 'error');
  const warnings = diagnostics.filter(d => d.severity === 'warning');

  const parts: string[] = [];

  if (errors.length > 0) {
    parts.push(`\n\n⚠️ ${errors.length} error(s) detected:`);
    for (const err of errors.slice(0, 5)) {
      const loc = `${path.basename(filePath)}:${err.range.start.line + 1}:${err.range.start.character + 1}`;
      parts.push(`  • [${loc}] ${err.message}`);
    }
    if (errors.length > 5) {
      parts.push(`  ... and ${errors.length - 5} more errors`);
    }
  }

  if (warnings.length > 0) {
    parts.push(`\n📋 ${warnings.length} warning(s):`);
    for (const warn of warnings.slice(0, 3)) {
      const loc = `${path.basename(filePath)}:${warn.range.start.line + 1}`;
      parts.push(`  • [${loc}] ${warn.message}`);
    }
    if (warnings.length > 3) {
      parts.push(`  ... and ${warnings.length - 3} more warnings`);
    }
  }

  return parts.join('\n');
}

async function waitForDiagnostics(
  lsp: LSPManager,
  filePath: string,
  delay: number
): Promise<LSPDiagnostic[]> {
  // Notify LSP that file changed
  try {
    const content = await fs.readFile(filePath, 'utf-8');
    lsp.notifyFileChanged(filePath, content, Date.now());
  } catch {
    // File might not exist yet, that's ok
  }

  // Wait for diagnostics to be computed
  await new Promise(resolve => setTimeout(resolve, delay));

  return lsp.getDiagnostics(filePath);
}

// =============================================================================
// LSP-AWARE EDIT FILE TOOL
// =============================================================================

const lspEditFileSchema = z.object({
  path: z.string().describe('Path to the file to edit'),
  old_string: z.string().describe('Exact string to find (must be unique in file)'),
  new_string: z.string().describe('String to replace it with'),
});

/**
 * Create an LSP-aware edit_file tool.
 */
export function createLSPEditFileTool(config: LSPFileToolsConfig): ToolDefinition {
  const { lspManager, diagnosticDelay = 500, includeWarnings = true } = config;

  return {
    name: 'edit_file',
    description: 'Make a surgical edit by replacing a unique string in a file (with LSP diagnostics)',
    parameters: lspEditFileSchema.shape as unknown as Record<string, unknown>,
    dangerLevel: 'moderate',
    async execute(args: Record<string, unknown>) {
      const input = lspEditFileSchema.parse(args);

      try {
        // Read file
        const content = await fs.readFile(input.path, 'utf-8');

        // Count occurrences
        const regex = new RegExp(escapeRegExp(input.old_string), 'g');
        const matches = content.match(regex);
        const count = matches?.length ?? 0;

        if (count === 0) {
          return `String not found in ${input.path}. Make sure old_string exactly matches the file content, including whitespace.`;
        }

        if (count > 1) {
          return `String found ${count} times in ${input.path}. The old_string must be unique. Include more surrounding context.`;
        }

        // Replace
        const newContent = content.replace(input.old_string, input.new_string);
        await fs.writeFile(input.path, newContent, 'utf-8');

        const linesDiff = input.new_string.split('\n').length - input.old_string.split('\n').length;
        let output = `Successfully edited ${input.path} (${linesDiff >= 0 ? '+' : ''}${linesDiff} lines)`;

        // Get LSP diagnostics
        const diagnostics = await waitForDiagnostics(lspManager, input.path, diagnosticDelay);
        const diagOutput = formatDiagnostics(
          includeWarnings ? diagnostics : diagnostics.filter(d => d.severity === 'error'),
          input.path
        );

        if (diagOutput) {
          output += diagOutput;
        } else {
          output += '\n✅ No errors detected';
        }

        return output;
      } catch (error) {
        const err = error as NodeJS.ErrnoException;
        if (err.code === 'ENOENT') {
          return `File not found: ${input.path}`;
        }
        return `Error editing file: ${err.message}`;
      }
    },
  };
}

// =============================================================================
// LSP-AWARE WRITE FILE TOOL
// =============================================================================

const lspWriteFileSchema = z.object({
  path: z.string().describe('Path to the file to write'),
  content: z.string().describe('Content to write to the file'),
});

/**
 * Create an LSP-aware write_file tool.
 */
export function createLSPWriteFileTool(config: LSPFileToolsConfig): ToolDefinition {
  const { lspManager, diagnosticDelay = 500, includeWarnings = true } = config;

  return {
    name: 'write_file',
    description: 'Write content to a file (creates or overwrites) with LSP diagnostics',
    parameters: lspWriteFileSchema.shape as unknown as Record<string, unknown>,
    dangerLevel: 'moderate',
    async execute(args: Record<string, unknown>) {
      const input = lspWriteFileSchema.parse(args);

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

        await fs.writeFile(input.path, input.content, 'utf-8');
        const lines = input.content.split('\n').length;

        let output = `Successfully ${action} ${input.path} (${lines} lines, ${input.content.length} bytes)`;

        // Get LSP diagnostics
        const diagnostics = await waitForDiagnostics(lspManager, input.path, diagnosticDelay);
        const diagOutput = formatDiagnostics(
          includeWarnings ? diagnostics : diagnostics.filter(d => d.severity === 'error'),
          input.path
        );

        if (diagOutput) {
          output += diagOutput;
        } else {
          output += '\n✅ No errors detected';
        }

        return output;
      } catch (error) {
        const err = error as NodeJS.ErrnoException;
        return `Error writing file: ${err.message}`;
      }
    },
  };
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create all LSP-aware file tools.
 */
export function createLSPFileTools(config: LSPFileToolsConfig): ToolDefinition[] {
  return [
    createLSPEditFileTool(config),
    createLSPWriteFileTool(config),
  ];
}

/**
 * Check if LSP diagnostics are available for a file type.
 */
export function isLSPSupportedFile(filePath: string): boolean {
  const ext = path.extname(filePath).toLowerCase();
  const supported = [
    '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs',  // TypeScript/JavaScript
    '.py', '.pyi',                                   // Python
    '.rs',                                           // Rust
    '.go',                                           // Go
    '.json', '.jsonc',                               // JSON
  ];
  return supported.includes(ext);
}
