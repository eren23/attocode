/**
 * Lesson 20: Docker Sandbox
 *
 * Container-based isolation using Docker.
 * Provides stronger isolation than process-level sandboxing.
 */

import type {
  Sandbox,
  SandboxConfig,
  SandboxStatus,
  ExecutionCommand,
  ExecutionResult,
  ResourceUsage,
  SandboxEvent,
  SandboxEventListener,
} from './types.js';
import { generateSandboxId, STRICT_SANDBOX_CONFIG, mergeConfig } from './types.js';
import { LimitEnforcer, OutputLimiter, withTimeout, TimeoutError } from './resource-limits.js';

// =============================================================================
// DOCKER SANDBOX
// =============================================================================

/**
 * Sandbox using Docker containers.
 */
export class DockerSandbox implements Sandbox {
  readonly id: string;
  readonly config: SandboxConfig;

  private listeners: Set<SandboxEventListener> = new Set();
  private executionCount: number = 0;
  private totalExecutionMs: number = 0;
  private containerId: string | null = null;
  private enforcer: LimitEnforcer;

  constructor(config: Partial<SandboxConfig> = {}) {
    this.id = generateSandboxId();
    this.config = mergeConfig(
      { ...config, isolationLevel: 'container' },
      STRICT_SANDBOX_CONFIG
    );
    this.enforcer = new LimitEnforcer(this.config.resourceLimits);

    this.emit({
      type: 'sandbox.created',
      sandboxId: this.id,
      config: this.config,
    });
  }

  /**
   * Execute a command in a Docker container.
   */
  async execute(command: ExecutionCommand): Promise<ExecutionResult> {
    const startTime = Date.now();
    this.executionCount++;

    this.emit({
      type: 'execution.started',
      sandboxId: this.id,
      command,
    });

    // Build Docker command
    const dockerCmd = this.buildDockerCommand(command);

    console.log(`[DockerSandbox ${this.id}] Would execute:`);
    console.log(`  ${dockerCmd}`);

    // Simulate execution for demo purposes
    // In production, would actually run the Docker command
    const result = await this.simulateExecution(command, startTime);

    this.emit({
      type: 'execution.completed',
      sandboxId: this.id,
      result,
    });

    return result;
  }

  /**
   * Build the Docker run command.
   */
  private buildDockerCommand(command: ExecutionCommand): string {
    const flags: string[] = ['docker', 'run', '--rm'];

    // Add container name
    flags.push(`--name`, `sandbox-${this.id}`);

    // Add resource limits
    flags.push(...this.enforcer.getDockerFlags());

    // Network settings
    if (!this.config.allowNetwork) {
      flags.push('--network', 'none');
    } else if (this.config.allowedHosts && this.config.allowedHosts.length > 0) {
      // Would need custom network rules
      flags.push('--network', 'bridge');
    }

    // Security options
    const { security } = this.config;

    if (security.dropCapabilities) {
      flags.push('--cap-drop', 'ALL');
    }

    if (security.runAsNonRoot && security.userId) {
      flags.push('--user', `${security.userId}:${security.groupId || security.userId}`);
    }

    if (security.readOnlyRootFilesystem) {
      flags.push('--read-only');
    }

    if (security.noNewPrivileges) {
      flags.push('--security-opt', 'no-new-privileges');
    }

    if (security.seccompProfile) {
      if (security.seccompProfile === 'strict') {
        // Would use a custom strict profile
        flags.push('--security-opt', 'seccomp=strict.json');
      }
    }

    // Working directory
    flags.push('-w', this.config.workingDirectory);

    // Environment variables
    for (const [key, value] of Object.entries(this.config.environment)) {
      flags.push('-e', `${key}=${value}`);
    }
    for (const [key, value] of Object.entries(command.env || {})) {
      flags.push('-e', `${key}=${value}`);
    }

    // Mount volumes for allowed paths
    for (const path of this.config.allowedReadPaths) {
      flags.push('-v', `${path}:${path}:ro`);
    }
    for (const path of this.config.allowedWritePaths) {
      flags.push('-v', `${path}:${path}:rw`);
    }

    // Add tmpfs for temp directory
    flags.push('--tmpfs', '/tmp:exec,size=64M');

    // Image (would be configurable in production)
    flags.push('alpine:latest');

    // Command to run
    const shell = command.shell || '/bin/sh';
    const fullCommand = [command.command, ...command.args].join(' ');
    flags.push(shell, '-c', fullCommand);

    return flags.join(' ');
  }

  /**
   * Simulate execution for demo.
   */
  private async simulateExecution(
    command: ExecutionCommand,
    startTime: number
  ): Promise<ExecutionResult> {
    // Simulate some delay
    await new Promise((resolve) => setTimeout(resolve, 100));

    const durationMs = Date.now() - startTime;
    this.totalExecutionMs += durationMs;

    return {
      exitCode: 0,
      stdout: `[Simulated Docker output for: ${command.command}]`,
      stderr: '',
      durationMs,
      resourceUsage: {
        cpuTimeMs: 50,
        peakMemoryMB: 32,
        diskReadBytes: 1024,
        diskWriteBytes: 512,
        networkSentBytes: 0,
        networkReceivedBytes: 0,
      },
      killed: false,
      sandboxId: this.id,
    };
  }

  /**
   * Check if Docker is available.
   */
  async isReady(): Promise<boolean> {
    // In production, would check:
    // - Docker daemon is running
    // - Required image is available
    // - Sufficient resources
    return true;
  }

  /**
   * Get sandbox status.
   */
  async getStatus(): Promise<SandboxStatus> {
    return {
      active: this.containerId !== null,
      executionCount: this.executionCount,
      totalExecutionMs: this.totalExecutionMs,
      currentUsage: {},
      warnings: [],
    };
  }

  /**
   * Clean up resources.
   */
  async cleanup(): Promise<void> {
    if (this.containerId) {
      console.log(`[DockerSandbox] Would stop container: ${this.containerId}`);
      this.containerId = null;
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
        console.error('Docker sandbox listener error:', err);
      }
    }
  }
}

// =============================================================================
// DOCKER IMAGE BUILDER
// =============================================================================

/**
 * Builds minimal Docker images for sandboxing.
 */
export class SandboxImageBuilder {
  /**
   * Generate Dockerfile for a minimal sandbox image.
   */
  static generateDockerfile(options: {
    baseImage?: string;
    packages?: string[];
    user?: number;
  } = {}): string {
    const {
      baseImage = 'alpine:latest',
      packages = [],
      user = 65534,
    } = options;

    const lines: string[] = [
      `FROM ${baseImage}`,
      '',
      '# Install packages if needed',
    ];

    if (packages.length > 0) {
      lines.push(`RUN apk add --no-cache ${packages.join(' ')}`);
    }

    lines.push(
      '',
      '# Create sandbox user',
      `RUN adduser -D -u ${user} sandbox`,
      '',
      '# Create working directory',
      'RUN mkdir -p /sandbox && chown sandbox:sandbox /sandbox',
      '',
      '# Set working directory',
      'WORKDIR /sandbox',
      '',
      '# Switch to non-root user',
      'USER sandbox',
      '',
      '# Default command',
      'CMD ["/bin/sh"]',
    );

    return lines.join('\n');
  }

  /**
   * Get recommended packages for different use cases.
   */
  static getPackagesFor(useCase: 'shell' | 'python' | 'node' | 'minimal'): string[] {
    switch (useCase) {
      case 'shell':
        return ['bash', 'coreutils', 'grep', 'sed', 'awk'];
      case 'python':
        return ['python3', 'py3-pip'];
      case 'node':
        return ['nodejs', 'npm'];
      case 'minimal':
      default:
        return [];
    }
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createDockerSandbox(
  config?: Partial<SandboxConfig>
): DockerSandbox {
  return new DockerSandbox(config);
}
