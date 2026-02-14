/**
 * Shared State Modules
 *
 * Thin shared-state layers that swarm workers plug into for
 * cross-worker failure learning, reference pooling, and doom loop aggregation.
 */

export {
  SharedContextState,
  createSharedContextState,
  type SharedContextConfig,
} from './shared-context-state.js';

export {
  SharedEconomicsState,
  createSharedEconomicsState,
  type SharedEconomicsConfig,
} from './shared-economics-state.js';

export {
  type PersistenceAdapter,
  JSONFilePersistenceAdapter,
  SQLitePersistenceAdapter,
  createPersistenceAdapter,
} from './persistence.js';

export {
  SharedContextEngine,
  createSharedContextEngine,
  type SharedContextEngineConfig,
  type WorkerTask,
} from './context-engine.js';

export {
  WorkerBudgetTracker,
  createWorkerBudgetTracker,
  type WorkerBudgetConfig,
  type WorkerBudgetCheckResult,
} from './budget-tracker.js';
