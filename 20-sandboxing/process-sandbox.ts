/**
 * Lesson 20: Process Sandbox
 *
 * OS-level process isolation using Node.js child processes
 * with resource limits and path restrictions.
 */

import { spawn, ChildProcess } from 'child_process';
import type {
  Sandbox,
  SandboxConfig,
  SandboxStatus,
  ExecutionCommand,
  ExecutionResult,
  ResourceUsage,
  KillReason,
  SandboxEvent,
  SandboxEventListener,
} from './types.js';
import { generateSandboxId, DEFAULT_SANDBOX_CONFIG, mergeConfig } from './types.js';
import {
  ResourceMonitor,
  LimitEnforcer,
  OutputLimiter,
  withTimeout,
  TimeoutError,
} from './resource-limits.js';

// =============================================================================
// PROCESS SANDBOX
// =============================================================================

/**
 * Sandbox using OS processes with restrictions.
 */
export class ProcessSandbox implements Sandbox {
  readonly id: string;
  readonly config: SandboxConfig;

  private listeners: Set<SandboxEventListener> = new Set();
  private executionCount: number = 0;
  private totalExecutionMs: number = 0;
  private activeProcess: ChildProcess | null = null;
  private monitor: ResourceMonitor;
  private enforcer: LimitEnforcer;

  constructor(config: Partial<SandboxConfig> = {}) {
    this.id = generateSandboxId();
    this.config = mergeConfig(config, DEFAULT_SANDBOX_CONFIG);
    this.monitor = new ResourceMonitor(this.id, this.config.resourceLimits);
    this.enforcer = new LimitEnforcer(this.config.resourceLimits);

    this.emit({
      type: 'sandbox.created',
      sandboxId: this.id,
      config: this.config,
    });
  }

  /**
   * Execute a command in the sandbox.
   */
  async execute(command: ExecutionCommand): Promise<ExecutionResult> {
    const startTime = Date.now();
    this.executionCount++;

    this.emit({
      type: 'execution.started',
      sandboxId: this.id,
      command,
    });

    // Validate command
    const validation = this.validateCommand(command);
    if (!validation.valid) {
      return this.createErrorResult(startTime, validation.reason || 'Invalid command');
    }

    // Build the command
    const fullCommand = this.buildCommand(command);

    // Create output limiters
    const stdoutLimiter = new OutputLimiter(this.config.resourceLimits.maxOutputBytes);
    const stderrLimiter = new OutputLimiter(this.config.resourceLimits.maxOutputBytes);

    // Start monitoring
    this.monitor.start();

    try {
      const result = await withTimeout(
        this.runProcess(fullCommand, command, stdoutLimiter, stderrLimiter),
        this.enforcer.getTimeoutMs(),
        () => this.killProcess('timeout')
      );

      const durationMs = Date.now() - startTime;
      this.totalExecutionMs += durationMs;

      const executionResult: ExecutionResult = {
        ...result,
        durationMs,
        sandboxId: this.id,
      };

      this.emit({
        type: 'execution.completed',
        sandboxId: this.id,
        result: executionResult,
      });

      return executionResult;
    } catch (err) {
      const durationMs = Date.now() - startTime;
      this.totalExecutionMs += durationMs;

      if (err instanceof TimeoutError) {
        return {
          exitCode: 124,
          stdout: stdoutLimiter.getOutput(),
          stderr: stderrLimiter.getOutput() + '\nExecution timed out',
          durationMs,
          resourceUsage: this.monitor.getUsage(),
          killed: true,
          killReason: 'timeout',
          sandboxId: this.id,
        };
      }

      return this.createErrorResult(
        startTime,
        err instanceof Error ? err.message : String(err)
      );
    } finally {
      this.monitor.stop();
      this.activeProcess = null;
    }
  }

  /**
   * Run the actual process.
   */
  private runProcess(
    fullCommand: string,
    command: ExecutionCommand,
    stdoutLimiter: OutputLimiter,
    stderrLimiter: OutputLimiter
  ): Promise<Omit<ExecutionResult, 'durationMs' | 'sandboxId'>> {
    return new Promise((resolve) => {
      const cwd = command.cwd || this.config.workingDirectory;
      const env = this.buildEnvironment(command.env);

      // Spawn with shell for command execution
      const shell = command.shell || '/bin/sh';
      this.activeProcess = spawn(shell, ['-c', fullCommand], {
        cwd,
        env,
        stdio: ['pipe', 'pipe', 'pipe'],
      });

      const proc = this.activeProcess;

      // Provide stdin if specified
      if (command.stdin) {
        proc.stdin?.write(command.stdin);
        proc.stdin?.end();
      } else {
        proc.stdin?.end();
      }

      // Collect stdout
      proc.stdout?.on('data', (data: Buffer) => {
        const str = data.toString();
        if (!stdoutLimiter.append(str)) {
          // Output limit reached
          this.killProcess('output_limit');
        }
      });

      // Collect stderr
      proc.stderr?.on('data', (data: Buffer) => {
        const str = data.toString();
        stderrLimiter.append(str);
      });

      let killed = false;
      let killReason: KillReason | undefined;

      proc.on('close', (code) => {
        resolve({
          exitCode: code ?? 1,
          stdout: stdoutLimiter.getOutput(),
          stderr: stderrLimiter.getOutput(),
          resourceUsage: this.monitor.getUsage(),
          killed,
          killReason,
        });
      });

      proc.on('error', (err) => {
        resolve({
          exitCode: 1,
          stdout: stdoutLimiter.getOutput(),
          stderr: stderrLimiter.getOutput() + '\n' + err.message,
          resourceUsage: this.monitor.getUsage(),
          killed: false,
        });
      });

      // Monitor for resource limits
      const limitInterval = setInterval(() => {
        const limitExceeded = this.monitor.checkLimits();
        if (limitExceeded) {
          killed = true;
          killReason = limitExceeded;
          this.killProcess(limitExceeded);
          clearInterval(limitInterval);
        }
      }, 100);

      proc.on('close', () => {
        clearInterval(limitInterval);
      });
    });
  }

  /**
   * Kill the active process.
   */
  private killProcess(reason: KillReason): void {
    if (this.activeProcess && !this.activeProcess.killed) {
      this.activeProcess.kill('SIGKILL');

      this.emit({
        type: 'execution.killed',
        sandboxId: this.id,
        reason,
      });
    }
  }

  /**
   * Validate command against sandbox rules.
   */
  private validateCommand(command: ExecutionCommand): { valid: boolean; reason?: string } {
    // Check for dangerous patterns
    const dangerous = [
      /rm\s+-rf\s+\//, // rm -rf /
      /:\s*>\s*\//, // : > / (truncate root files)
      /mkfs/, // Format filesystems
      /dd\s+.*of=\/dev/, // Write to devices
    ];

    const fullCmd = `${command.command} ${command.args.join(' ')}`;

    for (const pattern of dangerous) {
      if (pattern.test(fullCmd)) {
        this.emit({
          type: 'security.violation',
          sandboxId: this.id,
          violation: `Dangerous command pattern detected: ${pattern}`,
        });
        return { valid: false, reason: 'Command matches dangerous pattern' };
      }
    }

    // Check working directory
    const cwd = command.cwd || this.config.workingDirectory;
    if (!this.isPathAllowed(cwd, 'read')) {
      return { valid: false, reason: `Working directory not allowed: ${cwd}` };
    }

    return { valid: true };
  }

  /**
   * Build the full command with restrictions.
   */
  private buildCommand(command: ExecutionCommand): string {
    const parts: string[] = [];

    // Add ulimit restrictions
    const ulimits = this.enforcer.getUlimitFlags();
    parts.push(`ulimit ${ulimits.join(' ')} 2>/dev/null;`);

    // Add the actual command
    parts.push(command.command);
    if (command.args.length > 0) {
      parts.push(...command.args.map((arg) => this.escapeArg(arg)));
    }

    return parts.join(' ');
  }

  /**
   * Build environment variables.
   */
  private buildEnvironment(extra?: Record<string, string>): Record<string, string> {
    const env: Record<string, string> = {
      // Minimal safe environment
      PATH: '/usr/local/bin:/usr/bin:/bin',
      HOME: this.config.workingDirectory,
      TMPDIR: '/tmp',
      LANG: 'C.UTF-8',
      // Sandbox markers
      SANDBOX_ID: this.id,
      SANDBOX_ISOLATION: this.config.isolationLevel,
      ...this.config.environment,
      ...extra,
    };

    return env;
  }

  /**
   * Check if a path is allowed.
   */
  private isPathAllowed(path: string, mode: 'read' | 'write'): boolean {
    const allowed = mode === 'read'
      ? this.config.allowedReadPaths
      : this.config.allowedWritePaths;

    return allowed.some((allowedPath) => {
      if (allowedPath.endsWith('*')) {
        return path.startsWith(allowedPath.slice(0, -1));
      }
      return path === allowedPath || path.startsWith(allowedPath + '/');
    });
  }

  /**
   * Escape shell argument.
   */
  private escapeArg(arg: string): string {
    // Simple escaping - wrap in single quotes, escape existing quotes
    return `'${arg.replace(/'/g, "'\\''")}'`;
  }

  /**
   * Create error result.
   */
  private createErrorResult(startTime: number, error: string): ExecutionResult {
    return {
      exitCode: 1,
      stdout: '',
      stderr: error,
      durationMs: Date.now() - startTime,
      resourceUsage: this.createEmptyUsage(),
      killed: false,
      sandboxId: this.id,
    };
  }

  /**
   * Create empty usage.
   */
  private createEmptyUsage(): ResourceUsage {
    return {
      cpuTimeMs: 0,
      peakMemoryMB: 0,
      diskReadBytes: 0,
      diskWriteBytes: 0,
      networkSentBytes: 0,
      networkReceivedBytes: 0,
    };
  }

  /**
   * Check if sandbox is ready.
   */
  async isReady(): Promise<boolean> {
    return this.activeProcess === null;
  }

  /**
   * Get sandbox status.
   */
  async getStatus(): Promise<SandboxStatus> {
    return {
      active: this.activeProcess !== null,
      executionCount: this.executionCount,
      totalExecutionMs: this.totalExecutionMs,
      currentUsage: this.activeProcess ? this.monitor.getUsage() : {},
      warnings: [],
    };
  }

  /**
   * Clean up resources.
   */
  async cleanup(): Promise<void> {
    if (this.activeProcess) {
      this.killProcess('manual');
    }

    this.emit({
      type: 'sandbox.destroyed',
      sandboxId: this.id,
    });
  }

  /**
   * Subscribe to events.
   */
  on(listener: SandboxEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(event: SandboxEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch (err) {
        console.error('Process sandbox listener error:', err);
      }
    }
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createProcessSandbox(
  config?: Partial<SandboxConfig>
): ProcessSandbox {
  return new ProcessSandbox(config);
}
