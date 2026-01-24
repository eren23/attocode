/**
 * Protocol Bridge
 *
 * Connects UI layer to Agent layer via queue-based communication.
 * Maps internal agent events to protocol events with submission correlation.
 *
 * Architecture:
 * ```
 * UI (REPL/TUI)                    Agent Core
 *      |                                |
 *      └─── Op ──► SubmissionQueue ───► handleOperation()
 *                       (64)                  |
 *                                            |
 *      ◄── Event ─ EventQueue ◄───────── emit()
 *                 (unbounded)
 * ```
 */

import type { AgentEvent, Submission, SubmissionId } from './types.js';
import type { SubmissionQueue } from '../queues/submission-queue.js';
import type { EventQueue } from '../queues/event-queue.js';

/**
 * Handler for incoming operations from the UI.
 */
export type OperationHandler = (submission: Submission) => Promise<void>;

/**
 * Protocol bridge interface for UI/Agent communication.
 */
export interface IProtocolBridge {
  /**
   * Starts the bridge, consuming from the submission queue.
   * @param submissionQueue - Queue for incoming operations from UI
   * @param eventQueue - Queue for outgoing events to UI
   */
  start(submissionQueue: SubmissionQueue, eventQueue: EventQueue): void;

  /**
   * Stops the bridge and cleans up resources.
   */
  stop(): void;

  /**
   * Registers a handler for incoming operations.
   * Only one handler is supported - subsequent calls replace the previous handler.
   * @param handler - The handler function for operations
   */
  onOperation(handler: OperationHandler): void;

  /**
   * Emits an event to the UI, correlated with a submission.
   * @param submissionId - The submission this event relates to
   * @param event - The event to emit
   */
  emit(submissionId: SubmissionId, event: AgentEvent): void;

  /**
   * Returns true if the bridge is currently running.
   */
  isRunning(): boolean;

  /**
   * Returns a promise that resolves when the bridge stops.
   * Useful for testing or waiting for graceful shutdown.
   */
  waitForStop(): Promise<void>;
}

/**
 * Protocol bridge implementation.
 *
 * Manages the async loop that consumes from the submission queue
 * and dispatches to the registered operation handler.
 */
export class ProtocolBridge implements IProtocolBridge {
  private submissionQueue: SubmissionQueue | null = null;
  private eventQueue: EventQueue | null = null;
  private operationHandler: OperationHandler | null = null;
  private running = false;
  private consumePromise: Promise<void> | null = null;

  /**
   * Starts the bridge, consuming from the submission queue.
   * @throws Error if the bridge is already running
   */
  start(submissionQueue: SubmissionQueue, eventQueue: EventQueue): void {
    if (this.running) {
      throw new Error('ProtocolBridge is already running');
    }

    this.submissionQueue = submissionQueue;
    this.eventQueue = eventQueue;
    this.running = true;

    // Start the consume loop
    this.consumePromise = this.consumeLoop();
  }

  /**
   * Stops the bridge and cleans up resources.
   * Waits for the current operation to complete before stopping.
   */
  stop(): void {
    this.running = false;

    // The consume loop will exit on the next iteration
    // We don't close the queues - that's the caller's responsibility
  }

  /**
   * Registers a handler for incoming operations.
   * Only one handler is supported - subsequent calls replace the previous handler.
   */
  onOperation(handler: OperationHandler): void {
    this.operationHandler = handler;
  }

  /**
   * Emits an event to the UI, correlated with a submission.
   * @throws Error if the bridge is not started
   */
  emit(submissionId: SubmissionId, event: AgentEvent): void {
    if (!this.eventQueue) {
      throw new Error('ProtocolBridge not started - cannot emit events');
    }

    this.eventQueue.emit(submissionId, event);
  }

  /**
   * Returns true if the bridge is currently running.
   */
  isRunning(): boolean {
    return this.running;
  }

  /**
   * Returns a promise that resolves when the bridge stops.
   * Useful for testing or waiting for graceful shutdown.
   */
  async waitForStop(): Promise<void> {
    if (this.consumePromise) {
      await this.consumePromise;
    }
  }

  /**
   * The main consume loop that processes submissions.
   * Runs until stop() is called or the queue is closed.
   */
  private async consumeLoop(): Promise<void> {
    if (!this.submissionQueue) {
      return;
    }

    while (this.running) {
      try {
        // Take the next submission (blocks if empty)
        const submission = await this.submissionQueue.take();

        // null means the queue was closed
        if (submission === null) {
          this.running = false;
          break;
        }

        // Dispatch to handler if one is registered
        if (this.operationHandler) {
          try {
            await this.operationHandler(submission);
          } catch (error) {
            // Log handler errors but don't crash the bridge
            // The handler is responsible for emitting error events
            this.handleOperationError(submission, error);
          }
        }
      } catch (error) {
        // Queue errors (closed, etc.) - stop the loop
        if (this.running) {
          this.running = false;
        }
        break;
      }
    }
  }

  /**
   * Handles errors from the operation handler.
   * Emits an error event to the UI.
   */
  private handleOperationError(submission: Submission, error: unknown): void {
    // Only emit error event if we have an event queue
    if (!this.eventQueue) {
      return;
    }

    const errorMessage = error instanceof Error ? error.message : String(error);
    const errorStack = error instanceof Error ? error.stack : undefined;

    this.eventQueue.emit(submission.id, {
      type: 'error',
      code: 'OPERATION_HANDLER_ERROR',
      message: `Operation handler failed: ${errorMessage}`,
      recoverable: true,
      stack: errorStack,
    });
  }
}

/**
 * Creates a new ProtocolBridge instance.
 */
export function createProtocolBridge(): ProtocolBridge {
  return new ProtocolBridge();
}
