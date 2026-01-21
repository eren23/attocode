/**
 * Example Plugin: Metrics
 *
 * A plugin that collects and exposes metrics about agent performance.
 * Demonstrates tool registration and inter-plugin communication.
 */

import { z } from 'zod';
import type { Plugin, PluginContext, ToolDefinition } from '../types.js';

/**
 * Metric data structure.
 */
interface Metric {
  name: string;
  value: number;
  type: 'counter' | 'gauge' | 'histogram';
  labels?: Record<string, string>;
  timestamp: Date;
}

/**
 * Histogram bucket for duration tracking.
 */
interface HistogramBucket {
  le: number; // Less than or equal
  count: number;
}

export const metricsPlugin: Plugin = {
  metadata: {
    name: 'metrics',
    version: '1.0.0',
    description: 'Collects performance metrics and exposes them via tools',
    author: 'First Principles Agent',
    tags: ['metrics', 'monitoring', 'observability'],
  },

  async initialize(context: PluginContext) {
    context.log('info', 'Metrics plugin initializing...');

    // Metrics storage
    const counters = new Map<string, number>();
    const gauges = new Map<string, number>();
    const histograms = new Map<string, number[]>();

    // Helper functions
    const incrementCounter = (name: string, value = 1) => {
      counters.set(name, (counters.get(name) ?? 0) + value);
    };

    const setGauge = (name: string, value: number) => {
      gauges.set(name, value);
    };

    const recordHistogram = (name: string, value: number) => {
      const values = histograms.get(name) ?? [];
      values.push(value);
      histograms.set(name, values);
    };

    // Register hooks to collect metrics
    context.registerHook('tool.before', () => {
      incrementCounter('tool_calls_total');
    }, { priority: 50, description: 'Count tool calls' });

    context.registerHook('tool.after', (event) => {
      recordHistogram('tool_duration_ms', event.durationMs);
      incrementCounter(`tool_calls_by_name:${event.tool}`);
    }, { priority: 50, description: 'Track tool duration' });

    context.registerHook('tool.error', () => {
      incrementCounter('tool_errors_total');
    }, { priority: 50, description: 'Count tool errors' });

    context.registerHook('session.start', () => {
      incrementCounter('sessions_total');
      setGauge('active_sessions', (gauges.get('active_sessions') ?? 0) + 1);
    }, { priority: 50, description: 'Track sessions' });

    context.registerHook('session.end', (event) => {
      setGauge('active_sessions', Math.max(0, (gauges.get('active_sessions') ?? 1) - 1));
      if (event.summary) {
        recordHistogram('session_duration_ms', event.summary.durationMs);
        if (event.summary.tokens) {
          incrementCounter('tokens_input_total', event.summary.tokens.input);
          incrementCounter('tokens_output_total', event.summary.tokens.output);
        }
      }
    }, { priority: 50, description: 'Track session completion' });

    context.registerHook('error', () => {
      incrementCounter('errors_total');
    }, { priority: 50, description: 'Count errors' });

    // Listen for security events from security plugin
    context.subscribe('security.blocked', () => {
      incrementCounter('security_blocked_total');
    });

    // Register tool to get metrics
    const getMetricsTool: ToolDefinition<typeof getMetricsSchema> = {
      name: 'get_metrics',
      description: 'Get current agent metrics',
      parameters: getMetricsSchema,
      dangerLevel: 'safe',
      execute: async (input) => {
        const result: Record<string, unknown> = {};

        if (input.type === 'all' || input.type === 'counters') {
          result.counters = Object.fromEntries(counters);
        }

        if (input.type === 'all' || input.type === 'gauges') {
          result.gauges = Object.fromEntries(gauges);
        }

        if (input.type === 'all' || input.type === 'histograms') {
          const histogramStats: Record<string, unknown> = {};
          for (const [name, values] of histograms) {
            if (values.length > 0) {
              histogramStats[name] = {
                count: values.length,
                min: Math.min(...values),
                max: Math.max(...values),
                avg: values.reduce((a, b) => a + b, 0) / values.length,
                p50: percentile(values, 50),
                p95: percentile(values, 95),
                p99: percentile(values, 99),
              };
            }
          }
          result.histograms = histogramStats;
        }

        return {
          success: true,
          output: JSON.stringify(result, null, 2),
          metadata: { timestamp: new Date().toISOString() },
        };
      },
    };

    context.registerTool(getMetricsTool);

    // Register tool to reset metrics
    const resetMetricsTool: ToolDefinition<typeof resetMetricsSchema> = {
      name: 'reset_metrics',
      description: 'Reset all metrics to zero',
      parameters: resetMetricsSchema,
      dangerLevel: 'moderate',
      execute: async (input) => {
        if (input.confirm !== true) {
          return {
            success: false,
            output: 'Must confirm reset by setting confirm: true',
          };
        }

        counters.clear();
        gauges.clear();
        histograms.clear();

        context.emit('metrics.reset', { timestamp: new Date() });

        return {
          success: true,
          output: 'All metrics have been reset',
        };
      },
    };

    context.registerTool(resetMetricsTool);

    // Expose metrics via custom events
    context.subscribe('metrics.request', () => {
      context.emit('metrics.response', {
        counters: Object.fromEntries(counters),
        gauges: Object.fromEntries(gauges),
        histogramCounts: Object.fromEntries(
          [...histograms.entries()].map(([k, v]) => [k, v.length])
        ),
      });
    });

    context.log('info', 'Metrics plugin initialized');
  },

  async cleanup() {
    console.log('[metrics] Cleanup complete');
  },
};

// Schema definitions
const getMetricsSchema = z.object({
  type: z.enum(['all', 'counters', 'gauges', 'histograms']).default('all')
    .describe('Type of metrics to retrieve'),
});

const resetMetricsSchema = z.object({
  confirm: z.boolean().describe('Must be true to confirm reset'),
});

/**
 * Calculate percentile of a sorted array.
 */
function percentile(values: number[], p: number): number {
  if (values.length === 0) return 0;

  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.ceil((p / 100) * sorted.length) - 1;

  return sorted[Math.max(0, index)];
}

export default metricsPlugin;
