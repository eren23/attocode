/**
 * Exercise Test Setup
 *
 * Global setup for exercise tests. Runs before all exercise test files.
 */

import { beforeAll, afterAll, vi } from 'vitest';

// Ensure we're not using real API keys during exercise tests
beforeAll(() => {
  // Clear any API keys to prevent accidental real API calls
  const keysToMock = [
    'ANTHROPIC_API_KEY',
    'OPENAI_API_KEY',
    'AZURE_OPENAI_API_KEY',
    'OPENROUTER_API_KEY',
  ];

  for (const key of keysToMock) {
    if (process.env[key]) {
      // Store original value for restoration
      (process.env as Record<string, string>)[`__ORIGINAL_${key}`] = process.env[key]!;
      delete process.env[key];
    }
  }
});

afterAll(() => {
  // Restore original API keys
  const keysToRestore = [
    'ANTHROPIC_API_KEY',
    'OPENAI_API_KEY',
    'AZURE_OPENAI_API_KEY',
    'OPENROUTER_API_KEY',
  ];

  for (const key of keysToRestore) {
    const originalKey = `__ORIGINAL_${key}`;
    if (process.env[originalKey]) {
      process.env[key] = process.env[originalKey];
      delete process.env[originalKey];
    }
  }
});

// Global mocks that apply to all exercise tests
vi.mock('dotenv', () => ({
  config: vi.fn(),
}));
