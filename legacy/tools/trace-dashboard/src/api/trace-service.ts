/**
 * Trace Service
 *
 * Service layer that wraps trace-viewer functionality for the API.
 * Handles file discovery, parsing, and analysis.
 */

import { readdir, stat, writeFile, mkdir } from 'node:fs/promises';
import { basename, dirname, join } from 'node:path';
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

// =============================================================================
// OBSERVABILITY VISUALIZATION DATA
// =============================================================================

import type { CodeMapData, CodeMapFile } from '../lib/codemap-types.js';
import type { AgentGraphData, AgentNode, DataFlow } from '../lib/agent-graph-types.js';

function inferFileType(filePath: string, entryPoints: string[], coreModules: string[]): CodeMapFile['type'] {
  if (entryPoints.some(ep => filePath.includes(ep))) return 'entry_point';
  if (coreModules.some(cm => filePath.includes(cm))) return 'core_module';
  if (filePath.includes('.test.') || filePath.includes('.spec.') || filePath.includes('/test/')) return 'test';
  if (filePath.includes('/types') || filePath.endsWith('.d.ts')) return 'types';
  if (filePath.includes('config') || filePath.includes('.env')) return 'config';
  if (filePath.includes('/utils/') || filePath.includes('/helpers/')) return 'utility';
  return 'other';
}

function normalizePathCandidate(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const v = value.replaceAll('\\', '/').trim();
  if (!v) return null;
  const cleaned = v.replace(/\/{2,}/g, '/');
  if (!cleaned.includes('/') && !cleaned.includes('.')) return null;
  if (cleaned.length > 400) return null;
  if (cleaned.startsWith('-')) return null;
  if (cleaned === '/' || cleaned === '.') return null;
  if (!/[A-Za-z0-9]/.test(cleaned)) return null;
  return cleaned;
}

function extractFilePathsFromUnknown(value: unknown, out: Map<string, number>): void {
  if (!value) return;

  if (Array.isArray(value)) {
    for (const item of value) extractFilePathsFromUnknown(item, out);
    return;
  }

  if (typeof value === 'object') {
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (k.toLowerCase().includes('path') || k === 'file' || k === 'files' || k === 'cwd') {
        const normalized = normalizePathCandidate(v);
        if (normalized) out.set(normalized, (out.get(normalized) ?? 0) + 1);
      }
      extractFilePathsFromUnknown(v, out);
    }
    return;
  }

  if (typeof value === 'string') {
    // Best-effort path extraction from shell commands.
    const matches = value.match(/(?:\/|\.{1,2}\/)[A-Za-z0-9_./\-]+(?:\.[A-Za-z0-9]+)?/g) ?? [];
    for (const m of matches) {
      const normalized = normalizePathCandidate(m);
      if (normalized) out.set(normalized, (out.get(normalized) ?? 0) + 1);
    }
  }
}

function buildFallbackCodeMapFromTrace(rawEntries: Array<Record<string, unknown>>): CodeMapData | null {
  const pathCounts = new Map<string, number>();

  for (const entry of rawEntries) {
    if (entry._type !== 'tool.execution') continue;
    extractFilePathsFromUnknown(entry.input, pathCounts);
  }

  if (pathCounts.size === 0) return null;

  const sorted = Array.from(pathCounts.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 400);

  const fileLike = sorted.filter(([p]) => {
    const name = basename(p);
    return name.includes('.');
  });
  const candidates = fileLike.length >= 8 ? fileLike : sorted;

  const files: CodeMapFile[] = candidates.map(([filePath, hits]) => {
    const directory = dirname(filePath);
    return {
      filePath,
      directory: directory === '.' ? '' : directory,
      fileName: basename(filePath),
      tokenCount: 0,
      importance: hits,
      type: inferFileType(filePath, [], []),
      symbols: [],
      inDegree: 0,
      outDegree: 0,
    };
  });

  const root = files
    .map(f => f.directory)
    .filter(Boolean)
    .sort((a, b) => a.length - b.length)[0] ?? '';

  return {
    root,
    totalFiles: files.length,
    totalTokens: 0,
    files,
    dependencyEdges: [],
    entryPoints: [],
    coreModules: [],
  };
}

/**
 * Extract code map data from a session's trace entries.
 */
export async function getSessionCodeMap(idOrPath: string): Promise<CodeMapData | null> {
  const session = await getSession(idOrPath);
  if (!session) return null;

  // Find codebase.map entries
  const mapEntries = session.rawEntries?.filter((e: Record<string, unknown>) => e._type === 'codebase.map') ?? [];

  if (mapEntries.length === 0) {
    // Backward-compatible fallback for traces created before codebase.map emission was wired.
    return buildFallbackCodeMapFromTrace(session.rawEntries ?? []);
  }

  // Use the last (most complete) map entry
  const rawEntry = mapEntries[mapEntries.length - 1];
  const entry = (rawEntry.data as Record<string, unknown> | undefined) ?? rawEntry;

  const topChunks = (entry.topChunks as Array<Record<string, unknown>>) ?? [];
  const entryFiles = (entry.files as Array<Record<string, unknown>>) ?? [];
  const depEdges = (entry.dependencyEdges as Array<{ file: string; imports: string[] }>) ?? [];

  const entryPoints = (entry.entryPoints as string[]) ?? [];
  const coreModules = (entry.coreModules as string[]) ?? [];
  const normalizeSymbols = (raw: unknown): CodeMapFile['symbols'] =>
    ((raw as unknown[]) ?? []).map((s) => {
      if (typeof s === 'string') {
        return { name: s, kind: 'symbol', exported: false, line: 0 };
      }
      const sym = (s as Record<string, unknown>) ?? {};
      return {
        name: (sym.name as string) ?? '',
        kind: (sym.kind as string) ?? 'symbol',
        exported: (sym.exported as boolean) ?? false,
        line: (sym.line as number) ?? 0,
      };
    });

  const toFile = (chunk: Record<string, unknown>): CodeMapFile => {
    const filePath = (chunk.filePath as string) ?? '';
    const parts = filePath.split('/');
    const fileName = parts[parts.length - 1] ?? filePath;
    const directory = parts.slice(0, -1).join('/');

    const outDegree = (chunk.outDegree as number) ?? depEdges.find(e => e.file === filePath)?.imports.length ?? 0;
    const inDegree = (chunk.inDegree as number) ?? depEdges.filter(e => e.imports.includes(filePath)).length;
    const rawType = (chunk.type as string | undefined) ?? inferFileType(filePath, entryPoints, coreModules);
    const type: CodeMapFile['type'] = (
      rawType === 'entry_point' ||
      rawType === 'core_module' ||
      rawType === 'types' ||
      rawType === 'test' ||
      rawType === 'utility' ||
      rawType === 'config' ||
      rawType === 'other'
    ) ? rawType : 'other';

    return {
      filePath,
      directory,
      fileName,
      tokenCount: (chunk.tokenCount as number) ?? 0,
      importance: (chunk.importance as number) ?? 0,
      type,
      symbols: normalizeSymbols(chunk.symbols),
      inDegree,
      outDegree,
    };
  };

  // Prefer full files array when available; fallback to legacy topChunks.
  const files: CodeMapFile[] = (entryFiles.length > 0 ? entryFiles : topChunks).map(toFile);

  // Build normalized dependency edges
  const normalizedEdges = depEdges.flatMap(edge =>
    edge.imports.map(imp => ({
      source: edge.file,
      target: imp,
      importedNames: [] as string[],
    }))
  );

  return {
    root: '',
    totalFiles: (entry.totalFiles as number) ?? files.length,
    totalTokens: (entry.totalTokens as number) ?? 0,
    files,
    dependencyEdges: normalizedEdges,
    entryPoints,
    coreModules,
  };
}

/**
 * Build agent graph data from a session's trace entries.
 */
export async function getSessionAgentGraph(idOrPath: string): Promise<AgentGraphData | null> {
  const session = await getSession(idOrPath);
  if (!session) return null;

  const rawEntries = session.rawEntries ?? [];

  const agentMap = new Map<string, AgentNode>();
  const dataFlows: DataFlow[] = [];
  let flowIdCounter = 0;

  // Process subagent.link entries to build agent hierarchy
  const linkEntries = rawEntries.filter(e => e._type === 'subagent.link');
  for (const entry of linkEntries) {
    const link = entry.link as Record<string, unknown> | undefined;
    if (!link) continue;

    const childConfig = (link.childConfig as Record<string, unknown>) ?? {};
    const childSessionId = (link.childSessionId as string) ?? '';
    const parentSessionId = (link.parentSessionId as string) ?? '';
    const result = link.result as Record<string, unknown> | undefined;

    // Ensure parent exists
    if (!agentMap.has(parentSessionId)) {
      agentMap.set(parentSessionId, {
        id: parentSessionId,
        label: 'Root Agent',
        model: (entry as Record<string, unknown>).model as string ?? '',
        type: 'root',
        status: 'completed',
        tokensUsed: 0,
        costUsed: 0,
        filesAccessed: [],
        findingsPosted: 0,
      });
    }

    // Add child agent
    const agentType = (childConfig.agentType as string) ?? 'subagent';
    let nodeType: AgentNode['type'] = 'subagent';
    if (agentType.includes('orchestrator')) nodeType = 'orchestrator';
    else if (agentType.includes('worker')) nodeType = 'worker';
    else if (agentType.includes('judge')) nodeType = 'judge';
    else if (agentType.includes('manager')) nodeType = 'manager';

    agentMap.set(childSessionId, {
      id: childSessionId,
      label: agentType,
      model: (childConfig.model as string) ?? '',
      type: nodeType,
      status: result ? ((result.success as boolean) ? 'completed' : 'failed') : 'running',
      parentId: parentSessionId,
      tokensUsed: (result?.tokensUsed as number) ?? 0,
      costUsed: 0,
      filesAccessed: [],
      findingsPosted: 0,
    });

    // Create context injection flow
    dataFlows.push({
      id: `flow-${flowIdCounter++}`,
      timestamp: new Date((entry._ts as string) ?? '').getTime(),
      sourceAgentId: parentSessionId,
      targetAgentId: childSessionId,
      type: 'task_assignment',
      payload: {
        summary: (childConfig.task as string)?.slice(0, 200) ?? 'Task assigned',
      },
    });

    // Create result return flow if completed
    if (result) {
      dataFlows.push({
        id: `flow-${flowIdCounter++}`,
        timestamp: new Date((entry._ts as string) ?? '').getTime() + 1,
        sourceAgentId: childSessionId,
        targetAgentId: parentSessionId,
        type: 'result_return',
        payload: {
          summary: (result.summary as string)?.slice(0, 200) ?? 'Result returned',
          size: result.tokensUsed as number,
        },
      });
    }
  }

  // Process context.injection entries
  const injectionEntries = rawEntries.filter(e => e._type === 'context.injection');
  for (const entry of injectionEntries) {
    dataFlows.push({
      id: `flow-${flowIdCounter++}`,
      timestamp: new Date((entry._ts as string) ?? '').getTime(),
      sourceAgentId: (entry.parentAgentId as string) ?? 'root',
      targetAgentId: (entry.agentId as string) ?? '',
      type: 'context_injection',
      payload: {
        summary: `Injected repo map (${entry.repoMapTokens}tok), ${entry.blackboardFindings} findings, ${(entry.modifiedFiles as string[])?.length ?? 0} files`,
        size: (entry.repoMapTokens as number) ?? 0,
      },
    });
  }

  // Process blackboard.event entries
  const bbEntries = rawEntries.filter(e => e._type === 'blackboard.event');
  for (const entry of bbEntries) {
    if (entry.action === 'finding.posted') {
      dataFlows.push({
        id: `flow-${flowIdCounter++}`,
        timestamp: new Date((entry._ts as string) ?? '').getTime(),
        sourceAgentId: (entry.agentId as string) ?? '',
        targetAgentId: 'blackboard',
        type: 'finding',
        payload: {
          summary: (entry.topic as string) ?? 'Finding posted',
          topic: entry.topic as string,
          confidence: entry.confidence as number,
        },
      });
    }
  }

  // Process budget.pool entries
  const budgetEntries = rawEntries.filter(e => e._type === 'budget.pool');
  for (const entry of budgetEntries) {
    if (entry.action === 'allocate') {
      dataFlows.push({
        id: `flow-${flowIdCounter++}`,
        timestamp: new Date((entry._ts as string) ?? '').getTime(),
        sourceAgentId: 'budget-pool',
        targetAgentId: (entry.agentId as string) ?? '',
        type: 'budget_transfer',
        payload: {
          summary: `Allocated ${entry.tokensAllocated} tokens`,
          size: entry.tokensAllocated as number,
        },
      });
    }
  }

  // If no agents found, create a root from session info
  if (agentMap.size === 0) {
    agentMap.set('root', {
      id: 'root',
      label: 'Root Agent',
      model: session.model,
      type: 'root',
      status: session.status === 'completed' ? 'completed' : session.status === 'failed' ? 'failed' : 'running',
      tokensUsed: session.metrics.inputTokens + session.metrics.outputTokens,
      costUsed: session.metrics.totalCost,
      filesAccessed: [],
      findingsPosted: 0,
    });
  }

  return {
    agents: Array.from(agentMap.values()),
    dataFlows: dataFlows.sort((a, b) => a.timestamp - b.timestamp),
  };
}
