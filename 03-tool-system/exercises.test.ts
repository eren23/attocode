/**
 * Exercise Tests: Lesson 3 - JSON Validator Tool
 *
 * Run with: npm run test:lesson:3:exercise
 */

import { describe, it, expect } from 'vitest';
import { z } from 'zod';

// Import from answers for testing
import {
  createValidatorTool,
  formatZodErrors,
  validatorInputSchema,
} from './exercises/answers/exercise-1.js';

// =============================================================================
// TEST SCHEMAS
// =============================================================================

const userSchema = z.object({
  name: z.string().min(1, 'Name is required'),
  email: z.string().email('Invalid email format'),
  age: z.number().min(0, 'Age must be positive'),
});

const configSchema = z.object({
  debug: z.boolean(),
  maxRetries: z.number().int().min(0).max(10),
  timeout: z.number().positive(),
});

// =============================================================================
// TESTS: Tool Definition
// =============================================================================

describe('createValidatorTool', () => {
  describe('tool definition structure', () => {
    it('should create tool with correct name', () => {
      const tool = createValidatorTool('user', userSchema);
      expect(tool.name).toBe('validate_user');
    });

    it('should have descriptive description', () => {
      const tool = createValidatorTool('user', userSchema);
      expect(tool.description).toContain('user');
      expect(tool.description.toLowerCase()).toContain('valid');
    });

    it('should use validatorInputSchema as parameters', () => {
      const tool = createValidatorTool('user', userSchema);
      expect(tool.parameters).toBe(validatorInputSchema);
    });

    it('should be marked as safe', () => {
      const tool = createValidatorTool('user', userSchema);
      expect(tool.dangerLevel).toBe('safe');
    });

    it('should have async execute function', () => {
      const tool = createValidatorTool('user', userSchema);
      expect(typeof tool.execute).toBe('function');
    });
  });

  describe('validation of valid data', () => {
    it('should validate correct user data', async () => {
      const tool = createValidatorTool('user', userSchema);
      const result = await tool.execute({
        jsonData: JSON.stringify({
          name: 'Alice',
          email: 'alice@example.com',
          age: 30,
        }),
      });

      expect(result.success).toBe(true);
      expect(result.output.toLowerCase()).toContain('valid');
    });

    it('should validate correct config data', async () => {
      const tool = createValidatorTool('config', configSchema);
      const result = await tool.execute({
        jsonData: JSON.stringify({
          debug: true,
          maxRetries: 3,
          timeout: 5000,
        }),
      });

      expect(result.success).toBe(true);
    });
  });

  describe('validation of invalid data', () => {
    it('should reject missing required fields', async () => {
      const tool = createValidatorTool('user', userSchema);
      const result = await tool.execute({
        jsonData: JSON.stringify({
          name: 'Alice',
          // missing email and age
        }),
      });

      expect(result.success).toBe(false);
      expect(result.output.toLowerCase()).toContain('error');
    });

    it('should reject invalid email format', async () => {
      const tool = createValidatorTool('user', userSchema);
      const result = await tool.execute({
        jsonData: JSON.stringify({
          name: 'Alice',
          email: 'not-an-email',
          age: 30,
        }),
      });

      expect(result.success).toBe(false);
      expect(result.output).toContain('email');
    });

    it('should reject wrong types', async () => {
      const tool = createValidatorTool('user', userSchema);
      const result = await tool.execute({
        jsonData: JSON.stringify({
          name: 'Alice',
          email: 'alice@example.com',
          age: 'thirty', // should be number
        }),
      });

      expect(result.success).toBe(false);
    });

    it('should reject out-of-range values', async () => {
      const tool = createValidatorTool('config', configSchema);
      const result = await tool.execute({
        jsonData: JSON.stringify({
          debug: true,
          maxRetries: 100, // max is 10
          timeout: 5000,
        }),
      });

      expect(result.success).toBe(false);
    });
  });

  describe('invalid JSON handling', () => {
    it('should handle malformed JSON', async () => {
      const tool = createValidatorTool('user', userSchema);
      const result = await tool.execute({
        jsonData: '{ invalid json }',
      });

      expect(result.success).toBe(false);
      expect(result.output.toLowerCase()).toContain('json');
    });

    it('should handle empty string', async () => {
      const tool = createValidatorTool('user', userSchema);
      const result = await tool.execute({
        jsonData: '',
      });

      expect(result.success).toBe(false);
    });

    it('should handle non-object JSON', async () => {
      const tool = createValidatorTool('user', userSchema);
      const result = await tool.execute({
        jsonData: '"just a string"',
      });

      expect(result.success).toBe(false);
    });
  });
});

// =============================================================================
// TESTS: formatZodErrors helper
// =============================================================================

describe('formatZodErrors', () => {
  it('should format single error', () => {
    const result = userSchema.safeParse({ name: '', email: 'valid@email.com', age: 25 });
    if (!result.success) {
      const formatted = formatZodErrors(result.error);
      expect(formatted).toContain('name');
    }
  });

  it('should format multiple errors', () => {
    const result = userSchema.safeParse({});
    if (!result.success) {
      const formatted = formatZodErrors(result.error);
      expect(formatted).toContain('name');
      expect(formatted).toContain('email');
      expect(formatted).toContain('age');
    }
  });

  it('should include field paths', () => {
    const nestedSchema = z.object({
      user: z.object({
        profile: z.object({
          name: z.string().min(1),
        }),
      }),
    });

    const result = nestedSchema.safeParse({ user: { profile: { name: '' } } });
    if (!result.success) {
      const formatted = formatZodErrors(result.error);
      expect(formatted).toContain('user.profile.name');
    }
  });
});
