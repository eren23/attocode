/**
 * Status Badge Component
 */

import { cn } from '../lib/utils';

interface StatusBadgeProps {
  status: 'running' | 'completed' | 'failed' | 'cancelled' | 'success' | 'error' | 'pending' | 'partial' | 'failure';
  size?: 'sm' | 'md';
}

export function StatusBadge({ status, size = 'md' }: StatusBadgeProps) {
  const colors = {
    running: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    pending: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    completed: 'bg-green-500/20 text-green-400 border-green-500/30',
    success: 'bg-green-500/20 text-green-400 border-green-500/30',
    failed: 'bg-red-500/20 text-red-400 border-red-500/30',
    error: 'bg-red-500/20 text-red-400 border-red-500/30',
    failure: 'bg-red-500/20 text-red-400 border-red-500/30',
    cancelled: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
    partial: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  };

  const sizeClasses = {
    sm: 'px-1.5 py-0.5 text-xs',
    md: 'px-2 py-1 text-sm',
  };

  const labels = {
    running: 'Running',
    pending: 'Pending',
    completed: 'Completed',
    success: 'Success',
    failed: 'Failed',
    error: 'Error',
    failure: 'Failed',
    cancelled: 'Cancelled',
    partial: 'Partial',
  };

  return (
    <span
      className={cn(
        'inline-flex items-center rounded border font-medium',
        colors[status],
        sizeClasses[size],
        status === 'running' && 'status-running'
      )}
    >
      {status === 'running' && (
        <span className="mr-1.5 h-2 w-2 rounded-full bg-yellow-400 animate-pulse" />
      )}
      {labels[status]}
    </span>
  );
}
