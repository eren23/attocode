/**
 * Basic Sandbox (Fallback)
 *
 * A simple allowlist/blocklist-based sandbox that works everywhere.
 * Does not provide true isolation but validates commands before execution.
 *
 * Features:
 * - Command allowlist validation
 * - Dangerous pattern blocking
 * - Path validation
 * - Timeout enforcement
 *
 * Note: This is NOT a security sandbox - it's a best-effort validation
 * layer for environments where proper sandboxing isn't available.
 */

import { spawn } from 'child_process';
import type { Sandbox, SandboxMode, SandboxOptions, ExecResult } from './index.js';

// =============================================================================
// DANGEROUS PATTERNS
// =============================================================================

/**
 * Patterns that should always be blocked.
 */
const DANGEROUS_PATTERNS = [
  // Recursive deletion of root or home
  /rm\s+(-[rf]+\s+)*\//,
  /rm\s+(-[rf]+\s+)*~/,

  // Fork bomb
  /:\(\)\{.*\};:/,

  // Writing to block devices
  />\s*\/dev\/sd[a-z]/,
  /dd\s+.*of=\/dev/,

  // Filesystem formatting
  /mkfs/,

  // Download and execute
  /curl\s+.*\|\s*(ba)?sh/,
  /wget\s+.*\|\s*(ba)?sh/,

  // Privilege escalation
  /sudo\s/,
  /su\s+-/,
  /doas\s/,

  // Dangerous chmod
  /chmod\s+777\s+\//,
  /chmod\s+-R\s+777/,

  // Network data exfiltration patterns
  /curl\s+.*-d\s+.*\$\(/,
  /nc\s+-e/,
];

/**
 * Commands that are always blocked.
 */
const BLOCKED_COMMANDS = [
  'shutdown',
  'reboot',
  'halt',
  'poweroff',
  'init',
  'systemctl stop',
  'systemctl disable',
  'mkfs',
  'fdisk',
  'parted',
  'mount',
  'umount',
  'iptables',
  'firewall-cmd',
];

// =============================================================================
// BASIC SANDBOX
// =============================================================================

/**
 * Basic allowlist-based sandbox.
 */
export class BasicSandbox implements Sandbox {
  private options: SandboxOptions;

  constructor(options: SandboxOptions) {
    this.options = options;
  }

  /**
   * Execute a command with validation.
   */
  async execute(command: string, options?: Partial<SandboxOptions>): Promise<ExecResult> {
    const mergedOptions = { ...this.options, ...options };

    // Validate command
    const validation = this.validateCommand(command, mergedOptions);
    if (!validation.allowed) {
      return {
        stdout: '',
        stderr: `Command blocked: ${validation.reason}`,
        exitCode: 1,
        killed: false,
        timedOut: false,
        error: validation.reason,
      };
    }

    const timeout = mergedOptions.timeout ?? 60000;
    const workDir = mergedOptions.workingDir ?? process.cwd();

    return new Promise((resolve) => {
      const proc = spawn('bash', ['-c', command], {
        cwd: workDir,
        env: {
          ...process.env,
          ...mergedOptions.env,
        },
        stdio: ['pipe', 'pipe', 'pipe'],
      });

      let stdout = '';
      let stderr = '';
      let killed = false;
      let timedOut = false;

      const timer = setTimeout(() => {
        timedOut = true;
        killed = true;
        proc.kill('SIGKILL');
      }, timeout);

      proc.stdout?.on('data', (data) => {
        stdout += data.toString();
      });

      proc.stderr?.on('data', (data) => {
        stderr += data.toString();
      });

      proc.on('close', (code) => {
        clearTimeout(timer);
        resolve({
          stdout,
          stderr,
          exitCode: code ?? 1,
          killed,
          timedOut,
        });
      });

      proc.on('error', (err) => {
        clearTimeout(timer);
        resolve({
          stdout,
          stderr,
          exitCode: 1,
          killed: false,
          timedOut: false,
          error: err.message,
        });
      });
    });
  }

  /**
   * Validate a command against allowlist and blocklist.
   */
  validateCommand(
    command: string,
    options: SandboxOptions
  ): { allowed: boolean; reason?: string } {
    // Check for dangerous patterns
    for (const pattern of DANGEROUS_PATTERNS) {
      if (pattern.test(command)) {
        return { allowed: false, reason: 'Command matches dangerous pattern' };
      }
    }

    // Check for blocked commands
    for (const blocked of BLOCKED_COMMANDS) {
      if (command.includes(blocked)) {
        return { allowed: false, reason: `Blocked command: ${blocked}` };
      }
    }

    // Check user-specified blocked commands
    for (const blocked of options.blockedCommands ?? []) {
      if (command.includes(blocked)) {
        return { allowed: false, reason: `Blocked by configuration: ${blocked}` };
      }
    }

    // Extract the base command
    const baseCommand = this.extractBaseCommand(command);

    // Check against allowlist if provided
    const allowedCommands = options.allowedCommands;
    if (allowedCommands && allowedCommands.length > 0) {
      if (!allowedCommands.includes(baseCommand)) {
        return {
          allowed: false,
          reason: `Command '${baseCommand}' not in allowlist`,
        };
      }
    }

    // Check path access
    const pathValidation = this.validatePaths(command, options);
    if (!pathValidation.allowed) {
      return pathValidation;
    }

    return { allowed: true };
  }

  /**
   * Extract the base command from a command string.
   */
  private extractBaseCommand(command: string): string {
    // Handle pipes and redirects
    const firstPart = command.split(/[|;&]/)[0].trim();

    // Handle env vars and other prefixes
    const parts = firstPart.split(/\s+/);

    // Skip env var assignments
    for (const part of parts) {
      if (!part.includes('=') && !part.startsWith('-')) {
        // Get just the command name without path
        return part.split('/').pop() || part;
      }
    }

    return parts[0] || '';
  }

  /**
   * Validate path access in command.
   */
  private validatePaths(
    command: string,
    options: SandboxOptions
  ): { allowed: boolean; reason?: string } {
    const writablePaths = options.writablePaths ?? ['.'];
    const workDir = options.workingDir ?? process.cwd();

    // Check for writes to paths outside writable areas
    const writePatterns = [
      />>\?\s*["']?([^"'\s]+)/g,      // Append redirect
      />\s*["']?([^"'\s]+)/g,         // Write redirect
      /\btee\s+["']?([^"'\s]+)/g,     // tee command
    ];

    for (const pattern of writePatterns) {
      let match;
      while ((match = pattern.exec(command)) !== null) {
        const path = match[1];
        if (path && !this.isPathWritable(path, writablePaths, workDir)) {
          return { allowed: false, reason: `Write to path not allowed: ${path}` };
        }
      }
    }

    return { allowed: true };
  }

  /**
   * Check if a path is in the writable list.
   */
  private isPathWritable(
    path: string,
    writablePaths: string[],
    workDir: string
  ): boolean {
    // Resolve the path
    const resolvedPath = path.startsWith('/')
      ? path
      : `${workDir}/${path}`;

    // Check against writable paths
    for (const writable of writablePaths) {
      const resolvedWritable = writable.startsWith('/')
        ? writable
        : writable === '.'
          ? workDir
          : `${workDir}/${writable}`;

      if (resolvedPath.startsWith(resolvedWritable)) {
        return true;
      }
    }

    // Allow /tmp and /dev/null
    if (resolvedPath.startsWith('/tmp') || resolvedPath === '/dev/null') {
      return true;
    }

    return false;
  }

  /**
   * Always available.
   */
  async isAvailable(): Promise<boolean> {
    return true;
  }

  /**
   * Get sandbox type.
   */
  getType(): SandboxMode {
    return 'basic';
  }

  /**
   * Cleanup resources.
   */
  async cleanup(): Promise<void> {
    // No cleanup needed
  }
}

// =============================================================================
// UTILITY FUNCTIONS
// =============================================================================

/**
 * Check if a command is safe to execute (static validation).
 */
export function isCommandSafe(command: string): { safe: boolean; reason?: string } {
  // Check dangerous patterns
  for (const pattern of DANGEROUS_PATTERNS) {
    if (pattern.test(command)) {
      return { safe: false, reason: 'Matches dangerous pattern' };
    }
  }

  // Check blocked commands
  for (const blocked of BLOCKED_COMMANDS) {
    if (command.includes(blocked)) {
      return { safe: false, reason: `Contains blocked command: ${blocked}` };
    }
  }

  return { safe: true };
}

/**
 * Sanitize a command argument for safe shell use.
 */
export function sanitizeArgument(arg: string): string {
  // Escape special shell characters
  return arg.replace(/([\\$`"!])/g, '\\$1');
}

/**
 * Build a safe command string from parts.
 */
export function buildSafeCommand(command: string, args: string[]): string {
  const sanitizedArgs = args.map((arg) => {
    // Quote arguments with spaces or special chars
    if (/[\s\\$`"'!*?<>|;&]/.test(arg)) {
      return `"${sanitizeArgument(arg)}"`;
    }
    return arg;
  });

  return `${command} ${sanitizedArgs.join(' ')}`;
}
