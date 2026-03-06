/**
 * Metric Card Component
 *
 * Displays a single metric with label and optional trend indicator.
 */

import type { ReactNode } from 'react';
import { cn } from '../lib/utils';

interface MetricCardProps {
  label: string;
  value: ReactNode;
  subtext?: ReactNode;
  trend?: 'up' | 'down' | 'neutral';
  status?: 'good' | 'warn' | 'bad' | 'neutral';
  className?: string;
}

export function MetricCard({
  label,
  value,
  subtext,
  trend,
  status = 'neutral',
  className,
}: MetricCardProps) {
  const statusColors = {
    good: 'border-green-700/50 bg-green-900/20',
    warn: 'border-yellow-700/50 bg-yellow-900/20',
    bad: 'border-red-700/50 bg-red-900/20',
    neutral: 'border-gray-700 bg-gray-800/50',
  };

  const trendIcons = {
    up: (
      <svg className="w-4 h-4 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
      </svg>
    ),
    down: (
      <svg className="w-4 h-4 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
      </svg>
    ),
    neutral: null,
  };

  return (
    <div
      className={cn(
        'rounded-lg border p-4 transition-colors',
        statusColors[status],
        className
      )}
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-gray-400">{label}</span>
        {trend && trendIcons[trend]}
      </div>
      <div className="mt-1">
        <span className="text-2xl font-bold text-white">{value}</span>
        {subtext && (
          <span className="ml-2 text-sm text-gray-500">{subtext}</span>
        )}
      </div>
    </div>
  );
}
