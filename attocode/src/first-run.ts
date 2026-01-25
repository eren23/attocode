/**
 * First-run detection and setup for attocode.
 *
 * Detects available API keys and guides users through initial setup.
 */

import { existsSync, writeFileSync } from 'fs';
import { getConfigPath, ensureDirectories } from './paths.js';

export interface DetectedProvider {
  name: 'anthropic' | 'openrouter' | 'openai';
  source: 'env' | 'config';
  hasKey: boolean;
}

/**
 * Detect available providers from environment variables.
 */
export function detectProviders(): DetectedProvider[] {
  const providers: DetectedProvider[] = [];

  if (process.env.ANTHROPIC_API_KEY) {
    providers.push({ name: 'anthropic', source: 'env', hasKey: true });
  }
  if (process.env.OPENROUTER_API_KEY) {
    providers.push({ name: 'openrouter', source: 'env', hasKey: true });
  }
  if (process.env.OPENAI_API_KEY) {
    providers.push({ name: 'openai', source: 'env', hasKey: true });
  }

  return providers;
}

/**
 * Check if this is the first run (no config exists).
 */
export function isFirstRun(): boolean {
  return !existsSync(getConfigPath());
}

/**
 * Check if we have any usable provider.
 */
export function hasUsableProvider(): boolean {
  return detectProviders().length > 0;
}

/**
 * Get the default provider based on available keys.
 */
export function getDefaultProvider(): DetectedProvider | null {
  const providers = detectProviders();
  // Prefer Anthropic > OpenRouter > OpenAI
  return providers.find(p => p.name === 'anthropic')
    || providers.find(p => p.name === 'openrouter')
    || providers.find(p => p.name === 'openai')
    || null;
}

/**
 * Create initial config file with detected settings.
 */
export async function createInitialConfig(): Promise<void> {
  await ensureDirectories();

  const config = {
    "$schema": "https://attocode.dev/schema/config.json",
    "version": 1,
    "providers": {
      "default": getDefaultProvider()?.name || "anthropic"
    },
    "model": "claude-sonnet-4-20250514",
    "maxIterations": 50,
    "timeout": 300000
  };

  writeFileSync(getConfigPath(), JSON.stringify(config, null, 2));
}

/**
 * Show first-run message with setup instructions.
 */
export function getFirstRunMessage(): string {
  const providers = detectProviders();

  if (providers.length === 0) {
    return `
╔══════════════════════════════════════════════════════════════╗
║                    Welcome to Attocode!                       ║
╠══════════════════════════════════════════════════════════════╣
║  No API key found. Set one of these environment variables:   ║
║                                                              ║
║    export ANTHROPIC_API_KEY="sk-ant-..."                     ║
║    export OPENROUTER_API_KEY="sk-or-..."                     ║
║    export OPENAI_API_KEY="sk-..."                            ║
║                                                              ║
║  Or run: attocode init                                       ║
╚══════════════════════════════════════════════════════════════╝
`.trim();
  }

  const provider = getDefaultProvider()!;
  return `
╔══════════════════════════════════════════════════════════════╗
║                    Welcome to Attocode!                       ║
╠══════════════════════════════════════════════════════════════╣
║  ✓ Found ${provider.name.toUpperCase()} API key from environment             ║
║  Ready to go! Type your request or use /help for commands.   ║
╚══════════════════════════════════════════════════════════════╝
`.trim();
}
