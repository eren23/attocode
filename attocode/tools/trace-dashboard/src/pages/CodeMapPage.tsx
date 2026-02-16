/**
 * CodeMapPage - Code map visualization page
 *
 * Route: /codemap and /codemap/:sessionId
 *
 * If no sessionId, shows a session picker.
 * If sessionId, fetches code map and shows the force-directed graph
 * with controls and a sidebar for file details.
 */

import { useState, useCallback, useMemo } from 'react';
import { useParams, Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useCodeMap } from '../hooks/useCodeMap';
import { useSwarmStream } from '../hooks/useSwarmStream';
import { useSessions } from '../hooks/useApi';
import { LoadingSpinner } from '../components/LoadingSpinner';
import {
  CodeMapGraph,
  CodeMapControls,
  CodeMapSidebar,
  SymbolMapGraph,
} from '../components/codemap';
import type { DetailMode, LayoutMode } from '../components/codemap';
import type { CodeMapData, CodeMapFile } from '../lib/codemap-types';
import { formatTokens, relativeTime, truncate } from '../lib/utils';

const ALL_TYPES: CodeMapFile['type'][] = [
  'entry_point',
  'core_module',
  'types',
  'test',
  'utility',
  'config',
  'other',
];

function SessionPicker() {
  const { data: sessions, loading, error, refetch } = useSessions();
  const navigate = useNavigate();
  const [filter, setFilter] = useState('');

  if (loading) {
    return <LoadingSpinner text="Loading sessions..." />;
  }

  if (error) {
    return (
      <div className="text-center py-12">
        <p className="text-red-400 mb-4">
          Failed to load sessions: {error.message}
        </p>
        <button
          onClick={refetch}
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!sessions || sessions.length === 0) {
    return (
      <div className="text-center py-12">
        <h3 className="text-lg font-medium text-gray-300 mb-2">
          No Sessions Found
        </h3>
        <p className="text-gray-500">
          Run some agent sessions to generate code maps.
        </p>
      </div>
    );
  }

  const filtered = filter
    ? sessions.filter(
        (s) =>
          s.task.toLowerCase().includes(filter.toLowerCase()) ||
          s.model.toLowerCase().includes(filter.toLowerCase()) ||
          s.id.toLowerCase().includes(filter.toLowerCase())
      )
    : sessions;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white mb-2">Code Map</h1>
        <p className="text-gray-400 text-sm">
          Select a session to visualize its code map and file dependencies.
        </p>
      </div>

      <div className="mb-4">
        <input
          type="text"
          placeholder="Search by task, model, or ID..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="w-full max-w-md px-4 py-2 bg-gray-800 border border-gray-700 rounded text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 transition-colors"
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {filtered.map((session) => (
          <button
            key={session.id}
            onClick={() =>
              navigate(
                `/codemap/${encodeURIComponent(session.filePath)}`
              )
            }
            className="bg-gray-900 border border-gray-800 rounded-lg p-4 text-left hover:border-gray-700 hover:bg-gray-900/80 transition-colors"
          >
            <div className="text-sm text-gray-200 font-medium truncate mb-1">
              {truncate(session.task, 60)}
            </div>
            <div className="text-xs text-gray-500 font-mono mb-2">
              {session.id}
            </div>
            <div className="flex items-center gap-3 text-[10px] text-gray-500">
              <span>{relativeTime(session.startTime)}</span>
              <span>{session.model}</span>
              <span>{formatTokens(session.metrics.totalTokens)} tokens</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function CodeMapView({ sessionId }: { sessionId: string }) {
  const [showAllFiles, setShowAllFiles] = useState(false);
  const { data, loading, error, refetch } = useCodeMap(sessionId, { all: showAllFiles });
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [typeFilters, setTypeFilters] = useState<Set<CodeMapFile['type']>>(
    () => new Set(ALL_TYPES)
  );
  const [minImportance, setMinImportance] = useState(0);
  const [layoutMode, setLayoutMode] = useState<LayoutMode>('force');
  const [detailMode, setDetailMode] = useState<DetailMode>('overview');
  const [zoom, setZoom] = useState(1);

  const handleToggleType = useCallback((type: CodeMapFile['type']) => {
    setTypeFilters((prev) => {
      const next = new Set(prev);
      if (next.has(type)) {
        // Don't allow deselecting all types
        if (next.size <= 1) return prev;
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  }, []);

  const handleZoomIn = useCallback(() => {
    setZoom((z) => Math.min(z + 0.15, 3));
  }, []);

  const handleZoomOut = useCallback(() => {
    setZoom((z) => Math.max(z - 0.15, 0.3));
  }, []);

  const handleZoomReset = useCallback(() => {
    setZoom(1);
  }, []);

  const visibleFileCount = useMemo(() => {
    if (!data) return 0;
    return data.files.filter(
      (f) => typeFilters.has(f.type) && f.importance >= minImportance
    ).length;
  }, [data, typeFilters, minImportance]);
  const effectiveSelectedFile = selectedFile ?? data?.files[0]?.filePath ?? null;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <LoadingSpinner text="Loading code map..." />
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-12">
        <p className="text-red-400 mb-4">
          Failed to load code map: {error.message}
        </p>
        <div className="flex items-center justify-center gap-3">
          <button
            onClick={refetch}
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors"
          >
            Retry
          </button>
          <Link
            to="/codemap"
            className="px-4 py-2 text-gray-300 border border-gray-700 rounded hover:bg-gray-800 transition-colors"
          >
            Back to sessions
          </Link>
        </div>
      </div>
    );
  }

  if (!data || data.files.length === 0) {
    return (
      <div className="text-center py-12">
        <h3 className="text-lg font-medium text-gray-300 mb-2">
          No Code Map Data
        </h3>
        <p className="text-gray-500 mb-4">
          This session does not have code map data available.
        </p>
        <Link
          to="/codemap"
          className="px-4 py-2 text-gray-300 border border-gray-700 rounded hover:bg-gray-800 transition-colors"
        >
          Back to sessions
        </Link>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)]">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <Link
            to="/codemap"
            className="text-gray-500 hover:text-gray-300 transition-colors"
          >
            <svg
              className="w-5 h-5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M15 19l-7-7 7-7"
              />
            </svg>
          </Link>
          <div>
            <h1 className="text-lg font-bold text-white">Code Map</h1>
            <div className="text-xs text-gray-500">
              {data.root} &middot; {formatTokens(data.totalTokens)} total tokens
            </div>
          </div>
        </div>

        {/* Legend summary */}
        <div className="flex items-center gap-2 text-[10px] text-gray-500">
          <span>{data.entryPoints.length} entry points</span>
          <span className="text-gray-700">|</span>
          <span>{data.coreModules.length} core modules</span>
          <span className="text-gray-700">|</span>
          <span>{data.dependencyEdges.length} edges</span>
        </div>
      </div>

      {/* Controls */}
      <CodeMapControls
        totalFiles={data.totalFiles}
        visibleFiles={visibleFileCount}
        detailMode={detailMode}
        onDetailModeChange={setDetailMode}
        typeFilters={typeFilters}
        onToggleType={handleToggleType}
        minImportance={minImportance}
        onMinImportanceChange={setMinImportance}
        layoutMode={layoutMode}
        onLayoutModeChange={setLayoutMode}
        zoom={zoom}
        onZoomIn={handleZoomIn}
        onZoomOut={handleZoomOut}
        onZoomReset={handleZoomReset}
      />

      {data.selectionMeta && data.selectionMeta.original > data.selectionMeta.selected && (
        <div className="mt-2 rounded border border-amber-700/40 bg-amber-900/10 px-3 py-2 text-xs text-amber-300 flex items-center justify-between">
          <span>
            Showing {data.selectionMeta.selected} of {data.selectionMeta.original} files for performance.
          </span>
          <button
            onClick={() => setShowAllFiles(v => !v)}
            className="rounded border border-amber-700/50 px-2 py-0.5 text-amber-200 hover:bg-amber-900/30 transition-colors"
          >
            {showAllFiles ? 'Use Smart Subset' : 'Load Full Map'}
          </button>
        </div>
      )}

      {/* Main content: Graph + Sidebar */}
      <div className="flex gap-3 mt-3 flex-1 min-h-0">
        {detailMode === 'overview' ? (
          <CodeMapGraph
            data={data}
            selectedFile={effectiveSelectedFile}
            onSelectFile={setSelectedFile}
            layoutMode={layoutMode}
            zoom={zoom}
            typeFilters={typeFilters}
            minImportance={minImportance}
          />
        ) : (
          <SymbolMapGraph
            data={data}
            selectedFile={effectiveSelectedFile}
            onSelectFile={setSelectedFile}
          />
        )}

        {effectiveSelectedFile && (
          <CodeMapSidebar
            data={data}
            selectedFile={effectiveSelectedFile}
            onClose={() => setSelectedFile(null)}
          />
        )}
      </div>
    </div>
  );
}

function normalizeSwarmCodeMap(snapshot: NonNullable<ReturnType<typeof useSwarmStream>['codeMap']>): CodeMapData {
  const depEdges = snapshot.dependencyEdges ?? [];
  const rawFiles = snapshot.files ?? snapshot.topChunks ?? [];
  const files: CodeMapFile[] = rawFiles.map((chunk) => {
    const filePath = chunk.filePath;
    const parts = filePath.split('/');
    const fileName = parts[parts.length - 1] ?? filePath;
    const directory = parts.slice(0, -1).join('/');
    const outDegree = 'outDegree' in chunk && typeof chunk.outDegree === 'number'
      ? chunk.outDegree
      : depEdges.find((e) => e.file === filePath)?.imports.length ?? 0;
    const inDegree = 'inDegree' in chunk && typeof chunk.inDegree === 'number'
      ? chunk.inDegree
      : depEdges.filter((e) => e.imports.includes(filePath)).length;

    const type = (
      (chunk as Record<string, unknown>).type === 'entry_point' ||
      (chunk as Record<string, unknown>).type === 'core_module' ||
      (chunk as Record<string, unknown>).type === 'types' ||
      (chunk as Record<string, unknown>).type === 'test' ||
      (chunk as Record<string, unknown>).type === 'utility' ||
      (chunk as Record<string, unknown>).type === 'config' ||
      (chunk as Record<string, unknown>).type === 'other'
    ) ? (chunk as Record<string, unknown>).type as CodeMapFile['type'] : 'other';

    const symbols = Array.isArray((chunk as Record<string, unknown>).symbols)
      ? ((chunk as Record<string, unknown>).symbols as Array<Record<string, unknown>>).map((s) => ({
          name: String(s.name ?? ''),
          kind: String(s.kind ?? 'symbol'),
          exported: Boolean(s.exported ?? false),
          line: Number(s.line ?? 0),
        }))
      : [];

    return {
      filePath,
      directory,
      fileName,
      tokenCount: Number((chunk as Record<string, unknown>).tokenCount ?? 0),
      importance: Number((chunk as Record<string, unknown>).importance ?? 0),
      type,
      symbols,
      inDegree,
      outDegree,
    };
  });

  return {
    root: '',
    totalFiles: snapshot.totalFiles ?? files.length,
    totalTokens: snapshot.totalTokens ?? 0,
    files,
    dependencyEdges: depEdges.flatMap((e) => e.imports.map((imp) => ({
      source: e.file,
      target: imp,
      importedNames: [],
    }))),
    entryPoints: snapshot.entryPoints ?? [],
    coreModules: snapshot.coreModules ?? [],
  };
}

function SwarmCodeMapView({ swarmDir }: { swarmDir?: string }) {
  const { codeMap, idle, connected } = useSwarmStream(swarmDir);
  const data = useMemo(() => (codeMap ? normalizeSwarmCodeMap(codeMap) : null), [codeMap]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [typeFilters, setTypeFilters] = useState<Set<CodeMapFile['type']>>(() => new Set(ALL_TYPES));
  const [minImportance, setMinImportance] = useState(0);
  const [layoutMode, setLayoutMode] = useState<LayoutMode>('force');
  const [detailMode, setDetailMode] = useState<DetailMode>('overview');
  const [zoom, setZoom] = useState(1);

  const handleToggleType = useCallback((type: CodeMapFile['type']) => {
    setTypeFilters((prev) => {
      const next = new Set(prev);
      if (next.has(type)) {
        if (next.size <= 1) return prev;
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  }, []);
  const effectiveSelectedFile = selectedFile ?? data?.files[0]?.filePath ?? null;
  const visibleFileCount = useMemo(() => {
    if (!data) return 0;
    return data.files.filter((f) => typeFilters.has(f.type) && f.importance >= minImportance).length;
  }, [data, typeFilters, minImportance]);

  if (!data) {
    if (!idle && !connected) {
      return (
        <div className="flex items-center justify-center py-20">
          <LoadingSpinner text="Loading live swarm code map..." />
        </div>
      );
    }
    return (
      <div className="text-center py-12">
        <h3 className="text-lg font-medium text-gray-300 mb-2">No Live Code Map</h3>
        <p className="text-gray-500 mb-4">Start a swarm run to populate codemap snapshot.</p>
        <Link
          to={swarmDir ? `/swarm?dir=${encodeURIComponent(swarmDir)}` : '/swarm'}
          className="px-4 py-2 text-gray-300 border border-gray-700 rounded hover:bg-gray-800 transition-colors"
        >
          Back to Swarm
        </Link>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)]">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <Link
            to={swarmDir ? `/swarm?dir=${encodeURIComponent(swarmDir)}` : '/swarm'}
            className="text-gray-500 hover:text-gray-300 transition-colors"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </Link>
          <div>
            <h1 className="text-lg font-bold text-white">Live Swarm Code Map</h1>
            <div className="text-xs text-gray-500">{formatTokens(data.totalTokens)} total tokens</div>
          </div>
        </div>
        <div className="flex items-center gap-2 text-[10px] text-gray-500">
          <span>{data.entryPoints.length} entry points</span>
          <span className="text-gray-700">|</span>
          <span>{data.coreModules.length} core modules</span>
          <span className="text-gray-700">|</span>
          <span>{data.dependencyEdges.length} edges</span>
        </div>
      </div>

      <CodeMapControls
        totalFiles={data.totalFiles}
        visibleFiles={visibleFileCount}
        detailMode={detailMode}
        onDetailModeChange={setDetailMode}
        typeFilters={typeFilters}
        onToggleType={handleToggleType}
        minImportance={minImportance}
        onMinImportanceChange={setMinImportance}
        layoutMode={layoutMode}
        onLayoutModeChange={setLayoutMode}
        zoom={zoom}
        onZoomIn={() => setZoom((z) => Math.min(z + 0.15, 3))}
        onZoomOut={() => setZoom((z) => Math.max(z - 0.15, 0.3))}
        onZoomReset={() => setZoom(1)}
      />

      <div className="flex gap-3 mt-3 flex-1 min-h-0">
        {detailMode === 'overview' ? (
          <CodeMapGraph
            data={data}
            selectedFile={effectiveSelectedFile}
            onSelectFile={setSelectedFile}
            layoutMode={layoutMode}
            zoom={zoom}
            typeFilters={typeFilters}
            minImportance={minImportance}
          />
        ) : (
          <SymbolMapGraph
            data={data}
            selectedFile={effectiveSelectedFile}
            onSelectFile={setSelectedFile}
          />
        )}
        {effectiveSelectedFile && (
          <CodeMapSidebar
            data={data}
            selectedFile={effectiveSelectedFile}
            onClose={() => setSelectedFile(null)}
          />
        )}
      </div>
    </div>
  );
}

export function CodeMapPage() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const swarmMode = searchParams.get('swarm') === '1';
  const swarmDir = searchParams.get('dir') ?? undefined;

  if (!id && !swarmMode) {
    return <SessionPicker />;
  }

  if (!id && swarmMode) {
    return <SwarmCodeMapView swarmDir={swarmDir} />;
  }

  return <CodeMapView sessionId={id} />;
}
