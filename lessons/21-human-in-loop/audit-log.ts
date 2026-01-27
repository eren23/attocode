/**
 * Lesson 21: Audit Log
 *
 * Records all actions for compliance and debugging.
 * Supports querying and filtering audit entries.
 */

import type {
  AuditEntry,
  AuditEventType,
  AuditActor,
  AuditAction,
  AuditOutcome,
  RollbackData,
  PendingAction,
  ApprovalResult,
  HILEvent,
  HILEventListener,
} from './types.js';
import { generateId } from './types.js';

// =============================================================================
// AUDIT LOGGER
// =============================================================================

/**
 * Audit log storage interface.
 */
export interface AuditStorage {
  append(entry: AuditEntry): Promise<void>;
  query(filter: AuditFilter): Promise<AuditEntry[]>;
  getById(id: string): Promise<AuditEntry | null>;
  getByIds(ids: string[]): Promise<AuditEntry[]>;
}

/**
 * Filter for querying audit entries.
 */
export interface AuditFilter {
  /** Filter by event types */
  eventTypes?: AuditEventType[];

  /** Filter by actor */
  actorId?: string;

  /** Filter by action type */
  actionType?: string;

  /** Filter by session */
  sessionId?: string;

  /** Filter by time range */
  startTime?: Date;
  endTime?: Date;

  /** Filter reversible only */
  reversibleOnly?: boolean;

  /** Maximum results */
  limit?: number;

  /** Offset for pagination */
  offset?: number;
}

/**
 * In-memory audit storage.
 */
export class InMemoryAuditStorage implements AuditStorage {
  private entries: AuditEntry[] = [];
  private maxEntries: number;

  constructor(maxEntries: number = 10000) {
    this.maxEntries = maxEntries;
  }

  async append(entry: AuditEntry): Promise<void> {
    this.entries.push(entry);

    // Trim if needed
    if (this.entries.length > this.maxEntries) {
      this.entries = this.entries.slice(-this.maxEntries);
    }
  }

  async query(filter: AuditFilter): Promise<AuditEntry[]> {
    let results = this.entries;

    if (filter.eventTypes) {
      results = results.filter((e) => filter.eventTypes!.includes(e.eventType));
    }

    if (filter.actorId) {
      results = results.filter((e) => e.actor.id === filter.actorId);
    }

    if (filter.actionType) {
      results = results.filter((e) => e.action.type === filter.actionType);
    }

    if (filter.sessionId) {
      results = results.filter((e) => e.sessionId === filter.sessionId);
    }

    if (filter.startTime) {
      results = results.filter((e) => e.timestamp >= filter.startTime!);
    }

    if (filter.endTime) {
      results = results.filter((e) => e.timestamp <= filter.endTime!);
    }

    if (filter.reversibleOnly) {
      results = results.filter((e) => e.reversible);
    }

    // Apply pagination
    if (filter.offset) {
      results = results.slice(filter.offset);
    }

    if (filter.limit) {
      results = results.slice(0, filter.limit);
    }

    return results;
  }

  async getById(id: string): Promise<AuditEntry | null> {
    return this.entries.find((e) => e.id === id) || null;
  }

  async getByIds(ids: string[]): Promise<AuditEntry[]> {
    return this.entries.filter((e) => ids.includes(e.id));
  }
}

/**
 * Main audit logger.
 */
export class AuditLogger {
  private storage: AuditStorage;
  private listeners: Set<HILEventListener> = new Set();

  constructor(storage: AuditStorage = new InMemoryAuditStorage()) {
    this.storage = storage;
  }

  /**
   * Log an action request.
   */
  async logActionRequested(
    action: PendingAction,
    actor: AuditActor
  ): Promise<AuditEntry> {
    const entry: AuditEntry = {
      id: generateId(),
      timestamp: new Date(),
      eventType: 'action_requested',
      actor,
      action: {
        type: action.type,
        description: action.description,
        data: action.data as unknown as Record<string, unknown>,
      },
      outcome: { success: true, message: 'Action requested' },
      reversible: false,
      sessionId: action.context.sessionId,
      metadata: { risk: action.risk },
    };

    await this.storage.append(entry);
    return entry;
  }

  /**
   * Log an approval decision.
   */
  async logApprovalDecision(
    action: PendingAction,
    result: ApprovalResult,
    previousEntryId?: string
  ): Promise<AuditEntry> {
    const entry: AuditEntry = {
      id: generateId(),
      timestamp: new Date(),
      eventType: result.decision === 'approved' ? 'action_approved' : 'action_rejected',
      actor: {
        type: result.decidedBy === 'system' || result.decidedBy === 'policy' ? 'system' : 'human',
        id: result.decidedBy,
        name: result.decidedBy,
      },
      action: {
        type: action.type,
        description: action.description,
        data: action.data as unknown as Record<string, unknown>,
      },
      outcome: {
        success: true,
        message: result.reason || `Action ${result.decision}`,
      },
      reversible: false,
      relatedEntries: previousEntryId ? [previousEntryId] : undefined,
      sessionId: action.context.sessionId,
      metadata: { conditions: result.conditions },
    };

    await this.storage.append(entry);
    return entry;
  }

  /**
   * Log action execution.
   */
  async logActionExecuted(
    action: PendingAction,
    outcome: AuditOutcome,
    rollbackData?: RollbackData,
    previousEntryId?: string
  ): Promise<AuditEntry> {
    const entry: AuditEntry = {
      id: generateId(),
      timestamp: new Date(),
      eventType: outcome.success ? 'action_executed' : 'action_failed',
      actor: {
        type: 'agent',
        id: action.context.requestor,
      },
      action: {
        type: action.type,
        description: action.description,
        data: action.data as unknown as Record<string, unknown>,
      },
      outcome,
      reversible: !!rollbackData,
      rollbackData,
      relatedEntries: previousEntryId ? [previousEntryId] : undefined,
      sessionId: action.context.sessionId,
    };

    await this.storage.append(entry);

    this.emit({
      type: 'action.executed',
      action,
      outcome,
    });

    return entry;
  }

  /**
   * Log a rollback.
   */
  async logRollback(
    originalEntry: AuditEntry,
    actor: AuditActor,
    success: boolean,
    message: string
  ): Promise<AuditEntry> {
    const entry: AuditEntry = {
      id: generateId(),
      timestamp: new Date(),
      eventType: 'action_rolled_back',
      actor,
      action: {
        type: originalEntry.action.type,
        description: `Rollback: ${originalEntry.action.description}`,
        data: originalEntry.action.data,
      },
      outcome: { success, message },
      reversible: false,
      relatedEntries: [originalEntry.id],
      sessionId: originalEntry.sessionId,
    };

    await this.storage.append(entry);
    return entry;
  }

  /**
   * Log an escalation.
   */
  async logEscalation(
    action: PendingAction,
    escalateTo: string
  ): Promise<AuditEntry> {
    const entry: AuditEntry = {
      id: generateId(),
      timestamp: new Date(),
      eventType: 'escalation_triggered',
      actor: { type: 'system', id: 'escalation-manager' },
      action: {
        type: action.type,
        description: action.description,
        data: action.data as unknown as Record<string, unknown>,
      },
      outcome: {
        success: true,
        message: `Escalated to ${escalateTo}`,
      },
      reversible: false,
      sessionId: action.context.sessionId,
      metadata: { escalateTo },
    };

    await this.storage.append(entry);
    return entry;
  }

  /**
   * Log a policy application.
   */
  async logPolicyApplied(
    action: PendingAction,
    policyName: string,
    result: string
  ): Promise<AuditEntry> {
    const entry: AuditEntry = {
      id: generateId(),
      timestamp: new Date(),
      eventType: 'policy_applied',
      actor: { type: 'policy', id: policyName },
      action: {
        type: action.type,
        description: action.description,
        data: action.data as unknown as Record<string, unknown>,
      },
      outcome: { success: true, message: result },
      reversible: false,
      sessionId: action.context.sessionId,
    };

    await this.storage.append(entry);
    return entry;
  }

  /**
   * Log session start.
   */
  async logSessionStart(
    sessionId: string,
    actor: AuditActor
  ): Promise<AuditEntry> {
    const entry: AuditEntry = {
      id: generateId(),
      timestamp: new Date(),
      eventType: 'session_started',
      actor,
      action: {
        type: 'system_modification' as const,
        description: 'Session started',
        data: {},
      },
      outcome: { success: true },
      reversible: false,
      sessionId,
    };

    await this.storage.append(entry);
    return entry;
  }

  /**
   * Log session end.
   */
  async logSessionEnd(
    sessionId: string,
    actor: AuditActor,
    summary?: Record<string, unknown>
  ): Promise<AuditEntry> {
    const entry: AuditEntry = {
      id: generateId(),
      timestamp: new Date(),
      eventType: 'session_ended',
      actor,
      action: {
        type: 'system_modification' as const,
        description: 'Session ended',
        data: summary || {},
      },
      outcome: { success: true },
      reversible: false,
      sessionId,
    };

    await this.storage.append(entry);
    return entry;
  }

  /**
   * Query audit entries.
   */
  async query(filter: AuditFilter): Promise<AuditEntry[]> {
    return this.storage.query(filter);
  }

  /**
   * Get entry by ID.
   */
  async getEntry(id: string): Promise<AuditEntry | null> {
    return this.storage.getById(id);
  }

  /**
   * Get related entries.
   */
  async getRelatedEntries(entry: AuditEntry): Promise<AuditEntry[]> {
    if (!entry.relatedEntries || entry.relatedEntries.length === 0) {
      return [];
    }
    return this.storage.getByIds(entry.relatedEntries);
  }

  /**
   * Get reversible entries for a session.
   */
  async getReversibleEntries(sessionId: string): Promise<AuditEntry[]> {
    return this.storage.query({
      sessionId,
      reversibleOnly: true,
    });
  }

  /**
   * Subscribe to events.
   */
  on(listener: HILEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(event: HILEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch (err) {
        console.error('Audit logger listener error:', err);
      }
    }
  }
}

// =============================================================================
// AUDIT REPORT GENERATOR
// =============================================================================

/**
 * Generates audit reports.
 */
export class AuditReportGenerator {
  /**
   * Generate a session summary.
   */
  static async sessionSummary(
    logger: AuditLogger,
    sessionId: string
  ): Promise<string> {
    const entries = await logger.query({ sessionId });

    const stats = {
      total: entries.length,
      approved: entries.filter((e) => e.eventType === 'action_approved').length,
      rejected: entries.filter((e) => e.eventType === 'action_rejected').length,
      executed: entries.filter((e) => e.eventType === 'action_executed').length,
      failed: entries.filter((e) => e.eventType === 'action_failed').length,
      rolledBack: entries.filter((e) => e.eventType === 'action_rolled_back').length,
      escalated: entries.filter((e) => e.eventType === 'escalation_triggered').length,
    };

    const lines: string[] = [
      '═══════════════════════════════════════',
      '         SESSION AUDIT SUMMARY',
      '═══════════════════════════════════════',
      '',
      `  Session ID: ${sessionId}`,
      `  Total Events: ${stats.total}`,
      '',
      '  Actions:',
      `    Approved:    ${stats.approved}`,
      `    Rejected:    ${stats.rejected}`,
      `    Executed:    ${stats.executed}`,
      `    Failed:      ${stats.failed}`,
      `    Rolled Back: ${stats.rolledBack}`,
      `    Escalated:   ${stats.escalated}`,
      '',
      '═══════════════════════════════════════',
    ];

    return lines.join('\n');
  }

  /**
   * Generate a timeline.
   */
  static async timeline(
    logger: AuditLogger,
    filter: AuditFilter
  ): Promise<string> {
    const entries = await logger.query(filter);
    const lines: string[] = [];

    for (const entry of entries) {
      const time = entry.timestamp.toISOString().slice(11, 19);
      const icon = AuditReportGenerator.getEventIcon(entry.eventType);
      const actor = entry.actor.name || entry.actor.id;

      lines.push(`  ${time} ${icon} [${actor}] ${entry.action.description}`);

      if (entry.outcome.message) {
        lines.push(`           └─ ${entry.outcome.message}`);
      }
    }

    return lines.join('\n');
  }

  /**
   * Get icon for event type.
   */
  private static getEventIcon(type: AuditEventType): string {
    const icons: Record<AuditEventType, string> = {
      action_requested: '📝',
      action_approved: '✅',
      action_rejected: '❌',
      action_executed: '⚡',
      action_failed: '💥',
      action_rolled_back: '↩️',
      escalation_triggered: '📢',
      policy_applied: '📋',
      session_started: '🚀',
      session_ended: '🏁',
    };
    return icons[type] || '•';
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createAuditLogger(storage?: AuditStorage): AuditLogger {
  return new AuditLogger(storage);
}

export function createInMemoryAuditStorage(maxEntries?: number): InMemoryAuditStorage {
  return new InMemoryAuditStorage(maxEntries);
}
