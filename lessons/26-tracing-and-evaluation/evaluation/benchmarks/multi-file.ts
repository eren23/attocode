/**
 * Lesson 26: Multi-File Benchmark
 *
 * Tasks that require coordinating changes across multiple files.
 * Tests ability to understand project structure and maintain consistency.
 */

import { task, suite } from '../benchmark-schema.js';
import type { BenchmarkSuite } from '../../types.js';

// =============================================================================
// TASK DEFINITIONS
// =============================================================================

const extractInterface = task()
  .id('multi-file-001')
  .name('Extract Interface')
  .category('multi-file')
  .difficulty('medium')
  .prompt(`The file user-service.ts has a UserService class with methods.

Extract an interface called \`IUserService\` into a new file \`user-service.interface.ts\`, then update the class to implement it.

Requirements:
1. Create user-service.interface.ts with the IUserService interface
2. The interface should include all public methods: getUser, createUser, deleteUser
3. Update UserService to implement IUserService
4. The tests should still pass`)
  .setupFiles({
    'user-service.ts': `
/**
 * Service for managing users.
 */
export class UserService {
  private users: Map<string, { id: string; name: string; email: string }> = new Map();

  async getUser(id: string): Promise<{ id: string; name: string; email: string } | null> {
    return this.users.get(id) ?? null;
  }

  async createUser(name: string, email: string): Promise<{ id: string; name: string; email: string }> {
    const id = Math.random().toString(36).slice(2);
    const user = { id, name, email };
    this.users.set(id, user);
    return user;
  }

  async deleteUser(id: string): Promise<boolean> {
    return this.users.delete(id);
  }
}
`,
    'user-service.test.ts': `
import { UserService } from './user-service.js';

describe('UserService', () => {
  let service: UserService;

  beforeEach(() => {
    service = new UserService();
  });

  test('creates and retrieves user', async () => {
    const user = await service.createUser('Alice', 'alice@test.com');
    expect(user.name).toBe('Alice');
    expect(user.email).toBe('alice@test.com');

    const retrieved = await service.getUser(user.id);
    expect(retrieved).toEqual(user);
  });

  test('returns null for unknown user', async () => {
    const result = await service.getUser('unknown');
    expect(result).toBeNull();
  });

  test('deletes user', async () => {
    const user = await service.createUser('Bob', 'bob@test.com');
    const deleted = await service.deleteUser(user.id);
    expect(deleted).toBe(true);

    const retrieved = await service.getUser(user.id);
    expect(retrieved).toBeNull();
  });
});
`,
    'package.json': `{
  "name": "benchmark-extract-interface",
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
  .expectFileContains('user-service.interface.ts', ['export interface IUserService', 'getUser', 'createUser', 'deleteUser'])
  .expectFileContains('user-service.ts', ['implements IUserService'])
  .timeout(90000)
  .maxIterations(7)
  .tags('medium', 'multi-file', 'refactor', 'interface')
  .build();

const splitModule = task()
  .id('multi-file-002')
  .name('Split Module')
  .category('multi-file')
  .difficulty('hard')
  .prompt(`The file utils.ts contains multiple unrelated utilities mixed together.

Split it into organized modules:
1. Create string-utils.ts with string functions (capitalize, truncate)
2. Create array-utils.ts with array functions (unique, chunk)
3. Create index.ts that re-exports everything from both modules
4. Delete the original utils.ts

The tests import from './utils.js' - update index.ts so tests still pass.`)
  .setupFiles({
    'utils.ts': `
/**
 * Mixed utilities - needs organization.
 */

// String utilities
export function capitalize(str: string): string {
  if (!str) return str;
  return str.charAt(0).toUpperCase() + str.slice(1);
}

export function truncate(str: string, maxLength: number): string {
  if (str.length <= maxLength) return str;
  return str.slice(0, maxLength - 3) + '...';
}

// Array utilities
export function unique<T>(arr: T[]): T[] {
  return [...new Set(arr)];
}

export function chunk<T>(arr: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let i = 0; i < arr.length; i += size) {
    chunks.push(arr.slice(i, i + size));
  }
  return chunks;
}
`,
    'utils.test.ts': `
import { capitalize, truncate, unique, chunk } from './index.js';

describe('String Utils', () => {
  test('capitalize', () => {
    expect(capitalize('hello')).toBe('Hello');
    expect(capitalize('')).toBe('');
  });

  test('truncate', () => {
    expect(truncate('hello world', 8)).toBe('hello...');
    expect(truncate('short', 10)).toBe('short');
  });
});

describe('Array Utils', () => {
  test('unique', () => {
    expect(unique([1, 2, 2, 3, 3, 3])).toEqual([1, 2, 3]);
  });

  test('chunk', () => {
    expect(chunk([1, 2, 3, 4, 5], 2)).toEqual([[1, 2], [3, 4], [5]]);
  });
});
`,
    'package.json': `{
  "name": "benchmark-split-module",
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
  .expectFileContains('string-utils.ts', ['export function capitalize', 'export function truncate'])
  .expectFileContains('array-utils.ts', ['export function unique', 'export function chunk'])
  .expectFileContains('index.ts', ['string-utils', 'array-utils'])
  .expectFileNotContains('index.ts', ['function capitalize', 'function truncate', 'function unique', 'function chunk'])
  .timeout(120000)
  .maxIterations(10)
  .tags('hard', 'multi-file', 'refactor', 'organization')
  .build();

const addSharedUtility = task()
  .id('multi-file-003')
  .name('Add Shared Utility')
  .category('multi-file')
  .difficulty('medium')
  .prompt(`Two service files have duplicated validation logic.

Create a shared validation utility and update both services to use it:
1. Create validators.ts with a validateEmail function
2. Update user-service.ts to use validateEmail
3. Update newsletter-service.ts to use validateEmail
4. Remove the duplicated isValidEmail functions from both services

The tests should pass after your changes.`)
  .setupFiles({
    'user-service.ts': `
/**
 * User management service.
 */
export class UserService {
  // Duplicated validation - should be extracted
  private isValidEmail(email: string): boolean {
    return /^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/.test(email);
  }

  createUser(email: string): { email: string; valid: boolean } {
    const valid = this.isValidEmail(email);
    return { email, valid };
  }
}
`,
    'newsletter-service.ts': `
/**
 * Newsletter subscription service.
 */
export class NewsletterService {
  private subscribers: Set<string> = new Set();

  // Duplicated validation - should be extracted
  private isValidEmail(email: string): boolean {
    return /^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/.test(email);
  }

  subscribe(email: string): { success: boolean; message: string } {
    if (!this.isValidEmail(email)) {
      return { success: false, message: 'Invalid email' };
    }
    this.subscribers.add(email);
    return { success: true, message: 'Subscribed' };
  }
}
`,
    'services.test.ts': `
import { UserService } from './user-service.js';
import { NewsletterService } from './newsletter-service.js';
import { validateEmail } from './validators.js';

describe('validators', () => {
  test('validateEmail works correctly', () => {
    expect(validateEmail('test@example.com')).toBe(true);
    expect(validateEmail('invalid')).toBe(false);
    expect(validateEmail('@missing.com')).toBe(false);
  });
});

describe('UserService', () => {
  test('validates email on create', () => {
    const service = new UserService();
    expect(service.createUser('valid@test.com').valid).toBe(true);
    expect(service.createUser('invalid').valid).toBe(false);
  });
});

describe('NewsletterService', () => {
  test('validates email on subscribe', () => {
    const service = new NewsletterService();
    expect(service.subscribe('valid@test.com').success).toBe(true);
    expect(service.subscribe('invalid').success).toBe(false);
  });
});
`,
    'package.json': `{
  "name": "benchmark-shared-utility",
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
  .expectFileContains('validators.ts', ['export function validateEmail'])
  .expectFileContains('user-service.ts', ['validateEmail'])
  .expectFileContains('newsletter-service.ts', ['validateEmail'])
  .expectFileNotContains('user-service.ts', ['private isValidEmail'])
  .expectFileNotContains('newsletter-service.ts', ['private isValidEmail'])
  .timeout(90000)
  .maxIterations(7)
  .tags('medium', 'multi-file', 'refactor', 'dry')
  .build();

// =============================================================================
// SUITE EXPORT
// =============================================================================

export const multiFileSuite: BenchmarkSuite = suite()
  .id('multi-file')
  .name('Multi-File Tasks')
  .description('Tasks that require coordinating changes across multiple files')
  .addTasks(extractInterface, splitModule, addSharedUtility)
  .metadata({
    version: '1.0.0',
    author: 'Lesson 26',
    estimatedDuration: '10-15 minutes',
  })
  .build();

export default multiFileSuite;
