/**
 * Session Browser Hook
 *
 * Scans trace directories for JSONL trace files and extracts lightweight
 * session metadata (task, model, token counts, cost) by reading only the
 * first and last few KB of each file. Provides sorting, filtering, and
 * refresh capabilities for the sessions list tab.
 */

import { useState, useEffect, useCallback } from 'react';
import * as fs from 'fs';
import * as path from 'path';

export interface SessionSummary {
  id: string;
  fileName: string;
  task: string;
  model: string;
  startTime: Date;
  status: string;
  iterations: number;
  totalTokens: number;
  totalCost: number;
  fileSizeBytes: number;
}

export type SessionSortField = 'startTime' | 'totalTokens' | 'totalCost' | 'iterations';
export type SessionSortDir = 'asc' | 'desc';

interface UseSessionBrowserOptions {
  traceDir?: string;
}

/**
 * Extract session metadata from a JSONL trace file by reading only the
 * head and tail of the file (up to 4KB each). This avoids loading the
 * entire trace into memory for the session list view.
 */
function extractSessionMeta(filePath: string): SessionSummary | null {
  try {
    const stat = fs.statSync(filePath);
    const fd = fs.openSync(filePath, 'r');
    const buf = Buffer.alloc(Math.min(4096, stat.size));
    fs.readSync(fd, buf, 0, buf.length, 0);

    // Read last few KB for end-of-session data
    const endBuf = Buffer.alloc(Math.min(4096, stat.size));
    const endPos = Math.max(0, stat.size - endBuf.length);
    fs.readSync(fd, endBuf, 0, endBuf.length, endPos);
    fs.closeSync(fd);

    const firstLines = buf.toString('utf-8').split('\n').filter(Boolean);
    const lastLines = endBuf.toString('utf-8').split('\n').filter(Boolean);

    let sessionId = path.basename(filePath, '.jsonl');
    let task = '';
    let model = '';
    let startTime = stat.mtime;
    let status = 'unknown';
    let iterations = 0;
    let totalTokens = 0;
    let totalCost = 0;

    // Parse first line for session start
    for (const line of firstLines.slice(0, 5)) {
      try {
        const entry = JSON.parse(line);
        if (entry.type === 'session.start' || entry.data?.type === 'session.start') {
          const d = entry.data || entry;
          sessionId = d.sessionId || d.data?.sessionId || sessionId;
          task = d.task || d.data?.task || '';
          model = d.model || d.data?.model || '';
          startTime = new Date(entry.timestamp || d.timestamp);
        }
      } catch { /* skip malformed lines */ }
    }

    // Parse last lines for session end / metrics
    for (const line of lastLines.slice(-10)) {
      try {
        const entry = JSON.parse(line);
        const d = entry.data || entry;
        if (entry.type === 'session.end' || d.type === 'session.end') {
          status = d.status || 'completed';
          iterations = d.iterations || d.metrics?.iterations || 0;
          totalTokens = d.totalTokens || (d.metrics?.inputTokens || 0) + (d.metrics?.outputTokens || 0) || 0;
          totalCost = d.totalCost || d.metrics?.totalCost || 0;
        }
        if (d.type === 'iteration.complete') {
          iterations = Math.max(iterations, d.iteration || 0);
        }
      } catch { /* skip malformed */ }
    }

    return {
      id: sessionId,
      fileName: path.basename(filePath),
      task: task || '(no task)',
      model,
      startTime,
      status,
      iterations,
      totalTokens,
      totalCost,
      fileSizeBytes: stat.size,
    };
  } catch {
    return null;
  }
}

/**
 * Hook for browsing and filtering trace sessions from the filesystem.
 *
 * Scans configured trace directories (`.traces`, `.agent/traces`, or a
 * custom path) for JSONL files and extracts lightweight metadata. Results
 * are sortable by start time, tokens, cost, or iteration count, and
 * filterable by free-text search across task, session ID, and model.
 *
 * @param options - Optional configuration including custom trace directory.
 * @returns Sessions list, sorting/filtering controls, and refresh function.
 *
 * @example
 * ```tsx
 * const { sessions, loading, setSortField, setFilterText, refresh } = useSessionBrowser();
 *
 * // Sort by cost descending
 * setSortField('totalCost');
 *
 * // Filter by model name
 * setFilterText('claude');
 * ```
 */
export function useSessionBrowser(options: UseSessionBrowserOptions = {}) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [sortField, setSortField] = useState<SessionSortField>('startTime');
  const [sortDir, setSortDir] = useState<SessionSortDir>('desc');
  const [filterText, setFilterText] = useState('');

  const traceDirs = [
    options.traceDir,
    '.traces',
    '.agent/traces',
  ].filter(Boolean) as string[];

  const refresh = useCallback(() => {
    setLoading(true);
    const allSessions: SessionSummary[] = [];

    for (const dir of traceDirs) {
      try {
        if (!fs.existsSync(dir)) continue;
        const files = fs.readdirSync(dir).filter(f => f.endsWith('.jsonl'));
        for (const file of files) {
          const meta = extractSessionMeta(path.join(dir, file));
          if (meta) allSessions.push(meta);
        }
      } catch { /* skip inaccessible dirs */ }
    }

    setSessions(allSessions);
    setLoading(false);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const sortedFiltered = sessions
    .filter(s => {
      if (!filterText) return true;
      const lower = filterText.toLowerCase();
      return s.task.toLowerCase().includes(lower) ||
        s.id.toLowerCase().includes(lower) ||
        s.model.toLowerCase().includes(lower);
    })
    .sort((a, b) => {
      const aVal = a[sortField];
      const bVal = b[sortField];
      const cmp = aVal instanceof Date
        ? aVal.getTime() - (bVal as Date).getTime()
        : (aVal as number) - (bVal as number);
      return sortDir === 'desc' ? -cmp : cmp;
    });

  return {
    sessions: sortedFiltered,
    loading,
    sortField,
    sortDir,
    filterText,
    setSortField,
    setSortDir,
    setFilterText,
    refresh,
    totalSessions: sessions.length,
  };
}
