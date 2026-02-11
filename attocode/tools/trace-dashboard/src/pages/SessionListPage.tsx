/**
 * Session List Page
 *
 * Displays all trace sessions with filtering and sorting.
 */

import { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useSessions } from '../hooks/useApi';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { StatusBadge } from '../components/StatusBadge';
import { UploadModal } from '../components/UploadModal';
import { formatTokens, formatCost, formatDuration, formatPercent, relativeTime } from '../lib/utils';
import { ExportDropdown } from '../components/ExportDropdown';

type SortKey = 'startTime' | 'tokens' | 'cost' | 'iterations' | 'cacheHitRate';
type SortOrder = 'asc' | 'desc';

export function SessionListPage() {
  const { data: sessions, loading, error, refetch } = useSessions();
  const [sortKey, setSortKey] = useState<SortKey>('startTime');
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc');
  const [filter, setFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [showUploadModal, setShowUploadModal] = useState(false);

  const filteredAndSorted = useMemo(() => {
    if (!sessions) return [];

    let result = [...sessions];

    // Apply status filter
    if (statusFilter !== 'all') {
      result = result.filter((s) => s.status === statusFilter);
    }

    // Apply text filter
    if (filter) {
      const lowerFilter = filter.toLowerCase();
      result = result.filter(
        (s) =>
          s.task.toLowerCase().includes(lowerFilter) ||
          s.model.toLowerCase().includes(lowerFilter) ||
          s.id.toLowerCase().includes(lowerFilter)
      );
    }

    // Apply sorting
    result.sort((a, b) => {
      let aVal: number;
      let bVal: number;

      switch (sortKey) {
        case 'startTime':
          aVal = new Date(a.startTime).getTime();
          bVal = new Date(b.startTime).getTime();
          break;
        case 'tokens':
          aVal = a.metrics.totalTokens;
          bVal = b.metrics.totalTokens;
          break;
        case 'cost':
          aVal = a.metrics.cost;
          bVal = b.metrics.cost;
          break;
        case 'iterations':
          aVal = a.metrics.iterations;
          bVal = b.metrics.iterations;
          break;
        case 'cacheHitRate':
          aVal = a.metrics.cacheHitRate;
          bVal = b.metrics.cacheHitRate;
          break;
        default:
          return 0;
      }

      return sortOrder === 'asc' ? aVal - bVal : bVal - aVal;
    });

    return result;
  }, [sessions, sortKey, sortOrder, filter, statusFilter]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortOrder('desc');
    }
  };

  const SortHeader = ({ label, sortKeyName }: { label: string; sortKeyName: SortKey }) => (
    <th
      className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider cursor-pointer hover:text-white transition-colors"
      onClick={() => handleSort(sortKeyName)}
    >
      <div className="flex items-center gap-1">
        {label}
        {sortKey === sortKeyName && (
          <svg
            className={`w-4 h-4 transition-transform ${sortOrder === 'desc' ? 'rotate-180' : ''}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
          </svg>
        )}
      </div>
    </th>
  );

  if (loading) {
    return <LoadingSpinner size="lg" text="Loading sessions..." />;
  }

  if (error) {
    return (
      <div className="text-center py-12">
        <p className="text-red-400 mb-4">Failed to load sessions: {error.message}</p>
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
        <svg
          className="w-16 h-16 mx-auto text-gray-600 mb-4"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
          />
        </svg>
        <h3 className="text-lg font-medium text-gray-300 mb-2">No Traces Found</h3>
        <p className="text-gray-500">
          Run some agent sessions to see traces here.
          <br />
          Traces are stored in .traces/ or .agent/traces/ directories.
        </p>
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Sessions</h1>
          <p className="text-gray-400 text-sm mt-1">
            {filteredAndSorted.length} of {sessions.length} sessions
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ExportDropdown
            label="Export All"
            options={[
              {
                label: 'JSON (all sessions)',
                onClick: () => {
                  const ids = filteredAndSorted.map(s => encodeURIComponent(s.filePath)).join(',');
                  window.open(`/api/sessions/export/batch?ids=${ids}&format=json`, '_blank');
                },
              },
              {
                label: 'CSV (all sessions)',
                onClick: () => {
                  const ids = filteredAndSorted.map(s => encodeURIComponent(s.filePath)).join(',');
                  window.open(`/api/sessions/export/batch?ids=${ids}&format=csv`, '_blank');
                },
              },
            ]}
          />
          <button
            onClick={() => setShowUploadModal(true)}
            className="flex items-center gap-2 px-3 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
            Upload
          </button>
          <button
            onClick={refetch}
            className="flex items-center gap-2 px-3 py-2 text-sm text-gray-300 hover:text-white border border-gray-700 rounded hover:bg-gray-800 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
            Refresh
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-4 mb-6">
        <div className="flex-1">
          <input
            type="text"
            placeholder="Search by task, model, or ID..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="w-full px-4 py-2 bg-gray-800 border border-gray-700 rounded text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 transition-colors"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="px-4 py-2 bg-gray-800 border border-gray-700 rounded text-white focus:outline-none focus:border-blue-500 transition-colors"
        >
          <option value="all">All Status</option>
          <option value="completed">Completed</option>
          <option value="running">Running</option>
          <option value="failed">Failed</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>

      {/* Table */}
      <div className="bg-gray-900/50 border border-gray-700 rounded-lg overflow-hidden">
        <table className="min-w-full divide-y divide-gray-700">
          <thead className="bg-gray-800/50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                Task
              </th>
              <SortHeader label="Time" sortKeyName="startTime" />
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                Status
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                Model
              </th>
              <SortHeader label="Iterations" sortKeyName="iterations" />
              <SortHeader label="Tokens" sortKeyName="tokens" />
              <SortHeader label="Cache" sortKeyName="cacheHitRate" />
              <SortHeader label="Cost" sortKeyName="cost" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {filteredAndSorted.map((session) => (
              <tr
                key={session.id}
                className="hover:bg-gray-800/50 transition-colors"
              >
                <td className="px-4 py-4">
                  <Link
                    to={`/session/${encodeURIComponent(session.filePath)}`}
                    className="text-blue-400 hover:text-blue-300 hover:underline"
                  >
                    <span className="flex items-center gap-2 max-w-md">
                      <span className="truncate">{session.task}</span>
                      {session.isSwarm && (
                        <span className="flex-shrink-0 inline-flex items-center px-1.5 py-0.5 text-xs font-medium rounded bg-purple-500/20 text-purple-400 border border-purple-500/30">
                          Swarm
                        </span>
                      )}
                    </span>
                  </Link>
                  <span className="text-xs text-gray-500 font-mono">{session.id}</span>
                </td>
                <td className="px-4 py-4 whitespace-nowrap">
                  <div className="text-sm text-gray-300">
                    {relativeTime(session.startTime)}
                  </div>
                  {session.durationMs && (
                    <div className="text-xs text-gray-500">
                      {formatDuration(session.durationMs)}
                    </div>
                  )}
                </td>
                <td className="px-4 py-4 whitespace-nowrap">
                  <StatusBadge status={session.status} size="sm" />
                </td>
                <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-300">
                  {session.model}
                </td>
                <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-300">
                  {session.metrics.iterations}
                </td>
                <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-300">
                  {formatTokens(session.metrics.totalTokens)}
                </td>
                <td className="px-4 py-4 whitespace-nowrap text-sm">
                  <span
                    className={
                      session.metrics.cacheHitRate > 0.7
                        ? 'text-green-400'
                        : session.metrics.cacheHitRate > 0.4
                        ? 'text-yellow-400'
                        : 'text-red-400'
                    }
                  >
                    {formatPercent(session.metrics.cacheHitRate)}
                  </span>
                </td>
                <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-300">
                  {formatCost(session.metrics.cost)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Upload Modal */}
      <UploadModal
        isOpen={showUploadModal}
        onClose={() => setShowUploadModal(false)}
        onUploadSuccess={refetch}
      />
    </div>
  );
}
