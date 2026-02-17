/**
 * Persistent PTY Shell
 *
 * Provides a persistent shell session that maintains state between commands.
 * Uses Node.js child_process with PTY-like behavior.
 *
 * Key features:
 * - Persistent shell process (bash/zsh)
 * - Command history tracking
 * - Environment inheritance
 * - Working directory state
 * - Output buffering with timeout
 */

import { spawn, ChildProcess } from 'node:child_process';
import { platform } from 'node:os';

// =============================================================================
// TYPES
// =============================================================================

export interface PTYShellConfig {
  /** Shell to use (default: auto-detect) */
  shell?: string;
  /** Initial working directory */
  cwd?: string;
  /** Environment variables */
  env?: Record<string, string>;
  /** Command timeout in ms (default: 30000) */
  timeout?: number;
  /** Maximum output buffer size (default: 1MB) */
  maxOutputSize?: number;
  /** Shell prompt to detect command completion */
  promptPattern?: string;
}

export interface CommandResult {
  output: string;
  exitCode: number | null;
  duration: number;
  timedOut: boolean;
}

export interface ShellState {
  cwd: string;
  env: Record<string, string>;
  history: string[];
  isRunning: boolean;
  pid?: number;
}

export type PTYEvent =
  | { type: 'shell.started'; pid: number; shell: string }
  | { type: 'shell.stopped'; exitCode: number | null }
  | { type: 'command.start'; command: string }
  | { type: 'command.output'; data: string }
  | { type: 'command.complete'; result: CommandResult }
  | { type: 'command.timeout'; command: string }
  | { type: 'error'; error: string };

export type PTYEventListener = (event: PTYEvent) => void;

// =============================================================================
// PTY SHELL MANAGER
// =============================================================================

/**
 * Manages persistent shell sessions.
 */
export class PTYShellManager {
  private config: Required<PTYShellConfig>;
  private process: ChildProcess | null = null;
  private outputBuffer: string = '';
  private commandHistory: string[] = [];
  private currentCwd: string;
  private currentEnv: Record<string, string>;
  private commandResolve: ((result: CommandResult) => void) | null = null;
  private commandStartTime: number = 0;
  private commandTimeoutId: NodeJS.Timeout | null = null;
  private eventListeners: Set<PTYEventListener> = new Set();
  private readonly endMarker: string;

  constructor(config: PTYShellConfig = {}) {
    this.config = {
      shell: config.shell || this.detectShell(),
      cwd: config.cwd || process.cwd(),
      env: config.env || {},
      timeout: config.timeout ?? 30000,
      maxOutputSize: config.maxOutputSize ?? 1024 * 1024, // 1MB
      promptPattern: config.promptPattern || '__CMD_DONE__',
    };
    this.currentCwd = this.config.cwd;
    this.currentEnv = { ...process.env, ...this.config.env } as Record<string, string>;
    this.endMarker = `\necho "${this.config.promptPattern} $?"`;
  }

  /**
   * Auto-detect the user's preferred shell.
   */
  private detectShell(): string {
    const userShell = process.env.SHELL;
    if (userShell) return userShell;

    if (platform() === 'win32') {
      return 'cmd.exe';
    }

    return '/bin/bash';
  }

  /**
   * Start the persistent shell.
   */
  async start(): Promise<void> {
    if (this.process && !this.process.killed) {
      return; // Already running
    }

    return new Promise((resolve, reject) => {
      const env = {
        ...process.env,
        ...this.config.env,
        // Disable shell prompt customization that might interfere
        PS1: '$ ',
        PROMPT_COMMAND: '',
      };

      this.process = spawn(this.config.shell, [], {
        cwd: this.config.cwd,
        env,
        stdio: ['pipe', 'pipe', 'pipe'],
        shell: false, // We're spawning a shell directly
      });

      // Set up output handlers
      this.process.stdout?.on('data', (data: Buffer) => {
        const output = data.toString();
        this.handleOutput(output);
      });

      this.process.stderr?.on('data', (data: Buffer) => {
        const output = data.toString();
        this.handleOutput(output);
      });

      this.process.on('error', (error) => {
        this.emitEvent({ type: 'error', error: error.message });
        reject(error);
      });

      this.process.on('exit', (code) => {
        this.emitEvent({ type: 'shell.stopped', exitCode: code });
        this.process = null;
      });

      // Wait a bit for shell to initialize
      setTimeout(() => {
        if (this.process && this.process.pid) {
          this.emitEvent({
            type: 'shell.started',
            pid: this.process.pid,
            shell: this.config.shell,
          });
          resolve();
        } else {
          reject(new Error('Failed to start shell'));
        }
      }, 100);
    });
  }

  /**
   * Handle output from the shell.
   */
  private handleOutput(data: string): void {
    this.outputBuffer += data;
    this.emitEvent({ type: 'command.output', data });

    // Trim buffer if too large
    if (this.outputBuffer.length > this.config.maxOutputSize) {
      this.outputBuffer = this.outputBuffer.slice(-this.config.maxOutputSize);
    }

    // Check for command completion
    if (this.commandResolve && this.outputBuffer.includes(this.config.promptPattern)) {
      this.handleCommandComplete();
    }
  }

  /**
   * Handle command completion.
   */
  private handleCommandComplete(): void {
    if (!this.commandResolve) return;

    // Clear timeout
    if (this.commandTimeoutId) {
      clearTimeout(this.commandTimeoutId);
      this.commandTimeoutId = null;
    }

    // Extract output and exit code
    const markerIndex = this.outputBuffer.lastIndexOf(this.config.promptPattern);
    let output = this.outputBuffer.slice(0, markerIndex).trim();
    const exitCodeMatch = this.outputBuffer.slice(markerIndex).match(/(\d+)/);
    const exitCode = exitCodeMatch ? parseInt(exitCodeMatch[1], 10) : null;

    // Remove the echo command from output
    const echoIndex = output.lastIndexOf('echo "');
    if (echoIndex !== -1) {
      output = output.slice(0, echoIndex).trim();
    }

    // Also remove any command echo (bash echoes input commands)
    const lines = output.split('\n');
    if (lines.length > 1 && this.commandHistory.length > 0) {
      const lastCmd = this.commandHistory[this.commandHistory.length - 1];
      if (lines[0].endsWith(lastCmd) || lines[0].includes(lastCmd)) {
        lines.shift();
        output = lines.join('\n');
      }
    }

    const result: CommandResult = {
      output: output.trim(),
      exitCode,
      duration: Date.now() - this.commandStartTime,
      timedOut: false,
    };

    this.emitEvent({ type: 'command.complete', result });

    const resolve = this.commandResolve;
    this.commandResolve = null;
    this.outputBuffer = '';

    resolve(result);
  }

  /**
   * Execute a command in the persistent shell.
   */
  async execute(command: string): Promise<CommandResult> {
    if (!this.process || this.process.killed) {
      await this.start();
    }

    if (!this.process?.stdin) {
      throw new Error('Shell not running');
    }

    // Track command
    this.commandHistory.push(command);
    this.commandStartTime = Date.now();
    this.outputBuffer = '';

    this.emitEvent({ type: 'command.start', command });

    return new Promise((resolve) => {
      this.commandResolve = resolve;

      // Set timeout
      this.commandTimeoutId = setTimeout(() => {
        if (this.commandResolve) {
          this.emitEvent({ type: 'command.timeout', command });

          const result: CommandResult = {
            output: this.outputBuffer.trim(),
            exitCode: null,
            duration: Date.now() - this.commandStartTime,
            timedOut: true,
          };

          this.commandResolve = null;
          this.outputBuffer = '';

          resolve(result);
        }
      }, this.config.timeout);

      // Write command with completion marker
      const fullCommand = `${command}${this.endMarker}\n`;
      this.process!.stdin!.write(fullCommand);
    });
  }

  /**
   * Change the working directory.
   */
  async cd(directory: string): Promise<CommandResult> {
    const result = await this.execute(`cd "${directory}" && pwd`);
    if (result.exitCode === 0) {
      this.currentCwd = result.output.trim();
    }
    return result;
  }

  /**
   * Set an environment variable.
   */
  async setEnv(key: string, value: string): Promise<void> {
    await this.execute(`export ${key}="${value}"`);
    this.currentEnv[key] = value;
  }

  /**
   * Get the current state.
   */
  getState(): ShellState {
    return {
      cwd: this.currentCwd,
      env: this.currentEnv,
      history: [...this.commandHistory],
      isRunning: this.process !== null && !this.process.killed,
      pid: this.process?.pid,
    };
  }

  /**
   * Get command history.
   */
  getHistory(): string[] {
    return [...this.commandHistory];
  }

  /**
   * Clear command history.
   */
  clearHistory(): void {
    this.commandHistory = [];
  }

  /**
   * Subscribe to events.
   */
  subscribe(listener: PTYEventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  /**
   * Emit an event.
   */
  private emitEvent(event: PTYEvent): void {
    for (const listener of this.eventListeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }

  /**
   * Stop the shell.
   */
  async stop(): Promise<void> {
    if (!this.process) return;

    return new Promise((resolve) => {
      if (!this.process) {
        resolve();
        return;
      }

      const timeout = setTimeout(() => {
        this.process?.kill('SIGKILL');
        resolve();
      }, 1000);

      this.process.once('exit', () => {
        clearTimeout(timeout);
        resolve();
      });

      // Try graceful exit first
      this.process.stdin?.write('exit\n');
    });
  }

  /**
   * Cleanup resources.
   */
  async cleanup(): Promise<void> {
    if (this.commandTimeoutId) {
      clearTimeout(this.commandTimeoutId);
    }
    await this.stop();
    this.eventListeners.clear();
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a PTY shell manager.
 */
export function createPTYShell(config?: PTYShellConfig): PTYShellManager {
  return new PTYShellManager(config);
}

/**
 * Create and start a PTY shell.
 */
export async function createAndStartPTYShell(config?: PTYShellConfig): Promise<PTYShellManager> {
  const shell = new PTYShellManager(config);
  await shell.start();
  return shell;
}

// =============================================================================
// TOOL FACTORY
// =============================================================================

/**
 * Create a shell execution tool that uses the persistent PTY.
 */
export function createPTYShellTool(shell: PTYShellManager) {
  return {
    name: 'shell_exec',
    description:
      'Execute a command in the persistent shell session. Maintains state between calls (working directory, environment variables, etc.)',
    parameters: {
      type: 'object',
      properties: {
        command: {
          type: 'string',
          description: 'The command to execute',
        },
      },
      required: ['command'],
    },
    dangerLevel: 'dangerous' as const,
    async execute(args: Record<string, unknown>) {
      const command = args.command as string;
      if (!command) {
        return 'Error: command is required';
      }

      const result = await shell.execute(command);

      if (result.timedOut) {
        return `Command timed out after ${result.duration}ms. Partial output:\n${result.output}`;
      }

      const exitInfo = result.exitCode !== 0 ? ` (exit code: ${result.exitCode})` : '';
      return `${result.output}${exitInfo}`;
    },
  };
}

/**
 * Format shell state for display.
 */
export function formatShellState(state: ShellState): string {
  const lines = [
    `Shell: ${state.isRunning ? 'Running' : 'Stopped'}${state.pid ? ` (PID: ${state.pid})` : ''}`,
    `CWD: ${state.cwd}`,
    `History: ${state.history.length} commands`,
  ];

  if (state.history.length > 0) {
    lines.push('Recent commands:');
    for (const cmd of state.history.slice(-5)) {
      lines.push(`  $ ${cmd}`);
    }
  }

  return lines.join('\n');
}
