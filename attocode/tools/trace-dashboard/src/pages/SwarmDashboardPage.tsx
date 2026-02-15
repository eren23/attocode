/**
 * SwarmDashboardPage - Main layout for live swarm visualization
 */

import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useSwarmStream } from '../hooks/useSwarmStream';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { ExportDropdown } from '../components/ExportDropdown';
import {
  SwarmHeader,
  MetricsStrip,
  TaskDAGPanel,
  WorkerTimelinePanel,
  BudgetPanel,
  ModelDistributionPanel,
  QualityHeatmapPanel,
  EventFeedPanel,
  WaveProgressStrip,
  ExpandablePanel,
} from '../components/swarm';

interface SwarmDir {
  path: string;
  label: string;
}

const STORAGE_KEY = 'swarm-extra-dirs';

function loadExtraDirs(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveExtraDirs(dirs: string[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(dirs));
}

function SwarmDirPicker({
  selectedDir,
  onSelect,
}: {
  selectedDir: string | undefined;
  onSelect: (dir: string | undefined) => void;
}) {
  const [dirs, setDirs] = useState<SwarmDir[]>([]);
  const [extraDirs, setExtraDirs] = useState<string[]>(loadExtraDirs);
  const [addInput, setAddInput] = useState('');
  const [showAdd, setShowAdd] = useState(false);

  const fetchDirs = useCallback(() => {
    fetch('/api/swarm/dirs')
      .then((res) => res.json())
      .then((data) => {
        if (data.success && Array.isArray(data.data)) {
          // Merge server dirs with client-side extra dirs
          const serverDirs: SwarmDir[] = data.data;
          const serverPaths = new Set(serverDirs.map((d: SwarmDir) => d.path));

          const merged = [...serverDirs];
          for (const extra of extraDirs) {
            if (!serverPaths.has(extra)) {
              // Derive label from path
              const parts = extra.split('/').filter(Boolean);
              const agentIdx = parts.lastIndexOf('.agent');
              const label = agentIdx > 0 ? parts[agentIdx - 1] : parts.slice(-2).join('/');
              merged.push({ path: extra, label: `${label} (custom)` });
            }
          }
          setDirs(merged);
        }
      })
      .catch(() => {
        // Use extra dirs only
        setDirs(
          extraDirs.map((p) => {
            const parts = p.split('/').filter(Boolean);
            const agentIdx = parts.lastIndexOf('.agent');
            const label = agentIdx > 0 ? parts[agentIdx - 1] : parts.slice(-2).join('/');
            return { path: p, label: `${label} (custom)` };
          })
        );
      });
  }, [extraDirs]);

  useEffect(() => {
    fetchDirs();
  }, [fetchDirs]);

  const handleAdd = () => {
    const trimmed = addInput.trim();
    if (!trimmed) return;
    const updated = [...new Set([...extraDirs, trimmed])];
    setExtraDirs(updated);
    saveExtraDirs(updated);
    setAddInput('');
    setShowAdd(false);
    // Select the newly added dir
    onSelect(trimmed);
  };

  const handleRemoveExtra = (dirPath: string) => {
    const updated = extraDirs.filter((d) => d !== dirPath);
    setExtraDirs(updated);
    saveExtraDirs(updated);
    if (selectedDir === dirPath) {
      onSelect(undefined);
    }
  };

  if (dirs.length <= 1 && !showAdd) {
    // Single or no dirs — show compact inline
    return (
      <div className="flex items-center gap-2">
        {dirs.length === 1 && (
          <span className="text-xs text-gray-400 truncate max-w-[200px]" title={dirs[0].path}>
            {dirs[0].label}
          </span>
        )}
        <button
          onClick={() => setShowAdd(true)}
          className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
          title="Add swarm directory"
        >
          + Add path
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <select
        value={selectedDir ?? ''}
        onChange={(e) => onSelect(e.target.value || undefined)}
        className="bg-gray-800 border border-gray-700 text-gray-200 text-xs rounded px-2 py-1 max-w-[220px] truncate focus:outline-none focus:border-blue-500"
      >
        {!selectedDir && <option value="">Auto-detect</option>}
        {dirs.map((d) => (
          <option key={d.path} value={d.path}>
            {d.label}
          </option>
        ))}
      </select>

      {selectedDir && extraDirs.includes(selectedDir) && (
        <button
          onClick={() => handleRemoveExtra(selectedDir)}
          className="text-xs text-gray-500 hover:text-red-400 transition-colors"
          title="Remove custom path"
        >
          x
        </button>
      )}

      {showAdd ? (
        <div className="flex items-center gap-1">
          <input
            type="text"
            value={addInput}
            onChange={(e) => setAddInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
            placeholder="/path/to/.agent/swarm-live"
            className="bg-gray-800 border border-gray-700 text-gray-200 text-xs rounded px-2 py-1 w-[280px] focus:outline-none focus:border-blue-500"
            autoFocus
          />
          <button
            onClick={handleAdd}
            className="text-xs bg-blue-600 text-white px-2 py-1 rounded hover:bg-blue-500 transition-colors"
          >
            Add
          </button>
          <button
            onClick={() => { setShowAdd(false); setAddInput(''); }}
            className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
          >
            Cancel
          </button>
        </div>
      ) : (
        <button
          onClick={() => setShowAdd(true)}
          className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
          title="Add swarm directory"
        >
          +
        </button>
      )}
    </div>
  );
}

export function SwarmDashboardPage() {
  const [selectedDir, setSelectedDir] = useState<string | undefined>(undefined);
  const { connected, idle, state, recentEvents, codeMap, error, reconnect } = useSwarmStream(selectedDir);

  // Still loading initial state
  if (!state && !error && !idle) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <LoadingSpinner text="Connecting to swarm..." />
      </div>
    );
  }

  // No active swarm (idle or error without state)
  if (!state) {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <SwarmDirPicker selectedDir={selectedDir} onSelect={setSelectedDir} />
        </div>
        <div className="flex flex-col items-center justify-center py-20">
          {error && <div className="text-red-400 text-sm mb-4">{error.message}</div>}
          <div className="text-gray-400 text-lg mb-2">No active swarm</div>
          <p className="text-xs text-gray-500 max-w-md text-center mb-4">
            Start a swarm task with <code className="text-gray-400">--swarm</code> flag
            to see live visualization. The dashboard will auto-connect when a swarm starts.
          </p>
          <button
            onClick={reconnect}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-500 transition-colors"
          >
            Refresh
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center gap-3">
        <SwarmDirPicker selectedDir={selectedDir} onSelect={setSelectedDir} />
        <div className="flex-1">
          <SwarmHeader state={state} connected={connected} />
        </div>
        <Link
          to={selectedDir
            ? `/topology?swarm=1&dir=${encodeURIComponent(selectedDir)}`
            : '/topology?swarm=1'}
          className="px-3 py-1.5 text-xs font-medium text-gray-300 bg-gray-800 border border-gray-700 rounded-lg hover:bg-gray-700 hover:text-white transition-colors"
        >
          Live Topology
        </Link>
        <Link
          to={selectedDir
            ? `/codemap?swarm=1&dir=${encodeURIComponent(selectedDir)}`
            : '/codemap?swarm=1'}
          className="px-3 py-1.5 text-xs font-medium text-gray-300 bg-gray-800 border border-gray-700 rounded-lg hover:bg-gray-700 hover:text-white transition-colors"
        >
          Live Code Map
        </Link>
        <ExportDropdown
          options={[
            {
              label: 'Download Events (JSONL)',
              onClick: async () => {
                try {
                  const url = selectedDir
                    ? `/api/swarm/history?dir=${encodeURIComponent(selectedDir)}`
                    : '/api/swarm/history';
                  const res = await fetch(url);
                  const data = await res.json();
                  if (data.success && data.data?.length > 0) {
                    window.open(`/api/swarm/events/${data.data[0].filename}`, '_blank');
                  }
                } catch { /* ignore */ }
              },
            },
            {
              label: 'Download State (JSON)',
              onClick: () => {
                const blob = new Blob([JSON.stringify(state, null, 2)], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'swarm-state.json';
                a.click();
                URL.revokeObjectURL(url);
              },
            },
          ]}
        />
      </div>

      {/* Metrics Strip */}
      <MetricsStrip state={state} />

      {/* Error banner */}
      {error && (
        <div className="bg-red-900/20 border border-red-800 rounded-lg px-4 py-2 text-sm text-red-400 flex items-center justify-between">
          <span>{error.message}</span>
          <button onClick={reconnect} className="text-xs text-red-300 hover:text-white">
            Reconnect
          </button>
        </div>
      )}

      {/* Main 2-column grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* Row 1: DAG + Timeline */}
        <ExpandablePanel title="Task DAG">
          <TaskDAGPanel
            tasks={state?.tasks ?? []}
            edges={state?.edges ?? []}
            dir={selectedDir}
          />
        </ExpandablePanel>
        <ExpandablePanel title="Worker Timeline">
          <WorkerTimelinePanel tasks={state?.tasks ?? []} />
        </ExpandablePanel>

        {/* Row 2: Budget + Model Distribution */}
        <ExpandablePanel title="Budget">
          <BudgetPanel state={state} />
        </ExpandablePanel>
        <ExpandablePanel title="Model Distribution">
          <ModelDistributionPanel state={state} />
        </ExpandablePanel>

        {/* Row 3: Quality + Events */}
        <ExpandablePanel title="Quality Heatmap">
          <QualityHeatmapPanel tasks={state?.tasks ?? []} />
        </ExpandablePanel>
        <ExpandablePanel title="Event Feed">
          <EventFeedPanel events={recentEvents} />
        </ExpandablePanel>

        {/* Row 4: Code Map Snapshot */}
        <ExpandablePanel title="Code Map Snapshot">
          {!codeMap ? (
            <div className="text-xs text-gray-500">No codemap snapshot yet.</div>
          ) : (
            <div className="space-y-3">
              <div className="grid grid-cols-3 gap-2 text-xs">
                <div className="rounded bg-gray-800/50 px-2 py-1">
                  <div className="text-gray-500">Files</div>
                  <div className="text-gray-200">{codeMap.totalFiles}</div>
                </div>
                <div className="rounded bg-gray-800/50 px-2 py-1">
                  <div className="text-gray-500">Tokens</div>
                  <div className="text-gray-200">{codeMap.totalTokens.toLocaleString()}</div>
                </div>
                <div className="rounded bg-gray-800/50 px-2 py-1">
                  <div className="text-gray-500">Edges</div>
                  <div className="text-gray-200">{codeMap.dependencyEdges.length}</div>
                </div>
              </div>
              <div className="space-y-1 max-h-48 overflow-y-auto text-xs">
                {(codeMap.files?.slice(0, 20) ?? codeMap.topChunks.slice(0, 20)).map((f) => (
                  <div key={f.filePath} className="flex items-center justify-between gap-2 rounded bg-gray-800/30 px-2 py-1">
                    <div className="font-mono text-gray-300 truncate">{f.filePath}</div>
                    <div className="text-gray-500">{Math.round((f.importance ?? 0) * 100)}%</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </ExpandablePanel>
      </div>

      {/* Wave Progress Strip */}
      <WaveProgressStrip state={state} />
    </div>
  );
}
