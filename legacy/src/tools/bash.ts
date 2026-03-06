/**
 * Lesson 3: Bash Tool
 *
 * Tool for executing shell commands with safety checks.
 */

import { z } from 'zod';
import { spawn } from 'node:child_process';
import { defineTool } from './registry.js';
import { classifyCommand, classifyBashCommandDangerLevel } from './permission.js';
import { coerceBoolean } from './coercion.js';
import type { ToolResult, DangerLevel } from './types.js';
import { logger } from '../integrations/utilities/logger.js';

// =============================================================================
// BASH COMMAND TOOL
// =============================================================================

const bashSchema = z.object({
  command: z.string().describe('The bash command to execute'),
  cwd: z.string().optional().describe('Working directory (default: current directory)'),
  timeout: z.coerce.number().optional().default(30000).describe('Timeout in milliseconds'),
});

/**
 * Auto-convert timeout: values < 300 are almost certainly seconds, not milliseconds.
 * Models (especially weaker ones) often pass e.g. 60 meaning 60 seconds.
 * Threshold at 300 avoids mangling legitimate sub-second timeouts (500-999ms in tests).
 */
export function normalizeTimeoutMs(timeout: number): number {
  if (timeout > 0 && timeout < 300) {
    return timeout * 1000;
  }
  return timeout;
}

/**
 * Execute a bash command.
 *
 * Key safety features:
 * 1. Danger classification for permission checking
 * 2. Timeout to prevent hanging
 * 3. Output capture with size limits
 * 4. Non-interactive execution
 */
export const bashTool = defineTool(
  'bash',
  'Execute a bash command and return the output',
  bashSchema,
  async (input): Promise<ToolResult> => {
    input.timeout = normalizeTimeoutMs(input.timeout);

    // Classify the command's danger level
    const { level, reasons } = classifyCommand(input.command);

    // Add warning to output for dangerous commands
    let warning = '';
    if (reasons.length > 0) {
      warning = `⚠️  Detected: ${reasons.join(', ')}\n\n`;
    }

    return new Promise((resolve) => {
      const proc = spawn('bash', ['-c', input.command], {
        cwd: input.cwd || process.cwd(),
        env: { ...process.env, TERM: 'dumb' }, // Disable colors/formatting
        stdio: ['ignore', 'pipe', 'pipe'], // No stdin, capture stdout/stderr
      });

      let stdout = '';
      let stderr = '';
      let killed = false;
      const maxOutput = 100000; // 100KB limit

      // Set timeout with proper cleanup
      const timer = setTimeout(() => {
        killed = true;
        proc.kill('SIGTERM');

        // Escalate to SIGKILL after 1 second
        setTimeout(() => {
          if (!proc.killed) {
            proc.kill('SIGKILL');

            // Verify termination after SIGKILL, attempt process group kill if needed
            setTimeout(() => {
              if (!proc.killed && proc.pid) {
                logger.warn(
                  `[Bash] Process ${proc.pid} may be zombie after SIGKILL, attempting process group kill`,
                );
                try {
                  // Try to kill the entire process group (negative PID)
                  process.kill(-proc.pid, 'SIGKILL');
                } catch {
                  // Ignore errors - process may already be dead or we lack permissions
                }
              }
            }, 2000);
          }
        }, 1000);
      }, input.timeout);

      // Capture stdout
      proc.stdout?.on('data', (data: Buffer) => {
        if (stdout.length < maxOutput) {
          stdout += data.toString();
        }
      });

      // Capture stderr
      proc.stderr?.on('data', (data: Buffer) => {
        if (stderr.length < maxOutput) {
          stderr += data.toString();
        }
      });

      // Handle completion
      proc.on('close', (code) => {
        clearTimeout(timer);

        if (killed) {
          resolve({
            success: false,
            output: `${warning}Command timed out after ${input.timeout}ms`,
            metadata: { timedOut: true, dangerLevel: level },
          });
          return;
        }

        const output = stdout + (stderr ? `\n--- stderr ---\n${stderr}` : '');
        const truncated = output.length > maxOutput;
        const finalOutput = truncated
          ? output.slice(0, maxOutput) + '\n... (output truncated)'
          : output;

        resolve({
          success: code === 0,
          output: warning + (finalOutput || '(no output)'),
          metadata: {
            exitCode: code,
            dangerLevel: level,
            truncated,
          },
        });
      });

      // Handle errors
      proc.on('error', (error) => {
        clearTimeout(timer);
        resolve({
          success: false,
          output: `${warning}Failed to execute command: ${error.message}`,
          metadata: { dangerLevel: level },
        });
      });
    });
  },
  {
    // Default to moderate for backwards compatibility
    dangerLevel: 'moderate' as DangerLevel,
    // Dynamic danger level based on actual command
    getDangerLevel: (input: { command: string }) => classifyBashCommandDangerLevel(input.command),
  },
);

// =============================================================================
// SPECIALIZED BASH COMMANDS
// =============================================================================

const grepSchema = z.object({
  pattern: z.string().describe('Regex pattern to search for'),
  path: z.string().describe('File or directory to search in'),
  recursive: coerceBoolean().optional().default(false).describe('Search recursively'),
});

export const grepTool = defineTool(
  'grep',
  'Search for a pattern in files',
  grepSchema,
  async (input): Promise<ToolResult> => {
    const flags = input.recursive ? '-rn' : '-n';
    const command = `grep ${flags} "${input.pattern}" "${input.path}" || true`;

    return bashTool.execute({ command, timeout: 10000 });
  },
  'safe',
);

const globSchema = z.object({
  pattern: z.string().describe('Glob pattern to match files'),
  path: z.string().optional().default('.').describe('Directory to search in'),
});

export const globTool = defineTool(
  'glob',
  'Find files matching a glob pattern',
  globSchema,
  async (input): Promise<ToolResult> => {
    const command = `find "${input.path}" -name "${input.pattern}" 2>/dev/null | head -100`;

    return bashTool.execute({ command, timeout: 10000 });
  },
  'safe',
);
