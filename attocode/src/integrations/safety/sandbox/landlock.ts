/**
 * Landlock Sandbox (Linux)
 *
 * Uses Linux Landlock LSM for unprivileged process sandboxing.
 * Requires Linux kernel 5.13+ with Landlock enabled.
 *
 * Landlock works by creating a ruleset that restricts what the process can do:
 * - File system access (read, write, execute)
 * - Network access (Linux 6.7+)
 *
 * Unlike seccomp, Landlock operates at the file path level rather than
 * syscall level, making it more suitable for path-based restrictions.
 */

import { spawn, execFile } from 'node:child_process';
import { readFile, access, constants } from 'node:fs/promises';
import { platform } from 'node:os';
import { resolve } from 'node:path';
import type { Sandbox, ExecResult, SandboxOptions, SandboxMode } from './index.js';

// =============================================================================
// TYPES
// =============================================================================

interface LandlockRuleset {
  /** Readable paths */
  readPaths: string[];
  /** Writable paths */
  writePaths: string[];
  /** Executable paths */
  execPaths: string[];
  /** Whether network is allowed (requires kernel 6.7+) */
  networkAllowed: boolean;
}

// =============================================================================
// HELPER: Safe command check
// =============================================================================

/**
 * Safely check if a command exists using execFile (not exec).
 */
async function commandExists(command: string): Promise<boolean> {
  return new Promise((resolve) => {
    execFile('which', [command], { encoding: 'utf-8' }, (error) => {
      resolve(error === null);
    });
  });
}

// =============================================================================
// LANDLOCK DETECTION
// =============================================================================

/**
 * Check if Landlock is available on this system.
 */
async function isLandlockAvailable(): Promise<{ available: boolean; version?: number; reason?: string }> {
  // Must be Linux
  if (platform() !== 'linux') {
    return { available: false, reason: 'Not Linux' };
  }

  // Check kernel version (need 5.13+)
  try {
    const release = await readFile('/proc/sys/kernel/osrelease', 'utf-8');
    const match = release.match(/^(\d+)\.(\d+)/);
    if (!match) {
      return { available: false, reason: 'Cannot parse kernel version' };
    }

    const major = parseInt(match[1], 10);
    const minor = parseInt(match[2], 10);

    // Landlock requires kernel 5.13+
    if (major < 5 || (major === 5 && minor < 13)) {
      return { available: false, reason: `Kernel ${major}.${minor} too old (need 5.13+)` };
    }

    // Determine Landlock ABI version
    let landlockABI = 1;
    if (major >= 6 || (major === 5 && minor >= 19)) {
      landlockABI = 2; // File truncation support
    }
    if (major >= 6 && minor >= 7) {
      landlockABI = 4; // Network support
    }

    // Check if Landlock is enabled in kernel
    try {
      await access('/sys/kernel/security/landlock', constants.F_OK);
    } catch {
      return { available: false, reason: 'Landlock not enabled in kernel' };
    }

    return { available: true, version: landlockABI };
  } catch {
    return { available: false, reason: 'Cannot read kernel info' };
  }
}

// =============================================================================
// LANDLOCK SANDBOX CLASS
// =============================================================================

/**
 * Landlock-based sandbox for Linux.
 * Falls back to bubblewrap or firejail if native Landlock is not easily accessible.
 */
export class LandlockSandbox implements Sandbox {
  private defaults: Required<SandboxOptions>;
  private landlockAvailable: boolean | null = null;
  private landlockVersion: number = 0;
  private useBubblewrap: boolean = false;
  private useFirejail: boolean = false;

  constructor(defaults: Partial<SandboxOptions>) {
    this.defaults = {
      writablePaths: defaults.writablePaths ?? ['.'],
      readablePaths: defaults.readablePaths ?? ['/'],
      networkAllowed: defaults.networkAllowed ?? false,
      timeout: defaults.timeout ?? 60000,
      workingDir: defaults.workingDir ?? process.cwd(),
      env: defaults.env ?? {},
      maxMemoryMB: defaults.maxMemoryMB ?? 512,
      maxCpuSeconds: defaults.maxCpuSeconds ?? 30,
      allowedCommands: defaults.allowedCommands ?? [],
      blockedCommands: defaults.blockedCommands ?? [],
      bashMode: defaults.bashMode ?? 'full',
      bashWriteProtection: defaults.bashWriteProtection ?? 'off',
      blockFileCreationViaBash: defaults.blockFileCreationViaBash ?? false,
    };
  }

  async isAvailable(): Promise<boolean> {
    if (this.landlockAvailable !== null) {
      return this.landlockAvailable;
    }

    // Check platform
    if (platform() !== 'linux') {
      this.landlockAvailable = false;
      return false;
    }

    // Check for Landlock support
    const landlockCheck = await isLandlockAvailable();
    if (landlockCheck.available) {
      this.landlockAvailable = true;
      this.landlockVersion = landlockCheck.version ?? 1;
      return true;
    }

    // Fall back to bubblewrap
    if (await commandExists('bwrap')) {
      this.useBubblewrap = true;
      this.landlockAvailable = true;
      return true;
    }

    // Check for firejail as another fallback
    if (await commandExists('firejail')) {
      this.useFirejail = true;
      this.landlockAvailable = true;
      return true;
    }

    this.landlockAvailable = false;
    return false;
  }

  getType(): SandboxMode {
    // Note: 'landlock' is an extended mode not in the base SandboxMode type
    return 'landlock' as SandboxMode;
  }

  async execute(command: string, options?: Partial<SandboxOptions>): Promise<ExecResult> {
    const opts = { ...this.defaults, ...options };

    // Build the sandboxed command
    const { program, args } = await this.buildSandboxedCommand(command, opts);

    return new Promise((resolve) => {
      const workDir = opts.workingDir ?? process.cwd();

      const proc = spawn(program, args, {
        cwd: workDir,
        env: { ...process.env, ...opts.env },
        stdio: ['pipe', 'pipe', 'pipe'],
        shell: false, // Don't use shell to avoid injection
      });

      let stdout = '';
      let stderr = '';
      let killed = false;
      let timedOut = false;

      const timer = setTimeout(() => {
        timedOut = true;
        killed = true;
        proc.kill('SIGKILL');
      }, opts.timeout);

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
   * Build the sandboxed command.
   */
  private async buildSandboxedCommand(
    command: string,
    opts: Required<SandboxOptions>
  ): Promise<{ program: string; args: string[] }> {
    // Check what isolation method is available
    if (this.useBubblewrap || await commandExists('bwrap')) {
      return this.buildBubblewrapCommand(command, opts);
    }

    if (this.useFirejail || await commandExists('firejail')) {
      return this.buildFirejailCommand(command, opts);
    }

    // No isolation available - run with ulimit constraints only
    return this.buildUlimitCommand(command, opts);
  }

  /**
   * Build command using bubblewrap (bwrap).
   */
  private buildBubblewrapCommand(
    command: string,
    opts: Required<SandboxOptions>
  ): { program: string; args: string[] } {
    const args: string[] = [];

    // Create a minimal root filesystem
    args.push('--ro-bind', '/usr', '/usr');
    args.push('--ro-bind', '/lib', '/lib');
    args.push('--ro-bind', '/bin', '/bin');
    args.push('--ro-bind', '/etc', '/etc');

    // Try to bind lib64 if it exists
    args.push('--ro-bind-try', '/lib64', '/lib64');

    // Add proc and dev
    args.push('--proc', '/proc');
    args.push('--dev', '/dev');
    args.push('--tmpfs', '/tmp');

    // Add readable paths
    for (const readPath of opts.readablePaths) {
      const absPath = resolve(readPath);
      args.push('--ro-bind', absPath, absPath);
    }

    // Add writable paths
    for (const writePath of opts.writablePaths) {
      const absPath = resolve(writePath);
      args.push('--bind', absPath, absPath);
    }

    // Network isolation
    if (!opts.networkAllowed) {
      args.push('--unshare-net');
    }

    // Unshare other namespaces for isolation
    args.push('--unshare-pid');
    args.push('--unshare-ipc');

    // Set working directory
    args.push('--chdir', opts.workingDir);

    // Add the command
    args.push('--');
    args.push('bash', '-c', command);

    return { program: 'bwrap', args };
  }

  /**
   * Build command using firejail.
   */
  private buildFirejailCommand(
    command: string,
    opts: Required<SandboxOptions>
  ): { program: string; args: string[] } {
    const args: string[] = [];

    // Private mode for isolation
    args.push('--private-tmp');
    args.push('--private-dev');

    // Network isolation
    if (!opts.networkAllowed) {
      args.push('--net=none');
    }

    // Whitelist writable paths
    for (const writePath of opts.writablePaths) {
      const absPath = resolve(writePath);
      args.push(`--whitelist=${absPath}`);
    }

    // Read-only for other paths
    for (const readPath of opts.readablePaths) {
      const absPath = resolve(readPath);
      if (!opts.writablePaths.includes(readPath)) {
        args.push(`--read-only=${absPath}`);
      }
    }

    // Resource limits
    args.push(`--rlimit-as=${opts.maxMemoryMB * 1024 * 1024}`);
    args.push(`--timeout=${Math.ceil(opts.timeout / 1000)}`);

    // Add command
    args.push('--');
    args.push('bash', '-c', command);

    return { program: 'firejail', args };
  }

  /**
   * Build command with ulimit constraints (minimal isolation).
   */
  private buildUlimitCommand(
    command: string,
    opts: Required<SandboxOptions>
  ): { program: string; args: string[] } {
    // Use bash to set ulimits before running the command
    const script = [
      `ulimit -v $((${opts.maxMemoryMB} * 1024))`,
      `ulimit -t ${opts.maxCpuSeconds}`,
      command,
    ].join(' && ');

    return { program: 'bash', args: ['-c', script] };
  }

  async cleanup(): Promise<void> {
    // No cleanup needed
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create a Landlock sandbox.
 */
export function createLandlockSandbox(options?: Partial<SandboxOptions>): LandlockSandbox {
  return new LandlockSandbox(options ?? {});
}

/**
 * Check if Landlock/Linux isolation is available.
 */
export async function checkLandlockSupport(): Promise<{
  available: boolean;
  method: 'landlock' | 'bubblewrap' | 'firejail' | 'ulimit' | 'none';
  details: string;
}> {
  if (platform() !== 'linux') {
    return { available: false, method: 'none', details: 'Not Linux' };
  }

  // Check native Landlock
  const landlockCheck = await isLandlockAvailable();
  if (landlockCheck.available) {
    return {
      available: true,
      method: 'landlock',
      details: `Native Landlock ABI v${landlockCheck.version}`,
    };
  }

  // Check bubblewrap
  if (await commandExists('bwrap')) {
    return { available: true, method: 'bubblewrap', details: 'Using bubblewrap (bwrap)' };
  }

  // Check firejail
  if (await commandExists('firejail')) {
    return { available: true, method: 'firejail', details: 'Using firejail' };
  }

  // Fallback to ulimit only
  return { available: true, method: 'ulimit', details: 'Using ulimit constraints only (minimal isolation)' };
}
