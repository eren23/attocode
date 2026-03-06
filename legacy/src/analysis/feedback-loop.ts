/**
 * Feedback Loop Manager
 *
 * Tracks analysis results, proposed fixes, and improvements over time.
 * Uses SQLite for persistence.
 */

import Database from 'better-sqlite3';
import { join } from 'path';
import { mkdirSync, existsSync } from 'fs';

/**
 * Analysis record stored in database.
 */
export interface AnalysisRecord {
  id: string;
  sessionId: string;
  timestamp: number;
  efficiencyScore: number;
  issueCount: number;
  issues: string; // JSON string
  recommendations: string; // JSON string
}

/**
 * Proposed fix record.
 */
export interface ProposedFix {
  id: string;
  analysisId: string;
  issueId: string;
  description: string;
  codeLocations: string; // JSON string
  status: 'pending' | 'implemented' | 'rejected' | 'verified';
  createdAt: number;
  implementedAt?: number;
  verifiedAt?: number;
}

/**
 * Improvement metric record.
 */
export interface ImprovementMetric {
  id: string;
  fixId: string;
  metricName: string;
  beforeValue: number;
  afterValue: number;
  improvement: number;
  measuredAt: number;
}

/**
 * Feedback loop manager for tracking improvements.
 */
export class FeedbackLoopManager {
  private db: Database.Database;
  private dbPath: string;

  constructor(dataDir = '.agent/analysis') {
    // Ensure directory exists
    if (!existsSync(dataDir)) {
      mkdirSync(dataDir, { recursive: true });
    }

    this.dbPath = join(dataDir, 'feedback-loop.db');
    this.db = new Database(this.dbPath);

    this.initSchema();
  }

  /**
   * Initialize database schema.
   */
  private initSchema(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS analysis_results (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        timestamp INTEGER NOT NULL,
        efficiency_score INTEGER NOT NULL,
        issue_count INTEGER NOT NULL,
        issues TEXT NOT NULL,
        recommendations TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS proposed_fixes (
        id TEXT PRIMARY KEY,
        analysis_id TEXT NOT NULL,
        issue_id TEXT NOT NULL,
        description TEXT NOT NULL,
        code_locations TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at INTEGER NOT NULL,
        implemented_at INTEGER,
        verified_at INTEGER,
        FOREIGN KEY (analysis_id) REFERENCES analysis_results(id)
      );

      CREATE TABLE IF NOT EXISTS improvement_metrics (
        id TEXT PRIMARY KEY,
        fix_id TEXT NOT NULL,
        metric_name TEXT NOT NULL,
        before_value REAL NOT NULL,
        after_value REAL NOT NULL,
        improvement REAL NOT NULL,
        measured_at INTEGER NOT NULL,
        FOREIGN KEY (fix_id) REFERENCES proposed_fixes(id)
      );

      CREATE INDEX IF NOT EXISTS idx_analysis_session ON analysis_results(session_id);
      CREATE INDEX IF NOT EXISTS idx_analysis_timestamp ON analysis_results(timestamp);
      CREATE INDEX IF NOT EXISTS idx_fixes_status ON proposed_fixes(status);
      CREATE INDEX IF NOT EXISTS idx_fixes_analysis ON proposed_fixes(analysis_id);
    `);
  }

  /**
   * Store an analysis result.
   */
  storeAnalysis(
    sessionId: string,
    efficiencyScore: number,
    issues: Array<{ id: string; description: string; severity: string }>,
    recommendations: Array<{ priority: number; recommendation: string }>,
  ): string {
    const id = `analysis-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

    const stmt = this.db.prepare(`
      INSERT INTO analysis_results (id, session_id, timestamp, efficiency_score, issue_count, issues, recommendations)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `);

    stmt.run(
      id,
      sessionId,
      Date.now(),
      efficiencyScore,
      issues.length,
      JSON.stringify(issues),
      JSON.stringify(recommendations),
    );

    return id;
  }

  /**
   * Get analysis results for a session.
   */
  getAnalysisForSession(sessionId: string): AnalysisRecord[] {
    const stmt = this.db.prepare(`
      SELECT id, session_id as sessionId, timestamp, efficiency_score as efficiencyScore,
             issue_count as issueCount, issues, recommendations
      FROM analysis_results
      WHERE session_id = ?
      ORDER BY timestamp DESC
    `);

    return stmt.all(sessionId) as AnalysisRecord[];
  }

  /**
   * Get recent analyses.
   */
  getRecentAnalyses(limit = 10): AnalysisRecord[] {
    const stmt = this.db.prepare(`
      SELECT id, session_id as sessionId, timestamp, efficiency_score as efficiencyScore,
             issue_count as issueCount, issues, recommendations
      FROM analysis_results
      ORDER BY timestamp DESC
      LIMIT ?
    `);

    return stmt.all(limit) as AnalysisRecord[];
  }

  /**
   * Store a proposed fix.
   */
  storeFix(
    analysisId: string,
    issueId: string,
    description: string,
    codeLocations: string[],
  ): string {
    const id = `fix-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

    const stmt = this.db.prepare(`
      INSERT INTO proposed_fixes (id, analysis_id, issue_id, description, code_locations, status, created_at)
      VALUES (?, ?, ?, ?, ?, 'pending', ?)
    `);

    stmt.run(id, analysisId, issueId, description, JSON.stringify(codeLocations), Date.now());

    return id;
  }

  /**
   * Update fix status.
   */
  updateFixStatus(fixId: string, status: ProposedFix['status']): void {
    const now = Date.now();
    let column = '';

    if (status === 'implemented') column = ', implemented_at = ?';
    if (status === 'verified') column = ', verified_at = ?';

    const stmt = this.db.prepare(`
      UPDATE proposed_fixes
      SET status = ?${column}
      WHERE id = ?
    `);

    if (column) {
      stmt.run(status, now, fixId);
    } else {
      stmt.run(status, fixId);
    }
  }

  /**
   * Get pending fixes.
   */
  getPendingFixes(): ProposedFix[] {
    const stmt = this.db.prepare(`
      SELECT id, analysis_id as analysisId, issue_id as issueId, description,
             code_locations as codeLocations, status, created_at as createdAt,
             implemented_at as implementedAt, verified_at as verifiedAt
      FROM proposed_fixes
      WHERE status = 'pending'
      ORDER BY created_at DESC
    `);

    return stmt.all() as ProposedFix[];
  }

  /**
   * Store improvement metric.
   */
  storeImprovement(
    fixId: string,
    metricName: string,
    beforeValue: number,
    afterValue: number,
  ): void {
    const id = `metric-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const improvement = beforeValue !== 0 ? ((afterValue - beforeValue) / beforeValue) * 100 : 0;

    const stmt = this.db.prepare(`
      INSERT INTO improvement_metrics (id, fix_id, metric_name, before_value, after_value, improvement, measured_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `);

    stmt.run(id, fixId, metricName, beforeValue, afterValue, improvement, Date.now());
  }

  /**
   * Get improvement history.
   */
  getImprovementHistory(limit = 20): ImprovementMetric[] {
    const stmt = this.db.prepare(`
      SELECT id, fix_id as fixId, metric_name as metricName,
             before_value as beforeValue, after_value as afterValue,
             improvement, measured_at as measuredAt
      FROM improvement_metrics
      ORDER BY measured_at DESC
      LIMIT ?
    `);

    return stmt.all(limit) as ImprovementMetric[];
  }

  /**
   * Get summary statistics.
   */
  getSummaryStats(): {
    totalAnalyses: number;
    avgEfficiencyScore: number;
    totalFixes: number;
    implementedFixes: number;
    verifiedFixes: number;
    avgImprovement: number;
  } {
    const analysisStats = this.db
      .prepare(
        `
      SELECT COUNT(*) as count, AVG(efficiency_score) as avgScore
      FROM analysis_results
    `,
      )
      .get() as { count: number; avgScore: number };

    const fixStats = this.db
      .prepare(
        `
      SELECT
        COUNT(*) as total,
        SUM(CASE WHEN status = 'implemented' OR status = 'verified' THEN 1 ELSE 0 END) as implemented,
        SUM(CASE WHEN status = 'verified' THEN 1 ELSE 0 END) as verified
      FROM proposed_fixes
    `,
      )
      .get() as { total: number; implemented: number; verified: number };

    const improvementStats = this.db
      .prepare(
        `
      SELECT AVG(improvement) as avgImprovement
      FROM improvement_metrics
      WHERE improvement > 0
    `,
      )
      .get() as { avgImprovement: number | null };

    return {
      totalAnalyses: analysisStats.count,
      avgEfficiencyScore: Math.round(analysisStats.avgScore || 0),
      totalFixes: fixStats.total,
      implementedFixes: fixStats.implemented,
      verifiedFixes: fixStats.verified,
      avgImprovement: Math.round(improvementStats.avgImprovement || 0),
    };
  }

  /**
   * Close database connection.
   */
  close(): void {
    this.db.close();
  }
}

/**
 * Factory function.
 */
export function createFeedbackLoopManager(dataDir?: string): FeedbackLoopManager {
  return new FeedbackLoopManager(dataDir);
}
