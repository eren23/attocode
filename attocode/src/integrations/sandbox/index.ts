/**
 * OS-Specific Sandbox Integration
 *
 * Provides platform-aware sandboxing for command execution:
 * - macOS: Uses sandbox-exec with Seatbelt profiles
 * - Linux: Uses Docker containers for isolation
 * - Fallback: Basic allowlist-based validation
 *
 * Inspired by Codex's approach to secure code execution.
 *
 * Usage:
 *   const sandbox = createSandbox({ writablePaths: ['.'], networkAllowed: false });
 *   const result = await sandbox.execute('npm install');
 */

import { SeatbeltSandbox } from './seatbelt.js';
import { DockerSandbox } from './docker.js';
import { BasicSandbox } from './basic.js';
import { LandlockSandbox } from './landlock.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Sandbox execution result.
 */
export interface ExecResult {
  stdout: string;
  stderr: string;
  exitCode: number;
  killed: boolean;
  timedOut: boolean;
  error?: string;
}

/**
 * Sandbox configuration options.
 */
export interface SandboxOptions {
  /** Paths that can be written to */
  writablePaths?: string[];

  /** Paths that can be read from */
  readablePaths?: string[];

  /** Whether network access is allowed */
  networkAllowed?: boolean;

  /** Execution timeout in milliseconds */
  timeout?: number;

  /** Working directory */
  workingDir?: string;

  /** Environment variables */
  env?: Record<string, string>;

  /** Maximum memory in MB */
  maxMemoryMB?: number;

  /** Maximum CPU time in seconds */
  maxCpuSeconds?: number;

  /** Allowed commands (for basic sandbox) */
  allowedCommands?: string[];

  /** Blocked commands (for basic sandbox) */
  blockedCommands?: string[];

  /** Bash policy mode */
  bashMode?: 'disabled' | 'read_only' | 'task_scoped' | 'full';

  /** Bash write protection behavior */
  bashWriteProtection?: 'off' | 'block_file_mutation';

  /** Legacy compatibility flag */
  blockFileCreationViaBash?: boolean;
}

/**
 * Sandbox mode.
 */
export type SandboxMode = 'auto' | 'seatbelt' | 'landlock' | 'docker' | 'basic' | 'none';

/**
 * Sandbox interface that all implementations must follow.
 */
export interface Sandbox {
  /** Execute a command in the sandbox */
  execute(command: string, options?: Partial<SandboxOptions>): Promise<ExecResult>;

  /** Check if the sandbox is available on this system */
  isAvailable(): Promise<boolean>;

  /** Get the sandbox type name */
  getType(): SandboxMode;

  /** Cleanup any resources */
  cleanup(): Promise<void>;
}

/**
 * Sandbox manager configuration.
 */
export interface SandboxManagerConfig {
  /** Sandbox mode to use */
  mode?: SandboxMode;

  /** Default sandbox options */
  defaults?: SandboxOptions;

  /** Docker image to use (for docker mode) */
  dockerImage?: string;

  /** Enable verbose logging */
  verbose?: boolean;
}

/**
 * Sandbox event types.
 */
export type SandboxEvent =
  | { type: 'sandbox.execute.start'; command: string; mode: SandboxMode }
  | { type: 'sandbox.execute.complete'; command: string; exitCode: number; duration: number }
  | { type: 'sandbox.execute.error'; command: string; error: string }
  | { type: 'sandbox.blocked'; command: string; reason: string }
  | { type: 'sandbox.mode.changed'; from: SandboxMode; to: SandboxMode };

export type SandboxEventListener = (event: SandboxEvent) => void;

// =============================================================================
// DEFAULT OPTIONS
// =============================================================================

const DEFAULT_OPTIONS: Required<SandboxOptions> = {
  writablePaths: ['.'],
  readablePaths: ['/'],
  networkAllowed: false,
  timeout: 60000, // 1 minute
  workingDir: process.cwd(),
  env: {},
  maxMemoryMB: 512,
  maxCpuSeconds: 30,
  allowedCommands: [
    'node', 'npm', 'npx', 'yarn', 'pnpm', 'bun',
    'git', 'ls', 'cat', 'head', 'tail', 'grep', 'find', 'wc',
    'echo', 'pwd', 'which', 'env', 'mkdir', 'cp', 'mv', 'touch',
    'tsc', 'eslint', 'prettier', 'jest', 'vitest', 'mocha',
  ],
  blockedCommands: [
    'rm -rf /',
    'rm -rf ~',
    'sudo',
    'chmod 777',
    'curl | sh',
    'curl | bash',
    'wget | sh',
    'wget | bash',
    ':(){:|:&};:',
    'mkfs',
    'dd if=/dev/zero',
  ],
  bashMode: 'full',
  bashWriteProtection: 'off',
  blockFileCreationViaBash: false,
};

// =============================================================================
// SANDBOX MANAGER
// =============================================================================

/**
 * Manages sandbox selection and execution.
 */
export class SandboxManager {
  private config: Required<SandboxManagerConfig>;
  private activeSandbox: Sandbox | null = null;
  private eventListeners: Set<SandboxEventListener> = new Set();

  constructor(config: SandboxManagerConfig = {}) {
    this.config = {
      mode: config.mode ?? 'auto',
      defaults: { ...DEFAULT_OPTIONS, ...config.defaults },
      dockerImage: config.dockerImage ?? 'agent-sandbox:latest',
      verbose: config.verbose ?? false,
    };
  }

  /**
   * Get or create the appropriate sandbox for this system.
   */
  async getSandbox(): Promise<Sandbox> {
    if (this.activeSandbox) {
      return this.activeSandbox;
    }

    this.activeSandbox = await this.createSandbox(this.config.mode);
    return this.activeSandbox;
  }

  /**
   * Execute a command in the sandbox.
   */
  async execute(command: string, options?: Partial<SandboxOptions>): Promise<ExecResult> {
    const sandbox = await this.getSandbox();
    const startTime = Date.now();

    this.emit({
      type: 'sandbox.execute.start',
      command,
      mode: sandbox.getType(),
    });

    try {
      const mergedOptions = { ...this.config.defaults, ...options };
      const result = await sandbox.execute(command, mergedOptions);

      const duration = Date.now() - startTime;
      this.emit({
        type: 'sandbox.execute.complete',
        command,
        exitCode: result.exitCode,
        duration,
      });

      return result;
    } catch (err) {
      const error = err instanceof Error ? err.message : String(err);
      this.emit({ type: 'sandbox.execute.error', command, error });
      throw err;
    }
  }

  /**
   * Check if a command should be blocked.
   */
  isCommandBlocked(command: string): { blocked: boolean; reason?: string } {
    const blockedPatterns = this.config.defaults.blockedCommands ?? [];

    for (const pattern of blockedPatterns) {
      if (command.includes(pattern)) {
        return { blocked: true, reason: `Command contains blocked pattern: ${pattern}` };
      }
    }

    // Check for dangerous patterns
    const dangerousPatterns = [
      /rm\s+-[rf]*\s+\/(?!\w)/,        // rm -rf / or similar
      />\s*\/dev\/sd[a-z]/,             // writing to block devices
      /mkfs/,                            // formatting filesystems
      /:\(\)\{.*\};:/,                   // fork bomb
      /wget.*\|\s*(?:ba)?sh/,            // download and execute
      /curl.*\|\s*(?:ba)?sh/,            // download and execute
    ];

    for (const pattern of dangerousPatterns) {
      if (pattern.test(command)) {
        return { blocked: true, reason: `Command matches dangerous pattern` };
      }
    }

    return { blocked: false };
  }

  /**
   * Set the sandbox mode.
   */
  async setMode(mode: SandboxMode): Promise<void> {
    if (mode === this.config.mode) return;

    const oldMode = this.config.mode;

    // Cleanup old sandbox
    if (this.activeSandbox) {
      await this.activeSandbox.cleanup();
      this.activeSandbox = null;
    }

    this.config.mode = mode;
    this.emit({ type: 'sandbox.mode.changed', from: oldMode, to: mode });
  }

  /**
   * Get the current sandbox mode.
   */
  getMode(): SandboxMode {
    return this.config.mode;
  }

  /**
   * Get info about available sandboxes.
   */
  async getAvailableSandboxes(): Promise<{ mode: SandboxMode; available: boolean }[]> {
    const results: { mode: SandboxMode; available: boolean }[] = [];

    // Check Seatbelt (macOS)
    const seatbelt = new SeatbeltSandbox(this.config.defaults);
    results.push({ mode: 'seatbelt', available: await seatbelt.isAvailable() });

    // Check Landlock (Linux)
    const landlock = new LandlockSandbox(this.config.defaults);
    results.push({ mode: 'landlock', available: await landlock.isAvailable() });

    // Check Docker
    const docker = new DockerSandbox(this.config.defaults, this.config.dockerImage);
    results.push({ mode: 'docker', available: await docker.isAvailable() });

    // Basic is always available
    results.push({ mode: 'basic', available: true });

    // None is always available
    results.push({ mode: 'none', available: true });

    return results;
  }

  /**
   * Subscribe to sandbox events.
   */
  subscribe(listener: SandboxEventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  /**
   * Cleanup resources.
   */
  async cleanup(): Promise<void> {
    if (this.activeSandbox) {
      await this.activeSandbox.cleanup();
      this.activeSandbox = null;
    }
    this.eventListeners.clear();
  }

  // Internal methods

  /**
   * Create a sandbox based on mode.
   */
  private async createSandbox(mode: SandboxMode): Promise<Sandbox> {
    if (mode === 'auto') {
      return this.autoDetectSandbox();
    }

    switch (mode) {
      case 'seatbelt': {
        const seatbelt = new SeatbeltSandbox(this.config.defaults);
        if (await seatbelt.isAvailable()) {
          return seatbelt;
        }
        throw new Error('Seatbelt sandbox not available (requires macOS)');
      }

      case 'landlock': {
        const landlock = new LandlockSandbox(this.config.defaults);
        if (await landlock.isAvailable()) {
          return landlock;
        }
        throw new Error('Landlock sandbox not available (requires Linux with Landlock/bwrap/firejail)');
      }

      case 'docker': {
        const docker = new DockerSandbox(this.config.defaults, this.config.dockerImage);
        if (await docker.isAvailable()) {
          return docker;
        }
        throw new Error('Docker sandbox not available');
      }

      case 'basic':
        return new BasicSandbox(this.config.defaults);

      case 'none':
        return new NoSandbox();

      default:
        throw new Error(`Unknown sandbox mode: ${mode}`);
    }
  }

  /**
   * Auto-detect the best available sandbox.
   */
  private async autoDetectSandbox(): Promise<Sandbox> {
    // Try Seatbelt first (macOS)
    if (process.platform === 'darwin') {
      const seatbelt = new SeatbeltSandbox(this.config.defaults);
      if (await seatbelt.isAvailable()) {
        if (this.config.verbose) {
          console.log('[Sandbox] Auto-detected: Seatbelt (macOS)');
        }
        return seatbelt;
      }
    }

    // Try Landlock on Linux (preferred over Docker for lower overhead)
    if (process.platform === 'linux') {
      const landlock = new LandlockSandbox(this.config.defaults);
      if (await landlock.isAvailable()) {
        if (this.config.verbose) {
          console.log('[Sandbox] Auto-detected: Landlock (Linux)');
        }
        return landlock;
      }
    }

    // Try Docker (any platform with Docker)
    const docker = new DockerSandbox(this.config.defaults, this.config.dockerImage);
    if (await docker.isAvailable()) {
      if (this.config.verbose) {
        console.log('[Sandbox] Auto-detected: Docker');
      }
      return docker;
    }

    // Fall back to basic sandbox
    if (this.config.verbose) {
      console.log('[Sandbox] Auto-detected: Basic (allowlist-based)');
    }
    return new BasicSandbox(this.config.defaults);
  }

  /**
   * Emit a sandbox event.
   */
  private emit(event: SandboxEvent): void {
    for (const listener of this.eventListeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }
}

// =============================================================================
// NO SANDBOX (PASSTHROUGH)
// =============================================================================

/**
 * No sandbox - executes commands directly (unsafe).
 */
class NoSandbox implements Sandbox {
  async execute(command: string, options?: Partial<SandboxOptions>): Promise<ExecResult> {
    const { spawn } = await import('child_process');

    return new Promise((resolve) => {
      const timeout = options?.timeout ?? 60000;
      const workDir = options?.workingDir ?? process.cwd();

      const proc = spawn('bash', ['-c', command], {
        cwd: workDir,
        env: { ...process.env, ...options?.env },
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

  async isAvailable(): Promise<boolean> {
    return true;
  }

  getType(): SandboxMode {
    return 'none';
  }

  async cleanup(): Promise<void> {
    // No cleanup needed
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a sandbox manager.
 */
export function createSandboxManager(config?: SandboxManagerConfig): SandboxManager {
  return new SandboxManager(config);
}

/**
 * Create a sandbox directly with auto-detection.
 */
export async function createSandbox(options?: SandboxOptions): Promise<Sandbox> {
  const manager = new SandboxManager({ defaults: options });
  return manager.getSandbox();
}

/**
 * Quick execute with auto-detected sandbox.
 */
export async function sandboxExec(
  command: string,
  options?: SandboxOptions
): Promise<ExecResult> {
  const sandbox = await createSandbox(options);
  try {
    return await sandbox.execute(command, options);
  } finally {
    await sandbox.cleanup();
  }
}

// =============================================================================
// RE-EXPORTS
// =============================================================================

export { SeatbeltSandbox } from './seatbelt.js';
export { DockerSandbox } from './docker.js';
export { BasicSandbox } from './basic.js';
export { LandlockSandbox, createLandlockSandbox, checkLandlockSupport } from './landlock.js';
