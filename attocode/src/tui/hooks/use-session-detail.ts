/**
 * Session Detail Hook
 *
 * Loads a full trace session by dynamically importing the trace-dashboard
 * lib and running its analyzers (summary, timeline, tree, token flow,
 * inefficiency detection). Designed for the session detail tab where the
 * user drills into a specific trace.
 */

import { useState, useEffect, useCallback } from 'react';

/**
 * Aggregated session detail data produced by the trace-dashboard lib analyzers.
 *
 * The `summary`, `timeline`, `tree`, and `tokenFlow` fields use `any` because
 * they hold output from the trace-dashboard lib's view generators, and we avoid
 * importing those types directly to prevent build path coupling between the
 * TUI package and the tools/ directory.
 */
export interface SessionDetailData {
  sessionId: string;
  summary: any;
  timeline: any;
  tree: any;
  tokenFlow: any;
  inefficiencies: any[];
  loading: boolean;
  error: string | null;
}

/**
 * Hook that loads and analyzes a trace session on demand.
 *
 * When `sessionId` changes to a non-null value, the hook dynamically imports
 * the trace-dashboard lib, locates the matching JSONL file, parses it, and
 * runs all analyzers (summary, timeline, tree, token flow, inefficiencies).
 *
 * @param sessionId - The session ID to load, or null to clear.
 * @param traceDir - Optional custom trace directory to search first.
 * @returns Session detail data including loading/error state.
 *
 * @example
 * ```tsx
 * const detail = useSessionDetail(selectedSessionId);
 *
 * if (detail.loading) return <Text>Loading...</Text>;
 * if (detail.error) return <Text color="red">{detail.error}</Text>;
 *
 * // Render summary
 * <SummaryPanel data={detail.summary} />
 *
 * // Show inefficiencies
 * {detail.inefficiencies.map(issue => (
 *   <Text key={issue.id}>{issue.description}</Text>
 * ))}
 * ```
 */
export function useSessionDetail(sessionId: string | null, traceDir?: string): SessionDetailData {
  const [data, setData] = useState<SessionDetailData>({
    sessionId: '',
    summary: null,
    timeline: null,
    tree: null,
    tokenFlow: null,
    inefficiencies: [],
    loading: false,
    error: null,
  });

  const loadSession = useCallback(async (sid: string) => {
    setData(prev => ({ ...prev, loading: true, error: null, sessionId: sid }));

    try {
      // Dynamic import of trace-dashboard lib to avoid bundling issues
      const libPath = '../../../tools/trace-dashboard/src/lib/index.js';
      const lib = await import(/* webpackIgnore: true */ libPath);

      const dirs = [traceDir, '.traces', '.agent/traces'].filter(Boolean) as string[];
      let parsed = null;

      for (const dir of dirs) {
        try {
          const fs = await import('fs');
          const pathMod = await import('path');
          const files = fs.readdirSync(dir).filter((f: string) => f.endsWith('.jsonl'));
          const matchingFile = files.find((f: string) => f.includes(sid));
          if (matchingFile) {
            const parser = lib.createJSONLParser();
            parsed = await parser.parseFile(pathMod.join(dir, matchingFile));
            break;
          }
        } catch { /* try next dir */ }
      }

      if (!parsed) {
        setData(prev => ({ ...prev, loading: false, error: `Session ${sid} not found` }));
        return;
      }

      const summaryView = lib.createSummaryView();
      const timelineView = lib.createTimelineView();
      const treeView = lib.createTreeView();
      const tokenAnalyzer = lib.createTokenAnalyzer();
      const inefficiencyDetector = lib.createInefficiencyDetector();

      const summary = summaryView.generate(parsed);
      const timeline = timelineView.generate(parsed);
      const tree = treeView.generate(parsed);
      const tokenFlow = tokenAnalyzer.analyzeTokenFlow(parsed);
      const inefficiencies = inefficiencyDetector.detect(parsed);

      setData({
        sessionId: sid,
        summary,
        timeline,
        tree,
        tokenFlow,
        inefficiencies,
        loading: false,
        error: null,
      });
    } catch (err) {
      setData(prev => ({
        ...prev,
        loading: false,
        error: `Failed to load session: ${err instanceof Error ? err.message : String(err)}`,
      }));
    }
  }, [traceDir]);

  useEffect(() => {
    if (sessionId) {
      loadSession(sessionId);
    }
  }, [sessionId, loadSession]);

  return data;
}
