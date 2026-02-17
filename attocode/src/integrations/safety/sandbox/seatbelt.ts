/**
 * Seatbelt Sandbox (macOS)
 *
 * Uses macOS sandbox-exec with Seatbelt profiles to restrict command execution.
 * Seatbelt is Apple's mandatory access control framework.
 *
 * Key features:
 * - Fine-grained file system access control
 * - Network access restrictions
 * - Process spawning limits
 * - Signal restrictions
 *
 * Note: This uses spawn() with explicit shell arguments for the sandboxed execution.
 * The sandbox itself provides the security layer - we're wrapping shell execution
 * with OS-level access controls.
 *
 * Reference: https://reverse.put.as/wp-content/uploads/2011/09/Apple-Sandbox-Guide-v1.0.pdf
 */

import { spawn, execSync } from 'child_process';
import type { Sandbox, SandboxMode, SandboxOptions, ExecResult } from './index.js';

// =============================================================================
// SEATBELT PROFILE GENERATION
// =============================================================================

/**
 * Generate a Seatbelt profile based on options.
 */
function generateSeatbeltProfile(options: SandboxOptions): string {
  const writablePaths = options.writablePaths ?? ['.'];
  const readablePaths = options.readablePaths ?? ['/'];
  const networkAllowed = options.networkAllowed ?? false;
  const workingDir = options.workingDir ?? process.cwd();

  // Start with version declaration and deny default
  const rules: string[] = ['(version 1)', '(deny default)'];

  // Allow process management
  rules.push('(allow process-fork)');
  rules.push('(allow process-exec)');
  rules.push('(allow signal (target self))');

  // Allow system basics
  rules.push('(allow sysctl-read)');
  rules.push('(allow mach-lookup)');
  rules.push('(allow ipc-posix-shm)');

  // Allow file reads for standard paths
  const standardReadPaths = [
    '/bin',
    '/usr/bin',
    '/usr/local/bin',
    '/opt/homebrew/bin',
    '/sbin',
    '/usr/sbin',
    '/lib',
    '/usr/lib',
    '/usr/local/lib',
    '/opt/homebrew/lib',
    '/System',
    '/Library/Frameworks',
    '/private/var/db',
    '/dev/null',
    '/dev/urandom',
    '/dev/random',
    '/dev/tty',
    '/etc',
    '/private/etc',
    '/var/folders', // Temp files
    '/private/var/folders',
    '/tmp',
    '/private/tmp',
  ];

  // Add read access for standard paths
  for (const path of standardReadPaths) {
    rules.push(`(allow file-read* (subpath "${path}"))`);
  }

  // Add user-specified readable paths
  for (const path of readablePaths) {
    const resolvedPath = resolvePath(path, workingDir);
    rules.push(`(allow file-read* (subpath "${resolvedPath}"))`);
  }

  // Add write access for specified paths
  for (const path of writablePaths) {
    const resolvedPath = resolvePath(path, workingDir);
    rules.push(`(allow file-read* (subpath "${resolvedPath}"))`);
    rules.push(`(allow file-write* (subpath "${resolvedPath}"))`);
  }

  // Temp directory access
  rules.push('(allow file-read* (subpath "/tmp"))');
  rules.push('(allow file-write* (subpath "/tmp"))');
  rules.push('(allow file-read* (subpath "/private/tmp"))');
  rules.push('(allow file-write* (subpath "/private/tmp"))');

  // Allow write to stderr/stdout
  rules.push('(allow file-write* (literal "/dev/tty"))');
  rules.push('(allow file-write* (literal "/dev/null"))');

  // Network access
  if (networkAllowed) {
    rules.push('(allow network*)');
  } else {
    // Still allow localhost for dev servers
    rules.push('(allow network-inbound (local ip "*:*"))');
    rules.push('(allow network-outbound (local ip "localhost:*"))');
    rules.push('(allow network-outbound (local ip "127.0.0.1:*"))');
    rules.push('(allow network-outbound (local ip "::1:*"))');
  }

  return rules.join('\n');
}

/**
 * Resolve a path relative to working directory.
 */
function resolvePath(path: string, workingDir: string): string {
  if (path.startsWith('/')) {
    return path;
  }
  if (path === '.') {
    return workingDir;
  }
  return `${workingDir}/${path}`;
}

// =============================================================================
// SEATBELT SANDBOX
// =============================================================================

/**
 * macOS Seatbelt sandbox implementation.
 */
export class SeatbeltSandbox implements Sandbox {
  private options: SandboxOptions;
  private available: boolean | null = null;

  constructor(options: SandboxOptions) {
    this.options = options;
  }

  /**
   * Execute a command inside the Seatbelt sandbox.
   *
   * Note: We use spawn with 'bash -c' because the sandbox-exec command
   * itself provides the security boundary. The command string is passed
   * to the sandboxed shell, which has restricted access via Seatbelt.
   */
  async execute(command: string, options?: Partial<SandboxOptions>): Promise<ExecResult> {
    const mergedOptions = { ...this.options, ...options };
    const profile = generateSeatbeltProfile(mergedOptions);
    const timeout = mergedOptions.timeout ?? 60000;
    const workDir = mergedOptions.workingDir ?? process.cwd();

    return new Promise((resolve) => {
      // sandbox-exec -p 'profile' bash -c 'command'
      // The sandbox profile restricts what the shell can do
      const proc = spawn('sandbox-exec', ['-p', profile, 'bash', '-c', command], {
        cwd: workDir,
        env: {
          ...process.env,
          ...mergedOptions.env,
          // Add common paths to PATH
          PATH: [process.env.PATH, '/usr/local/bin', '/opt/homebrew/bin', '/usr/bin', '/bin']
            .filter(Boolean)
            .join(':'),
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

        // Check if the sandbox blocked something
        const sandboxError = this.parseSandboxError(stderr);

        resolve({
          stdout,
          stderr,
          exitCode: code ?? 1,
          killed,
          timedOut,
          error: sandboxError,
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
   * Check if Seatbelt is available on this system.
   */
  async isAvailable(): Promise<boolean> {
    if (this.available !== null) {
      return this.available;
    }

    // Must be macOS
    if (process.platform !== 'darwin') {
      this.available = false;
      return false;
    }

    // Check if sandbox-exec exists
    try {
      execSync('which sandbox-exec', { stdio: 'pipe' });
      this.available = true;
      return true;
    } catch {
      this.available = false;
      return false;
    }
  }

  /**
   * Get sandbox type.
   */
  getType(): SandboxMode {
    return 'seatbelt';
  }

  /**
   * Cleanup resources.
   */
  async cleanup(): Promise<void> {
    // No persistent resources to clean up
  }

  /**
   * Parse sandbox error from stderr.
   */
  private parseSandboxError(stderr: string): string | undefined {
    // Look for sandbox denial messages
    if (stderr.includes('sandbox-exec:') || stderr.includes('deny')) {
      const match = stderr.match(/sandbox-exec: (.+)/);
      if (match) {
        return `Sandbox denied: ${match[1]}`;
      }
    }
    return undefined;
  }
}

// =============================================================================
// PREDEFINED PROFILES
// =============================================================================

/**
 * Strict profile - minimal access for pure computation.
 */
export const STRICT_PROFILE: SandboxOptions = {
  writablePaths: [],
  readablePaths: ['/usr/lib', '/System'],
  networkAllowed: false,
  timeout: 30000,
  maxMemoryMB: 256,
  maxCpuSeconds: 10,
};

/**
 * Development profile - allows npm, node, git operations.
 */
export const DEV_PROFILE: SandboxOptions = {
  writablePaths: ['.', 'node_modules', '.git'],
  readablePaths: ['/'],
  networkAllowed: true, // Allow npm install
  timeout: 300000, // 5 minutes
  maxMemoryMB: 1024,
  maxCpuSeconds: 120,
};

/**
 * Build profile - allows compilation but no network.
 */
export const BUILD_PROFILE: SandboxOptions = {
  writablePaths: ['.', 'dist', 'build', 'node_modules/.cache'],
  readablePaths: ['/'],
  networkAllowed: false,
  timeout: 300000,
  maxMemoryMB: 2048,
  maxCpuSeconds: 300,
};

/**
 * Test profile - allows test execution with limited write access.
 */
export const TEST_PROFILE: SandboxOptions = {
  writablePaths: ['.', 'coverage', 'test-results', 'node_modules/.cache'],
  readablePaths: ['/'],
  networkAllowed: false, // Tests should be isolated
  timeout: 600000, // 10 minutes
  maxMemoryMB: 1024,
  maxCpuSeconds: 300,
};
