/**
 * Resource Monitor Integration
 *
 * Provides lightweight resource usage tracking and limits for agent operations.
 * Integrates with the economics system to check both token budget AND system resources.
 * Adapted from tricks/resource-monitor.ts.
 *
 * Usage:
 *   const resources = createResourceManager({ maxMemoryMB: 512 });
 *   const check = resources.check();
 *   if (check.status === 'exceeded') { ... }
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * Resource limits configuration.
 */
export interface ResourceLimitsConfig {
  /** Enable/disable resource monitoring */
  enabled?: boolean;
  /** Max memory in MB */
  maxMemoryMB?: number;
  /** Max CPU time in seconds */
  maxCpuTimeSec?: number;
  /** Max concurrent operations */
  maxConcurrentOps?: number;
  /** Warning threshold (0-1) - emit warning when usage exceeds this */
  warnThreshold?: number;
  /** Critical threshold (0-1) - slow down operations when exceeded */
  criticalThreshold?: number;
}

/**
 * Current resource usage.
 */
export interface ResourceUsage {
  memoryMB: number;
  memoryPercent: number;
  cpuTimeSec: number;
  cpuPercent: number;
  concurrentOps: number;
  opsPercent: number;
  timestamp: Date;
}

/**
 * Resource status levels.
 */
export type ResourceStatus = 'healthy' | 'warning' | 'critical' | 'exceeded';

/**
 * Result of a resource check.
 */
export interface ResourceCheck {
  status: ResourceStatus;
  usage: ResourceUsage;
  canContinue: boolean;
  message?: string;
  recommendation?: 'continue' | 'slow_down' | 'stop';
}

/**
 * Resource event types.
 */
export type ResourceEvent =
  | { type: 'resource.warning'; metric: string; value: number; threshold: number }
  | { type: 'resource.critical'; metric: string; value: number; threshold: number }
  | { type: 'resource.exceeded'; metric: string; value: number; limit: number }
  | { type: 'resource.recovered'; metric: string; previousStatus: ResourceStatus };

export type ResourceEventListener = (event: ResourceEvent) => void;

// =============================================================================
// RESOURCE MANAGER
// =============================================================================

/**
 * Manages resource monitoring and limits for the agent.
 */
export class ResourceManager {
  private config: Required<ResourceLimitsConfig>;
  private startTime: number;
  private concurrentOps: number = 0;
  private previousStatus: ResourceStatus = 'healthy';
  private eventListeners: Set<ResourceEventListener> = new Set();

  constructor(config: ResourceLimitsConfig = {}) {
    this.config = {
      enabled: config.enabled ?? true,
      maxMemoryMB: config.maxMemoryMB ?? 512,
      maxCpuTimeSec: config.maxCpuTimeSec ?? 300, // 5 minutes
      maxConcurrentOps: config.maxConcurrentOps ?? 10,
      warnThreshold: config.warnThreshold ?? 0.7,
      criticalThreshold: config.criticalThreshold ?? 0.9,
    };
    this.startTime = Date.now();
  }

  /**
   * Get current resource usage.
   */
  getUsage(): ResourceUsage {
    const mem = process.memoryUsage();
    const memoryMB = mem.heapUsed / 1024 / 1024;
    const cpuTimeSec = (Date.now() - this.startTime) / 1000;

    return {
      memoryMB,
      memoryPercent: memoryMB / this.config.maxMemoryMB,
      cpuTimeSec,
      cpuPercent: cpuTimeSec / this.config.maxCpuTimeSec,
      concurrentOps: this.concurrentOps,
      opsPercent: this.concurrentOps / this.config.maxConcurrentOps,
      timestamp: new Date(),
    };
  }

  /**
   * Check resource status and determine if operations can continue.
   */
  check(): ResourceCheck {
    if (!this.config.enabled) {
      return {
        status: 'healthy',
        usage: this.getUsage(),
        canContinue: true,
        recommendation: 'continue',
      };
    }

    const usage = this.getUsage();
    let status: ResourceStatus = 'healthy';
    let message: string | undefined;
    let canContinue = true;
    let recommendation: 'continue' | 'slow_down' | 'stop' = 'continue';

    // Check memory
    if (usage.memoryPercent >= 1) {
      status = 'exceeded';
      message = `Memory limit exceeded (${usage.memoryMB.toFixed(1)}MB / ${this.config.maxMemoryMB}MB)`;
      canContinue = false;
      recommendation = 'stop';
      this.emit({
        type: 'resource.exceeded',
        metric: 'memory',
        value: usage.memoryMB,
        limit: this.config.maxMemoryMB,
      });
    } else if (usage.memoryPercent >= this.config.criticalThreshold) {
      status = 'critical';
      message = `Memory critically high (${(usage.memoryPercent * 100).toFixed(1)}%)`;
      recommendation = 'slow_down';
      this.emit({
        type: 'resource.critical',
        metric: 'memory',
        value: usage.memoryPercent,
        threshold: this.config.criticalThreshold,
      });
    } else if (usage.memoryPercent >= this.config.warnThreshold) {
      status = 'warning';
      message = `Memory usage elevated (${(usage.memoryPercent * 100).toFixed(1)}%)`;
      this.emit({
        type: 'resource.warning',
        metric: 'memory',
        value: usage.memoryPercent,
        threshold: this.config.warnThreshold,
      });
    }

    // Check CPU time (only override if worse)
    if (usage.cpuPercent >= 1 && status !== 'exceeded') {
      status = 'exceeded';
      message = `CPU time limit exceeded (${usage.cpuTimeSec.toFixed(1)}s / ${this.config.maxCpuTimeSec}s)`;
      canContinue = false;
      recommendation = 'stop';
      this.emit({
        type: 'resource.exceeded',
        metric: 'cpuTime',
        value: usage.cpuTimeSec,
        limit: this.config.maxCpuTimeSec,
      });
    } else if (usage.cpuPercent >= this.config.criticalThreshold && status === 'healthy') {
      status = 'critical';
      message = `Approaching CPU time limit (${(usage.cpuPercent * 100).toFixed(1)}%)`;
      recommendation = 'slow_down';
      this.emit({
        type: 'resource.critical',
        metric: 'cpuTime',
        value: usage.cpuPercent,
        threshold: this.config.criticalThreshold,
      });
    } else if (usage.cpuPercent >= this.config.warnThreshold && status === 'healthy') {
      status = 'warning';
      message = `CPU time usage elevated (${(usage.cpuPercent * 100).toFixed(1)}%)`;
      this.emit({
        type: 'resource.warning',
        metric: 'cpuTime',
        value: usage.cpuPercent,
        threshold: this.config.warnThreshold,
      });
    }

    // Check concurrent operations
    if (usage.opsPercent >= 1 && status !== 'exceeded') {
      status = 'exceeded';
      message = `Max concurrent operations reached (${usage.concurrentOps}/${this.config.maxConcurrentOps})`;
      canContinue = false;
      recommendation = 'stop';
      this.emit({
        type: 'resource.exceeded',
        metric: 'concurrentOps',
        value: usage.concurrentOps,
        limit: this.config.maxConcurrentOps,
      });
    }

    // Check for recovery
    if (this.previousStatus !== 'healthy' && status === 'healthy') {
      this.emit({
        type: 'resource.recovered',
        metric: 'overall',
        previousStatus: this.previousStatus,
      });
    }

    this.previousStatus = status;

    return { status, usage, canContinue, message, recommendation };
  }

  /**
   * Check if we can start a new operation.
   */
  canStartOperation(): boolean {
    if (!this.config.enabled) return true;
    const check = this.check();
    return check.canContinue && this.concurrentOps < this.config.maxConcurrentOps;
  }

  /**
   * Track the start of an operation.
   * Returns a function to call when the operation completes.
   */
  startOperation(): () => void {
    this.concurrentOps++;
    return () => {
      this.concurrentOps = Math.max(0, this.concurrentOps - 1);
    };
  }

  /**
   * Run a function with operation tracking.
   * Throws ResourceLimitError if resources exceeded.
   */
  async runTracked<T>(fn: () => Promise<T>): Promise<T> {
    const check = this.check();
    if (!check.canContinue) {
      throw new ResourceLimitError(check.message || 'Resource limit exceeded');
    }

    const end = this.startOperation();
    try {
      return await fn();
    } finally {
      end();
    }
  }

  /**
   * Run only if resources are available.
   * Returns fallback value if resources exceeded.
   */
  async runIfAvailable<T>(fn: () => Promise<T>, fallback?: T): Promise<T | undefined> {
    if (!this.canStartOperation()) {
      return fallback;
    }

    const check = this.check();
    if (!check.canContinue || check.status === 'critical') {
      return fallback;
    }

    return this.runTracked(fn);
  }

  /**
   * Update resource limits.
   */
  setLimits(limits: Partial<ResourceLimitsConfig>): void {
    Object.assign(this.config, limits);
  }

  /**
   * Get current limits.
   */
  getLimits(): Required<ResourceLimitsConfig> {
    return { ...this.config };
  }

  /**
   * Reset timing and operation count.
   */
  reset(): void {
    this.startTime = Date.now();
    this.concurrentOps = 0;
    this.previousStatus = 'healthy';
  }

  /**
   * Reset only the CPU time counter (per-prompt reset).
   * This allows long sessions with multiple prompts without hitting the wall-clock limit.
   */
  resetCpuTime(): void {
    this.startTime = Date.now();
  }

  /**
   * Get formatted status string.
   */
  getStatusString(): string {
    const check = this.check();
    const usage = check.usage;

    return [
      `Memory: ${usage.memoryMB.toFixed(1)}MB / ${this.config.maxMemoryMB}MB (${(usage.memoryPercent * 100).toFixed(1)}%)`,
      `CPU Time: ${usage.cpuTimeSec.toFixed(1)}s / ${this.config.maxCpuTimeSec}s (${(usage.cpuPercent * 100).toFixed(1)}%)`,
      `Operations: ${usage.concurrentOps} / ${this.config.maxConcurrentOps}`,
      `Status: ${check.status.toUpperCase()}`,
    ].join('\n');
  }

  /**
   * Subscribe to resource events.
   */
  subscribe(listener: ResourceEventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  /**
   * Emit a resource event.
   */
  private emit(event: ResourceEvent): void {
    for (const listener of this.eventListeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }

  /**
   * Cleanup resources.
   */
  cleanup(): void {
    this.eventListeners.clear();
  }
}

// =============================================================================
// ERROR
// =============================================================================

/**
 * Error thrown when resource limits are exceeded.
 */
export class ResourceLimitError extends Error {
  readonly isResourceLimit = true;

  constructor(message: string) {
    super(message);
    this.name = 'ResourceLimitError';
  }
}

/**
 * Check if an error is a resource limit error.
 */
export function isResourceLimitError(error: unknown): error is ResourceLimitError {
  return (
    error instanceof ResourceLimitError ||
    (error instanceof Error &&
      'isResourceLimit' in error &&
      (error as ResourceLimitError).isResourceLimit === true)
  );
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a resource manager with default limits.
 */
export function createResourceManager(config?: ResourceLimitsConfig): ResourceManager {
  return new ResourceManager(config);
}

/**
 * Create a strict resource manager (lower limits).
 */
export function createStrictResourceManager(): ResourceManager {
  return new ResourceManager({
    enabled: true,
    maxMemoryMB: 128,
    maxCpuTimeSec: 60,
    maxConcurrentOps: 5,
    warnThreshold: 0.5,
    criticalThreshold: 0.8,
  });
}

/**
 * Create a lenient resource manager (higher limits).
 */
export function createLenientResourceManager(): ResourceManager {
  return new ResourceManager({
    enabled: true,
    maxMemoryMB: 1024,
    maxCpuTimeSec: 1800, // 30 minutes for complex tasks
    maxConcurrentOps: 50,
    warnThreshold: 0.8,
    criticalThreshold: 0.95,
  });
}

// =============================================================================
// INTEGRATION HELPERS
// =============================================================================

/**
 * Combine resource check with economics budget check.
 * Returns true only if BOTH resource AND budget checks pass.
 */
export function combinedShouldContinue(
  resourceManager: ResourceManager | null,
  economicsShouldContinue: boolean,
): { canContinue: boolean; reason?: string } {
  // If no resource manager, just use economics
  if (!resourceManager) {
    return {
      canContinue: economicsShouldContinue,
      reason: economicsShouldContinue ? undefined : 'Budget limit',
    };
  }

  // Check resources
  const resourceCheck = resourceManager.check();

  // Both must pass
  if (!economicsShouldContinue) {
    return { canContinue: false, reason: 'Budget limit' };
  }

  if (!resourceCheck.canContinue) {
    return { canContinue: false, reason: resourceCheck.message || 'Resource limit' };
  }

  return { canContinue: true };
}
