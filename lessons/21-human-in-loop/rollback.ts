/**
 * Lesson 21: Rollback
 *
 * Handles undoing actions that have been executed.
 * Supports various rollback strategies and verification.
 */

import type {
  RollbackData,
  RollbackRequest,
  RollbackResult,
  AuditEntry,
  AuditActor,
  HILEvent,
  HILEventListener,
} from './types.js';
import { AuditLogger } from './audit-log.js';
import { generateId } from './types.js';

// =============================================================================
// ROLLBACK HANDLER
// =============================================================================

/**
 * Handler for a specific rollback type.
 */
export interface RollbackHandler {
  type: RollbackData['type'];
  execute(data: RollbackData): Promise<RollbackResult>;
  verify?(data: RollbackData): Promise<boolean>;
}

/**
 * File restore handler.
 */
export const fileRestoreHandler: RollbackHandler = {
  type: 'file_restore',

  async execute(data: RollbackData): Promise<RollbackResult> {
    if (data.type !== 'file_restore') {
      return { success: false, entryId: '', message: 'Invalid rollback type' };
    }

    // In production, would use fs.writeFile or fs.unlink
    if (data.originalContent === null) {
      // File was created, delete it
      console.log(`[ROLLBACK] Would delete file: ${data.path}`);
    } else {
      // File was modified, restore content
      console.log(`[ROLLBACK] Would restore file: ${data.path}`);
    }

    return {
      success: true,
      entryId: generateId(),
      message: `File ${data.path} restored`,
    };
  },

  async verify(data: RollbackData): Promise<boolean> {
    if (data.type !== 'file_restore') return false;

    // In production, would verify file state matches expected
    console.log(`[VERIFY] Would check file: ${data.path}`);
    return true;
  },
};

/**
 * Command undo handler.
 */
export const commandUndoHandler: RollbackHandler = {
  type: 'command_undo',

  async execute(data: RollbackData): Promise<RollbackResult> {
    if (data.type !== 'command_undo') {
      return { success: false, entryId: '', message: 'Invalid rollback type' };
    }

    // In production, would execute the undo command
    console.log(`[ROLLBACK] Would execute: ${data.undoCommand}`);

    return {
      success: true,
      entryId: generateId(),
      message: `Executed undo command`,
    };
  },
};

/**
 * Database restore handler.
 */
export const databaseRestoreHandler: RollbackHandler = {
  type: 'database_restore',

  async execute(data: RollbackData): Promise<RollbackResult> {
    if (data.type !== 'database_restore') {
      return { success: false, entryId: '', message: 'Invalid rollback type' };
    }

    // In production, would execute the restore query
    console.log(`[ROLLBACK] Would execute SQL: ${data.query}`);

    return {
      success: true,
      entryId: generateId(),
      message: 'Database restored',
    };
  },
};

/**
 * Config restore handler.
 */
export const configRestoreHandler: RollbackHandler = {
  type: 'config_restore',

  async execute(data: RollbackData): Promise<RollbackResult> {
    if (data.type !== 'config_restore') {
      return { success: false, entryId: '', message: 'Invalid rollback type' };
    }

    // In production, would restore the config value
    console.log(`[ROLLBACK] Would restore config ${data.key} to:`, data.previousValue);

    return {
      success: true,
      entryId: generateId(),
      message: `Config ${data.key} restored`,
    };
  },
};

/**
 * Custom rollback handler.
 */
export const customRollbackHandler: RollbackHandler = {
  type: 'custom',

  async execute(data: RollbackData): Promise<RollbackResult> {
    if (data.type !== 'custom') {
      return { success: false, entryId: '', message: 'Invalid rollback type' };
    }

    try {
      await data.handler();
      return {
        success: true,
        entryId: generateId(),
        message: data.description,
      };
    } catch (err) {
      return {
        success: false,
        entryId: '',
        message: `Rollback failed: ${err instanceof Error ? err.message : String(err)}`,
      };
    }
  },
};

// =============================================================================
// ROLLBACK MANAGER
// =============================================================================

/**
 * Manages rollback operations.
 */
export class RollbackManager {
  private handlers: Map<RollbackData['type'], RollbackHandler> = new Map();
  private auditLogger: AuditLogger;
  private listeners: Set<HILEventListener> = new Set();

  constructor(auditLogger: AuditLogger) {
    this.auditLogger = auditLogger;

    // Register default handlers
    this.registerHandler(fileRestoreHandler);
    this.registerHandler(commandUndoHandler);
    this.registerHandler(databaseRestoreHandler);
    this.registerHandler(configRestoreHandler);
    this.registerHandler(customRollbackHandler);
  }

  /**
   * Register a rollback handler.
   */
  registerHandler(handler: RollbackHandler): void {
    this.handlers.set(handler.type, handler);
  }

  /**
   * Check if an entry can be rolled back.
   */
  canRollback(entry: AuditEntry): boolean {
    if (!entry.reversible || !entry.rollbackData) {
      return false;
    }
    return this.handlers.has(entry.rollbackData.type);
  }

  /**
   * Execute a rollback.
   */
  async rollback(
    request: RollbackRequest,
    actor: AuditActor
  ): Promise<RollbackResult> {
    // Get the entry
    const entry = await this.auditLogger.getEntry(request.entryId);
    if (!entry) {
      return {
        success: false,
        entryId: request.entryId,
        message: 'Entry not found',
      };
    }

    // Check if rollback is possible
    if (!this.canRollback(entry)) {
      return {
        success: false,
        entryId: request.entryId,
        message: 'Entry cannot be rolled back',
      };
    }

    // Get handler
    const handler = this.handlers.get(entry.rollbackData!.type);
    if (!handler) {
      return {
        success: false,
        entryId: request.entryId,
        message: `No handler for rollback type: ${entry.rollbackData!.type}`,
      };
    }

    // Execute rollback
    try {
      const result = await handler.execute(entry.rollbackData!);

      // Log the rollback
      const auditEntry = await this.auditLogger.logRollback(
        entry,
        actor,
        result.success,
        result.message
      );

      result.newEntryId = auditEntry.id;

      // Emit event
      this.emit({
        type: 'action.rolled_back',
        entry,
        result,
      });

      // Verify if handler supports it
      if (result.success && handler.verify) {
        const verified = await handler.verify(entry.rollbackData!);
        if (!verified) {
          console.warn('Rollback verification failed');
        }
      }

      return result;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);

      // Log the failed rollback
      await this.auditLogger.logRollback(entry, actor, false, message);

      return {
        success: false,
        entryId: request.entryId,
        message: `Rollback failed: ${message}`,
      };
    }
  }

  /**
   * Rollback multiple entries in reverse order.
   */
  async rollbackChain(
    entryIds: string[],
    actor: AuditActor,
    reason: string
  ): Promise<RollbackResult[]> {
    const results: RollbackResult[] = [];

    // Rollback in reverse order
    for (const entryId of [...entryIds].reverse()) {
      const result = await this.rollback(
        { entryId, reason, requestedBy: actor.id },
        actor
      );
      results.push(result);

      // Stop on failure
      if (!result.success) {
        break;
      }
    }

    return results;
  }

  /**
   * Get rollback preview.
   */
  async preview(entryId: string): Promise<RollbackPreview | null> {
    const entry = await this.auditLogger.getEntry(entryId);
    if (!entry || !this.canRollback(entry)) {
      return null;
    }

    return {
      entry,
      rollbackData: entry.rollbackData!,
      description: this.describeRollback(entry.rollbackData!),
      affectedResources: this.getAffectedResources(entry.rollbackData!),
    };
  }

  /**
   * Describe what a rollback will do.
   */
  private describeRollback(data: RollbackData): string {
    switch (data.type) {
      case 'file_restore':
        return data.originalContent === null
          ? `Delete file: ${data.path}`
          : `Restore file: ${data.path}`;

      case 'command_undo':
        return `Execute: ${data.undoCommand}`;

      case 'database_restore':
        return `Execute SQL restore query`;

      case 'config_restore':
        return `Restore config ${data.key}`;

      case 'custom':
        return data.description;

      default:
        return 'Unknown rollback action';
    }
  }

  /**
   * Get resources affected by rollback.
   */
  private getAffectedResources(data: RollbackData): string[] {
    switch (data.type) {
      case 'file_restore':
        return [data.path];

      case 'config_restore':
        return [`config:${data.key}`];

      case 'database_restore':
        // Could parse the query to find tables
        return ['database'];

      default:
        return [];
    }
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
        console.error('Rollback manager listener error:', err);
      }
    }
  }
}

/**
 * Rollback preview information.
 */
export interface RollbackPreview {
  entry: AuditEntry;
  rollbackData: RollbackData;
  description: string;
  affectedResources: string[];
}

// =============================================================================
// ROLLBACK PLAN BUILDER
// =============================================================================

/**
 * Builds rollback plans for complex operations.
 */
export class RollbackPlanBuilder {
  private steps: RollbackStep[] = [];

  /**
   * Add a file restore step.
   */
  fileRestore(path: string, originalContent: string | null): RollbackPlanBuilder {
    this.steps.push({
      type: 'file_restore',
      data: { type: 'file_restore', path, originalContent },
    });
    return this;
  }

  /**
   * Add a command undo step.
   */
  commandUndo(undoCommand: string): RollbackPlanBuilder {
    this.steps.push({
      type: 'command_undo',
      data: { type: 'command_undo', undoCommand },
    });
    return this;
  }

  /**
   * Add a database restore step.
   */
  databaseRestore(query: string, params: unknown[]): RollbackPlanBuilder {
    this.steps.push({
      type: 'database_restore',
      data: { type: 'database_restore', query, params },
    });
    return this;
  }

  /**
   * Add a config restore step.
   */
  configRestore(key: string, previousValue: unknown): RollbackPlanBuilder {
    this.steps.push({
      type: 'config_restore',
      data: { type: 'config_restore', key, previousValue },
    });
    return this;
  }

  /**
   * Add a custom step.
   */
  custom(handler: () => Promise<void>, description: string): RollbackPlanBuilder {
    this.steps.push({
      type: 'custom',
      data: { type: 'custom', handler, description },
    });
    return this;
  }

  /**
   * Build the plan.
   */
  build(): RollbackPlan {
    return {
      steps: [...this.steps],
      totalSteps: this.steps.length,
    };
  }
}

/**
 * Single rollback step.
 */
interface RollbackStep {
  type: RollbackData['type'];
  data: RollbackData;
}

/**
 * Complete rollback plan.
 */
export interface RollbackPlan {
  steps: RollbackStep[];
  totalSteps: number;
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createRollbackManager(auditLogger: AuditLogger): RollbackManager {
  return new RollbackManager(auditLogger);
}

export function createRollbackPlanBuilder(): RollbackPlanBuilder {
  return new RollbackPlanBuilder();
}
