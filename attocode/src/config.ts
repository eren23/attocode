/**
 * User Configuration Loading
 *
 * @deprecated Use `loadConfig()` from `./config/index.js` instead.
 * This module is kept for backward compatibility and will be removed in a future release.
 */

import { loadConfig } from './config/index.js';
import type { ProviderResilienceConfig } from './types.js';

/**
 * User configuration structure.
 * @deprecated Use `ValidatedUserConfig` from `./config/index.js` instead.
 */
export interface UserConfig {
  providers?: { default?: string };
  model?: string;
  maxIterations?: number;
  timeout?: number;
  /** Provider-level resilience (circuit breaker, fallback chain) */
  providerResilience?: ProviderResilienceConfig;
}

/**
 * Load user config from ~/.config/attocode/config.json
 * Returns undefined if file doesn't exist or is invalid.
 * @deprecated Use `loadConfig()` from `./config/index.js` instead.
 */
export function loadUserConfig(): UserConfig | undefined {
  const { config, sources } = loadConfig({ skipProject: true });
  const anyLoaded = sources.some((s) => s.loaded);
  if (!anyLoaded) {
    return undefined;
  }
  return config as UserConfig;
}
