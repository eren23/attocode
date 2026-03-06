/**
 * Compare API Routes
 */

import { Hono } from 'hono';
import { compareSessions } from '../trace-service.js';

export const compareRoutes = new Hono();

// Compare two sessions
compareRoutes.get('/', async (c) => {
  try {
    const a = c.req.query('a');
    const b = c.req.query('b');

    if (!a || !b) {
      return c.json({
        success: false,
        error: 'Both "a" and "b" query parameters are required',
      }, 400);
    }

    const comparison = await compareSessions(
      decodeURIComponent(a),
      decodeURIComponent(b)
    );

    if (!comparison) {
      return c.json({ success: false, error: 'One or both sessions not found' }, 404);
    }

    return c.json({ success: true, data: comparison });
  } catch (err) {
    console.error('Failed to compare sessions:', err);
    return c.json({ success: false, error: 'Failed to compare sessions' }, 500);
  }
});
