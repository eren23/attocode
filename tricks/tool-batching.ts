/**
 * Trick D: Tool Call Batching
 *
 * Execute multiple tool calls with controlled concurrency.
 * Supports batching, parallelization, and error handling.
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * Tool call definition.
 */
export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

/**
 * Tool result.
 */
export interface ToolResult {
  callId: string;
  success: boolean;
  result?: unknown;
  error?: string;
  duration?: number;
}

/**
 * Tool definition.
 */
export interface ToolDefinition {
  name: string;
  execute: (args: Record<string, unknown>) => Promise<unknown>;
}

/**
 * Tool registry.
 */
export interface ToolRegistry {
  get(name: string): ToolDefinition | undefined;
}

/**
 * Batch execution options.
 */
export interface BatchOptions {
  /** Maximum concurrent executions */
  concurrency?: number;
  /** Timeout per tool call (ms) */
  timeout?: number;
  /** Continue on error */
  continueOnError?: boolean;
  /** Callback for progress */
  onProgress?: (completed: number, total: number) => void;
}

// =============================================================================
// BATCH EXECUTOR
// =============================================================================

/**
 * Execute multiple tool calls with controlled concurrency.
 */
export async function executeBatch(
  calls: ToolCall[],
  registry: ToolRegistry,
  options: BatchOptions = {}
): Promise<ToolResult[]> {
  const { concurrency = 5, timeout = 30000, continueOnError = true, onProgress } = options;

  const results: ToolResult[] = [];
  let completed = 0;

  // Process in batches with concurrency limit
  const chunks = chunkArray(calls, concurrency);

  for (const chunk of chunks) {
    const chunkPromises = chunk.map(async (call) => {
      const result = await executeWithTimeout(call, registry, timeout);
      completed++;
      onProgress?.(completed, calls.length);
      return result;
    });

    const chunkResults = await Promise.all(chunkPromises);
    results.push(...chunkResults);

    // Check for errors if not continuing
    if (!continueOnError) {
      const error = chunkResults.find((r) => !r.success);
      if (error) {
        throw new Error(`Tool call failed: ${error.error}`);
      }
    }
  }

  return results;
}

/**
 * Execute a single tool call with timeout.
 */
async function executeWithTimeout(
  call: ToolCall,
  registry: ToolRegistry,
  timeout: number
): Promise<ToolResult> {
  const startTime = Date.now();

  const tool = registry.get(call.name);
  if (!tool) {
    return {
      callId: call.id,
      success: false,
      error: `Unknown tool: ${call.name}`,
      duration: 0,
    };
  }

  try {
    const result = await Promise.race([
      tool.execute(call.arguments),
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error('Timeout')), timeout)
      ),
    ]);

    return {
      callId: call.id,
      success: true,
      result,
      duration: Date.now() - startTime,
    };
  } catch (err) {
    return {
      callId: call.id,
      success: false,
      error: err instanceof Error ? err.message : String(err),
      duration: Date.now() - startTime,
    };
  }
}

// =============================================================================
// PARALLEL EXECUTOR
// =============================================================================

/**
 * Execute all calls in parallel (no concurrency limit).
 */
export async function executeParallel(
  calls: ToolCall[],
  registry: ToolRegistry,
  timeout: number = 30000
): Promise<ToolResult[]> {
  return Promise.all(calls.map((call) => executeWithTimeout(call, registry, timeout)));
}

/**
 * Execute calls sequentially.
 */
export async function executeSequential(
  calls: ToolCall[],
  registry: ToolRegistry,
  timeout: number = 30000
): Promise<ToolResult[]> {
  const results: ToolResult[] = [];

  for (const call of calls) {
    const result = await executeWithTimeout(call, registry, timeout);
    results.push(result);
  }

  return results;
}

// =============================================================================
// DEPENDENCY-AWARE EXECUTOR
// =============================================================================

/**
 * Tool call with dependencies.
 */
export interface DependentToolCall extends ToolCall {
  /** IDs of calls this depends on */
  dependsOn?: string[];
}

/**
 * Execute calls respecting dependencies.
 */
export async function executeWithDependencies(
  calls: DependentToolCall[],
  registry: ToolRegistry,
  options: BatchOptions = {}
): Promise<ToolResult[]> {
  const { timeout = 30000 } = options;
  const results = new Map<string, ToolResult>();
  const pending = new Set(calls.map((c) => c.id));

  // Keep processing until all done
  while (pending.size > 0) {
    // Find calls that can execute (dependencies satisfied)
    const ready = calls.filter((call) => {
      if (!pending.has(call.id)) return false;

      const deps = call.dependsOn || [];
      return deps.every((depId) => results.has(depId));
    });

    if (ready.length === 0 && pending.size > 0) {
      throw new Error('Circular dependency detected');
    }

    // Execute ready calls in parallel
    const batchResults = await executeParallel(ready, registry, timeout);

    // Store results and mark as done
    for (const result of batchResults) {
      results.set(result.callId, result);
      pending.delete(result.callId);
    }
  }

  // Return in original order
  return calls.map((call) => results.get(call.id)!);
}

// =============================================================================
// RETRYING EXECUTOR
// =============================================================================

/**
 * Retry options.
 */
export interface RetryOptions extends BatchOptions {
  maxRetries?: number;
  retryDelay?: number;
  shouldRetry?: (error: string) => boolean;
}

/**
 * Execute with retries.
 */
export async function executeWithRetry(
  call: ToolCall,
  registry: ToolRegistry,
  options: RetryOptions = {}
): Promise<ToolResult> {
  const {
    maxRetries = 3,
    retryDelay = 1000,
    timeout = 30000,
    shouldRetry = () => true,
  } = options;

  let lastResult: ToolResult | null = null;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    lastResult = await executeWithTimeout(call, registry, timeout);

    if (lastResult.success) {
      return lastResult;
    }

    // Check if we should retry
    if (attempt < maxRetries && shouldRetry(lastResult.error || '')) {
      await new Promise((r) => setTimeout(r, retryDelay * (attempt + 1)));
      continue;
    }

    break;
  }

  return lastResult!;
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Split array into chunks.
 */
function chunkArray<T>(array: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let i = 0; i < array.length; i += size) {
    chunks.push(array.slice(i, i + size));
  }
  return chunks;
}

/**
 * Create a simple tool registry.
 */
export function createToolRegistry(tools: ToolDefinition[]): ToolRegistry {
  const map = new Map(tools.map((t) => [t.name, t]));
  return {
    get: (name: string) => map.get(name),
  };
}

/**
 * Group results by success.
 */
export function groupResults(results: ToolResult[]): {
  successful: ToolResult[];
  failed: ToolResult[];
} {
  return {
    successful: results.filter((r) => r.success),
    failed: results.filter((r) => !r.success),
  };
}

// Usage:
// const registry = createToolRegistry([
//   { name: 'read_file', execute: async (args) => fs.readFile(args.path) },
//   { name: 'list_dir', execute: async (args) => fs.readdir(args.path) },
// ]);
//
// const calls: ToolCall[] = [
//   { id: '1', name: 'read_file', arguments: { path: 'a.txt' } },
//   { id: '2', name: 'read_file', arguments: { path: 'b.txt' } },
//   { id: '3', name: 'list_dir', arguments: { path: '.' } },
// ];
//
// const results = await executeBatch(calls, registry, { concurrency: 2 });
