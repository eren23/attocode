import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    environment: 'node',
    include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'],
    testTimeout: 30000,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'text-summary', 'html'],
      include: ['src/**/*.ts'],
      exclude: [
        'src/**/*.d.ts',
        'src/tui/**', // TUI components are hard to unit test
        'src/modes/tui.tsx', // TUI mode requires Ink
      ],
      thresholds: {
        // Set reasonable baseline thresholds
        lines: 20,
        functions: 20,
        branches: 15,
        statements: 20,
      },
    },
    // Benchmark configuration
    benchmark: {
      include: ['tests/benchmarks/**/*.bench.ts'],
      outputFile: './benchmark-results.json',
    },
  },
});
