/**
 * Lesson 26: Trace Exporter
 *
 * Enhanced JSONL export with filtering, compression, and format options.
 * Supports exporting full traces or filtered views for analysis.
 *
 * @example
 * ```typescript
 * const exporter = new TraceExporter({
 *   outputDir: '.traces',
 *   format: 'jsonl',
 *   includeMessageContent: false, // Reduce size
 * });
 *
 * // Export session trace
 * await exporter.exportSession(sessionTrace);
 *
 * // Export with filtering
 * await exporter.exportFiltered(sessionTrace, {
 *   includeToolResults: false,
 *   onlyErrors: true,
 * });
 * ```
 */

import { mkdir, writeFile, appendFile } from 'fs/promises';
import { join } from 'path';
import type {
  SessionTrace,
  IterationTrace,
  LLMRequestTrace,
  ToolExecutionTrace,
  JSONLEntry,
} from './types.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Export configuration.
 */
export interface TraceExportConfig {
  /** Output directory */
  outputDir: string;

  /** Export format */
  format: 'jsonl' | 'json' | 'csv';

  /** Include full message content */
  includeMessageContent: boolean;

  /** Include tool results */
  includeToolResults: boolean;

  /** Pretty print JSON */
  prettyPrint: boolean;

  /** Compress output (gzip) - future feature */
  compress: boolean;
}

/**
 * Default export configuration.
 */
export const DEFAULT_EXPORT_CONFIG: TraceExportConfig = {
  outputDir: '.traces',
  format: 'jsonl',
  includeMessageContent: true,
  includeToolResults: true,
  prettyPrint: false,
  compress: false,
};

/**
 * Filter options for export.
 */
export interface ExportFilterOptions {
  /** Only include iterations with errors */
  onlyErrors?: boolean;

  /** Only include specific tool names */
  toolNames?: string[];

  /** Minimum duration threshold (ms) */
  minDuration?: number;

  /** Maximum iterations to include */
  maxIterations?: number;

  /** Include tool results */
  includeToolResults?: boolean;

  /** Include message content */
  includeMessageContent?: boolean;
}

/**
 * Summary statistics for export.
 */
export interface ExportSummary {
  /** Output file path */
  filePath: string;

  /** Number of entries written */
  entriesWritten: number;

  /** File size in bytes */
  fileSizeBytes: number;

  /** Export duration in ms */
  exportDurationMs: number;

  /** Warnings during export */
  warnings: string[];
}

// =============================================================================
// TRACE EXPORTER
// =============================================================================

/**
 * Exports session traces in various formats.
 */
export class TraceExporter {
  private config: TraceExportConfig;

  constructor(config: Partial<TraceExportConfig> = {}) {
    this.config = { ...DEFAULT_EXPORT_CONFIG, ...config };
  }

  /**
   * Export a complete session trace.
   */
  async exportSession(
    trace: SessionTrace,
    filename?: string
  ): Promise<ExportSummary> {
    const startTime = Date.now();
    const warnings: string[] = [];

    await mkdir(this.config.outputDir, { recursive: true });

    const outputFilename = filename ?? this.generateFilename(trace);
    const filePath = join(this.config.outputDir, outputFilename);

    let entriesWritten = 0;

    switch (this.config.format) {
      case 'jsonl':
        entriesWritten = await this.exportAsJSONL(trace, filePath);
        break;
      case 'json':
        entriesWritten = await this.exportAsJSON(trace, filePath);
        break;
      case 'csv':
        entriesWritten = await this.exportAsCSV(trace, filePath);
        break;
    }

    // Get file size (approximate for now)
    const fileSizeBytes = await this.getFileSize(filePath);

    return {
      filePath,
      entriesWritten,
      fileSizeBytes,
      exportDurationMs: Date.now() - startTime,
      warnings,
    };
  }

  /**
   * Export with filtering.
   */
  async exportFiltered(
    trace: SessionTrace,
    filters: ExportFilterOptions,
    filename?: string
  ): Promise<ExportSummary> {
    // Apply filters to create a new trace
    const filteredTrace = this.applyFilters(trace, filters);
    return this.exportSession(filteredTrace, filename);
  }

  /**
   * Export multiple sessions to a single file.
   */
  async exportMultiple(
    traces: SessionTrace[],
    filename: string
  ): Promise<ExportSummary> {
    const startTime = Date.now();
    const warnings: string[] = [];

    await mkdir(this.config.outputDir, { recursive: true });
    const filePath = join(this.config.outputDir, filename);

    let entriesWritten = 0;

    // Clear file first
    await writeFile(filePath, '');

    for (const trace of traces) {
      const entries = await this.exportAsJSONL(trace, filePath);
      entriesWritten += entries;
    }

    const fileSizeBytes = await this.getFileSize(filePath);

    return {
      filePath,
      entriesWritten,
      fileSizeBytes,
      exportDurationMs: Date.now() - startTime,
      warnings,
    };
  }

  // ===========================================================================
  // FORMAT-SPECIFIC EXPORTS
  // ===========================================================================

  /**
   * Export as JSON Lines format.
   */
  private async exportAsJSONL(trace: SessionTrace, filePath: string): Promise<number> {
    const entries: string[] = [];

    // Session start
    entries.push(JSON.stringify({
      _type: 'session.start',
      _ts: new Date(trace.startTime).toISOString(),
      traceId: trace.traceId,
      sessionId: trace.sessionId,
      task: trace.task,
      model: trace.model,
    }));

    // Iterations
    for (const iteration of trace.iterations) {
      // LLM request
      if (iteration.llmRequest) {
        entries.push(JSON.stringify(this.formatLLMRequest(iteration.llmRequest)));
        entries.push(JSON.stringify(this.formatLLMResponse(iteration.llmRequest)));
      }

      // Tool executions
      for (const tool of iteration.toolExecutions) {
        entries.push(JSON.stringify(this.formatToolExecution(tool)));
      }
    }

    // Session end
    entries.push(JSON.stringify({
      _type: 'session.end',
      _ts: new Date(trace.endTime ?? Date.now()).toISOString(),
      traceId: trace.traceId,
      sessionId: trace.sessionId,
      status: trace.status,
      durationMs: trace.durationMs,
      metrics: trace.metrics,
    }));

    await writeFile(filePath, entries.join('\n') + '\n');
    return entries.length;
  }

  /**
   * Export as single JSON file.
   */
  private async exportAsJSON(trace: SessionTrace, filePath: string): Promise<number> {
    const exportData = {
      session: {
        id: trace.sessionId,
        traceId: trace.traceId,
        task: trace.task,
        model: trace.model,
        status: trace.status,
        startTime: trace.startTime,
        endTime: trace.endTime,
        durationMs: trace.durationMs,
      },
      metrics: trace.metrics,
      iterations: trace.iterations.map(iter => ({
        number: iter.iterationNumber,
        durationMs: iter.durationMs,
        metrics: iter.metrics,
        llmRequest: iter.llmRequest ? {
          model: iter.llmRequest.model,
          tokens: iter.llmRequest.tokens,
          cache: iter.llmRequest.cache,
          stopReason: iter.llmRequest.response.stopReason,
          toolCalls: iter.llmRequest.response.toolCalls?.length ?? 0,
          ...(this.config.includeMessageContent ? {
            messages: iter.llmRequest.request.messages,
            response: iter.llmRequest.response.content,
          } : {}),
        } : null,
        toolExecutions: iter.toolExecutions.map(tool => ({
          name: tool.toolName,
          status: tool.status,
          durationMs: tool.durationMs,
          ...(this.config.includeToolResults ? {
            result: tool.result,
            error: tool.error,
          } : {}),
        })),
      })),
      result: trace.result,
    };

    const content = this.config.prettyPrint
      ? JSON.stringify(exportData, null, 2)
      : JSON.stringify(exportData);

    await writeFile(filePath, content);
    return 1;
  }

  /**
   * Export as CSV format (summary only).
   */
  private async exportAsCSV(trace: SessionTrace, filePath: string): Promise<number> {
    const headers = [
      'iteration',
      'duration_ms',
      'input_tokens',
      'output_tokens',
      'cache_hit_rate',
      'tool_calls',
      'cost',
      'stop_reason',
    ];

    const rows: string[] = [headers.join(',')];

    for (const iteration of trace.iterations) {
      const row = [
        iteration.iterationNumber,
        iteration.durationMs,
        iteration.metrics.inputTokens,
        iteration.metrics.outputTokens,
        iteration.metrics.cacheHitRate.toFixed(3),
        iteration.metrics.toolCallCount,
        iteration.metrics.totalCost.toFixed(6),
        iteration.llmRequest?.response.stopReason ?? '',
      ];
      rows.push(row.join(','));
    }

    // Add summary row
    rows.push('');
    rows.push(`# Summary`);
    rows.push(`# Total Duration: ${trace.durationMs}ms`);
    rows.push(`# Total Cost: $${trace.metrics.estimatedCost.toFixed(4)}`);
    rows.push(`# Avg Cache Hit Rate: ${(trace.metrics.avgCacheHitRate * 100).toFixed(1)}%`);

    await writeFile(filePath, rows.join('\n'));
    return trace.iterations.length;
  }

  // ===========================================================================
  // FILTERING
  // ===========================================================================

  /**
   * Apply filters to a trace.
   */
  private applyFilters(trace: SessionTrace, filters: ExportFilterOptions): SessionTrace {
    let iterations = [...trace.iterations];

    // Filter by errors
    if (filters.onlyErrors) {
      iterations = iterations.filter(iter =>
        iter.toolExecutions.some(t => t.status === 'error') ||
        iter.llmRequest?.error !== undefined
      );
    }

    // Filter by tool names
    if (filters.toolNames && filters.toolNames.length > 0) {
      iterations = iterations.filter(iter =>
        iter.toolExecutions.some(t => filters.toolNames!.includes(t.toolName))
      );
    }

    // Filter by duration
    if (filters.minDuration !== undefined) {
      iterations = iterations.filter(iter => iter.durationMs >= filters.minDuration!);
    }

    // Limit iterations
    if (filters.maxIterations !== undefined) {
      iterations = iterations.slice(0, filters.maxIterations);
    }

    // Strip content if not included
    if (filters.includeMessageContent === false) {
      iterations = iterations.map(iter => ({
        ...iter,
        llmRequest: iter.llmRequest ? {
          ...iter.llmRequest,
          request: {
            ...iter.llmRequest.request,
            messages: iter.llmRequest.request.messages.map(m => ({
              ...m,
              content: '[content stripped]',
            })),
          },
          response: {
            ...iter.llmRequest.response,
            content: '[content stripped]',
          },
        } : iter.llmRequest,
      }));
    }

    // Strip tool results if not included
    if (filters.includeToolResults === false) {
      iterations = iterations.map(iter => ({
        ...iter,
        toolExecutions: iter.toolExecutions.map(t => ({
          ...t,
          result: undefined,
        })),
      }));
    }

    return {
      ...trace,
      iterations,
    };
  }

  // ===========================================================================
  // FORMATTING HELPERS
  // ===========================================================================

  /**
   * Format LLM request for JSONL.
   */
  private formatLLMRequest(request: LLMRequestTrace): object {
    return {
      _type: 'llm.request',
      _ts: new Date(request.timestamp).toISOString(),
      traceId: request.traceId,
      requestId: request.requestId,
      model: request.model,
      messageCount: request.request.messages.length,
      toolCount: request.request.tools?.length ?? 0,
      estimatedInputTokens: request.tokens.input,
    };
  }

  /**
   * Format LLM response for JSONL.
   */
  private formatLLMResponse(request: LLMRequestTrace): object {
    return {
      _type: 'llm.response',
      _ts: new Date(request.timestamp + (request.durationMs ?? 0)).toISOString(),
      traceId: request.traceId,
      requestId: request.requestId,
      durationMs: request.durationMs,
      tokens: request.tokens,
      cache: request.cache,
      stopReason: request.response.stopReason,
      toolCallCount: request.response.toolCalls?.length ?? 0,
    };
  }

  /**
   * Format tool execution for JSONL.
   */
  private formatToolExecution(tool: ToolExecutionTrace): object {
    return {
      _type: 'tool.execution',
      _ts: new Date(tool.startTime).toISOString(),
      traceId: tool.traceId,
      executionId: tool.executionId,
      toolName: tool.toolName,
      durationMs: tool.durationMs,
      status: tool.status,
      resultSize: tool.result?.originalSize,
    };
  }

  /**
   * Generate filename for export.
   */
  private generateFilename(trace: SessionTrace): string {
    const timestamp = new Date(trace.startTime).toISOString().replace(/[:.]/g, '-');
    const extension = this.config.format === 'csv' ? 'csv' : this.config.format;
    return `trace-${trace.sessionId}-${timestamp}.${extension}`;
  }

  /**
   * Get file size (approximate).
   */
  private async getFileSize(filePath: string): Promise<number> {
    try {
      const { stat } = await import('fs/promises');
      const stats = await stat(filePath);
      return stats.size;
    } catch {
      return 0;
    }
  }
}

// =============================================================================
// FACTORY FUNCTION
// =============================================================================

/**
 * Create a trace exporter.
 */
export function createTraceExporter(
  config: Partial<TraceExportConfig> = {}
): TraceExporter {
  return new TraceExporter(config);
}
