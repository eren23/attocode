/**
 * Trace Service
 *
 * Service layer that wraps trace-viewer functionality for the API.
 * Handles file discovery, parsing, and analysis.
 */

import { readdir, stat, writeFile, mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import {
  createJSONLParser,
  createJSONExporter,
  createTimelineView,
  createTreeView,
  createTokenFlowView,
  createInefficiencyDetector,
  type ParsedSession,
} from '../lib/index.js';

// Default trace directories to search (relative to project root)
const DEFAULT_TRACE_DIRS = [
  '.traces',
  '.agent/traces',
  'traces',
  'tools/eval/results',  // Eval framework traces
];

// Find project root by looking for package.json
function findProjectRoot(startDir: string): string {
  let dir = startDir;
  while (dir !== '/') {
    // Check if we're in tools/trace-dashboard, go up two levels
    if (dir.endsWith('tools/trace-dashboard') || dir.endsWith('tools\\trace-dashboard')) {
      return join(dir, '..', '..');
    }
    dir = join(dir, '..');
  }
  return startDir;
}

const PROJECT_ROOT = findProjectRoot(process.cwd());

// Directory for uploaded traces
const UPLOADS_DIR = join(process.cwd(), 'uploads');

// Ensure uploads directory exists
async function ensureUploadsDir() {
  try {
    await mkdir(UPLOADS_DIR, { recursive: true });
  } catch {
    // Directory exists
  }
}

// In-memory store for uploaded trace content (for traces uploaded as text)
const uploadedTraces = new Map<string, { content: string; name: string; uploadedAt: Date }>();

// Session cache to avoid reparsing
const sessionCache = new Map<string, { session: ParsedSession; timestamp: number }>();
const CACHE_TTL = 60_000; // 1 minute cache

export interface SessionListItem {
  id: string;
  task: string;
  model: string;
  status: 'running' | 'completed' | 'failed' | 'cancelled';
  startTime: string;
  durationMs?: number;
  /** Number of tasks in this session (for terminal sessions with multiple prompts) */
  taskCount: number;
  /** Whether this is a terminal session (multiple tasks) or single-task session */
  isTerminalSession: boolean;
  /** Whether this session used swarm mode */
  isSwarm: boolean;
  metrics: {
    iterations: number;
    totalTokens: number;
    cost: number;
    cacheHitRate: number;
    errors: number;
  };
  filePath: string;
}

/**
 * Find trace directories - searches project root and uploads
 */
async function findTraceDirs(basePath?: string): Promise<string[]> {
  const foundDirs: string[] = [];
  const searchPaths = [PROJECT_ROOT, process.cwd()];

  if (basePath && !searchPaths.includes(basePath)) {
    searchPaths.push(basePath);
  }

  for (const base of searchPaths) {
    for (const dir of DEFAULT_TRACE_DIRS) {
      const fullPath = join(base, dir);
      try {
        const stats = await stat(fullPath);
        if (stats.isDirectory()) {
          // Avoid duplicates
          if (!foundDirs.includes(fullPath)) {
            foundDirs.push(fullPath);
          }
        }
      } catch {
        // Directory doesn't exist, skip
      }
    }
  }

  // Also check uploads directory
  try {
    await ensureUploadsDir();
    const uploadsStats = await stat(UPLOADS_DIR);
    if (uploadsStats.isDirectory()) {
      foundDirs.push(UPLOADS_DIR);
    }
  } catch {
    // Uploads dir doesn't exist
  }

  return foundDirs;
}

/**
 * List all trace files from discovered directories
 */
async function listTraceFiles(basePath?: string): Promise<string[]> {
  const traceDirs = await findTraceDirs(basePath);
  const files: string[] = [];

  for (const dir of traceDirs) {
    try {
      const entries = await readdir(dir);
      for (const entry of entries) {
        if (entry.endsWith('.jsonl')) {
          files.push(join(dir, entry));
        }
      }
    } catch {
      // Directory read failed, skip
    }
  }

  // Sort by modification time (newest first)
  const filesWithStats = await Promise.all(
    files.map(async (file) => {
      try {
        const stats = await stat(file);
        return { file, mtime: stats.mtime.getTime() };
      } catch {
        return { file, mtime: 0 };
      }
    })
  );

  return filesWithStats
    .sort((a, b) => b.mtime - a.mtime)
    .map((f) => f.file);
}

/**
 * Parse a session from file, with caching
 */
async function parseSession(filePath: string): Promise<ParsedSession> {
  // Check cache
  const cached = sessionCache.get(filePath);
  if (cached && Date.now() - cached.timestamp < CACHE_TTL) {
    return cached.session;
  }

  // Parse file
  const parser = createJSONLParser();
  const session = await parser.parseFile(filePath);

  // Cache result
  sessionCache.set(filePath, { session, timestamp: Date.now() });

  return session;
}

/**
 * Get list of all sessions with basic metadata
 */
export async function getSessions(basePath?: string): Promise<SessionListItem[]> {
  const files = await listTraceFiles(basePath);
  const sessions: SessionListItem[] = [];

  for (const filePath of files) {
    try {
      const session = await parseSession(filePath);

      // Skip files with invalid timestamps (e.g. eval prediction JSONL files)
      if (isNaN(session.startTime.getTime())) continue;

      // Determine if this is a terminal session (multiple tasks) or single-task session
      const isTerminalSession = session.tasks && session.tasks.length > 0;
      const taskCount = isTerminalSession ? session.tasks.length : 1;

      // For terminal sessions, show summary; for single-task, show the task
      const displayTask = isTerminalSession
        ? `Terminal Session (${taskCount} tasks)`
        : session.task.slice(0, 200);

      sessions.push({
        id: session.sessionId,
        task: displayTask,
        model: session.model,
        status: session.status,
        startTime: session.startTime.toISOString(),
        durationMs: session.durationMs,
        taskCount,
        isTerminalSession,
        isSwarm: session.metrics.isSwarm === true || session.swarmData !== undefined,
        metrics: {
          iterations: session.metrics.iterations,
          totalTokens: session.metrics.inputTokens + session.metrics.outputTokens,
          cost: session.metrics.totalCost,
          cacheHitRate: session.metrics.avgCacheHitRate,
          errors: session.metrics.errors,
        },
        filePath,
      });
    } catch (err) {
      console.error(`Failed to parse ${filePath}:`, err);
    }
  }

  return sessions;
}

/**
 * Get a session by ID or file path
 */
export async function getSession(idOrPath: string): Promise<ParsedSession | null> {
  // Check in-memory uploads first
  const uploaded = uploadedTraces.get(idOrPath);
  if (uploaded) {
    const parser = createJSONLParser();
    return parser.parseString(uploaded.content);
  }

  // Try as direct path first
  try {
    const stats = await stat(idOrPath);
    if (stats.isFile()) {
      return parseSession(idOrPath);
    }
  } catch {
    // Not a direct path, search by ID
  }

  // Search all sessions for matching ID
  const files = await listTraceFiles();
  for (const filePath of files) {
    try {
      const session = await parseSession(filePath);
      if (session.sessionId === idOrPath) {
        return session;
      }
    } catch {
      // Skip failed parses
    }
  }

  return null;
}

/**
 * Get parsed session object (needed by HTMLGenerator and export endpoints)
 */
export async function getSessionParsed(idOrPath: string): Promise<ParsedSession | null> {
  return getSession(idOrPath);
}

/**
 * Get session summary (TraceSummary format)
 */
export async function getSessionSummary(idOrPath: string) {
  const session = await getSession(idOrPath);
  if (!session) return null;

  const exporter = createJSONExporter(session);
  return exporter.generateSummary();
}

/**
 * Get session timeline
 */
export async function getSessionTimeline(idOrPath: string) {
  const session = await getSession(idOrPath);
  if (!session) return null;

  const timelineView = createTimelineView(session);
  return timelineView.generate();
}

/**
 * Get session tree view
 */
export async function getSessionTree(idOrPath: string) {
  const session = await getSession(idOrPath);
  if (!session) return null;

  const treeView = createTreeView(session);
  return treeView.generate();
}

/**
 * Get session token flow data
 */
export async function getSessionTokens(idOrPath: string) {
  const session = await getSession(idOrPath);
  if (!session) return null;

  const tokenFlowView = createTokenFlowView(session);
  return tokenFlowView.generate();
}

/**
 * Get session inefficiencies/issues
 */
export async function getSessionIssues(idOrPath: string) {
  const session = await getSession(idOrPath);
  if (!session) return null;

  const detector = createInefficiencyDetector(session);
  return detector.detect();
}

/**
 * Compare two sessions
 */
export async function compareSessions(idA: string, idB: string) {
  const [sessionA, sessionB] = await Promise.all([
    getSession(idA),
    getSession(idB),
  ]);

  if (!sessionA || !sessionB) {
    return null;
  }

  const summaryA = createJSONExporter(sessionA).generateSummary();
  const summaryB = createJSONExporter(sessionB).generateSummary();

  // Calculate diffs
  const metricDiffs = {
    iterations: summaryB.metrics.iterations - summaryA.metrics.iterations,
    tokens: summaryB.metrics.totalTokens - summaryA.metrics.totalTokens,
    cost: summaryB.metrics.cost - summaryA.metrics.cost,
    cacheHitRate: summaryB.metrics.cacheHitRate - summaryA.metrics.cacheHitRate,
    errors: summaryB.metrics.errors - summaryA.metrics.errors,
  };

  const percentChanges = {
    iterations: summaryA.metrics.iterations > 0
      ? (metricDiffs.iterations / summaryA.metrics.iterations) * 100
      : 0,
    tokens: summaryA.metrics.totalTokens > 0
      ? (metricDiffs.tokens / summaryA.metrics.totalTokens) * 100
      : 0,
    cost: summaryA.metrics.cost > 0
      ? (metricDiffs.cost / summaryA.metrics.cost) * 100
      : 0,
    cacheHitRate: metricDiffs.cacheHitRate * 100, // Already a rate
  };

  // Identify regressions and improvements
  const regressions: string[] = [];
  const improvements: string[] = [];

  if (metricDiffs.iterations > 2) regressions.push(`+${metricDiffs.iterations} iterations`);
  else if (metricDiffs.iterations < -2) improvements.push(`${metricDiffs.iterations} iterations`);

  if (metricDiffs.cost > 0.01) regressions.push(`+$${metricDiffs.cost.toFixed(3)} cost`);
  else if (metricDiffs.cost < -0.01) improvements.push(`-$${Math.abs(metricDiffs.cost).toFixed(3)} cost`);

  if (metricDiffs.cacheHitRate < -0.1) regressions.push('Lower cache hit rate');
  else if (metricDiffs.cacheHitRate > 0.1) improvements.push('Better cache hit rate');

  if (metricDiffs.errors > 0) regressions.push(`+${metricDiffs.errors} errors`);
  else if (metricDiffs.errors < 0) improvements.push(`${metricDiffs.errors} errors`);

  // Overall assessment
  let assessment: 'improved' | 'regressed' | 'mixed' | 'similar' = 'similar';
  if (regressions.length > 0 && improvements.length === 0) assessment = 'regressed';
  else if (improvements.length > 0 && regressions.length === 0) assessment = 'improved';
  else if (regressions.length > 0 && improvements.length > 0) assessment = 'mixed';

  return {
    baselineId: idA,
    comparisonId: idB,
    baseline: summaryA,
    comparison: summaryB,
    metricDiffs,
    percentChanges,
    regressions,
    improvements,
    assessment,
  };
}

/**
 * Get swarm activity data for a session
 */
export async function getSessionSwarmData(idOrPath: string) {
  const session = await getSession(idOrPath);
  if (!session) return null;
  return session.swarmData ?? null;
}

/**
 * Get raw session JSON
 */
export async function getSessionRaw(idOrPath: string) {
  const session = await getSession(idOrPath);
  if (!session) return null;

  const exporter = createJSONExporter(session);
  return JSON.parse(exporter.exportFull());
}

/**
 * Upload a trace file (saves to uploads directory)
 */
export async function uploadTrace(content: string, filename?: string): Promise<{ id: string; filePath: string }> {
  await ensureUploadsDir();

  // Parse to validate and get session ID
  const parser = createJSONLParser();
  const session = parser.parseString(content);

  // Generate filename if not provided
  const name = filename || `uploaded-${session.sessionId}-${Date.now()}.jsonl`;
  const filePath = join(UPLOADS_DIR, name);

  // Save to file
  await writeFile(filePath, content, 'utf-8');

  // Also cache for immediate use
  uploadedTraces.set(session.sessionId, {
    content,
    name,
    uploadedAt: new Date(),
  });

  // Clear the session cache to pick up new file
  sessionCache.delete(filePath);

  return { id: session.sessionId, filePath };
}

/**
 * Upload trace from text content (in-memory only, no file save)
 */
export async function uploadTraceInMemory(content: string, name?: string): Promise<{ id: string }> {
  const parser = createJSONLParser();
  const session = parser.parseString(content);

  uploadedTraces.set(session.sessionId, {
    content,
    name: name || `uploaded-${session.sessionId}`,
    uploadedAt: new Date(),
  });

  return { id: session.sessionId };
}

/**
 * Get list of uploaded traces
 */
export function getUploadedTraces(): Array<{ id: string; name: string; uploadedAt: Date }> {
  return Array.from(uploadedTraces.entries()).map(([id, data]) => ({
    id,
    name: data.name,
    uploadedAt: data.uploadedAt,
  }));
}

/**
 * Parse an uploaded trace from memory
 */
export async function getUploadedSession(id: string): Promise<ParsedSession | null> {
  const uploaded = uploadedTraces.get(id);
  if (!uploaded) return null;

  const parser = createJSONLParser();
  return parser.parseString(uploaded.content);
}
