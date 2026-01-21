/**
 * Lesson 20: Sandboxing Types
 *
 * Types for secure execution environments, resource limits,
 * and isolation strategies.
 */

// =============================================================================
// ISOLATION LEVELS
// =============================================================================

/**
 * Level of isolation for code execution.
 */
export type IsolationLevel =
  | 'none'       // Direct execution (dangerous)
  | 'process'    // Separate process with restrictions
  | 'container'  // Docker container isolation
  | 'vm'         // Full VM isolation (most secure)
  | 'wasm';      // WebAssembly sandbox

// =============================================================================
// SANDBOX CONFIGURATION
// =============================================================================

/**
 * Sandbox configuration.
 */
export interface SandboxConfig {
  /** Isolation level */
  isolationLevel: IsolationLevel;

  /** Allow network access */
  allowNetwork: boolean;

  /** Allowed network hosts (if network enabled) */
  allowedHosts?: string[];

  /** Allowed file paths for read */
  allowedReadPaths: string[];

  /** Allowed file paths for write */
  allowedWritePaths: string[];

  /** Working directory */
  workingDirectory: string;

  /** Environment variables */
  environment: Record<string, string>;

  /** Resource limits */
  resourceLimits: ResourceLimits;

  /** Security options */
  security: SecurityOptions;
}

/**
 * Resource limits for sandboxed execution.
 */
export interface ResourceLimits {
  /** Maximum CPU time in seconds */
  maxCpuSeconds: number;

  /** Maximum memory in MB */
  maxMemoryMB: number;

  /** Maximum disk usage in MB */
  maxDiskMB: number;

  /** Maximum execution time in ms */
  timeoutMs: number;

  /** Maximum number of processes */
  maxProcesses: number;

  /** Maximum file descriptors */
  maxFileDescriptors: number;

  /** Maximum output size in bytes */
  maxOutputBytes: number;
}

/**
 * Security options.
 */
export interface SecurityOptions {
  /** Drop all capabilities */
  dropCapabilities: boolean;

  /** Run as non-root user */
  runAsNonRoot: boolean;

  /** User ID to run as */
  userId?: number;

  /** Group ID to run as */
  groupId?: number;

  /** Read-only root filesystem */
  readOnlyRootFilesystem: boolean;

  /** Disable setuid/setgid */
  noNewPrivileges: boolean;

  /** Seccomp profile */
  seccompProfile?: 'default' | 'strict' | 'custom';

  /** AppArmor profile */
  appArmorProfile?: string;
}

// =============================================================================
// EXECUTION
// =============================================================================

/**
 * Command to execute.
 */
export interface ExecutionCommand {
  /** Command or script to run */
  command: string;

  /** Command arguments */
  args: string[];

  /** Working directory override */
  cwd?: string;

  /** Additional environment variables */
  env?: Record<string, string>;

  /** Standard input */
  stdin?: string;

  /** Shell to use (for shell commands) */
  shell?: string;
}

/**
 * Execution result.
 */
export interface ExecutionResult {
  /** Exit code (0 = success) */
  exitCode: number;

  /** Standard output */
  stdout: string;

  /** Standard error */
  stderr: string;

  /** Execution duration in ms */
  durationMs: number;

  /** Resource usage */
  resourceUsage: ResourceUsage;

  /** Whether execution was killed (timeout/limit) */
  killed: boolean;

  /** Kill reason if applicable */
  killReason?: KillReason;

  /** Sandbox that was used */
  sandboxId: string;
}

/**
 * Resource usage statistics.
 */
export interface ResourceUsage {
  /** CPU time used in ms */
  cpuTimeMs: number;

  /** Peak memory usage in MB */
  peakMemoryMB: number;

  /** Disk I/O read bytes */
  diskReadBytes: number;

  /** Disk I/O write bytes */
  diskWriteBytes: number;

  /** Network bytes sent */
  networkSentBytes: number;

  /** Network bytes received */
  networkReceivedBytes: number;
}

/**
 * Reasons for killing execution.
 */
export type KillReason =
  | 'timeout'
  | 'memory_limit'
  | 'cpu_limit'
  | 'disk_limit'
  | 'output_limit'
  | 'process_limit'
  | 'security_violation'
  | 'manual';

// =============================================================================
// SANDBOX INTERFACE
// =============================================================================

/**
 * Sandbox interface for executing code safely.
 */
export interface Sandbox {
  /** Unique sandbox identifier */
  id: string;

  /** Sandbox configuration */
  config: SandboxConfig;

  /** Execute a command */
  execute(command: ExecutionCommand): Promise<ExecutionResult>;

  /** Check if sandbox is ready */
  isReady(): Promise<boolean>;

  /** Get sandbox status */
  getStatus(): Promise<SandboxStatus>;

  /** Clean up resources */
  cleanup(): Promise<void>;
}

/**
 * Sandbox status.
 */
export interface SandboxStatus {
  /** Whether sandbox is active */
  active: boolean;

  /** Number of executions performed */
  executionCount: number;

  /** Total execution time */
  totalExecutionMs: number;

  /** Current resource usage */
  currentUsage: Partial<ResourceUsage>;

  /** Any warnings or issues */
  warnings: string[];
}

// =============================================================================
// SANDBOX POOL
// =============================================================================

/**
 * Pool of reusable sandboxes.
 */
export interface SandboxPool {
  /** Acquire a sandbox from the pool */
  acquire(config?: Partial<SandboxConfig>): Promise<Sandbox>;

  /** Release a sandbox back to the pool */
  release(sandbox: Sandbox): Promise<void>;

  /** Get pool statistics */
  getStats(): SandboxPoolStats;

  /** Shutdown the pool */
  shutdown(): Promise<void>;
}

/**
 * Pool statistics.
 */
export interface SandboxPoolStats {
  /** Total sandboxes in pool */
  totalSandboxes: number;

  /** Available sandboxes */
  availableSandboxes: number;

  /** Sandboxes in use */
  inUseSandboxes: number;

  /** Total executions */
  totalExecutions: number;

  /** Average execution time */
  avgExecutionMs: number;
}

// =============================================================================
// EVENTS
// =============================================================================

/**
 * Sandbox events.
 */
export type SandboxEvent =
  | { type: 'sandbox.created'; sandboxId: string; config: SandboxConfig }
  | { type: 'sandbox.destroyed'; sandboxId: string }
  | { type: 'execution.started'; sandboxId: string; command: ExecutionCommand }
  | { type: 'execution.completed'; sandboxId: string; result: ExecutionResult }
  | { type: 'execution.killed'; sandboxId: string; reason: KillReason }
  | { type: 'limit.warning'; sandboxId: string; limitType: string; current: number; max: number }
  | { type: 'security.violation'; sandboxId: string; violation: string };

export type SandboxEventListener = (event: SandboxEvent) => void;

// =============================================================================
// DEFAULT CONFIGURATIONS
// =============================================================================

/**
 * Default resource limits.
 */
export const DEFAULT_RESOURCE_LIMITS: ResourceLimits = {
  maxCpuSeconds: 30,
  maxMemoryMB: 256,
  maxDiskMB: 100,
  timeoutMs: 60000,
  maxProcesses: 10,
  maxFileDescriptors: 100,
  maxOutputBytes: 1024 * 1024, // 1MB
};

/**
 * Default security options.
 */
export const DEFAULT_SECURITY_OPTIONS: SecurityOptions = {
  dropCapabilities: true,
  runAsNonRoot: true,
  userId: 1000,
  groupId: 1000,
  readOnlyRootFilesystem: false,
  noNewPrivileges: true,
  seccompProfile: 'default',
};

/**
 * Default sandbox configuration.
 */
export const DEFAULT_SANDBOX_CONFIG: SandboxConfig = {
  isolationLevel: 'process',
  allowNetwork: false,
  allowedReadPaths: ['/tmp'],
  allowedWritePaths: ['/tmp'],
  workingDirectory: '/tmp',
  environment: {},
  resourceLimits: DEFAULT_RESOURCE_LIMITS,
  security: DEFAULT_SECURITY_OPTIONS,
};

/**
 * Strict sandbox configuration (most restrictive).
 */
export const STRICT_SANDBOX_CONFIG: SandboxConfig = {
  isolationLevel: 'container',
  allowNetwork: false,
  allowedHosts: [],
  allowedReadPaths: [],
  allowedWritePaths: [],
  workingDirectory: '/sandbox',
  environment: {},
  resourceLimits: {
    maxCpuSeconds: 5,
    maxMemoryMB: 64,
    maxDiskMB: 10,
    timeoutMs: 10000,
    maxProcesses: 1,
    maxFileDescriptors: 20,
    maxOutputBytes: 65536, // 64KB
  },
  security: {
    dropCapabilities: true,
    runAsNonRoot: true,
    userId: 65534, // nobody
    groupId: 65534,
    readOnlyRootFilesystem: true,
    noNewPrivileges: true,
    seccompProfile: 'strict',
  },
};

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Generate sandbox ID.
 */
export function generateSandboxId(): string {
  return `sandbox-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * Merge configurations with defaults.
 */
export function mergeConfig(
  partial: Partial<SandboxConfig>,
  defaults: SandboxConfig = DEFAULT_SANDBOX_CONFIG
): SandboxConfig {
  return {
    ...defaults,
    ...partial,
    resourceLimits: {
      ...defaults.resourceLimits,
      ...partial.resourceLimits,
    },
    security: {
      ...defaults.security,
      ...partial.security,
    },
  };
}
