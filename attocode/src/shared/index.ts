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
