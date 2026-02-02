/**
 * Core Module
 *
 * Unified exports for the core infrastructure layer including:
 * - Op/Event Protocol: Typed message passing between UI and agent
 * - Process handlers for graceful shutdown
 *
 * @example
 * ```typescript
 * import {
 *   // Protocol types
 *   type Operation,
 *   type AgentEvent,
 *   type Submission,
 *   type EventEnvelope,
 *   // Validation
 *   OperationSchema,
 *   AgentEventSchema,
 *   // Type guards
 *   isUserTurn,
 *   isAgentMessage,
 * } from './core/index.js';
 * ```
 */

// Protocol types and validation
export * from './protocol/index.js';

// Process handlers and cleanup
export * from './process-handlers.js';

// Note: The queues/ directory was removed as unused dead code.
// The queue-based communication pattern was an over-engineered design
// that was never integrated. The codebase uses direct event subscriptions instead.
