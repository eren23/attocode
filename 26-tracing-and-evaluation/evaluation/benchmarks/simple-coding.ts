/**
 * Lesson 26: Simple Coding Benchmark
 *
 * Mini HumanEval-style tasks for basic coding ability.
 * Tests fundamental programming skills like loops, conditionals, and algorithms.
 */

import { task, suite } from '../benchmark-schema.js';
import type { BenchmarkSuite } from '../../types.js';

// =============================================================================
// TASK DEFINITIONS
// =============================================================================

const fizzBuzz = task()
  .id('simple-coding-001')
  .name('FizzBuzz')
  .category('function-completion')
  .difficulty('easy')
  .prompt(`Create a file called fizzbuzz.ts that exports a function \`fizzBuzz(n: number): string\`.

The function should return:
- "FizzBuzz" if n is divisible by both 3 and 5
- "Fizz" if n is divisible by 3
- "Buzz" if n is divisible by 5
- The number as a string otherwise

Example:
- fizzBuzz(15) → "FizzBuzz"
- fizzBuzz(9) → "Fizz"
- fizzBuzz(10) → "Buzz"
- fizzBuzz(7) → "7"`)
  .setupFiles({
    'fizzbuzz.test.ts': `
import { fizzBuzz } from './fizzbuzz.js';

describe('fizzBuzz', () => {
  test('returns FizzBuzz for multiples of 15', () => {
    expect(fizzBuzz(15)).toBe('FizzBuzz');
    expect(fizzBuzz(30)).toBe('FizzBuzz');
  });

  test('returns Fizz for multiples of 3', () => {
    expect(fizzBuzz(3)).toBe('Fizz');
    expect(fizzBuzz(9)).toBe('Fizz');
  });

  test('returns Buzz for multiples of 5', () => {
    expect(fizzBuzz(5)).toBe('Buzz');
    expect(fizzBuzz(10)).toBe('Buzz');
  });

  test('returns number as string otherwise', () => {
    expect(fizzBuzz(1)).toBe('1');
    expect(fizzBuzz(7)).toBe('7');
  });
});
`,
    'package.json': `{
  "name": "benchmark-fizzbuzz",
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
  .tags('easy', 'function', 'math')
  .build();

const isPrime = task()
  .id('simple-coding-002')
  .name('Is Prime')
  .category('function-completion')
  .difficulty('easy')
  .prompt(`Create a file called isPrime.ts that exports a function \`isPrime(n: number): boolean\`.

The function should return true if n is a prime number, false otherwise.
- A prime number is greater than 1 and only divisible by 1 and itself.
- Handle edge cases: 0, 1, and negative numbers are not prime.

Example:
- isPrime(2) → true
- isPrime(17) → true
- isPrime(4) → false
- isPrime(1) → false`)
  .setupFiles({
    'isPrime.test.ts': `
import { isPrime } from './isPrime.js';

describe('isPrime', () => {
  test('returns true for prime numbers', () => {
    expect(isPrime(2)).toBe(true);
    expect(isPrime(3)).toBe(true);
    expect(isPrime(17)).toBe(true);
    expect(isPrime(97)).toBe(true);
  });

  test('returns false for non-prime numbers', () => {
    expect(isPrime(4)).toBe(false);
    expect(isPrime(9)).toBe(false);
    expect(isPrime(100)).toBe(false);
  });

  test('handles edge cases', () => {
    expect(isPrime(0)).toBe(false);
    expect(isPrime(1)).toBe(false);
    expect(isPrime(-5)).toBe(false);
  });
});
`,
    'package.json': `{
  "name": "benchmark-isprime",
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
  .tags('easy', 'function', 'math')
  .build();

const reverseString = task()
  .id('simple-coding-003')
  .name('Reverse String')
  .category('function-completion')
  .difficulty('easy')
  .prompt(`Create a file called reverseString.ts that exports a function \`reverseString(s: string): string\`.

The function should return the input string reversed.

Example:
- reverseString("hello") → "olleh"
- reverseString("TypeScript") → "tpircSepyT"
- reverseString("") → ""`)
  .setupFiles({
    'reverseString.test.ts': `
import { reverseString } from './reverseString.js';

describe('reverseString', () => {
  test('reverses simple strings', () => {
    expect(reverseString('hello')).toBe('olleh');
    expect(reverseString('abc')).toBe('cba');
  });

  test('handles mixed case', () => {
    expect(reverseString('TypeScript')).toBe('tpircSepyT');
  });

  test('handles empty string', () => {
    expect(reverseString('')).toBe('');
  });

  test('handles single character', () => {
    expect(reverseString('a')).toBe('a');
  });

  test('handles spaces', () => {
    expect(reverseString('hello world')).toBe('dlrow olleh');
  });
});
`,
    'package.json': `{
  "name": "benchmark-reverse",
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
  .tags('easy', 'function', 'string')
  .build();

const findMax = task()
  .id('simple-coding-004')
  .name('Find Maximum')
  .category('function-completion')
  .difficulty('easy')
  .prompt(`Create a file called findMax.ts that exports a function \`findMax(arr: number[]): number\`.

The function should return the maximum value in the array.
- Throw an error if the array is empty.
- Handle negative numbers correctly.

Example:
- findMax([1, 3, 2]) → 3
- findMax([-5, -1, -10]) → -1
- findMax([42]) → 42`)
  .setupFiles({
    'findMax.test.ts': `
import { findMax } from './findMax.js';

describe('findMax', () => {
  test('finds max in positive numbers', () => {
    expect(findMax([1, 3, 2])).toBe(3);
    expect(findMax([5, 10, 15, 8])).toBe(15);
  });

  test('finds max in negative numbers', () => {
    expect(findMax([-5, -1, -10])).toBe(-1);
  });

  test('handles single element', () => {
    expect(findMax([42])).toBe(42);
  });

  test('handles mixed numbers', () => {
    expect(findMax([-10, 0, 10])).toBe(10);
  });

  test('throws on empty array', () => {
    expect(() => findMax([])).toThrow();
  });
});
`,
    'package.json': `{
  "name": "benchmark-findmax",
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
  .tags('easy', 'function', 'array')
  .build();

const fibonacci = task()
  .id('simple-coding-005')
  .name('Fibonacci')
  .category('function-completion')
  .difficulty('medium')
  .prompt(`Create a file called fibonacci.ts that exports a function \`fibonacci(n: number): number\`.

The function should return the nth Fibonacci number (0-indexed).
- fibonacci(0) = 0
- fibonacci(1) = 1
- fibonacci(n) = fibonacci(n-1) + fibonacci(n-2) for n > 1

Handle negative inputs by returning 0.

Example:
- fibonacci(0) → 0
- fibonacci(1) → 1
- fibonacci(6) → 8
- fibonacci(10) → 55`)
  .setupFiles({
    'fibonacci.test.ts': `
import { fibonacci } from './fibonacci.js';

describe('fibonacci', () => {
  test('returns correct base cases', () => {
    expect(fibonacci(0)).toBe(0);
    expect(fibonacci(1)).toBe(1);
  });

  test('calculates correctly for small numbers', () => {
    expect(fibonacci(2)).toBe(1);
    expect(fibonacci(3)).toBe(2);
    expect(fibonacci(4)).toBe(3);
    expect(fibonacci(5)).toBe(5);
    expect(fibonacci(6)).toBe(8);
  });

  test('calculates correctly for larger numbers', () => {
    expect(fibonacci(10)).toBe(55);
    expect(fibonacci(15)).toBe(610);
  });

  test('handles negative input', () => {
    expect(fibonacci(-1)).toBe(0);
    expect(fibonacci(-5)).toBe(0);
  });
});
`,
    'package.json': `{
  "name": "benchmark-fibonacci",
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
  .tags('medium', 'function', 'math', 'recursion')
  .build();

// =============================================================================
// SUITE EXPORT
// =============================================================================

export const simpleCodingSuite: BenchmarkSuite = suite()
  .id('simple-coding')
  .name('Simple Coding Tasks')
  .description('Basic programming tasks testing fundamental coding skills')
  .addTasks(fizzBuzz, isPrime, reverseString, findMax, fibonacci)
  .metadata({
    version: '1.0.0',
    author: 'Lesson 26',
    estimatedDuration: '5-10 minutes',
  })
  .build();

export default simpleCodingSuite;
