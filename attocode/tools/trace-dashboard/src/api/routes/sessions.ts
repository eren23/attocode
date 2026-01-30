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
  uploadTrace,
  uploadTraceInMemory,
  getUploadedTraces,
} from '../trace-service.js';

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
