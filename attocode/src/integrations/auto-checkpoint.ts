/**
 * Auto-Checkpoint Resumption
 *
 * Saves lightweight checkpoints at key execution points so that
 * work can be recovered if the agent crashes or times out.
 *
 * Key points where checkpoints are saved:
 * - After each tool batch execution
 * - Before LLM calls (so the prompt is recoverable)
 * - After significant state changes (plan approval, mode switch)
 *
 * On startup, detects recent sessions (<5 min) and offers auto-resume.
 */

import { writeFileSync, readFileSync, mkdirSync, existsSync, readdirSync, statSync, unlinkSync } from 'node:fs';
import { join } from 'node:path';

// =============================================================================
// TYPES
// =============================================================================

export interface Checkpoint {
  /** Unique checkpoint ID */
  id: string;
  /** Label describing the checkpoint point */
  label: string;
  /** Session ID this checkpoint belongs to */
  sessionId: string;
  /** Timestamp of the checkpoint */
  timestamp: number;
  /** Agent iteration count at this point */
  iteration: number;
  /** Messages up to this point (serialized) */
  messages?: unknown[];
  /** Current objective/task */
  objective?: string;
  /** Current mode */
  mode?: string;
  /** Files modified since last checkpoint */
  filesModified?: string[];
  /** Token usage at this point */
  tokensUsed?: number;
  /** Tool call history summary */
  toolCallSummary?: string;
  /** Custom metadata */
  metadata?: Record<string, unknown>;
}

export interface AutoCheckpointConfig {
  /** Directory for checkpoint storage (default: '.agent/checkpoints') */
  checkpointDir: string;
  /** Maximum checkpoints to keep per session (default: 10) */
  maxCheckpointsPerSession: number;
  /** Auto-cleanup checkpoints older than this (ms, default: 3600000 = 1hr) */
  maxAge: number;
  /** Whether checkpointing is enabled (default: true) */
  enabled: boolean;
  /** Minimum interval between checkpoints (ms, default: 30000) */
  minInterval: number;
}

export interface ResumeCandidate {
  /** Session ID */
  sessionId: string;
  /** Most recent checkpoint */
  checkpoint: Checkpoint;
  /** Age of the checkpoint in ms */
  ageMs: number;
  /** Number of checkpoints available */
  checkpointCount: number;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const DEFAULT_CONFIG: AutoCheckpointConfig = {
  checkpointDir: '.agent/checkpoints',
  maxCheckpointsPerSession: 10,
  maxAge: 3600000, // 1 hour
  enabled: true,
  minInterval: 30000, // 30 seconds
};

// =============================================================================
// AUTO-CHECKPOINT MANAGER
// =============================================================================

export class AutoCheckpointManager {
  private config: AutoCheckpointConfig;
  private lastCheckpointTime = 0;
  private checkpointCount = 0;

  constructor(config?: Partial<AutoCheckpointConfig>) {
    this.config = { ...DEFAULT_CONFIG, ...config };

    if (this.config.enabled) {
      try {
        mkdirSync(this.config.checkpointDir, { recursive: true });
      } catch {
        // Directory creation may fail
      }
    }
  }

  /**
   * Save a checkpoint at a key execution point.
   * Respects minInterval to avoid excessive I/O.
   */
  save(checkpoint: Omit<Checkpoint, 'id' | 'timestamp'>): string | null {
    if (!this.config.enabled) return null;

    const now = Date.now();
    if (now - this.lastCheckpointTime < this.config.minInterval) {
      return null; // Too soon since last checkpoint
    }

    const id = `ckpt-${now}-${Math.random().toString(36).slice(2, 6)}`;
    const fullCheckpoint: Checkpoint = {
      ...checkpoint,
      id,
      timestamp: now,
    };

    try {
      const sessionDir = join(this.config.checkpointDir, checkpoint.sessionId);
      mkdirSync(sessionDir, { recursive: true });

      const filePath = join(sessionDir, `${id}.json`);

      // Don't persist full messages array to save space - just metadata
      const persistable = {
        ...fullCheckpoint,
        messages: undefined, // Strip messages to keep checkpoints small
        _messageCount: fullCheckpoint.messages?.length ?? 0,
      };

      writeFileSync(filePath, JSON.stringify(persistable, null, 2), 'utf-8');

      this.lastCheckpointTime = now;
      this.checkpointCount++;

      // Cleanup old checkpoints for this session
      this.cleanupSession(checkpoint.sessionId);

      return id;
    } catch {
      return null;
    }
  }

  /**
   * Load a specific checkpoint.
   */
  load(sessionId: string, checkpointId: string): Checkpoint | null {
    try {
      const filePath = join(this.config.checkpointDir, sessionId, `${checkpointId}.json`);
      const content = readFileSync(filePath, 'utf-8');
      return JSON.parse(content) as Checkpoint;
    } catch {
      return null;
    }
  }

  /**
   * Find sessions with recent checkpoints that could be resumed.
   */
  findResumeCandidates(maxAgeMs?: number): ResumeCandidate[] {
    const maxAge = maxAgeMs ?? 300000; // Default: 5 minutes
    const now = Date.now();
    const candidates: ResumeCandidate[] = [];

    try {
      if (!existsSync(this.config.checkpointDir)) return [];

      const sessions = readdirSync(this.config.checkpointDir);

      for (const sessionId of sessions) {
        const sessionDir = join(this.config.checkpointDir, sessionId);
        try {
          const stat = statSync(sessionDir);
          if (!stat.isDirectory()) continue;
        } catch {
          continue;
        }

        const checkpoints = this.loadSessionCheckpoints(sessionId);
        if (checkpoints.length === 0) continue;

        // Most recent checkpoint
        const latest = checkpoints[checkpoints.length - 1];
        const age = now - latest.timestamp;

        if (age <= maxAge) {
          candidates.push({
            sessionId,
            checkpoint: latest,
            ageMs: age,
            checkpointCount: checkpoints.length,
          });
        }
      }
    } catch {
      // Directory reading may fail
    }

    // Sort by recency (most recent first)
    return candidates.sort((a, b) => a.ageMs - b.ageMs);
  }

  /**
   * Load all checkpoints for a session, sorted by timestamp.
   */
  loadSessionCheckpoints(sessionId: string): Checkpoint[] {
    const sessionDir = join(this.config.checkpointDir, sessionId);
    const checkpoints: Checkpoint[] = [];

    try {
      if (!existsSync(sessionDir)) return [];

      const files = readdirSync(sessionDir).filter(f => f.endsWith('.json'));

      for (const file of files) {
        try {
          const content = readFileSync(join(sessionDir, file), 'utf-8');
          checkpoints.push(JSON.parse(content) as Checkpoint);
        } catch {
          // Skip malformed checkpoints
        }
      }
    } catch {
      return [];
    }

    return checkpoints.sort((a, b) => a.timestamp - b.timestamp);
  }

  /**
   * Get a summary of a checkpoint for display.
   */
  formatCheckpointSummary(checkpoint: Checkpoint): string {
    const age = Date.now() - checkpoint.timestamp;
    const ageStr = age < 60000
      ? `${Math.round(age / 1000)}s ago`
      : `${Math.round(age / 60000)}m ago`;

    const lines: string[] = [
      `Session: ${checkpoint.sessionId}`,
      `Checkpoint: ${checkpoint.label} (${ageStr})`,
      `Iteration: ${checkpoint.iteration}`,
    ];

    if (checkpoint.objective) {
      lines.push(`Objective: ${checkpoint.objective.slice(0, 100)}`);
    }

    if (checkpoint.tokensUsed) {
      lines.push(`Tokens used: ${checkpoint.tokensUsed}`);
    }

    if (checkpoint.filesModified && checkpoint.filesModified.length > 0) {
      lines.push(`Files modified: ${checkpoint.filesModified.join(', ')}`);
    }

    return lines.join('\n');
  }

  /**
   * Clean up old checkpoints globally.
   */
  cleanupAll(): number {
    let cleaned = 0;
    const now = Date.now();

    try {
      if (!existsSync(this.config.checkpointDir)) return 0;

      const sessions = readdirSync(this.config.checkpointDir);

      for (const sessionId of sessions) {
        const sessionDir = join(this.config.checkpointDir, sessionId);
        try {
          const stat = statSync(sessionDir);
          if (!stat.isDirectory()) continue;
        } catch {
          continue;
        }

        const checkpoints = this.loadSessionCheckpoints(sessionId);
        for (const ckpt of checkpoints) {
          if (now - ckpt.timestamp > this.config.maxAge) {
            try {
              unlinkSync(join(sessionDir, `${ckpt.id}.json`));
              cleaned++;
            } catch {
              // Deletion may fail
            }
          }
        }
      }
    } catch {
      // Directory operations may fail
    }

    return cleaned;
  }

  // ===========================================================================
  // INTERNAL
  // ===========================================================================

  private cleanupSession(sessionId: string): void {
    const checkpoints = this.loadSessionCheckpoints(sessionId);

    if (checkpoints.length > this.config.maxCheckpointsPerSession) {
      // Remove oldest checkpoints
      const toRemove = checkpoints.slice(0, checkpoints.length - this.config.maxCheckpointsPerSession);
      const sessionDir = join(this.config.checkpointDir, sessionId);

      for (const ckpt of toRemove) {
        try {
          unlinkSync(join(sessionDir, `${ckpt.id}.json`));
        } catch {
          // Deletion may fail
        }
      }
    }
  }
}

/**
 * Create an auto-checkpoint manager.
 */
export function createAutoCheckpointManager(
  config?: Partial<AutoCheckpointConfig>,
): AutoCheckpointManager {
  return new AutoCheckpointManager(config);
}
