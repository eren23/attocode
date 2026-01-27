/**
 * Context Management Module
 *
 * Exports for conversation persistence, token management, and compaction.
 */

export {
  ContextManager,
  createContextManager,
  type ContextManagerConfig,
  type ContextStorage,
  type StoredMessage,
  type SessionMetadata,
  type ConversationState,
} from './context-manager.js';

export {
  FilesystemContextStorage,
  InMemoryContextStorage,
} from './filesystem-context.js';

export {
  truncateStrategy,
  slidingWindowStrategy,
  summarizeStrategy,
  hybridStrategy,
  type CompactionStrategy,
  type CompactionResult,
} from './compaction-strategies.js';
