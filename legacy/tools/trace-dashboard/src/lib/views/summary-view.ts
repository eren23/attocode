/**
 * Summary View
 *
 * Generates a high-level summary of a trace session.
 */

import type { ParsedSession, SummarySection, Inefficiency } from '../types.js';
import { createSessionAnalyzer } from '../analyzer/session-analyzer.js';
import { createInefficiencyDetector } from '../analyzer/inefficiency-detector.js';

/**
 * Summary view data.
 */
export interface SummaryViewData {
  /** Session header info */
  header: {
    sessionId: string;
    task: string;
    model: string;
    status: string;
    statusColor: 'green' | 'yellow' | 'red';
    duration: string;
  };
  /** Summary sections */
  sections: SummarySection[];
  /** Top inefficiencies (if analyzed) */
  inefficiencies?: Inefficiency[];
  /** Tool usage stats */
  toolStats: Array<{ tool: string; count: number; avgDuration: number }>;
  /** Decision stats */
  decisionStats: Array<{ type: string; count: number; outcomes: Record<string, number> }>;
}

/**
 * Generates summary view data.
 */
export class SummaryView {
  private session: ParsedSession;
  private analyzer;
  private inefficiencyDetector;

  constructor(session: ParsedSession) {
    this.session = session;
    this.analyzer = createSessionAnalyzer(session);
    this.inefficiencyDetector = createInefficiencyDetector(session);
  }

  /**
   * Generate summary view data.
   */
  generate(includeAnalysis = true): SummaryViewData {
    const statusInfo = this.analyzer.getStatusInfo();

    return {
      header: {
        sessionId: this.session.sessionId,
        task: this.session.task,
        model: this.session.model,
        status: statusInfo.status,
        statusColor: statusInfo.color,
        duration: this.formatDuration(this.session.durationMs || 0),
      },
      sections: this.analyzer.getSummarySections(),
      inefficiencies: includeAnalysis ? this.inefficiencyDetector.detect() : undefined,
      toolStats: this.analyzer.getToolUsageStats(),
      decisionStats: this.analyzer.getDecisionStats(),
    };
  }

  /**
   * Get efficiency score.
   */
  getEfficiencyScore(): number {
    return this.analyzer.calculateEfficiencyScore();
  }

  private formatDuration(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${Math.round(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
  }
}

/**
 * Factory function.
 */
export function createSummaryView(session: ParsedSession): SummaryView {
  return new SummaryView(session);
}
