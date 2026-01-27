/**
 * Vitest Configuration for Exercise Tests
 *
 * This configuration is specifically for running exercise tests.
 * It excludes the main lesson tests and focuses only on exercises.
 */

import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    // Only include exercise test files
    include: [
      '**/exercises.test.ts',
      '**/exercises/**/*.test.ts',
    ],

    // Exclude main lesson tests
    exclude: [
      'node_modules/**',
      'dist/**',
      '**/*.spec.ts',  // Spec files are for main lessons
    ],

    // Test environment
    environment: 'node',

    // Global test utilities
    globals: true,

    // Timeout for each test (exercises should be fast)
    testTimeout: 10000,

    // Reporter configuration
    reporters: ['verbose'],

    // Coverage configuration (optional)
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      include: ['**/exercises/**/*.ts'],
      exclude: ['**/exercises/**/answers/**'],
    },

    // Setup files
    setupFiles: ['./testing/exercise-setup.ts'],

    // Sequence configuration
    sequence: {
      // Run tests in the order they're defined
      shuffle: false,
    },

    // Pool configuration
    pool: 'forks',
    poolOptions: {
      forks: {
        singleFork: true,  // Run all tests in a single process for speed
      },
    },
  },

  // Resolve configuration
  resolve: {
    alias: {
      '@testing': './testing',
    },
  },
});
