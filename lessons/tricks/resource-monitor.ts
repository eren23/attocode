/**
 * Trick N: Resource Monitor (Lightweight)
 *
 * Simple resource usage tracking and limits.
 * For full features, see Lesson 24.
 *
 * Usage:
 *   const monitor = createResourceMonitor({ maxMemoryMB: 256 });
 *   monitor.check(); // { status: 'healthy', ... }
 *   await monitor.runTracked(async () => { ... });
 */

// =============================================================================
// TYPES
// =============================================================================

export interface ResourceLimits {
  /** Max memory in MB */
  maxMemoryMB?: number;
  /** Max CPU time in seconds */
  maxCpuTimeSec?: number;
  /** Max concurrent operations */
  maxOperations?: number;
  /** Warning threshold (0-1) */
  warnAt?: number;
}

export interface ResourceUsage {
  memoryMB: number;
  memoryPercent: number;
  cpuTimeSec: number;
  operations: number;
  timestamp: Date;
}

export type ResourceStatus = 'healthy' | 'warning' | 'critical' | 'exceeded';

export interface ResourceCheck {
  status: ResourceStatus;
  usage: ResourceUsage;
  message?: string;
}

// =============================================================================
// RESOURCE MONITOR
// =============================================================================

export class SimpleResourceMonitor {
  private limits: Required<ResourceLimits>;
  private startTime: number;
  private operations = 0;

  constructor(limits: ResourceLimits = {}) {
    this.limits = {
      maxMemoryMB: limits.maxMemoryMB ?? 512,
      maxCpuTimeSec: limits.maxCpuTimeSec ?? 300,
      maxOperations: limits.maxOperations ?? 10,
      warnAt: limits.warnAt ?? 0.7,
    };
    this.startTime = Date.now();
  }

  /**
   * Get current resource usage.
   */
  getUsage(): ResourceUsage {
    const mem = process.memoryUsage();
    const memoryMB = mem.heapUsed / 1024 / 1024;

    return {
      memoryMB,
      memoryPercent: memoryMB / this.limits.maxMemoryMB,
      cpuTimeSec: (Date.now() - this.startTime) / 1000,
      operations: this.operations,
      timestamp: new Date(),
    };
  }

  /**
   * Check resource status.
   */
  check(): ResourceCheck {
    const usage = this.getUsage();
    let status: ResourceStatus = 'healthy';
    let message: string | undefined;

    // Check memory
    if (usage.memoryPercent >= 1) {
      status = 'exceeded';
      message = 'Memory limit exceeded';
    } else if (usage.memoryPercent >= 0.9) {
      status = 'critical';
      message = 'Memory critically high';
    } else if (usage.memoryPercent >= this.limits.warnAt) {
      status = 'warning';
      message = 'Memory usage high';
    }

    // Check CPU time
    const cpuPercent = usage.cpuTimeSec / this.limits.maxCpuTimeSec;
    if (cpuPercent >= 1 && status !== 'exceeded') {
      status = 'exceeded';
      message = 'CPU time limit exceeded';
    } else if (cpuPercent >= 0.9 && status === 'healthy') {
      status = 'critical';
      message = 'Approaching CPU time limit';
    } else if (cpuPercent >= this.limits.warnAt && status === 'healthy') {
      status = 'warning';
      message = 'CPU time usage high';
    }

    // Check operations
    const opPercent = usage.operations / this.limits.maxOperations;
    if (opPercent >= 1 && status !== 'exceeded') {
      status = 'exceeded';
      message = 'Max operations reached';
    }

    return { status, usage, message };
  }

  /**
   * Check if we can start a new operation.
   */
  canStart(): boolean {
    return this.operations < this.limits.maxOperations;
  }

  /**
   * Track an operation.
   */
  startOperation(): () => void {
    this.operations++;
    return () => {
      this.operations = Math.max(0, this.operations - 1);
    };
  }

  /**
   * Run a function with operation tracking.
   */
  async runTracked<T>(fn: () => Promise<T>): Promise<T> {
    const check = this.check();
    if (check.status === 'exceeded') {
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
   * Run only if resources available.
   */
  async runIfAvailable<T>(
    fn: () => Promise<T>,
    fallback?: T
  ): Promise<T | undefined> {
    if (!this.canStart()) {
      return fallback;
    }

    const check = this.check();
    if (check.status === 'exceeded' || check.status === 'critical') {
      return fallback;
    }

    return this.runTracked(fn);
  }

  /**
   * Update limits.
   */
  setLimits(limits: Partial<ResourceLimits>): void {
    Object.assign(this.limits, limits);
  }

  /**
   * Reset timing.
   */
  reset(): void {
    this.startTime = Date.now();
    this.operations = 0;
  }

  /**
   * Get current limits.
   */
  getLimits(): Required<ResourceLimits> {
    return { ...this.limits };
  }
}

// =============================================================================
// ERROR
// =============================================================================

export class ResourceLimitError extends Error {
  readonly isResourceLimit = true;
  constructor(message: string) {
    super(message);
    this.name = 'ResourceLimitError';
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create a resource monitor.
 */
export function createResourceMonitor(
  limits?: ResourceLimits
): SimpleResourceMonitor {
  return new SimpleResourceMonitor(limits);
}

/**
 * Create a strict monitor (lower limits).
 */
export function createStrictMonitor(): SimpleResourceMonitor {
  return new SimpleResourceMonitor({
    maxMemoryMB: 128,
    maxCpuTimeSec: 60,
    maxOperations: 5,
    warnAt: 0.5,
  });
}

/**
 * Create a lenient monitor (higher limits).
 */
export function createLenientMonitor(): SimpleResourceMonitor {
  return new SimpleResourceMonitor({
    maxMemoryMB: 1024,
    maxCpuTimeSec: 600,
    maxOperations: 50,
    warnAt: 0.8,
  });
}
