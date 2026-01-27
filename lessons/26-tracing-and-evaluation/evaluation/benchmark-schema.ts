/**
 * Lesson 26: Benchmark Schema
 *
 * Zod validation schemas for benchmark task definitions.
 * Ensures consistent task structure and validates task files.
 *
 * @example
 * ```typescript
 * import { validateTask, validateSuite } from './benchmark-schema.js';
 *
 * const result = validateTask(taskData);
 * if (!result.success) {
 *   console.error('Invalid task:', result.errors);
 * }
 * ```
 */

import type {
  BenchmarkTask,
  BenchmarkSuite,
  ExpectedOutcome,
  ValidationResult,
} from '../types.js';

// =============================================================================
// VALIDATION RESULT TYPES
// =============================================================================

/**
 * Result of schema validation.
 */
export interface SchemaValidationResult<T> {
  success: boolean;
  data?: T;
  errors?: string[];
}

// =============================================================================
// VALIDATORS
// =============================================================================

/**
 * Validate a benchmark task.
 */
export function validateTask(data: unknown): SchemaValidationResult<BenchmarkTask> {
  const errors: string[] = [];

  if (!data || typeof data !== 'object') {
    return { success: false, errors: ['Task must be an object'] };
  }

  const task = data as Record<string, unknown>;

  // Required fields
  if (typeof task.id !== 'string' || !task.id) {
    errors.push('id: must be a non-empty string');
  }

  if (typeof task.name !== 'string' || !task.name) {
    errors.push('name: must be a non-empty string');
  }

  const validCategories = ['function-completion', 'bug-fixing', 'file-editing', 'multi-file'];
  if (!validCategories.includes(task.category as string)) {
    errors.push(`category: must be one of ${validCategories.join(', ')}`);
  }

  const validDifficulties = ['easy', 'medium', 'hard'];
  if (!validDifficulties.includes(task.difficulty as string)) {
    errors.push(`difficulty: must be one of ${validDifficulties.join(', ')}`);
  }

  if (typeof task.prompt !== 'string' || !task.prompt) {
    errors.push('prompt: must be a non-empty string');
  }

  if (typeof task.timeout !== 'number' || task.timeout <= 0) {
    errors.push('timeout: must be a positive number');
  }

  // Validate expectedOutcome
  const outcomeResult = validateExpectedOutcome(task.expectedOutcome);
  if (!outcomeResult.success) {
    errors.push(...(outcomeResult.errors ?? []).map(e => `expectedOutcome.${e}`));
  }

  // Optional fields validation
  if (task.setupFiles !== undefined) {
    if (typeof task.setupFiles !== 'object' || task.setupFiles === null) {
      errors.push('setupFiles: must be an object');
    } else {
      for (const [path, content] of Object.entries(task.setupFiles as Record<string, unknown>)) {
        if (typeof content !== 'string') {
          errors.push(`setupFiles.${path}: content must be a string`);
        }
      }
    }
  }

  if (task.setupCommands !== undefined) {
    if (!Array.isArray(task.setupCommands)) {
      errors.push('setupCommands: must be an array');
    } else {
      for (let i = 0; i < (task.setupCommands as unknown[]).length; i++) {
        const cmd = (task.setupCommands as unknown[])[i] as Record<string, unknown>;
        if (typeof cmd.command !== 'string') {
          errors.push(`setupCommands[${i}].command: must be a string`);
        }
        if (!Array.isArray(cmd.args)) {
          errors.push(`setupCommands[${i}].args: must be an array`);
        }
      }
    }
  }

  if (task.maxIterations !== undefined && (typeof task.maxIterations !== 'number' || task.maxIterations <= 0)) {
    errors.push('maxIterations: must be a positive number');
  }

  if (task.tags !== undefined) {
    if (!Array.isArray(task.tags)) {
      errors.push('tags: must be an array of strings');
    } else {
      for (let i = 0; i < (task.tags as unknown[]).length; i++) {
        if (typeof (task.tags as unknown[])[i] !== 'string') {
          errors.push(`tags[${i}]: must be a string`);
        }
      }
    }
  }

  if (errors.length > 0) {
    return { success: false, errors };
  }

  return { success: true, data: task as unknown as BenchmarkTask };
}

/**
 * Validate expected outcome.
 */
export function validateExpectedOutcome(data: unknown): SchemaValidationResult<ExpectedOutcome> {
  const errors: string[] = [];

  if (!data || typeof data !== 'object') {
    return { success: false, errors: ['expectedOutcome: must be an object'] };
  }

  const outcome = data as Record<string, unknown>;

  const validTypes = ['test_pass', 'file_match', 'file_contains', 'file_not_contains', 'custom'];
  if (!validTypes.includes(outcome.type as string)) {
    errors.push(`type: must be one of ${validTypes.join(', ')}`);
    return { success: false, errors };
  }

  switch (outcome.type) {
    case 'test_pass':
      if (typeof outcome.testCommand !== 'string') {
        errors.push('testCommand: must be a string for test_pass type');
      }
      break;

    case 'file_match':
      if (typeof outcome.filePath !== 'string') {
        errors.push('filePath: must be a string for file_match type');
      }
      if (typeof outcome.pattern !== 'string' && !(outcome.pattern instanceof RegExp)) {
        errors.push('pattern: must be a string or RegExp for file_match type');
      }
      break;

    case 'file_contains':
    case 'file_not_contains':
      if (typeof outcome.filePath !== 'string') {
        errors.push('filePath: must be a string for file_contains/file_not_contains type');
      }
      if (!Array.isArray(outcome.content)) {
        errors.push('content: must be an array of strings');
      }
      break;

    case 'custom':
      if (typeof outcome.validator !== 'function') {
        errors.push('validator: must be a function for custom type');
      }
      break;
  }

  if (errors.length > 0) {
    return { success: false, errors };
  }

  return { success: true, data: outcome as ExpectedOutcome };
}

/**
 * Validate a benchmark suite.
 */
export function validateSuite(data: unknown): SchemaValidationResult<BenchmarkSuite> {
  const errors: string[] = [];

  if (!data || typeof data !== 'object') {
    return { success: false, errors: ['Suite must be an object'] };
  }

  const suite = data as Record<string, unknown>;

  // Required fields
  if (typeof suite.id !== 'string' || !suite.id) {
    errors.push('id: must be a non-empty string');
  }

  if (typeof suite.name !== 'string' || !suite.name) {
    errors.push('name: must be a non-empty string');
  }

  if (typeof suite.description !== 'string' || !suite.description) {
    errors.push('description: must be a non-empty string');
  }

  // Validate tasks array
  if (!Array.isArray(suite.tasks)) {
    errors.push('tasks: must be an array');
  } else {
    for (let i = 0; i < (suite.tasks as unknown[]).length; i++) {
      const taskResult = validateTask((suite.tasks as unknown[])[i]);
      if (!taskResult.success) {
        errors.push(...(taskResult.errors ?? []).map(e => `tasks[${i}].${e}`));
      }
    }
  }

  // Optional setup validation
  if (suite.setup !== undefined) {
    const setup = suite.setup as Record<string, unknown>;

    if (setup.files !== undefined) {
      if (typeof setup.files !== 'object' || setup.files === null) {
        errors.push('setup.files: must be an object');
      }
    }

    if (setup.commands !== undefined) {
      if (!Array.isArray(setup.commands)) {
        errors.push('setup.commands: must be an array');
      }
    }
  }

  if (errors.length > 0) {
    return { success: false, errors };
  }

  return { success: true, data: suite as unknown as BenchmarkSuite };
}

// =============================================================================
// TASK BUILDER
// =============================================================================

/**
 * Builder for creating benchmark tasks with validation.
 */
export class BenchmarkTaskBuilder {
  private task: Partial<BenchmarkTask> = {};

  id(id: string): this {
    this.task.id = id;
    return this;
  }

  name(name: string): this {
    this.task.name = name;
    return this;
  }

  category(category: BenchmarkTask['category']): this {
    this.task.category = category;
    return this;
  }

  difficulty(difficulty: BenchmarkTask['difficulty']): this {
    this.task.difficulty = difficulty;
    return this;
  }

  prompt(prompt: string): this {
    this.task.prompt = prompt;
    return this;
  }

  setupFiles(files: Record<string, string>): this {
    this.task.setupFiles = files;
    return this;
  }

  setupCommand(command: string, args: string[]): this {
    if (!this.task.setupCommands) {
      this.task.setupCommands = [];
    }
    this.task.setupCommands.push({ command, args });
    return this;
  }

  expectTestPass(testCommand: string, testArgs?: string[], testFile?: string): this {
    this.task.expectedOutcome = { type: 'test_pass', testCommand, testArgs, testFile };
    return this;
  }

  expectFileMatch(filePath: string, pattern: string | RegExp): this {
    this.task.expectedOutcome = { type: 'file_match', filePath, pattern };
    return this;
  }

  expectFileContains(filePath: string, content: string[]): this {
    this.task.expectedOutcome = { type: 'file_contains', filePath, content };
    return this;
  }

  expectFileNotContains(filePath: string, content: string[]): this {
    this.task.expectedOutcome = { type: 'file_not_contains', filePath, content };
    return this;
  }

  expectCustom(validator: (sandbox: any) => Promise<ValidationResult>): this {
    this.task.expectedOutcome = { type: 'custom', validator };
    return this;
  }

  timeout(ms: number): this {
    this.task.timeout = ms;
    return this;
  }

  maxIterations(max: number): this {
    this.task.maxIterations = max;
    return this;
  }

  tags(...tags: string[]): this {
    this.task.tags = tags;
    return this;
  }

  metadata(data: Record<string, unknown>): this {
    this.task.metadata = data;
    return this;
  }

  build(): BenchmarkTask {
    const result = validateTask(this.task);
    if (!result.success) {
      throw new Error(`Invalid task: ${result.errors?.join(', ')}`);
    }
    return result.data!;
  }
}

/**
 * Create a task builder.
 */
export function task(): BenchmarkTaskBuilder {
  return new BenchmarkTaskBuilder();
}

// =============================================================================
// SUITE BUILDER
// =============================================================================

/**
 * Builder for creating benchmark suites.
 */
export class BenchmarkSuiteBuilder {
  private suite: Partial<BenchmarkSuite> = { tasks: [] };

  id(id: string): this {
    this.suite.id = id;
    return this;
  }

  name(name: string): this {
    this.suite.name = name;
    return this;
  }

  description(description: string): this {
    this.suite.description = description;
    return this;
  }

  addTask(task: BenchmarkTask): this {
    this.suite.tasks!.push(task);
    return this;
  }

  addTasks(...tasks: BenchmarkTask[]): this {
    this.suite.tasks!.push(...tasks);
    return this;
  }

  setupFiles(files: Record<string, string>): this {
    if (!this.suite.setup) {
      this.suite.setup = {};
    }
    this.suite.setup.files = files;
    return this;
  }

  setupCommand(command: string, args: string[]): this {
    if (!this.suite.setup) {
      this.suite.setup = {};
    }
    if (!this.suite.setup.commands) {
      this.suite.setup.commands = [];
    }
    this.suite.setup.commands.push({ command, args });
    return this;
  }

  metadata(data: Record<string, unknown>): this {
    this.suite.metadata = data;
    return this;
  }

  build(): BenchmarkSuite {
    const result = validateSuite(this.suite);
    if (!result.success) {
      throw new Error(`Invalid suite: ${result.errors?.join(', ')}`);
    }
    return result.data!;
  }
}

/**
 * Create a suite builder.
 */
export function suite(): BenchmarkSuiteBuilder {
  return new BenchmarkSuiteBuilder();
}
