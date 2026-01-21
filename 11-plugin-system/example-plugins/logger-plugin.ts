/**
 * Example Plugin: Logger
 *
 * A simple plugin that logs all agent events.
 * Demonstrates basic hook registration.
 */

import type { Plugin, PluginContext } from '../types.js';

export const loggerPlugin: Plugin = {
  metadata: {
    name: 'logger',
    version: '1.0.0',
    description: 'Logs all agent events to console',
    author: 'First Principles Agent',
    tags: ['logging', 'debugging'],
  },

  async initialize(context: PluginContext) {
    context.log('info', 'Logger plugin initializing...');

    // Track event count
    let eventCount = 0;

    // Register hooks for various events
    context.registerHook('tool.before', (event) => {
      eventCount++;
      context.log('debug', `[${eventCount}] Tool called: ${event.tool}`);
    }, { priority: 0 });

    context.registerHook('tool.after', (event) => {
      context.log('debug', `Tool ${event.tool} completed in ${event.durationMs}ms`);
    }, { priority: 0 });

    context.registerHook('tool.error', (event) => {
      context.log('error', `Tool ${event.tool} failed: ${event.error.message}`);
    }, { priority: 0 });

    context.registerHook('session.start', (event) => {
      context.log('info', `Session started: ${event.sessionId}`);
    }, { priority: 0 });

    context.registerHook('session.end', (event) => {
      context.log('info', `Session ended: ${event.sessionId} (${event.reason})`);
      context.log('info', `Total events logged: ${eventCount}`);
    }, { priority: 0 });

    context.registerHook('error', (event) => {
      const type = event.recoverable ? 'Recoverable' : 'Fatal';
      context.log('error', `${type} error: ${event.error.message}`);
    }, { priority: 0 });

    // Store the event count periodically
    await context.store('lastEventCount', eventCount);

    context.log('info', 'Logger plugin initialized');
  },

  async cleanup() {
    console.log('[logger] Cleanup complete');
  },
};

export default loggerPlugin;
