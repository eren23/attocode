/**
 * Lesson 20: Resource Limits
 *
 * Enforces CPU, memory, time, and other resource limits
 * for sandboxed execution.
 */

import type {
  ResourceLimits,
  ResourceUsage,
  KillReason,
  SandboxEvent,
  SandboxEventListener,
} from './types.js';

// =============================================================================
// RESOURCE MONITOR
// =============================================================================

/**
 * Monitors resource usage and enforces limits.
 */
export class ResourceMonitor {
  private sandboxId: string;
  private limits: ResourceLimits;
  private usage: ResourceUsage;
  private listeners: Set<SandboxEventListener> = new Set();
  private interval: NodeJS.Timeout | null = null;
  private startTime: number = 0;

  constructor(sandboxId: string, limits: ResourceLimits) {
    this.sandboxId = sandboxId;
    this.limits = limits;
    this.usage = this.createEmptyUsage();
  }

  /**
   * Start monitoring.
   */
  start(): void {
    this.startTime = Date.now();
    this.usage = this.createEmptyUsage();

    // Poll for resource usage
    this.interval = setInterval(() => {
      this.checkLimits();
    }, 100);
  }

  /**
   * Stop monitoring.
   */
  stop(): void {
    if (this.interval) {
      clearInterval(this.interval);
      this.interval = null;
    }
  }

  /**
   * Get current usage.
   */
  getUsage(): ResourceUsage {
    return { ...this.usage };
  }

  /**
   * Update usage metrics.
   */
  updateUsage(updates: Partial<ResourceUsage>): void {
    Object.assign(this.usage, updates);
  }

  /**
   * Check if any limits are exceeded.
   */
  checkLimits(): KillReason | null {
    const elapsed = Date.now() - this.startTime;

    // Check timeout
    if (elapsed > this.limits.timeoutMs) {
      this.emitWarning('timeout', elapsed, this.limits.timeoutMs);
      return 'timeout';
    }

    // Check CPU time
    if (this.usage.cpuTimeMs > this.limits.maxCpuSeconds * 1000) {
      this.emitWarning('cpu', this.usage.cpuTimeMs, this.limits.maxCpuSeconds * 1000);
      return 'cpu_limit';
    }

    // Check memory
    if (this.usage.peakMemoryMB > this.limits.maxMemoryMB) {
      this.emitWarning('memory', this.usage.peakMemoryMB, this.limits.maxMemoryMB);
      return 'memory_limit';
    }

    // Check disk
    const totalDisk = this.usage.diskWriteBytes / (1024 * 1024);
    if (totalDisk > this.limits.maxDiskMB) {
      this.emitWarning('disk', totalDisk, this.limits.maxDiskMB);
      return 'disk_limit';
    }

    // Warn at 80% thresholds
    this.checkThreshold('timeout', elapsed, this.limits.timeoutMs);
    this.checkThreshold('cpu', this.usage.cpuTimeMs, this.limits.maxCpuSeconds * 1000);
    this.checkThreshold('memory', this.usage.peakMemoryMB, this.limits.maxMemoryMB);

    return null;
  }

  /**
   * Check and warn at threshold.
   */
  private checkThreshold(type: string, current: number, max: number): void {
    const ratio = current / max;
    if (ratio > 0.8 && ratio < 1.0) {
      this.emit({
        type: 'limit.warning',
        sandboxId: this.sandboxId,
        limitType: type,
        current,
        max,
      });
    }
  }

  /**
   * Emit warning event.
   */
  private emitWarning(type: string, current: number, max: number): void {
    this.emit({
      type: 'limit.warning',
      sandboxId: this.sandboxId,
      limitType: type,
      current,
      max,
    });
  }

  /**
   * Create empty usage object.
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
        console.error('Resource monitor listener error:', err);
      }
    }
  }
}

// =============================================================================
// LIMIT ENFORCER
// =============================================================================

/**
 * Enforces resource limits on processes.
 */
export class LimitEnforcer {
  private limits: ResourceLimits;

  constructor(limits: ResourceLimits) {
    this.limits = limits;
  }

  /**
   * Get ulimit flags for shell execution.
   */
  getUlimitFlags(): string[] {
    return [
      `-t ${this.limits.maxCpuSeconds}`,  // CPU time
      `-v ${this.limits.maxMemoryMB * 1024}`, // Virtual memory (KB)
      `-f ${this.limits.maxDiskMB * 1024}`,   // File size (KB)
      `-u ${this.limits.maxProcesses}`,       // Max processes
      `-n ${this.limits.maxFileDescriptors}`, // File descriptors
    ];
  }

  /**
   * Get cgroup configuration (Linux).
   */
  getCgroupConfig(): Record<string, string> {
    return {
      'memory.limit_in_bytes': String(this.limits.maxMemoryMB * 1024 * 1024),
      'memory.memsw.limit_in_bytes': String(this.limits.maxMemoryMB * 1024 * 1024 * 2),
      'cpu.cfs_quota_us': String(this.limits.maxCpuSeconds * 1000000),
      'pids.max': String(this.limits.maxProcesses),
    };
  }

  /**
   * Get Docker resource flags.
   */
  getDockerFlags(): string[] {
    return [
      `--memory=${this.limits.maxMemoryMB}m`,
      `--memory-swap=${this.limits.maxMemoryMB * 2}m`,
      `--cpus=${Math.max(0.1, this.limits.maxCpuSeconds / 60)}`,
      `--pids-limit=${this.limits.maxProcesses}`,
      `--ulimit nofile=${this.limits.maxFileDescriptors}`,
    ];
  }

  /**
   * Check if output size is within limit.
   */
  checkOutputSize(currentSize: number): boolean {
    return currentSize <= this.limits.maxOutputBytes;
  }

  /**
   * Truncate output if needed.
   */
  truncateOutput(output: string): string {
    if (output.length <= this.limits.maxOutputBytes) {
      return output;
    }

    const truncated = output.slice(0, this.limits.maxOutputBytes);
    return truncated + '\n... [output truncated]';
  }

  /**
   * Get timeout for execution.
   */
  getTimeoutMs(): number {
    return this.limits.timeoutMs;
  }
}

// =============================================================================
// OUTPUT LIMITER
// =============================================================================

/**
 * Limits output size with streaming support.
 */
export class OutputLimiter {
  private maxBytes: number;
  private currentBytes: number = 0;
  private buffer: string[] = [];
  private truncated: boolean = false;

  constructor(maxBytes: number) {
    this.maxBytes = maxBytes;
  }

  /**
   * Add data to output.
   */
  append(data: string): boolean {
    const bytes = Buffer.byteLength(data, 'utf8');

    if (this.currentBytes + bytes > this.maxBytes) {
      // Calculate how much we can still take
      const remaining = this.maxBytes - this.currentBytes;
      if (remaining > 0) {
        this.buffer.push(data.slice(0, remaining));
        this.currentBytes = this.maxBytes;
      }
      this.truncated = true;
      return false; // Limit reached
    }

    this.buffer.push(data);
    this.currentBytes += bytes;
    return true;
  }

  /**
   * Get collected output.
   */
  getOutput(): string {
    let output = this.buffer.join('');
    if (this.truncated) {
      output += '\n... [output truncated at ' +
        Math.round(this.maxBytes / 1024) + 'KB]';
    }
    return output;
  }

  /**
   * Check if output was truncated.
   */
  wasTruncated(): boolean {
    return this.truncated;
  }

  /**
   * Get current size.
   */
  getCurrentSize(): number {
    return this.currentBytes;
  }

  /**
   * Reset the limiter.
   */
  reset(): void {
    this.buffer = [];
    this.currentBytes = 0;
    this.truncated = false;
  }
}

// =============================================================================
// TIMEOUT WRAPPER
// =============================================================================

/**
 * Wraps a promise with timeout.
 */
export async function withTimeout<T>(
  promise: Promise<T>,
  timeoutMs: number,
  onTimeout?: () => void
): Promise<T> {
  let timeoutId: NodeJS.Timeout;

  const timeoutPromise = new Promise<never>((_, reject) => {
    timeoutId = setTimeout(() => {
      if (onTimeout) onTimeout();
      reject(new TimeoutError(`Execution timed out after ${timeoutMs}ms`));
    }, timeoutMs);
  });

  try {
    const result = await Promise.race([promise, timeoutPromise]);
    clearTimeout(timeoutId!);
    return result;
  } catch (err) {
    clearTimeout(timeoutId!);
    throw err;
  }
}

/**
 * Timeout error.
 */
export class TimeoutError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'TimeoutError';
  }
}

// =============================================================================
// RESOURCE ESTIMATOR
// =============================================================================

/**
 * Estimates resource requirements for commands.
 */
export class ResourceEstimator {
  /**
   * Estimate memory needs for a command.
   */
  static estimateMemory(command: string): number {
    // Simple heuristics
    if (command.includes('node') || command.includes('npm')) {
      return 256; // Node.js typically needs ~256MB
    }
    if (command.includes('python')) {
      return 128;
    }
    if (command.includes('java')) {
      return 512;
    }
    if (command.includes('cargo') || command.includes('rustc')) {
      return 1024; // Rust compilation is memory-heavy
    }
    return 64; // Default for simple commands
  }

  /**
   * Estimate CPU time for a command.
   */
  static estimateCpuTime(command: string): number {
    if (command.includes('build') || command.includes('compile')) {
      return 60; // Build commands take longer
    }
    if (command.includes('test')) {
      return 30;
    }
    return 10; // Default
  }

  /**
   * Get recommended limits for a command.
   */
  static getRecommendedLimits(command: string): Partial<ResourceLimits> {
    return {
      maxMemoryMB: this.estimateMemory(command),
      maxCpuSeconds: this.estimateCpuTime(command),
      timeoutMs: this.estimateCpuTime(command) * 2 * 1000,
    };
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createResourceMonitor(
  sandboxId: string,
  limits: ResourceLimits
): ResourceMonitor {
  return new ResourceMonitor(sandboxId, limits);
}

export function createLimitEnforcer(limits: ResourceLimits): LimitEnforcer {
  return new LimitEnforcer(limits);
}

export function createOutputLimiter(maxBytes: number): OutputLimiter {
  return new OutputLimiter(maxBytes);
}
