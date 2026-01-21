/**
 * Lesson 26: File Editing Benchmark
 *
 * Tasks that require making specific edits to existing files.
 * Tests ability to understand and modify code correctly.
 */

import { task, suite } from '../benchmark-schema.js';
import type { BenchmarkSuite } from '../../types.js';

// =============================================================================
// TASK DEFINITIONS
// =============================================================================

const addExport = task()
  .id('file-editing-001')
  .name('Add Export')
  .category('file-editing')
  .difficulty('easy')
  .prompt(`The file math.ts has a function \`multiply\` that is not exported.

Add the \`export\` keyword to make the function available for import.`)
  .setupFiles({
    'math.ts': `
export function add(a: number, b: number): number {
  return a + b;
}

export function subtract(a: number, b: number): number {
  return a - b;
}

// This function should be exported
function multiply(a: number, b: number): number {
  return a * b;
}
`
  })
  .expectFileContains('math.ts', ['export function multiply'])
  .timeout(30000)
  .maxIterations(3)
  .tags('easy', 'edit', 'export')
  .build();

const renameFunction = task()
  .id('file-editing-002')
  .name('Rename Function')
  .category('file-editing')
  .difficulty('easy')
  .prompt(`The file utils.ts has a function called \`calc\`. This name is too vague.

Rename it to \`calculateTotal\` throughout the file.`)
  .setupFiles({
    'utils.ts': `
/**
 * Calculate total with tax.
 */
export function calc(price: number, taxRate: number): number {
  return price * (1 + taxRate);
}

/**
 * Apply discount and calculate final total.
 */
export function applyDiscount(price: number, discount: number, taxRate: number): number {
  const discounted = price * (1 - discount);
  return calc(discounted, taxRate);
}
`
  })
  .expectFileContains('utils.ts', ['export function calculateTotal', 'return calculateTotal(discounted, taxRate)'])
  .expectFileNotContains('utils.ts', ['function calc('])
  .timeout(30000)
  .maxIterations(3)
  .tags('easy', 'edit', 'rename')
  .build();

const addParameter = task()
  .id('file-editing-003')
  .name('Add Parameter')
  .category('file-editing')
  .difficulty('medium')
  .prompt(`The file greet.ts has a \`greet\` function that only takes a name.

Add an optional \`formal\` boolean parameter. When true, it should return "Good day, {name}" instead of "Hello, {name}".

The tests will verify your implementation.`)
  .setupFiles({
    'greet.ts': `
/**
 * Generate a greeting message.
 */
export function greet(name: string): string {
  return \`Hello, \${name}\`;
}
`,
    'greet.test.ts': `
import { greet } from './greet.js';

describe('greet', () => {
  test('casual greeting by default', () => {
    expect(greet('Alice')).toBe('Hello, Alice');
  });

  test('casual greeting when formal is false', () => {
    expect(greet('Bob', false)).toBe('Hello, Bob');
  });

  test('formal greeting when formal is true', () => {
    expect(greet('Charles', true)).toBe('Good day, Charles');
  });
});
`,
    'package.json': `{
  "name": "benchmark-edit-param",
  "type": "module",
  "scripts": {
    "test": "vitest run --reporter=verbose"
  },
  "devDependencies": {
    "vitest": "^1.0.0",
    "typescript": "^5.0.0"
  }
}`,
    'tsconfig.json': `{
  "compilerOptions": {
    "module": "ESNext",
    "moduleResolution": "bundler",
    "target": "ES2022",
    "strict": true
  }
}`
  })
  .setupCommand('npm', ['install'])
  .expectTestPass('npm', ['test'])
  .timeout(60000)
  .maxIterations(5)
  .tags('medium', 'edit', 'parameter')
  .build();

const removeDeadCode = task()
  .id('file-editing-004')
  .name('Remove Dead Code')
  .category('file-editing')
  .difficulty('easy')
  .prompt(`The file processor.ts has unused functions marked with "UNUSED" comments.

Remove all the dead code (unused functions) while keeping the used ones.`)
  .setupFiles({
    'processor.ts': `
// USED - keep this
export function processData(data: string): string {
  return data.trim().toUpperCase();
}

// UNUSED - remove this
function legacyProcess(data: string): string {
  return data.toLowerCase();
}

// USED - keep this
export function validateData(data: string): boolean {
  return data.length > 0;
}

// UNUSED - remove this
function oldValidation(data: string): boolean {
  return !!data;
}

// UNUSED - remove this
const DEPRECATED_CONSTANT = 'old value';
`
  })
  .expectFileContains('processor.ts', ['export function processData', 'export function validateData'])
  .expectFileNotContains('processor.ts', ['function legacyProcess', 'function oldValidation', 'DEPRECATED_CONSTANT'])
  .timeout(30000)
  .maxIterations(3)
  .tags('easy', 'edit', 'cleanup')
  .build();

const addTypeAnnotations = task()
  .id('file-editing-005')
  .name('Add Type Annotations')
  .category('file-editing')
  .difficulty('medium')
  .prompt(`The file calculator.ts has functions without explicit return type annotations.

Add proper TypeScript return type annotations to all exported functions.
- add: returns number
- concat: returns string
- isPositive: returns boolean`)
  .setupFiles({
    'calculator.ts': `
export function add(a: number, b: number) {
  return a + b;
}

export function concat(a: string, b: string) {
  return a + b;
}

export function isPositive(n: number) {
  return n > 0;
}
`
  })
  .expectFileContains('calculator.ts', [
    'export function add(a: number, b: number): number',
    'export function concat(a: string, b: string): string',
    'export function isPositive(n: number): boolean'
  ])
  .timeout(30000)
  .maxIterations(3)
  .tags('medium', 'edit', 'types')
  .build();

// =============================================================================
// SUITE EXPORT
// =============================================================================

export const fileEditingSuite: BenchmarkSuite = suite()
  .id('file-editing')
  .name('File Editing Tasks')
  .description('Tasks that require making specific edits to existing files')
  .addTasks(addExport, renameFunction, addParameter, removeDeadCode, addTypeAnnotations)
  .metadata({
    version: '1.0.0',
    author: 'Lesson 26',
    estimatedDuration: '5-10 minutes',
  })
  .build();

export default fileEditingSuite;
