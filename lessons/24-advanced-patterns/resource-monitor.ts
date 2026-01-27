/**
 * Lesson 24: Resource Monitor
 *
 * Monitors and limits resource usage to prevent runaway operations.
 * Tracks memory, CPU time, and concurrent operations.
 *
 * Key features:
 * - Real-time usage tracking
 * - Configurable limits with thresholds
 * - Automatic warnings and enforcement
 * - Resource-aware caching integration
 */

import type {
  ResourceUsage,
  ResourceLimits,
  ResourceStatus,
  ResourceCheck,
  AdvancedPatternEvent,
  AdvancedPatternEventListener,
} from './types.js';
import { DEFAULT_RESOURCE_LIMITS } from './types.js';

// =============================================================================
// RESOURCE MONITOR
// =============================================================================

/**
 * Monitors resource usage and enforces limits.
 */
export class ResourceMonitor {
  private limits: ResourceLimits;
  private startTime: number;
  private operationCount = 0;
  private eventListeners: Set<AdvancedPatternEventListener> = new Set();
  private lastCheck?: ResourceCheck;
  private checkInterval?: NodeJS.Timeout;

  constructor(limits: Partial<ResourceLimits> = {}) {
    this.limits = { ...DEFAULT_RESOURCE_LIMITS, ...limits };
    this.startTime = Date.now();
  }

  // ===========================================================================
  // RESOURCE TRACKING
  // ===========================================================================

  /**
   * Get current resource usage.
   */
  getUsage(): ResourceUsage {
    const memUsage = process.memoryUsage();

    return {
      memoryBytes: memUsage.heapUsed,
      memoryPercent: this.limits.maxMemoryBytes
        ? memUsage.heapUsed / this.limits.maxMemoryBytes
        : 0,
      cpuTimeMs: Date.now() - this.startTime,
      activeOperations: this.operationCount,
      timestamp: new Date(),
    };
  }

  /**
   * Check resource status against limits.
   */
  check(): ResourceCheck {
    const usage = this.getUsage();
    const status = this.getStatus(usage);
    const recommendations = this.getRecommendations(usage, status);

    const check: ResourceCheck = {
      status,
      usage,
      limits: this.limits,
      recommendations,
    };

    this.lastCheck = check;

    // Emit warnings if necessary
    if (status === 'warning') {
      this.emitWarning(usage);
    } else if (status === 'critical') {
      this.emitCritical(usage);
    } else if (status === 'exceeded') {
      this.emitExceeded(usage);
    }

    return check;
  }

  /**
   * Determine status based on usage vs limits.
   */
  private getStatus(usage: ResourceUsage): ResourceStatus {
    const { warningThreshold = 0.7, criticalThreshold = 0.9 } = this.limits;

    // Check memory
    if (this.limits.maxMemoryBytes) {
      const memRatio = usage.memoryBytes / this.limits.maxMemoryBytes;
      if (memRatio >= 1) return 'exceeded';
      if (memRatio >= criticalThreshold) return 'critical';
      if (memRatio >= warningThreshold) return 'warning';
    }

    // Check CPU time
    if (this.limits.maxCpuTimeMs) {
      const cpuRatio = usage.cpuTimeMs / this.limits.maxCpuTimeMs;
      if (cpuRatio >= 1) return 'exceeded';
      if (cpuRatio >= criticalThreshold) return 'critical';
      if (cpuRatio >= warningThreshold) return 'warning';
    }

    // Check operations
    if (this.limits.maxOperations) {
      const opRatio = usage.activeOperations / this.limits.maxOperations;
      if (opRatio >= 1) return 'exceeded';
      if (opRatio >= criticalThreshold) return 'critical';
      if (opRatio >= warningThreshold) return 'warning';
    }

    return 'healthy';
  }

  /**
   * Generate recommendations based on current state.
   */
  private getRecommendations(
    usage: ResourceUsage,
    status: ResourceStatus
  ): string[] {
    const recommendations: string[] = [];

    if (status === 'healthy') {
      return recommendations;
    }

    // Memory recommendations
    if (this.limits.maxMemoryBytes) {
      const memRatio = usage.memoryBytes / this.limits.maxMemoryBytes;
      if (memRatio > 0.7) {
        recommendations.push('Consider clearing caches or reducing batch sizes');
      }
      if (memRatio > 0.9) {
        recommendations.push('Memory critical: reduce memory usage immediately');
      }
    }

    // CPU time recommendations
    if (this.limits.maxCpuTimeMs) {
      const cpuRatio = usage.cpuTimeMs / this.limits.maxCpuTimeMs;
      if (cpuRatio > 0.7) {
        recommendations.push('Consider setting checkpoints for recovery');
      }
      if (cpuRatio > 0.9) {
        recommendations.push('Approaching timeout: wrap up current operations');
      }
    }

    // Operations recommendations
    if (this.limits.maxOperations) {
      const opRatio = usage.activeOperations / this.limits.maxOperations;
      if (opRatio > 0.7) {
        recommendations.push('Many concurrent operations: consider queuing');
      }
    }

    return recommendations;
  }

  // ===========================================================================
  // OPERATION TRACKING
  // ===========================================================================

  /**
   * Track the start of an operation.
   */
  startOperation(): () => void {
    this.operationCount++;
    this.checkLimits();

    return () => {
      this.operationCount = Math.max(0, this.operationCount - 1);
    };
  }

  /**
   * Run an operation with resource tracking.
   */
  async runOperation<T>(fn: () => Promise<T>): Promise<T> {
    const end = this.startOperation();
    try {
      return await fn();
    } finally {
      end();
    }
  }

  /**
   * Check if an operation can be started.
   */
  canStartOperation(): boolean {
    if (this.limits.maxOperations) {
      return this.operationCount < this.limits.maxOperations;
    }
    return true;
  }

  /**
   * Wait until an operation slot is available.
   */
  async waitForSlot(timeout?: number): Promise<boolean> {
    const startTime = Date.now();

    while (!this.canStartOperation()) {
      if (timeout && Date.now() - startTime > timeout) {
        return false;
      }
      await new Promise(resolve => setTimeout(resolve, 100));
    }

    return true;
  }

  // ===========================================================================
  // LIMIT ENFORCEMENT
  // ===========================================================================

  /**
   * Check limits and throw if exceeded.
   */
  checkLimits(): void {
    const check = this.check();

    if (check.status === 'exceeded') {
      throw new ResourceLimitError(
        `Resource limits exceeded: ${check.recommendations?.join('; ') || 'unknown'}`,
        check
      );
    }
  }

  /**
   * Check if any limit is exceeded.
   */
  isLimitExceeded(): boolean {
    const check = this.check();
    return check.status === 'exceeded';
  }

  /**
   * Check if we're in warning state.
   */
  isWarning(): boolean {
    const check = this.check();
    return check.status === 'warning' || check.status === 'critical';
  }

  // ===========================================================================
  // AUTOMATIC MONITORING
  // ===========================================================================

  /**
   * Start automatic periodic checking.
   */
  startMonitoring(intervalMs: number = 5000): () => void {
    this.checkInterval = setInterval(() => {
      this.check();
    }, intervalMs);

    return () => this.stopMonitoring();
  }

  /**
   * Stop automatic monitoring.
   */
  stopMonitoring(): void {
    if (this.checkInterval) {
      clearInterval(this.checkInterval);
      this.checkInterval = undefined;
    }
  }

  // ===========================================================================
  // CONFIGURATION
  // ===========================================================================

  /**
   * Update resource limits.
   */
  setLimits(limits: Partial<ResourceLimits>): void {
    this.limits = { ...this.limits, ...limits };
  }

  /**
   * Get current limits.
   */
  getLimits(): ResourceLimits {
    return { ...this.limits };
  }

  /**
   * Reset the monitor (for new sessions).
   */
  reset(): void {
    this.startTime = Date.now();
    this.operationCount = 0;
    this.lastCheck = undefined;
  }

  // ===========================================================================
  // EVENTS
  // ===========================================================================

  /**
   * Subscribe to events.
   */
  subscribe(listener: AdvancedPatternEventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  private emit(event: AdvancedPatternEvent): void {
    for (const listener of this.eventListeners) {
      try {
        listener(event);
      } catch (error) {
        console.error('Event listener error:', error);
      }
    }
  }

  private emitWarning(usage: ResourceUsage): void {
    const limit = this.getExceededLimit(usage, 'warning');
    this.emit({ type: 'resource.warning', usage, limit });
  }

  private emitCritical(usage: ResourceUsage): void {
    const limit = this.getExceededLimit(usage, 'critical');
    this.emit({ type: 'resource.critical', usage, limit });
  }

  private emitExceeded(usage: ResourceUsage): void {
    const limit = this.getExceededLimit(usage, 'exceeded');
    this.emit({ type: 'resource.exceeded', usage, limit });
  }

  private getExceededLimit(
    usage: ResourceUsage,
    _level: 'warning' | 'critical' | 'exceeded'
  ): string {
    if (this.limits.maxMemoryBytes) {
      const ratio = usage.memoryBytes / this.limits.maxMemoryBytes;
      if (ratio >= 0.7) return 'memory';
    }
    if (this.limits.maxCpuTimeMs) {
      const ratio = usage.cpuTimeMs / this.limits.maxCpuTimeMs;
      if (ratio >= 0.7) return 'cpu_time';
    }
    if (this.limits.maxOperations) {
      const ratio = usage.activeOperations / this.limits.maxOperations;
      if (ratio >= 0.7) return 'operations';
    }
    return 'unknown';
  }

  // ===========================================================================
  // STATISTICS
  // ===========================================================================

  /**
   * Get monitoring statistics.
   */
  getStats(): ResourceStats {
    const usage = this.getUsage();
    return {
      uptime: Date.now() - this.startTime,
      currentMemory: usage.memoryBytes,
      peakMemory: process.memoryUsage().heapUsed, // Simplified
      totalOperations: this.operationCount,
      checksPerformed: this.lastCheck ? 1 : 0, // Simplified
      warningsIssued: 0, // Would need tracking
      limitsExceeded: 0, // Would need tracking
    };
  }
}

/**
 * Resource statistics.
 */
export interface ResourceStats {
  uptime: number;
  currentMemory: number;
  peakMemory: number;
  totalOperations: number;
  checksPerformed: number;
  warningsIssued: number;
  limitsExceeded: number;
}

/**
 * Error thrown when resource limits are exceeded.
 */
export class ResourceLimitError extends Error {
  readonly isResourceLimit = true;
  readonly check: ResourceCheck;

  constructor(message: string, check: ResourceCheck) {
    super(message);
    this.name = 'ResourceLimitError';
    this.check = check;
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a resource monitor with default limits.
 */
export function createResourceMonitor(
  limits?: Partial<ResourceLimits>
): ResourceMonitor {
  return new ResourceMonitor(limits);
}

/**
 * Create a resource monitor with automatic monitoring.
 */
export function createAutoResourceMonitor(
  limits?: Partial<ResourceLimits>,
  intervalMs: number = 5000
): { monitor: ResourceMonitor; cleanup: () => void } {
  const monitor = new ResourceMonitor(limits);
  const cleanup = monitor.startMonitoring(intervalMs);
  return { monitor, cleanup };
}

/**
 * Create a strict resource monitor (lower limits).
 */
export function createStrictResourceMonitor(): ResourceMonitor {
  return new ResourceMonitor({
    maxMemoryBytes: 256 * 1024 * 1024, // 256 MB
    maxCpuTimeMs: 60000, // 1 minute
    maxOperations: 5,
    warningThreshold: 0.5,
    criticalThreshold: 0.8,
  });
}

/**
 * Create a lenient resource monitor (higher limits).
 */
export function createLenientResourceMonitor(): ResourceMonitor {
  return new ResourceMonitor({
    maxMemoryBytes: 2 * 1024 * 1024 * 1024, // 2 GB
    maxCpuTimeMs: 600000, // 10 minutes
    maxOperations: 50,
    warningThreshold: 0.8,
    criticalThreshold: 0.95,
  });
}

// =============================================================================
// RESOURCE-AWARE HELPERS
// =============================================================================

/**
 * Run a function only if resources are available.
 */
export async function runIfResourcesAvailable<T>(
  monitor: ResourceMonitor,
  fn: () => Promise<T>,
  fallback?: () => T
): Promise<T | undefined> {
  const check = monitor.check();

  if (check.status === 'exceeded') {
    return fallback?.();
  }

  if (check.status === 'critical' && !monitor.canStartOperation()) {
    return fallback?.();
  }

  return monitor.runOperation(fn);
}

/**
 * Create a resource-limited queue.
 */
export function createResourceLimitedQueue<T>(
  monitor: ResourceMonitor,
  concurrency: number = 3
): ResourceLimitedQueue<T> {
  return new ResourceLimitedQueue(monitor, concurrency);
}

/**
 * A queue that respects resource limits.
 */
export class ResourceLimitedQueue<T> {
  private queue: Array<{
    fn: () => Promise<T>;
    resolve: (value: T) => void;
    reject: (error: unknown) => void;
  }> = [];
  private running = 0;

  constructor(
    private monitor: ResourceMonitor,
    private concurrency: number
  ) {}

  /**
   * Add a task to the queue.
   */
  add(fn: () => Promise<T>): Promise<T> {
    return new Promise((resolve, reject) => {
      this.queue.push({ fn, resolve, reject });
      this.processNext();
    });
  }

  /**
   * Process the next item in queue if possible.
   */
  private async processNext(): Promise<void> {
    if (this.running >= this.concurrency) return;
    if (this.queue.length === 0) return;
    if (!this.monitor.canStartOperation()) return;

    const item = this.queue.shift();
    if (!item) return;

    this.running++;
    const end = this.monitor.startOperation();

    try {
      const result = await item.fn();
      item.resolve(result);
    } catch (error) {
      item.reject(error);
    } finally {
      end();
      this.running--;
      this.processNext();
    }
  }

  /**
   * Get queue length.
   */
  get length(): number {
    return this.queue.length;
  }

  /**
   * Get number of running tasks.
   */
  get activeCount(): number {
    return this.running;
  }
}
