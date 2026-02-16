/**
 * Docker Sandbox (Linux/Cross-platform)
 *
 * Uses Docker containers for process isolation and resource limiting.
 * Works on any platform with Docker installed.
 *
 * Key features:
 * - Complete filesystem isolation
 * - Network namespace separation
 * - CPU and memory limits via cgroups
 * - Capability dropping
 *
 * Note: Uses spawn() to invoke docker CLI commands with proper argument
 * arrays - the sandbox provides security via containerization.
 */

import { spawn, execSync } from 'child_process';
import type { Sandbox, SandboxMode, SandboxOptions, ExecResult } from './index.js';
import { logger } from '../../utilities/logger.js';

// =============================================================================
// DOCKER SANDBOX
// =============================================================================

/**
 * Docker-based sandbox implementation.
 */
export class DockerSandbox implements Sandbox {
  private options: SandboxOptions;
  private image: string;
  private available: boolean | null = null;
  private containerId: string | null = null;

  constructor(options: SandboxOptions, image: string = 'node:20-slim') {
    this.options = options;
    this.image = image;
  }

  /**
   * Execute a command inside a Docker container.
   *
   * Uses spawn with explicit argument arrays for security.
   */
  async execute(command: string, options?: Partial<SandboxOptions>): Promise<ExecResult> {
    const mergedOptions = { ...this.options, ...options };
    const timeout = mergedOptions.timeout ?? 60000;
    const workDir = mergedOptions.workingDir ?? process.cwd();

    // Build docker run arguments
    const dockerArgs = this.buildDockerArgs(command, mergedOptions, workDir);

    return new Promise((resolve) => {
      const proc = spawn('docker', dockerArgs, {
        cwd: workDir,
        env: process.env,
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
        // Also try to stop the container
        if (this.containerId) {
          try {
            execSync(`docker kill ${this.containerId}`, { stdio: 'pipe' });
          } catch {
            // Ignore - container may have already exited
          }
        }
      }, timeout);

      proc.stdout?.on('data', (data) => {
        stdout += data.toString();
      });

      proc.stderr?.on('data', (data) => {
        stderr += data.toString();
      });

      proc.on('close', (code) => {
        clearTimeout(timer);
        this.containerId = null;

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
        this.containerId = null;

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
   * Build docker run arguments.
   */
  private buildDockerArgs(
    command: string,
    options: SandboxOptions,
    workDir: string
  ): string[] {
    const args: string[] = ['run', '--rm'];

    // Security: drop all capabilities
    args.push('--cap-drop=ALL');

    // Security: no new privileges
    args.push('--security-opt=no-new-privileges');

    // Network isolation
    if (!options.networkAllowed) {
      args.push('--network=none');
    }

    // Memory limit
    if (options.maxMemoryMB) {
      args.push(`--memory=${options.maxMemoryMB}m`);
      args.push(`--memory-swap=${options.maxMemoryMB}m`); // No swap
    }

    // CPU limit
    if (options.maxCpuSeconds) {
      // Convert CPU seconds to CPU period/quota
      // For simplicity, use cpus limit
      args.push('--cpus=1');
    }

    // Mount working directory
    args.push('-v', `${workDir}:/workspace:rw`);

    // Mount additional readable paths
    for (const path of options.readablePaths ?? []) {
      if (path !== '/') {
        const resolvedPath = this.resolvePath(path, workDir);
        // Only mount if the path exists and is different from workspace
        if (resolvedPath !== workDir) {
          args.push('-v', `${resolvedPath}:${resolvedPath}:ro`);
        }
      }
    }

    // Mount additional writable paths
    for (const path of options.writablePaths ?? []) {
      const resolvedPath = this.resolvePath(path, workDir);
      // Only mount if different from workspace
      if (resolvedPath !== workDir && path !== '.') {
        args.push('-v', `${resolvedPath}:${resolvedPath}:rw`);
      }
    }

    // Set working directory inside container
    args.push('-w', '/workspace');

    // Set environment variables
    for (const [key, value] of Object.entries(options.env ?? {})) {
      args.push('-e', `${key}=${value}`);
    }

    // Pass through common env vars
    const passthrough = ['HOME', 'USER', 'PATH', 'NODE_ENV', 'npm_config_cache'];
    for (const key of passthrough) {
      if (process.env[key]) {
        args.push('-e', `${key}=${process.env[key]}`);
      }
    }

    // Image
    args.push(this.image);

    // Command (use sh -c for shell interpretation)
    args.push('sh', '-c', command);

    return args;
  }

  /**
   * Resolve a path relative to working directory.
   */
  private resolvePath(path: string, workDir: string): string {
    if (path.startsWith('/')) {
      return path;
    }
    if (path === '.') {
      return workDir;
    }
    return `${workDir}/${path}`;
  }

  /**
   * Check if Docker is available.
   */
  async isAvailable(): Promise<boolean> {
    if (this.available !== null) {
      return this.available;
    }

    try {
      // Check if docker command exists and daemon is running
      execSync('docker info', { stdio: 'pipe' });
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
    return 'docker';
  }

  /**
   * Cleanup resources.
   */
  async cleanup(): Promise<void> {
    if (this.containerId) {
      try {
        execSync(`docker kill ${this.containerId}`, { stdio: 'pipe' });
      } catch {
        // Ignore - container may have already exited
      }
      this.containerId = null;
    }
  }

  /**
   * Pull the Docker image if not present.
   */
  async ensureImage(): Promise<void> {
    try {
      execSync(`docker image inspect ${this.image}`, { stdio: 'pipe' });
    } catch {
      // Image not found, pull it
      logger.info(`[DockerSandbox] Pulling image: ${this.image}`);
      execSync(`docker pull ${this.image}`, { stdio: 'inherit' });
    }
  }

  /**
   * Set the Docker image to use.
   */
  setImage(image: string): void {
    this.image = image;
  }

  /**
   * Get the current Docker image.
   */
  getImage(): string {
    return this.image;
  }
}

// =============================================================================
// PREDEFINED IMAGES
// =============================================================================

/**
 * Recommended Docker images for different use cases.
 */
export const DOCKER_IMAGES = {
  /** Minimal Node.js for JavaScript/TypeScript */
  node: 'node:20-slim',

  /** Python for Python scripts */
  python: 'python:3.12-slim',

  /** Alpine for general shell commands */
  alpine: 'alpine:latest',

  /** Ubuntu for full Linux environment */
  ubuntu: 'ubuntu:22.04',

  /** Deno for Deno scripts */
  deno: 'denoland/deno:latest',

  /** Bun for Bun scripts */
  bun: 'oven/bun:latest',
} as const;

// =============================================================================
// DOCKER PROFILES
// =============================================================================

/**
 * Strict Docker profile - minimal access.
 */
export const DOCKER_STRICT_PROFILE: SandboxOptions = {
  writablePaths: [],
  readablePaths: [],
  networkAllowed: false,
  timeout: 30000,
  maxMemoryMB: 256,
  maxCpuSeconds: 10,
};

/**
 * Development Docker profile.
 */
export const DOCKER_DEV_PROFILE: SandboxOptions = {
  writablePaths: ['.', 'node_modules'],
  readablePaths: [],
  networkAllowed: true,
  timeout: 300000,
  maxMemoryMB: 1024,
  maxCpuSeconds: 120,
};

/**
 * CI/CD Docker profile.
 */
export const DOCKER_CI_PROFILE: SandboxOptions = {
  writablePaths: ['.'],
  readablePaths: [],
  networkAllowed: true, // For package downloads
  timeout: 600000,      // 10 minutes
  maxMemoryMB: 2048,
  maxCpuSeconds: 300,
};
