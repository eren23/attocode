/**
 * Swarm State Store
 *
 * Persistence layer for swarm checkpoints.
 * Saves/loads serialized swarm state to allow resume after interruption.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import type { SwarmCheckpoint } from './types.js';
import type { PersistenceAdapter } from '../../shared/persistence.js';

// ─── Map Serialization ───────────────────────────────────────────────────

/** JSON replacer that serializes Maps as { __type: 'Map', entries: [...] } */
function mapReplacer(_key: string, value: unknown): unknown {
  if (value instanceof Map) {
    return { __type: 'Map', entries: [...value.entries()] };
  }
  return value;
}

/** JSON reviver that deserializes Maps from { __type: 'Map', entries: [...] } */
function mapReviver(_key: string, value: unknown): unknown {
  if (value && typeof value === 'object' && (value as Record<string, unknown>).__type === 'Map') {
    return new Map((value as { entries: [unknown, unknown][] }).entries);
  }
  return value;
}

// ─── State Store ──────────────────────────────────────────────────────────

export class SwarmStateStore {
  private stateDir: string;
  private sessionId: string;
  private sessionDir: string;
  private checkpointCount = 0;
  private adapter?: PersistenceAdapter;

  constructor(stateDir: string, sessionId?: string, adapter?: PersistenceAdapter) {
    this.stateDir = stateDir;
    this.sessionId = sessionId ?? `swarm-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    this.sessionDir = path.join(stateDir, this.sessionId);
    this.adapter = adapter;
    // Resume: start numbering after existing checkpoints to avoid overwriting
    try {
      const files = fs.readdirSync(this.sessionDir).filter(f => f.startsWith('checkpoint-'));
      this.checkpointCount = files.length;
    } catch { /* dir doesn't exist yet */ }
  }

  get id(): string {
    return this.sessionId;
  }

  /**
   * Save a checkpoint. Writes both a numbered file and latest.json.
   * When a PersistenceAdapter is configured, also saves via the adapter.
   */
  saveCheckpoint(checkpoint: SwarmCheckpoint): void {
    fs.mkdirSync(this.sessionDir, { recursive: true });

    const data = JSON.stringify(checkpoint, mapReplacer, 2);

    // Write numbered checkpoint
    this.checkpointCount++;
    const numberedPath = path.join(this.sessionDir, `checkpoint-${String(this.checkpointCount).padStart(3, '0')}.json`);
    fs.writeFileSync(numberedPath, data);

    // Write latest.json (overwrites)
    const latestPath = path.join(this.sessionDir, 'latest.json');
    fs.writeFileSync(latestPath, data);

    // Also persist via adapter (fire-and-forget, non-blocking)
    if (this.adapter) {
      this.adapter.save('swarm-checkpoints', this.sessionId, checkpoint).catch(() => {});
    }
  }

  /**
   * Load the latest checkpoint for a given session.
   */
  static loadLatest(stateDir: string, sessionId: string): SwarmCheckpoint | null {
    const latestPath = path.join(stateDir, sessionId, 'latest.json');
    try {
      const data = fs.readFileSync(latestPath, 'utf-8');
      return JSON.parse(data, mapReviver) as SwarmCheckpoint;
    } catch {
      return null;
    }
  }

  /**
   * List all swarm sessions sorted by most recent first.
   */
  static listSessions(stateDir: string): Array<{ sessionId: string; lastModified: number }> {
    try {
      const entries = fs.readdirSync(stateDir, { withFileTypes: true });
      const sessions: Array<{ sessionId: string; lastModified: number }> = [];

      for (const entry of entries) {
        if (!entry.isDirectory()) continue;
        const latestPath = path.join(stateDir, entry.name, 'latest.json');
        try {
          const stat = fs.statSync(latestPath);
          sessions.push({ sessionId: entry.name, lastModified: stat.mtimeMs });
        } catch {
          // No latest.json — skip
        }
      }

      return sessions.sort((a, b) => b.lastModified - a.lastModified);
    } catch {
      return [];
    }
  }
}
