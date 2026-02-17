/**
 * Lesson 2: Provider Factory
 * 
 * Creates and manages LLM providers with auto-detection.
 */

import type { LLMProvider, ProviderConfig } from './types.js';
import { ProviderError } from './types.js';
import { logger } from '../integrations/utilities/logger.js';

// =============================================================================
// PROVIDER REGISTRY
// =============================================================================

/**
 * Registry of available providers.
 * Each provider has a detection function and factory.
 */
interface ProviderRegistry {
  detect: () => boolean;
  create: () => Promise<LLMProvider>;
  priority: number; // Lower = higher priority
}

const providers: Map<string, ProviderRegistry> = new Map();

/**
 * Register a provider.
 * Call this for each provider adapter.
 */
export function registerProvider(
  name: string,
  registry: ProviderRegistry
): void {
  providers.set(name, registry);
}

// =============================================================================
// PROVIDER FACTORY
// =============================================================================

/**
 * Auto-detect and create the best available provider.
 *
 * Detection order (by priority):
 * 0. OpenRouter (if OPENROUTER_API_KEY set)
 * 1. Anthropic (if ANTHROPIC_API_KEY set)
 * 2. OpenAI (if OPENAI_API_KEY set)
 * 3. Azure (if AZURE_OPENAI_* set)
 * 100. Mock (always available as fallback)
 */
export async function getProvider(preferred?: string): Promise<LLMProvider> {
  // If preferred provider specified, try it first
  if (preferred) {
    const registry = providers.get(preferred);
    if (registry?.detect()) {
      return registry.create();
    }
    throw new ProviderError(
      `Preferred provider "${preferred}" is not configured`,
      preferred,
      'NOT_CONFIGURED'
    );
  }

  // Sort by priority and find first configured provider
  const sorted = [...providers.entries()]
    .sort((a, b) => a[1].priority - b[1].priority);

  for (const [name, registry] of sorted) {
    if (registry.detect()) {
      logger.info(`Using provider: ${name}`);
      return registry.create();
    }
  }

  throw new ProviderError(
    'No LLM provider configured. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or AZURE_OPENAI_* environment variables.',
    'none',
    'NOT_CONFIGURED'
  );
}

/**
 * Create a provider from explicit configuration.
 * Use this when you don't want auto-detection.
 */
export async function createProvider(config: ProviderConfig): Promise<LLMProvider> {
  switch (config.type) {
    case 'anthropic': {
      const { AnthropicProvider } = await import('./adapters/anthropic.js');
      return new AnthropicProvider(config.config);
    }
    case 'openai': {
      const { OpenAIProvider } = await import('./adapters/openai.js');
      return new OpenAIProvider(config.config);
    }
    // Azure provider not included in attocode
    // case 'azure': {
    //   const { AzureOpenAIProvider } = await import('./adapters/azure.js');
    //   return new AzureOpenAIProvider(config.config);
    // }
    case 'openrouter': {
      const { OpenRouterProvider } = await import('./adapters/openrouter.js');
      return new OpenRouterProvider(config.config);
    }
    case 'mock': {
      const { MockProvider } = await import('./adapters/mock.js');
      return new MockProvider();
    }
    default:
      throw new ProviderError(
        `Unknown provider type: ${(config as ProviderConfig).type}`,
        'unknown',
        'INVALID_REQUEST'
      );
  }
}

/**
 * List all registered providers and their status.
 */
export function listProviders(): Array<{ name: string; configured: boolean; priority: number }> {
  return [...providers.entries()]
    .map(([name, registry]) => ({
      name,
      configured: registry.detect(),
      priority: registry.priority,
    }))
    .sort((a, b) => a.priority - b.priority);
}

// =============================================================================
// HELPER FOR ADAPTER REGISTRATION
// =============================================================================

/**
 * Check if an environment variable is set and non-empty.
 */
export function hasEnv(key: string): boolean {
  const value = process.env[key];
  return value !== undefined && value.trim() !== '';
}

/**
 * Get environment variable or throw.
 */
export function requireEnv(key: string): string {
  const value = process.env[key];
  if (!value) {
    throw new Error(`Missing required environment variable: ${key}`);
  }
  return value;
}
