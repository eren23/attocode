/**
 * Queue System Exports
 *
 * Provides the core queue infrastructure for UI/Agent communication:
 * - AtomicCounter: Lock-free ID generation
 * - SubmissionQueue: Bounded async queue with backpressure (UI -> Agent)
 * - EventQueue: Unbounded pub/sub event emitter (Agent -> UI)
 */

// Atomic counter
export { AtomicCounter, globalCounter } from './atomic-counter.js';

// Submission queue
export {
  SubmissionQueue,
  QueueTimeoutError,
  QueueClosedError,
  type SubmissionQueueConfig,
} from './submission-queue.js';

// Event queue
export {
  EventQueue,
  EventTimeoutError,
  type EventListener,
  type TypedEventListener,
  type EventQueueConfig,
  type EventQueueStats,
} from './event-queue.js';
