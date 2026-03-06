/**
 * TypeScript Compilation Checker
 *
 * Detects TypeScript projects, runs `tsc --noEmit` periodically during editing
 * and at completion, and formats errors for agent consumption.
 *
 * Uses the same safe spawn pattern as src/tools/bash.ts.
 */

import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join, dirname } from 'node:path';

// =============================================================================
// TYPES
// =============================================================================

export interface TypeCheckError {
  file: string;
  line: number;
  column: number;
  code: string; // e.g., "TS2554"
  message: string;
}

export interface TypeCheckResult {
  success: boolean; // exit code 0
  errorCount: number;
  errors: TypeCheckError[];
  duration: number; // ms
}

export interface TypeCheckerState {
  tsconfigDir: string | null; // directory with tsconfig.json, or null
  tsEditsSinceLastCheck: number; // .ts/.tsx edits since last tsc run
  lastResult: TypeCheckResult | null; // last tsc result
  hasRunOnce: boolean; // whether tsc has been run this session
}

// =============================================================================
// PROJECT DETECTION
// =============================================================================

/**
 * Walk up from cwd looking for tsconfig.json.
 * Returns the containing directory or null.
 */
export function detectTypeScriptProject(cwd: string): string | null {
  let dir = cwd;
  const root = dirname(dir) === dir ? dir : undefined; // filesystem root guard

  for (let i = 0; i < 20; i++) {
    if (existsSync(join(dir, 'tsconfig.json'))) {
      return dir;
    }
    const parent = dirname(dir);
    if (parent === dir || parent === root) break;
    dir = parent;
  }
  return null;
}

// =============================================================================
// TSC EXECUTION
// =============================================================================

/**
 * Run `npx tsc --noEmit --pretty false` in tsconfigDir.
 * Uses spawn (not exec) to avoid shell injection — same safe pattern as tools/bash.ts.
 * On spawn error (tsc not installed), returns success (graceful degradation).
 */
export async function runTypeCheck(
  tsconfigDir: string,
  timeout: number = 60_000,
): Promise<TypeCheckResult> {
  const start = Date.now();

  return new Promise<TypeCheckResult>((resolve) => {
    let stdout = '';
    let stderr = '';
    let resolved = false;

    const done = (success: boolean) => {
      if (resolved) return;
      resolved = true;
      const output = stdout + '\n' + stderr;
      const errors = parseTypeCheckOutput(output);
      resolve({
        success,
        errorCount: errors.length,
        errors,
        duration: Date.now() - start,
      });
    };

    try {
      const child = spawn('npx', ['tsc', '--noEmit', '--pretty', 'false'], {
        cwd: tsconfigDir,
        stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env },
        timeout,
      });

      child.stdout?.on('data', (data: Buffer) => {
        stdout += data.toString();
      });
      child.stderr?.on('data', (data: Buffer) => {
        stderr += data.toString();
      });

      child.on('close', (code) => {
        done(code === 0);
      });

      child.on('error', () => {
        // tsc not installed or spawn failed — graceful degradation
        done(true);
      });
    } catch {
      // Spawn itself failed — graceful degradation
      done(true);
    }
  });
}

// =============================================================================
// OUTPUT PARSING
// =============================================================================

/**
 * Parse tsc --pretty false output into structured errors.
 * Format: file(line,column): error TSxxxx: message
 */
export function parseTypeCheckOutput(output: string): TypeCheckError[] {
  const errors: TypeCheckError[] = [];
  const regex = /^(.+?)\((\d+),(\d+)\):\s+error\s+(TS\d+):\s+(.+)$/gm;

  let match: RegExpExecArray | null;
  while ((match = regex.exec(output)) !== null) {
    errors.push({
      file: match[1],
      line: parseInt(match[2], 10),
      column: parseInt(match[3], 10),
      code: match[4],
      message: match[5],
    });
  }

  return errors;
}

// =============================================================================
// NUDGE FORMATTING
// =============================================================================

/**
 * Format compilation errors into an agent-readable nudge message.
 * Shows up to maxErrors errors and ends with a fix instruction.
 */
export function formatTypeCheckNudge(result: TypeCheckResult, maxErrors: number = 15): string {
  const parts: string[] = [
    `[System] TypeScript compilation failed with ${result.errorCount} error(s):`,
    '',
  ];

  const shown = result.errors.slice(0, maxErrors);
  for (const err of shown) {
    parts.push(`  ${err.file}(${err.line},${err.column}): ${err.code}: ${err.message}`);
  }

  if (result.errors.length > maxErrors) {
    parts.push(`  ... and ${result.errors.length - maxErrors} more error(s)`);
  }

  parts.push('');
  parts.push('Fix these TypeScript compilation errors before completing the task.');

  return parts.join('\n');
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create initial TypeCheckerState by detecting the project.
 */
export function createTypeCheckerState(cwd: string): TypeCheckerState {
  return {
    tsconfigDir: detectTypeScriptProject(cwd),
    tsEditsSinceLastCheck: 0,
    lastResult: null,
    hasRunOnce: false,
  };
}
