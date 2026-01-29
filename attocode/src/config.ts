/**
 * User Configuration Loading
 *
 * Loads user config from ~/.config/attocode/config.json
 */

import { existsSync, readFileSync } from 'node:fs';
import { getConfigPath } from './paths.js';
import type { ProviderResilienceConfig } from './types.js';

/**
 * User configuration structure.
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
 */
export function loadUserConfig(): UserConfig | undefined {
  try {
    const configPath = getConfigPath();
    if (!existsSync(configPath)) {
      return undefined;
    }
    const content = readFileSync(configPath, 'utf-8');
    return JSON.parse(content) as UserConfig;
  } catch {
    return undefined;
  }
}
