/**
 * Lesson 26: Benchmark Suite Index
 *
 * Exports all built-in benchmark suites for evaluation.
 */

export { simpleCodingSuite } from './simple-coding.js';
export { bugFixingSuite } from './bug-fixing.js';
export { fileEditingSuite } from './file-editing.js';
export { multiFileSuite } from './multi-file.js';

import { simpleCodingSuite } from './simple-coding.js';
import { bugFixingSuite } from './bug-fixing.js';
import { fileEditingSuite } from './file-editing.js';
import { multiFileSuite } from './multi-file.js';
import type { BenchmarkSuite } from '../../types.js';

/**
 * All built-in benchmark suites.
 */
export const allSuites: BenchmarkSuite[] = [
  simpleCodingSuite,
  bugFixingSuite,
  fileEditingSuite,
  multiFileSuite,
];

/**
 * Get a suite by ID.
 */
export function getSuiteById(id: string): BenchmarkSuite | undefined {
  return allSuites.find(s => s.id === id);
}

/**
 * Get suites by category.
 */
export function getSuitesByCategory(category: string): BenchmarkSuite[] {
  return allSuites.filter(s =>
    s.tasks.some(t => t.category === category)
  );
}

/**
 * Get all available suite IDs.
 */
export function getAvailableSuiteIds(): string[] {
  return allSuites.map(s => s.id);
}

/**
 * Get total task count across all suites.
 */
export function getTotalTaskCount(): number {
  return allSuites.reduce((sum, s) => sum + s.tasks.length, 0);
}

/**
 * Summary statistics for all benchmarks.
 */
export function getBenchmarkStats(): {
  totalSuites: number;
  totalTasks: number;
  byDifficulty: Record<string, number>;
  byCategory: Record<string, number>;
} {
  const byDifficulty: Record<string, number> = {};
  const byCategory: Record<string, number> = {};

  for (const suite of allSuites) {
    for (const task of suite.tasks) {
      byDifficulty[task.difficulty] = (byDifficulty[task.difficulty] ?? 0) + 1;
      byCategory[task.category] = (byCategory[task.category] ?? 0) + 1;
    }
  }

  return {
    totalSuites: allSuites.length,
    totalTasks: getTotalTaskCount(),
    byDifficulty,
    byCategory,
  };
}
