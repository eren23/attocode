/**
 * Core Module
 *
 * Unified exports for the core infrastructure layer including:
 * - Op/Event Protocol: Typed message passing between UI and agent
 * - Queue System: Bounded submission queue and unbounded event queue
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
 *   // Queues
 *   SubmissionQueue,
 *   EventQueue,
 *   AtomicCounter,
 * } from './core/index.js';
 * ```
 */

// Protocol types and validation
export * from './protocol/index.js';

// Queue system
export * from './queues/index.js';

// Process handlers and cleanup
export * from './process-handlers.js';
