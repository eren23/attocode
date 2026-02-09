/**
 * SwarmHistoryPage - List of archived swarm event logs
 */

import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { relativeTime } from '../lib/utils';

interface HistoryEntry {
  filename: string;
  timestamp: string | null;
  sizeBytes: number;
}

export function SwarmHistoryPage() {
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/swarm/history')
      .then((res) => res.json())
      .then((data) => {
        if (data.success) {
          setEntries(data.data ?? []);
        } else {
          setError(data.error ?? 'Failed to load history');
        }
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <LoadingSpinner text="Loading swarm history..." />;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-white">Swarm History</h1>
        <Link
          to="/swarm"
          className="text-sm text-blue-400 hover:text-blue-300 transition-colors"
        >
          Back to Live
        </Link>
      </div>

      {error && (
        <div className="bg-red-900/20 border border-red-800 rounded-lg px-4 py-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {entries.length === 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-8 text-center">
          <p className="text-gray-400 text-sm">No archived swarm logs found.</p>
          <p className="text-gray-500 text-xs mt-1">
            Archived logs appear after multiple swarm executions.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {entries.map((entry) => (
            <div
              key={entry.filename}
              className="bg-gray-900 border border-gray-800 rounded-lg px-4 py-3 flex items-center justify-between hover:border-gray-700 transition-colors"
            >
              <div>
                <span className="text-sm text-white font-mono">{entry.filename}</span>
                {entry.timestamp && (
                  <span className="ml-3 text-xs text-gray-500">
                    {relativeTime(entry.timestamp)}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-gray-500">
                  {(entry.sizeBytes / 1024).toFixed(1)} KB
                </span>
                <a
                  href={`/api/swarm/events/${entry.filename}`}
                  download
                  className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
                >
                  Download
                </a>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
