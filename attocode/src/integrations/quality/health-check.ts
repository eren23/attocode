/**
 * Health Check System
 *
 * Proactively detects failing dependencies and provides health status
 * for LLM providers, MCP servers, databases, and file system access.
 *
 * @example
 * ```typescript
 * const health = createHealthChecker();
 *
 * // Register checks
 * health.register('llm', async () => {
 *   await provider.chat([{ role: 'user', content: 'ping' }]);
 *   return true;
 * });
 *
 * // Check all
 * const report = await health.checkAll();
 * console.log(report.healthy ? 'All systems go!' : 'Issues detected');
 *
 * // Start periodic checks
 * health.startPeriodicChecks(60000); // Every minute
 * ```
 */

import { logger } from '../utilities/logger.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Result of a single health check.
 */
export interface HealthCheckResult {
  /** Name of the check */
  name: string;

  /** Whether the check passed */
  healthy: boolean;

  /** Time taken for the check in ms */
  latencyMs: number;

  /** Error message if unhealthy */
  error?: string;

  /** Timestamp of the check */
  timestamp: Date;

  /** Additional details */
  details?: Record<string, unknown>;
}

/**
 * Aggregated health report.
 */
export interface HealthReport {
  /** Overall system health */
  healthy: boolean;

  /** Number of healthy checks */
  healthyCount: number;

  /** Total number of checks */
  totalCount: number;

  /** Individual check results */
  checks: HealthCheckResult[];

  /** Timestamp of the report */
  timestamp: Date;

  /** Total time to run all checks */
  totalLatencyMs: number;
}

/**
 * Health check function signature.
 * Returns true if healthy, false or throws if unhealthy.
 */
export type HealthCheckFn = () => Promise<boolean>;

/**
 * Configuration for a health check.
 */
export interface HealthCheckConfig {
  /** Name of the check */
  name: string;

  /** The check function */
  check: HealthCheckFn;

  /** Timeout for the check in ms (default: 5000) */
  timeout?: number;

  /** Whether this check is critical (default: true) */
  critical?: boolean;

  /** Optional description */
  description?: string;
}

/**
 * Configuration for the health checker.
 */
export interface HealthCheckerConfig {
  /** Default timeout for checks in ms */
  defaultTimeout?: number;

  /** Whether to run checks in parallel (default: true) */
  parallel?: boolean;

  /** Callback when health status changes */
  onStatusChange?: (name: string, healthy: boolean, previous: boolean | undefined) => void;
}

/**
 * Health check event types.
 */
export type HealthEvent =
  | { type: 'check.started'; name: string }
  | { type: 'check.completed'; name: string; result: HealthCheckResult }
  | { type: 'status.changed'; name: string; healthy: boolean; previous: boolean | undefined }
  | { type: 'report.generated'; report: HealthReport };

export type HealthEventListener = (event: HealthEvent) => void;

// =============================================================================
// HEALTH CHECKER IMPLEMENTATION
// =============================================================================

/**
 * Manages health checks for system dependencies.
 */
export class HealthChecker {
  private checks = new Map<string, HealthCheckConfig>();
  private lastResults = new Map<string, HealthCheckResult>();
  private listeners = new Set<HealthEventListener>();
  private periodicInterval?: ReturnType<typeof setInterval>;
  private config: Required<HealthCheckerConfig>;

  constructor(config: HealthCheckerConfig = {}) {
    this.config = {
      defaultTimeout: config.defaultTimeout ?? 5000,
      parallel: config.parallel ?? true,
      onStatusChange: config.onStatusChange ?? (() => {}),
    };
  }

  /**
   * Register a health check.
   */
  register(name: string, check: HealthCheckFn, options?: Partial<Omit<HealthCheckConfig, 'name' | 'check'>>): void {
    this.checks.set(name, {
      name,
      check,
      timeout: options?.timeout ?? this.config.defaultTimeout,
      critical: options?.critical ?? true,
      description: options?.description,
    });
  }

  /**
   * Unregister a health check.
   */
  unregister(name: string): boolean {
    this.lastResults.delete(name);
    return this.checks.delete(name);
  }

  /**
   * Run a single health check.
   */
  async check(name: string): Promise<HealthCheckResult> {
    const config = this.checks.get(name);
    if (!config) {
      return {
        name,
        healthy: false,
        latencyMs: 0,
        error: `Health check not found: ${name}`,
        timestamp: new Date(),
      };
    }

    this.emit({ type: 'check.started', name });

    const start = Date.now();
    let result: HealthCheckResult;

    try {
      const healthy = await Promise.race([
        config.check(),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error('Health check timeout')), config.timeout)
        ),
      ]);

      result = {
        name,
        healthy: healthy === true,
        latencyMs: Date.now() - start,
        timestamp: new Date(),
      };
    } catch (error) {
      result = {
        name,
        healthy: false,
        latencyMs: Date.now() - start,
        error: (error as Error).message,
        timestamp: new Date(),
      };
    }

    // Check for status change
    const previous = this.lastResults.get(name);
    if (previous?.healthy !== result.healthy) {
      this.emit({ type: 'status.changed', name, healthy: result.healthy, previous: previous?.healthy });
      this.config.onStatusChange(name, result.healthy, previous?.healthy);
    }

    this.lastResults.set(name, result);
    this.emit({ type: 'check.completed', name, result });

    return result;
  }

  /**
   * Run all health checks.
   */
  async checkAll(): Promise<HealthReport> {
    const start = Date.now();
    const checkNames = Array.from(this.checks.keys());

    let results: HealthCheckResult[];

    if (this.config.parallel) {
      results = await Promise.all(checkNames.map(name => this.check(name)));
    } else {
      results = [];
      for (const name of checkNames) {
        results.push(await this.check(name));
      }
    }

    const healthyCount = results.filter(r => r.healthy).length;

    const report: HealthReport = {
      healthy: healthyCount === results.length,
      healthyCount,
      totalCount: results.length,
      checks: results,
      timestamp: new Date(),
      totalLatencyMs: Date.now() - start,
    };

    this.emit({ type: 'report.generated', report });

    return report;
  }

  /**
   * Get the last result for a check.
   */
  getLastResult(name: string): HealthCheckResult | undefined {
    return this.lastResults.get(name);
  }

  /**
   * Get all last results.
   */
  getAllLastResults(): Map<string, HealthCheckResult> {
    return new Map(this.lastResults);
  }

  /**
   * Check if system is healthy based on last results.
   * Returns true if all critical checks passed.
   */
  isHealthy(): boolean {
    for (const [name, config] of this.checks) {
      const result = this.lastResults.get(name);
      if (config.critical && (!result || !result.healthy)) {
        return false;
      }
    }
    return true;
  }

  /**
   * Get list of unhealthy checks.
   */
  getUnhealthyChecks(): string[] {
    const unhealthy: string[] = [];
    for (const [name, result] of this.lastResults) {
      if (!result.healthy) {
        unhealthy.push(name);
      }
    }
    return unhealthy;
  }

  /**
   * Start periodic health checks.
   */
  startPeriodicChecks(intervalMs: number): void {
    this.stopPeriodicChecks();
    this.periodicInterval = setInterval(() => {
      this.checkAll().catch(err => {
        logger.error('Periodic health check failed', { error: String(err) });
      });
    }, intervalMs);

    // Run initial check
    this.checkAll().catch(err => {
      logger.error('Initial health check failed', { error: String(err) });
    });
  }

  /**
   * Stop periodic health checks.
   */
  stopPeriodicChecks(): void {
    if (this.periodicInterval) {
      clearInterval(this.periodicInterval);
      this.periodicInterval = undefined;
    }
  }

  /**
   * Add an event listener.
   */
  on(listener: HealthEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(event: HealthEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }

  /**
   * Get registered check names.
   */
  getCheckNames(): string[] {
    return Array.from(this.checks.keys());
  }

  /**
   * Cleanup resources.
   */
  dispose(): void {
    this.stopPeriodicChecks();
    this.checks.clear();
    this.lastResults.clear();
    this.listeners.clear();
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a health checker instance.
 */
export function createHealthChecker(config?: HealthCheckerConfig): HealthChecker {
  return new HealthChecker(config);
}

// =============================================================================
// BUILT-IN HEALTH CHECKS
// =============================================================================

/**
 * Create a health check for an LLM provider.
 * Uses a minimal ping request to verify connectivity.
 */
export function createProviderHealthCheck(
  provider: { chat: (messages: Array<{ role: string; content: string }>) => Promise<unknown> },
  providerName: string = 'llm'
): HealthCheckConfig {
  return {
    name: providerName,
    description: `LLM provider health check for ${providerName}`,
    timeout: 10000,
    critical: true,
    check: async () => {
      // Send minimal request to verify provider is responsive
      const response = await provider.chat([
        { role: 'user', content: 'ping' },
      ]);
      return response !== null && response !== undefined;
    },
  };
}

/**
 * Create a health check for file system access.
 */
export function createFileSystemHealthCheck(
  path: string = '/tmp'
): HealthCheckConfig {
  return {
    name: 'filesystem',
    description: 'File system write access check',
    timeout: 2000,
    critical: true,
    check: async () => {
      const { writeFile, unlink, access, constants } = await import('node:fs/promises');
      const testPath = `${path}/.health-check-${Date.now()}`;

      try {
        // Check write access by creating and deleting a temp file
        await writeFile(testPath, 'health-check');
        await access(testPath, constants.R_OK | constants.W_OK);
        await unlink(testPath);
        return true;
      } catch {
        return false;
      }
    },
  };
}

/**
 * Create a health check for SQLite database.
 */
export function createSQLiteHealthCheck(
  dbPath: string
): HealthCheckConfig {
  return {
    name: 'sqlite',
    description: `SQLite database health check for ${dbPath}`,
    timeout: 3000,
    critical: false, // Non-critical - agent can work without persistence
    check: async () => {
      const { existsSync } = await import('node:fs');
      const { access, constants } = await import('node:fs/promises');

      if (!existsSync(dbPath)) {
        return false;
      }

      try {
        await access(dbPath, constants.R_OK | constants.W_OK);
        return true;
      } catch {
        return false;
      }
    },
  };
}

/**
 * Create a health check for MCP server connectivity.
 */
export function createMCPHealthCheck(
  mcpClient: {
    listServers: () => Array<{ name: string; status: string }>;
  },
  serverName?: string
): HealthCheckConfig {
  return {
    name: serverName ? `mcp:${serverName}` : 'mcp',
    description: serverName
      ? `MCP server health check for ${serverName}`
      : 'MCP servers health check',
    timeout: 5000,
    critical: false, // Non-critical - agent can work without MCP
    check: async () => {
      const servers = mcpClient.listServers();

      if (serverName) {
        const server = servers.find(s => s.name === serverName);
        return server?.status === 'connected';
      }

      // At least one server should be connected
      return servers.some(s => s.status === 'connected');
    },
  };
}

/**
 * Create a health check for network connectivity.
 */
export function createNetworkHealthCheck(
  testUrl: string = 'https://api.anthropic.com'
): HealthCheckConfig {
  return {
    name: 'network',
    description: 'Network connectivity check',
    timeout: 5000,
    critical: true,
    check: async () => {
      try {
        const response = await fetch(testUrl, {
          method: 'HEAD',
          signal: AbortSignal.timeout(4000),
        });
        return response.status < 500;
      } catch {
        return false;
      }
    },
  };
}

// =============================================================================
// FORMATTING
// =============================================================================

/**
 * Format health report for display.
 */
export function formatHealthReport(report: HealthReport): string {
  const lines: string[] = [];

  const statusIcon = report.healthy ? '✓' : '✗';
  const statusText = report.healthy ? 'HEALTHY' : 'UNHEALTHY';

  lines.push(`${statusIcon} System Status: ${statusText}`);
  lines.push(`  Checks: ${report.healthyCount}/${report.totalCount} passing`);
  lines.push(`  Total latency: ${report.totalLatencyMs}ms`);
  lines.push('');

  for (const check of report.checks) {
    const icon = check.healthy ? '✓' : '✗';
    const latency = `${check.latencyMs}ms`;
    const error = check.error ? ` - ${check.error}` : '';
    lines.push(`  ${icon} ${check.name}: ${latency}${error}`);
  }

  return lines.join('\n');
}

/**
 * Format health report as JSON for APIs.
 */
export function healthReportToJSON(report: HealthReport): Record<string, unknown> {
  return {
    status: report.healthy ? 'healthy' : 'unhealthy',
    healthyCount: report.healthyCount,
    totalCount: report.totalCount,
    timestamp: report.timestamp.toISOString(),
    totalLatencyMs: report.totalLatencyMs,
    checks: report.checks.map(check => ({
      name: check.name,
      status: check.healthy ? 'pass' : 'fail',
      latencyMs: check.latencyMs,
      error: check.error,
      timestamp: check.timestamp.toISOString(),
    })),
  };
}
