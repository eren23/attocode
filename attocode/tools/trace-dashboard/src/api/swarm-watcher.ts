/**
 * Swarm File Watcher
 *
 * Watches .agent/swarm-live/ for changes to events.jsonl and state.json,
 * emitting callbacks for the SSE route to push to connected clients.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';

export interface SwarmFileWatcherOptions {
  /** Directory containing events.jsonl and state.json */
  dir: string;
  /** Callback when new event lines are appended */
  onEvents: (lines: string[]) => void;
  /** Callback when state.json changes */
  onState: (state: unknown) => void;
  /** Callback when blackboard.json changes */
  onBlackboard?: (data: unknown) => void;
  /** Callback when codemap.json changes */
  onCodeMap?: (data: unknown) => void;
  /** Callback when budget-pool.json changes */
  onBudgetPool?: (data: unknown) => void;
  /** Poll interval in ms for checking new lines (default: 200) */
  pollIntervalMs?: number;
}

export class SwarmFileWatcher {
  private dir: string;
  private eventsPath: string;
  private statePath: string;
  private onEvents: (lines: string[]) => void;
  private onState: (state: unknown) => void;
  private onBlackboard?: (data: unknown) => void;
  private onCodeMap?: (data: unknown) => void;
  private onBudgetPool?: (data: unknown) => void;
  private pollIntervalMs: number;

  private eventsOffset = 0;
  private watcher: fs.FSWatcher | null = null;
  private stateWatcher: fs.FSWatcher | null = null;
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private closed = false;

  constructor(options: SwarmFileWatcherOptions) {
    this.dir = options.dir;
    this.eventsPath = path.join(options.dir, 'events.jsonl');
    this.statePath = path.join(options.dir, 'state.json');
    this.onEvents = options.onEvents;
    this.onState = options.onState;
    this.onBlackboard = options.onBlackboard;
    this.onCodeMap = options.onCodeMap;
    this.onBudgetPool = options.onBudgetPool;
    this.pollIntervalMs = options.pollIntervalMs ?? 200;
  }

  /**
   * Start watching files. Reads any existing content first.
   */
  start(sinceSeq?: number): void {
    // Read existing events to find offset.
    // When sinceSeq is 0 or undefined, replay ALL existing events so the dashboard
    // shows the full event feed (not just events arriving after connection).
    if (fs.existsSync(this.eventsPath)) {
      if (sinceSeq !== undefined && sinceSeq > 0) {
        // Read all lines, find the offset after the requested seq
        const content = fs.readFileSync(this.eventsPath, 'utf-8');
        const lines = content.split('\n').filter(Boolean);
        let targetOffset = 0;
        for (const line of lines) {
          targetOffset += Buffer.byteLength(line + '\n');
          try {
            const parsed = JSON.parse(line);
            if (parsed.seq > sinceSeq) {
              // We want lines from this point, but we've already skipped past
              // Re-read from the beginning of this line
              targetOffset -= Buffer.byteLength(line + '\n');
              break;
            }
          } catch {
            // Skip malformed lines
          }
        }
        this.eventsOffset = targetOffset;
      } else {
        // Start from the beginning — replay all existing events
        // so the Event Feed and Worker Timeline get the full history
        this.eventsOffset = 0;
      }
    }

    // Watch for changes with fs.watch
    try {
      if (fs.existsSync(this.dir)) {
        this.watcher = fs.watch(this.dir, (_eventType, filename) => {
          if (this.closed) return;
          if (filename === 'events.jsonl') {
            this.readNewEvents();
          } else if (filename === 'state.json') {
            this.readState();
          } else if (filename === 'blackboard.json') {
            this.readJsonFile('blackboard.json', this.onBlackboard);
          } else if (filename === 'codemap.json') {
            this.readJsonFile('codemap.json', this.onCodeMap);
          } else if (filename === 'budget-pool.json') {
            this.readJsonFile('budget-pool.json', this.onBudgetPool);
          }
        });
        this.watcher.on('error', () => {
          // Watcher error - fall back to polling only
        });
      }
    } catch {
      // Watcher setup failed - polling will cover it
    }

    // Also poll as backup (fs.watch can be unreliable on some platforms)
    this.pollTimer = setInterval(() => {
      if (this.closed) return;
      this.readNewEvents();
    }, this.pollIntervalMs);

    // Read initial state and snapshots
    this.readState();
    this.readJsonFile('blackboard.json', this.onBlackboard);
    this.readJsonFile('codemap.json', this.onCodeMap);
    this.readJsonFile('budget-pool.json', this.onBudgetPool);
  }

  /**
   * Read new event lines since last offset.
   */
  private readNewEvents(): void {
    try {
      if (!fs.existsSync(this.eventsPath)) return;

      const stats = fs.statSync(this.eventsPath);
      if (stats.size <= this.eventsOffset) return;

      const fd = fs.openSync(this.eventsPath, 'r');
      const buf = Buffer.alloc(stats.size - this.eventsOffset);
      fs.readSync(fd, buf, 0, buf.length, this.eventsOffset);
      fs.closeSync(fd);

      this.eventsOffset = stats.size;

      const chunk = buf.toString('utf-8');
      const lines = chunk.split('\n').filter(Boolean);

      if (lines.length > 0) {
        this.onEvents(lines);
      }
    } catch {
      // File may be in mid-write; retry on next poll
    }
  }

  /**
   * Read state.json.
   */
  private readState(): void {
    try {
      if (!fs.existsSync(this.statePath)) return;

      const content = fs.readFileSync(this.statePath, 'utf-8');
      const state = JSON.parse(content);
      this.onState(state);
    } catch {
      // File may be in mid-write; retry on next poll
    }
  }

  /**
   * Read a JSON snapshot file and invoke its callback.
   */
  private readJsonFile(filename: string, callback?: (data: unknown) => void): void {
    if (!callback) return;
    try {
      const filePath = path.join(this.dir, filename);
      if (!fs.existsSync(filePath)) return;
      const content = fs.readFileSync(filePath, 'utf-8');
      const data = JSON.parse(content);
      callback(data);
    } catch {
      // File may be in mid-write; retry on next change
    }
  }

  /**
   * Stop watching and clean up.
   */
  close(): void {
    this.closed = true;
    if (this.watcher) {
      this.watcher.close();
      this.watcher = null;
    }
    if (this.stateWatcher) {
      this.stateWatcher.close();
      this.stateWatcher = null;
    }
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }
}

/**
 * Auto-detect the swarm-live directory.
 * Searches common locations relative to the project root,
 * supports SWARM_LIVE_DIR env var override, and scans sibling project dirs.
 * Returns null if no directory is found (instead of fabricating a path).
 */
export function findSwarmLiveDir(): string | null {
  // Env var override takes priority
  if (process.env.SWARM_LIVE_DIR) {
    const envDir = path.resolve(process.env.SWARM_LIVE_DIR);
    if (fs.existsSync(envDir)) return envDir;
  }

  const candidates: string[] = [
    path.join(process.cwd(), '.agent/swarm-live'),  // explicit CWD
    '.agent/swarm-live',                             // relative CWD
    '../../.agent/swarm-live',                       // attocode root from tools/trace-dashboard
    '../../../.agent/swarm-live',                    // first-principles-agent from tools/trace-dashboard
    '../../../../.agent/swarm-live',                 // AI/ dir from tools/trace-dashboard
  ];

  // Scan sibling project directories at multiple ancestor levels
  // From tools/trace-dashboard/:
  //   ../../..  = first-principles-agent/  (siblings of attocode)
  //   ../../../.. = AI/                    (siblings of first-principles-agent, e.g. attocode_swarm_tester)
  const ancestorLevels = ['../../..', '../../../..'];
  for (const level of ancestorLevels) {
    try {
      const ancestor = path.resolve(level);
      const entries = fs.readdirSync(ancestor, { withFileTypes: true });
      for (const entry of entries) {
        if (entry.isDirectory() && !entry.name.startsWith('.')) {
          candidates.push(path.join(ancestor, entry.name, '.agent/swarm-live'));
        }
      }
    } catch { /* ignore read errors */ }
  }

  const existing = candidates
    .map(candidate => path.resolve(candidate))
    .filter((resolved, idx, arr) => arr.indexOf(resolved) === idx)
    .filter(resolved => fs.existsSync(resolved));

  if (existing.length === 0) return null;

  // Prefer the most recently-updated swarm state to avoid stale project auto-selection.
  const ranked = existing
    .map((dirPath) => {
      const statePath = path.join(dirPath, 'state.json');
      let score = 0;
      try {
        if (fs.existsSync(statePath)) {
          const stateRaw = fs.readFileSync(statePath, 'utf-8');
          const state = JSON.parse(stateRaw) as { updatedAt?: string; active?: boolean; lastSeq?: number };
          if (state.updatedAt) {
            const ts = Date.parse(state.updatedAt);
            if (!Number.isNaN(ts)) score = ts;
          } else {
            score = fs.statSync(statePath).mtimeMs;
          }
          if (state.active) score += 10_000;
          if ((state.lastSeq ?? 0) > 0) score += Math.min(5_000, state.lastSeq ?? 0);
        } else {
          score = fs.statSync(dirPath).mtimeMs;
        }
      } catch {
        score = 0;
      }
      return { dirPath, score };
    })
    .sort((a, b) => b.score - a.score);

  return ranked[0]?.dirPath ?? null;
}

/**
 * Discover ALL swarm-live directories (not just the first match).
 * Returns an array of { path, label } where label is a human-friendly project name.
 * Also checks SWARM_EXTRA_DIRS env var (colon-separated absolute paths).
 */
export function findAllSwarmLiveDirs(): Array<{ path: string; label: string }> {
  const found = new Map<string, string>(); // resolved path → label

  // Helper to add a candidate if it exists
  const tryAdd = (candidate: string, labelOverride?: string) => {
    const resolved = path.resolve(candidate);
    if (found.has(resolved)) return;
    if (fs.existsSync(resolved)) {
      const label = labelOverride ?? labelFromPath(resolved);
      found.set(resolved, label);
    }
  };

  // Env var override paths
  if (process.env.SWARM_LIVE_DIR) {
    tryAdd(process.env.SWARM_LIVE_DIR);
  }

  // Extra dirs from env (colon-separated)
  if (process.env.SWARM_EXTRA_DIRS) {
    for (const dir of process.env.SWARM_EXTRA_DIRS.split(':').filter(Boolean)) {
      tryAdd(dir.trim());
    }
  }

  // Static candidates
  const candidates = [
    path.join(process.cwd(), '.agent/swarm-live'),
    '.agent/swarm-live',
    '../../.agent/swarm-live',
    '../../../.agent/swarm-live',
    '../../../../.agent/swarm-live',
  ];
  for (const c of candidates) tryAdd(c);

  // Scan sibling project directories at multiple ancestor levels
  const ancestorLevels = ['../../..', '../../../..'];
  for (const level of ancestorLevels) {
    try {
      const ancestor = path.resolve(level);
      const entries = fs.readdirSync(ancestor, { withFileTypes: true });
      for (const entry of entries) {
        if (entry.isDirectory() && !entry.name.startsWith('.')) {
          tryAdd(path.join(ancestor, entry.name, '.agent/swarm-live'));
        }
      }
    } catch { /* ignore read errors */ }
  }

  return Array.from(found.entries())
    .map(([p, label]) => {
      let updatedAtMs = 0;
      try {
        const statePath = path.join(p, 'state.json');
        if (fs.existsSync(statePath)) {
          const raw = fs.readFileSync(statePath, 'utf-8');
          const state = JSON.parse(raw) as { updatedAt?: string };
          if (state.updatedAt) {
            const parsed = Date.parse(state.updatedAt);
            if (!Number.isNaN(parsed)) updatedAtMs = parsed;
          } else {
            updatedAtMs = fs.statSync(statePath).mtimeMs;
          }
        } else {
          updatedAtMs = fs.statSync(p).mtimeMs;
        }
      } catch {
        updatedAtMs = 0;
      }
      return { path: p, label, updatedAtMs };
    })
    .sort((a, b) => b.updatedAtMs - a.updatedAtMs)
    .map(({ path, label }) => ({ path, label }));
}

/**
 * Derive a human-friendly label from a swarm-live directory path.
 * Takes the project directory name (parent of .agent/).
 */
function labelFromPath(swarmLivePath: string): string {
  // swarmLivePath is like /foo/bar/project-name/.agent/swarm-live
  const parts = swarmLivePath.split(path.sep);
  // Find '.agent' and take the segment before it
  const agentIdx = parts.lastIndexOf('.agent');
  if (agentIdx > 0) {
    return parts[agentIdx - 1];
  }
  // Fallback: last 2 meaningful segments
  return parts.filter(Boolean).slice(-3, -1).join('/');
}

/**
 * Validate and resolve a user-provided swarm-live directory path.
 * If dir is provided and valid, returns it. Otherwise falls back to findSwarmLiveDir().
 */
export function resolveSwarmDir(dir?: string): string | null {
  if (dir) {
    const resolved = path.resolve(dir);
    if (fs.existsSync(resolved) && fs.statSync(resolved).isDirectory()) {
      return resolved;
    }
    // Invalid path — fall through to default
  }
  return findSwarmLiveDir();
}
