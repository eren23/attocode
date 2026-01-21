/**
 * Lesson 26: Bug Fixing Benchmark
 *
 * Tasks that require finding and fixing bugs in existing code.
 * Tests debugging skills and code comprehension.
 */

import { task, suite } from '../benchmark-schema.js';
import type { BenchmarkSuite } from '../../types.js';

// =============================================================================
// TASK DEFINITIONS
// =============================================================================

const offByOne = task()
  .id('bug-fixing-001')
  .name('Off-by-One Error')
  .category('bug-fixing')
  .difficulty('easy')
  .prompt(`The file sum.ts has a bug. The \`sumRange\` function should sum all numbers from \`start\` to \`end\` (inclusive), but it has an off-by-one error.

Find and fix the bug. The tests will verify your fix.`)
  .setupFiles({
    'sum.ts': `
/**
 * Sum all integers from start to end (inclusive).
 */
export function sumRange(start: number, end: number): number {
  let sum = 0;
  // Bug: should be i <= end, not i < end
  for (let i = start; i < end; i++) {
    sum += i;
  }
  return sum;
}
`,
    'sum.test.ts': `
import { sumRange } from './sum.js';

describe('sumRange', () => {
  test('sums 1 to 5', () => {
    expect(sumRange(1, 5)).toBe(15); // 1+2+3+4+5
  });

  test('sums single number', () => {
    expect(sumRange(5, 5)).toBe(5);
  });

  test('sums negative range', () => {
    expect(sumRange(-2, 2)).toBe(0); // -2+-1+0+1+2
  });
});
`,
    'package.json': `{
  "name": "benchmark-bugfix-offbyone",
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
  .tags('easy', 'bug', 'loop')
  .build();

const nullCheck = task()
  .id('bug-fixing-002')
  .name('Missing Null Check')
  .category('bug-fixing')
  .difficulty('easy')
  .prompt(`The file user.ts has a bug. The \`getUserName\` function crashes when user is null or undefined.

Find and fix the bug to handle null/undefined gracefully by returning "Anonymous".`)
  .setupFiles({
    'user.ts': `
interface User {
  name: string;
  email: string;
}

/**
 * Get the user's name, or "Anonymous" if user is null/undefined.
 */
export function getUserName(user: User | null | undefined): string {
  // Bug: No null check before accessing .name
  return user.name;
}
`,
    'user.test.ts': `
import { getUserName } from './user.js';

describe('getUserName', () => {
  test('returns name for valid user', () => {
    expect(getUserName({ name: 'Alice', email: 'alice@test.com' })).toBe('Alice');
  });

  test('returns Anonymous for null', () => {
    expect(getUserName(null)).toBe('Anonymous');
  });

  test('returns Anonymous for undefined', () => {
    expect(getUserName(undefined)).toBe('Anonymous');
  });
});
`,
    'package.json': `{
  "name": "benchmark-bugfix-null",
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
  .tags('easy', 'bug', 'null-safety')
  .build();

const asyncAwait = task()
  .id('bug-fixing-003')
  .name('Missing Await')
  .category('bug-fixing')
  .difficulty('medium')
  .prompt(`The file fetchData.ts has a bug. The \`fetchAndProcess\` function is not awaiting the async call properly.

Find and fix the missing await keyword.`)
  .setupFiles({
    'fetchData.ts': `
/**
 * Simulates fetching data from an API.
 */
async function fetchData(): Promise<{ value: number }> {
  return { value: 42 };
}

/**
 * Fetch data and return the value multiplied by 2.
 */
export async function fetchAndProcess(): Promise<number> {
  // Bug: Missing await before fetchData()
  const data = fetchData();
  return data.value * 2;
}
`,
    'fetchData.test.ts': `
import { fetchAndProcess } from './fetchData.js';

describe('fetchAndProcess', () => {
  test('returns fetched value multiplied by 2', async () => {
    const result = await fetchAndProcess();
    expect(result).toBe(84); // 42 * 2
  });
});
`,
    'package.json': `{
  "name": "benchmark-bugfix-async",
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
  .tags('medium', 'bug', 'async')
  .build();

const importError = task()
  .id('bug-fixing-004')
  .name('Wrong Import Path')
  .category('bug-fixing')
  .difficulty('easy')
  .prompt(`The file main.ts has an import error. The import path is incorrect.

The \`utils.ts\` file is in the same directory. Fix the import path in main.ts.`)
  .setupFiles({
    'utils.ts': `
export function add(a: number, b: number): number {
  return a + b;
}
`,
    'main.ts': `
// Bug: Wrong import path - should be './utils.js' not '../utils.js'
import { add } from '../utils.js';

export function calculate(x: number, y: number): number {
  return add(x, y);
}
`,
    'main.test.ts': `
import { calculate } from './main.js';

describe('calculate', () => {
  test('adds two numbers', () => {
    expect(calculate(2, 3)).toBe(5);
  });
});
`,
    'package.json': `{
  "name": "benchmark-bugfix-import",
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
  .tags('easy', 'bug', 'import')
  .build();

const typeError = task()
  .id('bug-fixing-005')
  .name('Type Mismatch')
  .category('bug-fixing')
  .difficulty('medium')
  .prompt(`The file format.ts has a type error. The \`formatPrice\` function should return a string, but it's returning a number.

Fix the function to return a properly formatted price string with a dollar sign.`)
  .setupFiles({
    'format.ts': `
/**
 * Format a price as a string with dollar sign and 2 decimal places.
 * Example: formatPrice(19.99) → "$19.99"
 */
export function formatPrice(price: number): string {
  // Bug: Returns number instead of string
  return price.toFixed(2);
}
`,
    'format.test.ts': `
import { formatPrice } from './format.js';

describe('formatPrice', () => {
  test('formats with dollar sign', () => {
    expect(formatPrice(19.99)).toBe('$19.99');
  });

  test('formats integer prices', () => {
    expect(formatPrice(10)).toBe('$10.00');
  });

  test('formats small prices', () => {
    expect(formatPrice(0.5)).toBe('$0.50');
  });
});
`,
    'package.json': `{
  "name": "benchmark-bugfix-type",
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
  .tags('medium', 'bug', 'types')
  .build();

// =============================================================================
// SUITE EXPORT
// =============================================================================

export const bugFixingSuite: BenchmarkSuite = suite()
  .id('bug-fixing')
  .name('Bug Fixing Tasks')
  .description('Tasks that require finding and fixing bugs in existing code')
  .addTasks(offByOne, nullCheck, asyncAwait, importError, typeError)
  .metadata({
    version: '1.0.0',
    author: 'Lesson 26',
    estimatedDuration: '5-10 minutes',
  })
  .build();

export default bugFixingSuite;
