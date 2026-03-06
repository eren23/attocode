/**
 * Worker Repository
 *
 * Worker result CRUD operations and artifact tracking.
 * Stores full worker output outside main context, with lightweight
 * references for context injection.
 *
 * Extracted from sqlite-store.ts as part of Phase 3c restructuring.
 */

import type { WorkerResult, WorkerResultRef, SQLiteStoreDeps } from './sqlite-store.js';

// =============================================================================
// WORKER RESULT CRUD
// =============================================================================

/**
 * Create a pending worker result entry.
 * Call this when spawning a worker to reserve the result slot.
 * Returns the result ID for later reference.
 */
export function createWorkerResult(
  deps: SQLiteStoreDeps,
  workerId: string,
  taskDescription: string,
  modelUsed?: string,
): string | undefined {
  if (!deps.features.workerResults || !deps.stmts.insertWorkerResult) {
    return undefined;
  }

  if (!deps.getCurrentSessionId()) {
    deps.ensureSession();
  }

  const id = `wr-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
  const now = new Date().toISOString();

  deps.stmts.insertWorkerResult.run({
    id,
    sessionId: deps.getCurrentSessionId(),
    workerId,
    taskDescription,
    modelUsed: modelUsed ?? null,
    status: 'pending',
    summary: null,
    fullOutput: null,
    artifacts: null,
    metrics: null,
    error: null,
    createdAt: now,
    completedAt: null,
  });

  return id;
}

/**
 * Complete a worker result with output.
 * Stores full output in database, generates summary for context injection.
 */
export function completeWorkerResult(
  deps: SQLiteStoreDeps,
  resultId: string,
  output: {
    fullOutput: string;
    summary?: string;
    artifacts?: Record<string, unknown>[];
    metrics?: { tokens?: number; duration?: number; toolCalls?: number };
  },
): WorkerResultRef | undefined {
  if (!deps.features.workerResults || !deps.stmts.updateWorkerResult) {
    return undefined;
  }

  const now = new Date().toISOString();

  // Auto-generate summary if not provided (first 200 chars)
  const summary = output.summary ?? generateResultSummary(output.fullOutput);

  deps.stmts.updateWorkerResult.run({
    id: resultId,
    status: 'success',
    summary,
    fullOutput: output.fullOutput,
    artifacts: output.artifacts ? JSON.stringify(output.artifacts) : null,
    metrics: output.metrics ? JSON.stringify(output.metrics) : null,
    error: null,
    completedAt: now,
  });

  // Return reference for context injection
  const result = getWorkerResult(deps, resultId);
  return result ? toResultRef(result) : undefined;
}

/**
 * Mark a worker result as failed.
 */
export function failWorkerResult(deps: SQLiteStoreDeps, resultId: string, error: string): void {
  if (!deps.features.workerResults || !deps.stmts.updateWorkerResult) {
    return;
  }

  deps.stmts.updateWorkerResult.run({
    id: resultId,
    status: 'error',
    summary: `Failed: ${error.slice(0, 100)}`,
    fullOutput: null,
    artifacts: null,
    metrics: null,
    error,
    completedAt: new Date().toISOString(),
  });
}

/**
 * Get a worker result by ID (includes full output).
 */
export function getWorkerResult(deps: SQLiteStoreDeps, resultId: string): WorkerResult | undefined {
  if (!deps.features.workerResults || !deps.stmts.getWorkerResult) {
    return undefined;
  }
  return deps.stmts.getWorkerResult.get(resultId) as WorkerResult | undefined;
}

/**
 * Get a lightweight reference to a worker result (for context injection).
 * Does NOT include full output - that stays in database.
 */
export function getWorkerResultRef(
  deps: SQLiteStoreDeps,
  resultId: string,
): WorkerResultRef | undefined {
  const result = getWorkerResult(deps, resultId);
  return result ? toResultRef(result) : undefined;
}

/**
 * List all worker results for a session.
 */
export function listWorkerResults(deps: SQLiteStoreDeps, sessionId?: string): WorkerResult[] {
  if (!deps.features.workerResults || !deps.stmts.listWorkerResults) {
    return [];
  }
  const sid = sessionId ?? deps.getCurrentSessionId();
  if (!sid) return [];
  return deps.stmts.listWorkerResults.all(sid) as WorkerResult[];
}

/**
 * List pending worker results (workers still running).
 */
export function listPendingWorkerResults(
  deps: SQLiteStoreDeps,
  sessionId?: string,
): WorkerResult[] {
  if (!deps.features.workerResults || !deps.stmts.listPendingWorkerResults) {
    return [];
  }
  const sid = sessionId ?? deps.getCurrentSessionId();
  if (!sid) return [];
  return deps.stmts.listPendingWorkerResults.all(sid) as WorkerResult[];
}

/**
 * Get a summary of worker results for context injection.
 * Returns lightweight references, not full outputs.
 */
export function getWorkerResultsSummary(deps: SQLiteStoreDeps, sessionId?: string): string {
  if (!deps.features.workerResults) {
    return '';
  }

  const results = listWorkerResults(deps, sessionId);
  if (results.length === 0) {
    return '';
  }

  const lines: string[] = ['Worker Results:'];
  for (const r of results.slice(0, 10)) {
    const status = r.status === 'success' ? '\u2713' : r.status === 'error' ? '\u2717' : '\u23F3';
    const task =
      r.taskDescription.length > 50 ? r.taskDescription.slice(0, 47) + '...' : r.taskDescription;
    lines.push(`${status} [${r.id}] ${task}`);
    if (r.summary) {
      lines.push(`  \u2514\u2500 ${r.summary}`);
    }
  }
  if (results.length > 10) {
    lines.push(`  ... and ${results.length - 10} more`);
  }
  return lines.join('\n');
}

// =============================================================================
// HELPERS
// =============================================================================

/**
 * Convert a full WorkerResult to a lightweight reference.
 */
export function toResultRef(result: WorkerResult): WorkerResultRef {
  return {
    id: result.id,
    workerId: result.workerId,
    taskDescription: result.taskDescription,
    status: result.status,
    summary: result.summary,
    modelUsed: result.modelUsed,
    retrievalHint: `Full output available: store.getWorkerResult('${result.id}')`,
  };
}

/**
 * Generate a brief summary from full output.
 */
export function generateResultSummary(fullOutput: string): string {
  const firstLine = fullOutput.split('\n')[0].trim();
  if (firstLine.length <= 150) {
    return firstLine;
  }
  return firstLine.slice(0, 147) + '...';
}
