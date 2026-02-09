/**
 * Trace Dashboard API Server
 *
 * Hono-based API server that serves trace data using the trace-viewer library.
 */

import { serve } from '@hono/node-server';
import { Hono } from 'hono';
import { cors } from 'hono/cors';
import { logger } from 'hono/logger';
import { serveStatic } from '@hono/node-server/serve-static';
import { sessionsRoutes } from './routes/sessions.js';
import { compareRoutes } from './routes/compare.js';
import { swarmLiveRoutes } from './routes/swarm-live.js';

const app = new Hono();

// Middleware
app.use('*', logger());
app.use(
  '/api/*',
  cors({
    origin: [
      'http://localhost:5173',
      'http://localhost:3000',
      'http://localhost:3001',
      'http://localhost:4000',
    ],
    allowMethods: ['GET', 'POST', 'OPTIONS'],
  })
);

// API routes
app.route('/api/sessions', sessionsRoutes);
app.route('/api/compare', compareRoutes);
app.route('/api/swarm', swarmLiveRoutes);

// Health check
app.get('/api/health', (c) => {
  return c.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// Serve static files in production
app.use('/*', serveStatic({ root: './dist/client' }));

// Fallback to index.html for SPA routing
app.get('*', serveStatic({ path: './dist/client/index.html' }));

// Start server
const port = parseInt(process.env.PORT || '3001', 10);

console.log(`🚀 Trace Dashboard API server starting on http://localhost:${port}`);

serve({
  fetch: app.fetch,
  port,
  hostname: '0.0.0.0',
});
