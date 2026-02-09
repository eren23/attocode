/**
 * Sessions API Routes
 */

import { Hono } from 'hono';
import {
  getSessions,
  getSessionSummary,
  getSessionTimeline,
  getSessionTree,
  getSessionTokens,
  getSessionIssues,
  getSessionRaw,
  getSessionParsed,
  uploadTrace,
  uploadTraceInMemory,
  getUploadedTraces,
} from '../trace-service.js';
import { HTMLGenerator, createJSONExporter } from '../../lib/index.js';

export const sessionsRoutes = new Hono();

// List all sessions
sessionsRoutes.get('/', async (c) => {
  try {
    const sessions = await getSessions();
    return c.json({ success: true, data: sessions });
  } catch (err) {
    console.error('Failed to list sessions:', err);
    return c.json({ success: false, error: 'Failed to list sessions' }, 500);
  }
});

// Upload a trace file (saves to disk)
sessionsRoutes.post('/upload', async (c) => {
  try {
    const body = await c.req.json();
    const { content, filename } = body;

    if (!content) {
      return c.json({ success: false, error: 'Missing content field' }, 400);
    }

    const result = await uploadTrace(content, filename);
    return c.json({ success: true, data: result });
  } catch (err) {
    console.error('Failed to upload trace:', err);
    return c.json({ success: false, error: 'Failed to upload trace. Ensure valid JSONL format.' }, 400);
  }
});

// Upload a trace (in-memory only, for quick analysis)
sessionsRoutes.post('/upload-memory', async (c) => {
  try {
    const body = await c.req.json();
    const { content, name } = body;

    if (!content) {
      return c.json({ success: false, error: 'Missing content field' }, 400);
    }

    const result = await uploadTraceInMemory(content, name);
    return c.json({ success: true, data: result });
  } catch (err) {
    console.error('Failed to upload trace:', err);
    return c.json({ success: false, error: 'Failed to parse trace. Ensure valid JSONL format.' }, 400);
  }
});

// List uploaded traces
sessionsRoutes.get('/uploaded', async (c) => {
  try {
    const uploaded = getUploadedTraces();
    return c.json({ success: true, data: uploaded });
  } catch (err) {
    console.error('Failed to list uploaded traces:', err);
    return c.json({ success: false, error: 'Failed to list uploaded traces' }, 500);
  }
});

// Batch export multiple sessions (must be before /:id to avoid wildcard match)
sessionsRoutes.get('/export/batch', async (c) => {
  try {
    const idsParam = c.req.query('ids');
    const format = c.req.query('format') || 'json';

    if (!idsParam) {
      return c.json({ success: false, error: 'Missing ids query parameter' }, 400);
    }

    const ids = idsParam.split(',').map(id => id.trim());
    const results: Array<Record<string, unknown>> = [];

    for (const id of ids) {
      const session = await getSessionParsed(decodeURIComponent(id));
      if (!session) continue;

      results.push({
        sessionId: session.sessionId,
        task: session.task,
        model: session.model,
        status: session.status,
        startTime: session.startTime.toISOString(),
        durationMs: session.durationMs,
        iterations: session.metrics.iterations,
        inputTokens: session.metrics.inputTokens,
        outputTokens: session.metrics.outputTokens,
        totalCost: session.metrics.totalCost,
        cacheHitRate: session.metrics.avgCacheHitRate,
        errors: session.metrics.errors,
      });
    }

    if (format === 'csv') {
      const headers = ['sessionId', 'task', 'model', 'status', 'startTime', 'durationMs', 'iterations', 'inputTokens', 'outputTokens', 'totalCost', 'cacheHitRate', 'errors'];
      const rows = [headers.join(',')];
      for (const r of results) {
        const row = headers.map(h => {
          const val = r[h];
          if (typeof val === 'string') return `"${val.replace(/"/g, '""')}"`;
          return String(val ?? '');
        }).join(',');
        rows.push(row);
      }
      c.header('Content-Type', 'text/csv');
      c.header('Content-Disposition', 'attachment; filename="sessions-export.csv"');
      return c.body(rows.join('\n'));
    }

    c.header('Content-Type', 'application/json');
    c.header('Content-Disposition', 'attachment; filename="sessions-export.json"');
    return c.body(JSON.stringify(results, null, 2));
  } catch (err) {
    console.error('Failed to batch export:', err);
    return c.json({ success: false, error: 'Failed to batch export' }, 500);
  }
});

// Get session summary (default detail view)
sessionsRoutes.get('/:id', async (c) => {
  try {
    const id = c.req.param('id');
    const summary = await getSessionSummary(decodeURIComponent(id));
    if (!summary) {
      return c.json({ success: false, error: 'Session not found' }, 404);
    }
    return c.json({ success: true, data: summary });
  } catch (err) {
    console.error('Failed to get session:', err);
    return c.json({ success: false, error: 'Failed to get session' }, 500);
  }
});

// Get session timeline
sessionsRoutes.get('/:id/timeline', async (c) => {
  try {
    const id = c.req.param('id');
    const timeline = await getSessionTimeline(decodeURIComponent(id));
    if (!timeline) {
      return c.json({ success: false, error: 'Session not found' }, 404);
    }
    return c.json({ success: true, data: timeline });
  } catch (err) {
    console.error('Failed to get timeline:', err);
    return c.json({ success: false, error: 'Failed to get timeline' }, 500);
  }
});

// Get session tree view
sessionsRoutes.get('/:id/tree', async (c) => {
  try {
    const id = c.req.param('id');
    const tree = await getSessionTree(decodeURIComponent(id));
    if (!tree) {
      return c.json({ success: false, error: 'Session not found' }, 404);
    }
    return c.json({ success: true, data: tree });
  } catch (err) {
    console.error('Failed to get tree:', err);
    return c.json({ success: false, error: 'Failed to get tree' }, 500);
  }
});

// Get session token flow
sessionsRoutes.get('/:id/tokens', async (c) => {
  try {
    const id = c.req.param('id');
    const tokens = await getSessionTokens(decodeURIComponent(id));
    if (!tokens) {
      return c.json({ success: false, error: 'Session not found' }, 404);
    }
    return c.json({ success: true, data: tokens });
  } catch (err) {
    console.error('Failed to get tokens:', err);
    return c.json({ success: false, error: 'Failed to get tokens' }, 500);
  }
});

// Get session issues/inefficiencies
sessionsRoutes.get('/:id/issues', async (c) => {
  try {
    const id = c.req.param('id');
    const issues = await getSessionIssues(decodeURIComponent(id));
    if (!issues) {
      return c.json({ success: false, error: 'Session not found' }, 404);
    }
    return c.json({ success: true, data: issues });
  } catch (err) {
    console.error('Failed to get issues:', err);
    return c.json({ success: false, error: 'Failed to get issues' }, 500);
  }
});

// Export session as HTML report
sessionsRoutes.get('/:id/export/html', async (c) => {
  try {
    const id = c.req.param('id');
    const session = await getSessionParsed(decodeURIComponent(id));
    if (!session) {
      return c.json({ success: false, error: 'Session not found' }, 404);
    }
    const html = new HTMLGenerator(session).generate();
    c.header('Content-Type', 'text/html');
    c.header('Content-Disposition', `attachment; filename="trace-${session.sessionId}.html"`);
    return c.body(html);
  } catch (err) {
    console.error('Failed to export HTML:', err);
    return c.json({ success: false, error: 'Failed to export HTML' }, 500);
  }
});

// Export session as CSV
sessionsRoutes.get('/:id/export/csv', async (c) => {
  try {
    const id = c.req.param('id');
    const session = await getSessionParsed(decodeURIComponent(id));
    if (!session) {
      return c.json({ success: false, error: 'Session not found' }, 404);
    }

    const summary = createJSONExporter(session).generateSummary();
    const rows: string[] = ['iteration,action,outcome,tokens_used,flags'];

    for (const iter of summary.iterationSummaries) {
      const row = [
        iter.number,
        `"${iter.action.replace(/"/g, '""')}"`,
        iter.outcome,
        iter.tokensUsed,
        `"${iter.flags.join(';')}"`,
      ].join(',');
      rows.push(row);
    }

    const csv = rows.join('\n');
    c.header('Content-Type', 'text/csv');
    c.header('Content-Disposition', `attachment; filename="trace-${session.sessionId}.csv"`);
    return c.body(csv);
  } catch (err) {
    console.error('Failed to export CSV:', err);
    return c.json({ success: false, error: 'Failed to export CSV' }, 500);
  }
});

// Get raw session data
sessionsRoutes.get('/:id/raw', async (c) => {
  try {
    const id = c.req.param('id');
    const raw = await getSessionRaw(decodeURIComponent(id));
    if (!raw) {
      return c.json({ success: false, error: 'Session not found' }, 404);
    }
    return c.json({ success: true, data: raw });
  } catch (err) {
    console.error('Failed to get raw session:', err);
    return c.json({ success: false, error: 'Failed to get raw session' }, 500);
  }
});
