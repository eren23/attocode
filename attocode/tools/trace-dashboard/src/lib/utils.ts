import { clsx, type ClassValue } from 'clsx';

/**
 * Utility function for merging class names with clsx
 */
export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

/**
 * Format a number as a human-readable token count
 */
export function formatTokens(count: number): string {
  if (count >= 1_000_000) {
    return `${(count / 1_000_000).toFixed(1)}M`;
  }
  if (count >= 1_000) {
    return `${(count / 1_000).toFixed(1)}K`;
  }
  return count.toString();
}

/**
 * Format a number as a currency amount
 */
export function formatCost(cost: number): string {
  if (cost < 0.01) {
    return `$${cost.toFixed(4)}`;
  }
  return `$${cost.toFixed(2)}`;
}

/**
 * Format milliseconds as a human-readable duration
 */
export function formatDuration(ms: number): string {
  if (ms < 1000) {
    return `${ms}ms`;
  }
  if (ms < 60_000) {
    return `${(ms / 1000).toFixed(1)}s`;
  }
  if (ms < 3_600_000) {
    const minutes = Math.floor(ms / 60_000);
    const seconds = Math.round((ms % 60_000) / 1000);
    return `${minutes}m ${seconds}s`;
  }
  const hours = Math.floor(ms / 3_600_000);
  const minutes = Math.round((ms % 3_600_000) / 60_000);
  return `${hours}h ${minutes}m`;
}

/**
 * Format a percentage
 */
export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

/**
 * Get a color class based on status
 */
export function getStatusColor(status: string): string {
  switch (status) {
    case 'completed':
    case 'success':
      return 'text-trace-success';
    case 'failed':
    case 'error':
      return 'text-trace-error';
    case 'running':
    case 'pending':
      return 'text-trace-warning';
    case 'cancelled':
      return 'text-trace-muted';
    default:
      return 'text-gray-400';
  }
}

/**
 * Get a background color class based on severity
 */
export function getSeverityColor(severity: string): string {
  switch (severity) {
    case 'critical':
      return 'bg-red-900/50 border-red-700 text-red-200';
    case 'high':
      return 'bg-orange-900/50 border-orange-700 text-orange-200';
    case 'medium':
      return 'bg-yellow-900/50 border-yellow-700 text-yellow-200';
    case 'low':
      return 'bg-blue-900/50 border-blue-700 text-blue-200';
    default:
      return 'bg-gray-800 border-gray-700 text-gray-200';
  }
}

/**
 * Get a badge color class for node types
 */
export function getNodeTypeColor(type: string): string {
  switch (type) {
    case 'session':
      return 'bg-purple-600';
    case 'iteration':
      return 'bg-blue-600';
    case 'llm':
      return 'bg-green-600';
    case 'tool':
      return 'bg-orange-600';
    case 'decision':
      return 'bg-cyan-600';
    case 'subagent':
      return 'bg-pink-600';
    case 'error':
      return 'bg-red-600';
    default:
      return 'bg-gray-600';
  }
}

/**
 * Truncate a string with ellipsis
 */
export function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen - 3) + '...';
}

/**
 * Relative time from now
 */
export function relativeTime(date: Date | string): string {
  const d = typeof date === 'string' ? new Date(date) : date;
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);

  if (diffSec < 60) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHour < 24) return `${diffHour}h ago`;
  if (diffDay < 7) return `${diffDay}d ago`;
  return d.toLocaleDateString();
}
