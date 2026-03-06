/**
 * Swarm Live API Routes
 *
 * SSE streaming + REST endpoints for the live swarm dashboard.
 */

import { Hono } from 'hono';
import { streamSSE } from 'hono/streaming';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { SwarmFileWatcher, findAllSwarmLiveDirs, resolveSwarmDir } from '../swarm-watcher.js';

export const swarmLiveRoutes = new Hono();

/**
 * GET /dirs — List all discovered swarm-live directories
 */
swarmLiveRoutes.get('/dirs', (c) => {
  try {
    const dirs = findAllSwarmLiveDirs();
    return c.json({ success: true, data: dirs });
  } catch (err) {
    console.error('Failed to list swarm dirs:', err);
    return c.json({ success: false, error: 'Failed to list swarm dirs' }, 500);
  }
});

/**
 * GET /state?dir= — Read current state.json
 */
swarmLiveRoutes.get('/state', (c) => {
  try {
    const dir = resolveSwarmDir(c.req.query('dir'));
    if (!dir) {
      return c.json({ success: true, data: null });
    }

    const statePath = path.join(dir, 'state.json');
    if (!fs.existsSync(statePath)) {
      return c.json({ success: true, data: null });
    }

    const content = fs.readFileSync(statePath, 'utf-8');
    const state = JSON.parse(content);
    return c.json({ success: true, data: state });
  } catch (err) {
    console.error('Failed to read swarm state:', err);
    return c.json({ success: false, error: 'Failed to read swarm state' }, 500);
  }
});

/**
 * GET /stream?since=<seq>&dir= — SSE endpoint for live events
 *
 * When the swarm-live directory doesn't exist yet, sends an idle state
 * and polls for directory creation instead of returning a 404.
 */
swarmLiveRoutes.get('/stream', (c) => {
  const sinceStr = c.req.query('since');
  const sinceSeq = sinceStr ? parseInt(sinceStr, 10) : undefined;
  const dirParam = c.req.query('dir');

  return streamSSE(c, async (stream) => {
    let eventId = 0;
    let dir = resolveSwarmDir(dirParam);

    // If no directory found, send idle state and poll for creation
    if (!dir) {
      await stream.writeSSE({
        event: 'swarm-state',
        data: JSON.stringify({ active: false, idle: true, updatedAt: new Date().toISOString() }),
        id: String(++eventId),
      });

      // Poll for directory creation every 3 seconds
      const dirPoll = setInterval(() => {
        const found = resolveSwarmDir(dirParam);
        if (found) {
          dir = found;
          clearInterval(dirPoll);
          startWatching(dir);
        }
      }, 3000);

      // Heartbeat to keep SSE alive while waiting
      const idleHeartbeat = setInterval(() => {
        stream.writeSSE({
          event: 'heartbeat',
          data: JSON.stringify({ ts: new Date().toISOString() }),
          id: String(++eventId),
        }).catch(() => {
          clearInterval(idleHeartbeat);
          clearInterval(dirPoll);
        });
      }, 15_000);

      stream.onAbort(() => {
        clearInterval(idleHeartbeat);
        clearInterval(dirPoll);
      });

      // Keep stream open until aborted
      await new Promise<void>((resolve) => {
        stream.onAbort(() => resolve());
      });
      return;
    }

    // Directory exists — start watching immediately
    startWatching(dir);

    function startWatching(watchDir: string): void {
      // Send initial state
      try {
        const statePath = path.join(watchDir, 'state.json');
        if (fs.existsSync(statePath)) {
          const content = fs.readFileSync(statePath, 'utf-8');
          const state = JSON.parse(content);
          stream.writeSSE({
            event: 'swarm-state',
            data: JSON.stringify(state),
            id: String(++eventId),
          }).catch(() => { /* client disconnected */ });
        }
      } catch {
        // No initial state available
      }

      // Start file watcher
      const watcher = new SwarmFileWatcher({
        dir: watchDir,
        onEvents: (lines) => {
          for (const line of lines) {
            stream.writeSSE({
              event: 'swarm-event',
              data: line,
              id: String(++eventId),
            }).catch(() => {
              watcher.close();
            });
          }
        },
        onState: (state) => {
          stream.writeSSE({
            event: 'swarm-state',
            data: JSON.stringify(state),
            id: String(++eventId),
          }).catch(() => {
            watcher.close();
          });
        },
        onBlackboard: (data) => {
          stream.writeSSE({
            event: 'swarm-blackboard',
            data: JSON.stringify(data),
            id: String(++eventId),
          }).catch(() => { watcher.close(); });
        },
        onCodeMap: (data) => {
          stream.writeSSE({
            event: 'swarm-codemap',
            data: JSON.stringify(data),
            id: String(++eventId),
          }).catch(() => { watcher.close(); });
        },
        onBudgetPool: (data) => {
          stream.writeSSE({
            event: 'swarm-budget-pool',
            data: JSON.stringify(data),
            id: String(++eventId),
          }).catch(() => { watcher.close(); });
        },
      });

      watcher.start(sinceSeq);

      // Heartbeat every 15s
      const heartbeat = setInterval(() => {
        stream.writeSSE({
          event: 'heartbeat',
          data: JSON.stringify({ ts: new Date().toISOString() }),
          id: String(++eventId),
        }).catch(() => {
          clearInterval(heartbeat);
          watcher.close();
        });
      }, 15_000);

      stream.onAbort(() => {
        clearInterval(heartbeat);
        watcher.close();
      });
    }

    // Keep the stream open until aborted
    await new Promise<void>((resolve) => {
      stream.onAbort(() => resolve());
    });
  });
});

/**
 * GET /tasks?dir= — Return task list with dependency edges
 */
swarmLiveRoutes.get('/tasks', (c) => {
  try {
    const dir = resolveSwarmDir(c.req.query('dir'));
    if (!dir) {
      return c.json({ success: true, data: { tasks: [], edges: [] } });
    }

    const statePath = path.join(dir, 'state.json');
    if (!fs.existsSync(statePath)) {
      return c.json({ success: true, data: { tasks: [], edges: [] } });
    }

    const content = fs.readFileSync(statePath, 'utf-8');
    const state = JSON.parse(content);
    return c.json({
      success: true,
      data: {
        tasks: state.tasks ?? [],
        edges: state.edges ?? [],
      },
    });
  } catch (err) {
    console.error('Failed to read swarm tasks:', err);
    return c.json({ success: false, error: 'Failed to read tasks' }, 500);
  }
});

/**
 * GET /task/:taskId?dir= — Read detailed task output (worker output, quality feedback, closure report)
 */
swarmLiveRoutes.get('/task/:taskId', (c) => {
  try {
    const dir = resolveSwarmDir(c.req.query('dir'));
    if (!dir) {
      return c.json({ success: true, data: null });
    }

    const taskId = c.req.param('taskId');
    const taskFile = path.join(dir, 'tasks', `${taskId}.json`);
    if (!fs.existsSync(taskFile)) {
      return c.json({ success: true, data: null });
    }

    const content = fs.readFileSync(taskFile, 'utf-8');
    const detail = JSON.parse(content);
    return c.json({ success: true, data: detail });
  } catch (err) {
    console.error('Failed to read task detail:', err);
    return c.json({ success: false, error: 'Failed to read task detail' }, 500);
  }
});

/**
 * GET /history?dir= — List archived swarm event logs
 */
swarmLiveRoutes.get('/history', (c) => {
  try {
    const dir = resolveSwarmDir(c.req.query('dir'));
    if (!dir || !fs.existsSync(dir)) {
      return c.json({ success: true, data: [] });
    }

    const files = fs.readdirSync(dir)
      .filter((f) => f.startsWith('events-') && f.endsWith('.jsonl'))
      .map((f) => {
        const stats = fs.statSync(path.join(dir, f));
        const tsMatch = f.match(/events-(\d+)\.jsonl/);
        return {
          filename: f,
          timestamp: tsMatch ? new Date(parseInt(tsMatch[1], 10)).toISOString() : null,
          sizeBytes: stats.size,
        };
      })
      .sort((a, b) => (b.timestamp ?? '').localeCompare(a.timestamp ?? ''));

    return c.json({ success: true, data: files });
  } catch (err) {
    console.error('Failed to list swarm history:', err);
    return c.json({ success: false, error: 'Failed to list history' }, 500);
  }
});

// =============================================================================
// OBSERVABILITY SNAPSHOT ENDPOINTS
// =============================================================================

/**
 * GET /codemap?dir= — Read codemap.json snapshot
 */
swarmLiveRoutes.get('/codemap', (c) => {
  try {
    const dir = resolveSwarmDir(c.req.query('dir'));
    if (!dir) {
      return c.json({ success: false, error: 'No swarm-live directory found' }, 404);
    }
    const filePath = path.join(dir, 'codemap.json');
    if (!fs.existsSync(filePath)) {
      return c.json({ success: false, error: 'No codemap.json found' }, 404);
    }
    const data = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
    return c.json({ success: true, data });
  } catch (err) {
    console.error('Failed to read codemap:', err);
    return c.json({ success: false, error: 'Failed to read codemap' }, 500);
  }
});

/**
 * GET /blackboard?dir= — Read blackboard.json snapshot
 */
swarmLiveRoutes.get('/blackboard', (c) => {
  try {
    const dir = resolveSwarmDir(c.req.query('dir'));
    if (!dir) {
      return c.json({ success: false, error: 'No swarm-live directory found' }, 404);
    }
    const filePath = path.join(dir, 'blackboard.json');
    if (!fs.existsSync(filePath)) {
      return c.json({ success: false, error: 'No blackboard.json found' }, 404);
    }
    const data = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
    return c.json({ success: true, data });
  } catch (err) {
    console.error('Failed to read blackboard:', err);
    return c.json({ success: false, error: 'Failed to read blackboard' }, 500);
  }
});

/**
 * GET /budget-pool?dir= — Read budget-pool.json snapshot
 */
swarmLiveRoutes.get('/budget-pool', (c) => {
  try {
    const dir = resolveSwarmDir(c.req.query('dir'));
    if (!dir) {
      return c.json({ success: false, error: 'No swarm-live directory found' }, 404);
    }
    const filePath = path.join(dir, 'budget-pool.json');
    if (!fs.existsSync(filePath)) {
      return c.json({ success: false, error: 'No budget-pool.json found' }, 404);
    }
    const data = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
    return c.json({ success: true, data });
  } catch (err) {
    console.error('Failed to read budget-pool:', err);
    return c.json({ success: false, error: 'Failed to read budget-pool' }, 500);
  }
});
