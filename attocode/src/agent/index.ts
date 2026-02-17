/**
 * Agent builder and factory functions.
 */
export { createProductionAgent, ProductionAgentBuilder, buildAgent } from './agent-builder.js';

/**
 * Message builder (extracted from ProductionAgent.buildMessages).
 */
export { buildMessages, type MessageBuilderDeps } from './message-builder.js';

/**
 * Session, checkpoint, and file-change tracking API.
 */
export {
  trackFileChange,
  undoLastFileChange,
  undoCurrentTurn,
  reset,
  loadMessages,
  getSerializableState,
  validateCheckpoint,
  loadState,
  type SessionApiDeps,
} from './session-api.js';
