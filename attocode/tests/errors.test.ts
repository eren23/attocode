/**
 * Tests for the centralized error types.
 */

import { describe, it, expect } from 'vitest';
import {
  ErrorCategory,
  AgentError,
  ToolError,
  MCPError,
  FileOperationError,
  ProviderError,
  ValidationError,
  CancellationError,
  ResourceError,
  categorizeError,
  wrapError,
  isAgentError,
  isRecoverable,
  isTransient,
  isRateLimited,
  formatError,
} from '../src/errors/index.js';

describe('Error Types', () => {
  describe('AgentError', () => {
    it('should create error with all properties', () => {
      const error = new AgentError(
        'Something went wrong',
        ErrorCategory.TRANSIENT,
        true,
        { key: 'value' }
      );

      expect(error.message).toBe('Something went wrong');
      expect(error.category).toBe(ErrorCategory.TRANSIENT);
      expect(error.recoverable).toBe(true);
      expect(error.context).toEqual({ key: 'value' });
      expect(error.timestamp).toBeInstanceOf(Date);
    });

    it('should serialize to JSON', () => {
      const error = new AgentError(
        'Test error',
        ErrorCategory.PERMANENT,
        false,
        { foo: 'bar' }
      );

      const json = error.toJSON();
      expect(json.name).toBe('AgentError');
      expect(json.message).toBe('Test error');
      expect(json.category).toBe(ErrorCategory.PERMANENT);
      expect(json.recoverable).toBe(false);
      expect(json.context).toEqual({ foo: 'bar' });
    });

    it('should format for logging', () => {
      const error = new AgentError(
        'Test error',
        ErrorCategory.TRANSIENT,
        true,
        { key: 'value' }
      );

      const logString = error.toLogString();
      expect(logString).toContain('[AgentError]');
      expect(logString).toContain('(TRANSIENT)');
      expect(logString).toContain('Test error');
      expect(logString).toContain('context=');
    });
  });

  describe('ToolError', () => {
    it('should include tool name', () => {
      const error = new ToolError(
        'Tool failed',
        ErrorCategory.PERMANENT,
        false,
        'read_file'
      );

      expect(error.toolName).toBe('read_file');
      expect(error.context.tool).toBe('read_file');
      expect(error.name).toBe('ToolError');
    });

    it('should create from generic error', () => {
      const original = new Error('ETIMEDOUT');
      const toolError = ToolError.fromError(original, 'bash');

      expect(toolError.toolName).toBe('bash');
      expect(toolError.category).toBe(ErrorCategory.TRANSIENT);
      expect(toolError.recoverable).toBe(true);
      expect(toolError.cause).toBe(original);
    });
  });

  describe('MCPError', () => {
    it('should include server name', () => {
      const error = new MCPError(
        'Server error',
        ErrorCategory.DEPENDENCY,
        true,
        'playwright'
      );

      expect(error.serverName).toBe('playwright');
      expect(error.name).toBe('MCPError');
    });

    it('should create serverNotFound error', () => {
      const error = MCPError.serverNotFound('unknown');

      expect(error.serverName).toBe('unknown');
      expect(error.category).toBe(ErrorCategory.PERMANENT);
      expect(error.recoverable).toBe(false);
    });

    it('should create serverNotConnected error', () => {
      const error = MCPError.serverNotConnected('playwright');

      expect(error.category).toBe(ErrorCategory.DEPENDENCY);
      expect(error.recoverable).toBe(true);
    });

    it('should create timeout error', () => {
      const error = MCPError.timeout('playwright', 'tools/call');

      expect(error.category).toBe(ErrorCategory.TRANSIENT);
      expect(error.recoverable).toBe(true);
      expect(error.method).toBe('tools/call');
    });
  });

  describe('FileOperationError', () => {
    it('should include path and operation', () => {
      const error = new FileOperationError(
        'File error',
        ErrorCategory.PERMANENT,
        false,
        '/tmp/test.txt',
        'read'
      );

      expect(error.path).toBe('/tmp/test.txt');
      expect(error.operation).toBe('read');
      expect(error.name).toBe('FileOperationError');
    });

    it('should create notFound error', () => {
      const error = FileOperationError.notFound('/missing.txt', 'read');

      expect(error.category).toBe(ErrorCategory.PERMANENT);
      expect(error.recoverable).toBe(false);
    });

    it('should create busy error (recoverable)', () => {
      const error = FileOperationError.busy('/locked.txt', 'write');

      expect(error.category).toBe(ErrorCategory.TRANSIENT);
      expect(error.recoverable).toBe(true);
    });
  });

  describe('ProviderError', () => {
    it('should include provider name', () => {
      const error = new ProviderError(
        'API error',
        ErrorCategory.TRANSIENT,
        true,
        'anthropic',
        { statusCode: 500 }
      );

      expect(error.providerName).toBe('anthropic');
      expect(error.statusCode).toBe(500);
    });

    it('should create rateLimited error', () => {
      const error = ProviderError.rateLimited('openai', 60);

      expect(error.category).toBe(ErrorCategory.RATE_LIMITED);
      expect(error.recoverable).toBe(true);
      expect(error.context.retryAfter).toBe(60);
    });

    it('should create authenticationFailed error', () => {
      const error = ProviderError.authenticationFailed('anthropic');

      expect(error.category).toBe(ErrorCategory.PERMANENT);
      expect(error.recoverable).toBe(false);
    });
  });

  describe('ValidationError', () => {
    it('should include field names', () => {
      const error = new ValidationError(
        'Invalid input',
        ['field1', 'field2']
      );

      expect(error.fields).toEqual(['field1', 'field2']);
      expect(error.category).toBe(ErrorCategory.VALIDATION);
      expect(error.recoverable).toBe(false);
    });

    it('should create from Zod-like error', () => {
      const zodError = {
        issues: [
          { path: ['name'], message: 'Required' },
          { path: ['age'], message: 'Must be positive' },
        ],
      };

      const error = ValidationError.fromZodError(zodError);

      expect(error.fields).toEqual(['name', 'age']);
      expect(error.message).toContain('name: Required');
      expect(error.message).toContain('age: Must be positive');
    });
  });

  describe('CancellationError', () => {
    it('should have cancelled category', () => {
      const error = new CancellationError('User cancelled');

      expect(error.category).toBe(ErrorCategory.CANCELLED);
      expect(error.recoverable).toBe(false);
      expect(error.reason).toBe('User cancelled');
    });
  });

  describe('ResourceError', () => {
    it('should include resource type and limits', () => {
      const error = new ResourceError('Memory exceeded', 'memory', 600, 512);

      expect(error.resourceType).toBe('memory');
      expect(error.usage).toBe(600);
      expect(error.limit).toBe(512);
    });

    it('should create memoryExceeded error', () => {
      const error = ResourceError.memoryExceeded(600, 512);

      expect(error.resourceType).toBe('memory');
      expect(error.message).toContain('600MB');
      expect(error.message).toContain('512MB');
    });

    it('should create tokenLimitExceeded error', () => {
      const error = ResourceError.tokenLimitExceeded(100000, 80000);

      expect(error.resourceType).toBe('tokens');
    });
  });

  describe('categorizeError', () => {
    it('should categorize timeout as transient', () => {
      const error = new Error('Request timeout');
      const result = categorizeError(error);

      expect(result.category).toBe(ErrorCategory.TRANSIENT);
      expect(result.recoverable).toBe(true);
    });

    it('should categorize ETIMEDOUT code as transient', () => {
      const error = new Error('Connection failed');
      (error as NodeJS.ErrnoException).code = 'ETIMEDOUT';
      const result = categorizeError(error);

      expect(result.category).toBe(ErrorCategory.TRANSIENT);
      expect(result.recoverable).toBe(true);
    });

    it('should categorize rate limit as rate limited', () => {
      const error = new Error('Rate limit exceeded');
      const result = categorizeError(error);

      expect(result.category).toBe(ErrorCategory.RATE_LIMITED);
      expect(result.recoverable).toBe(true);
    });

    it('should categorize auth errors as permanent', () => {
      const error = new Error('Unauthorized');
      const result = categorizeError(error);

      expect(result.category).toBe(ErrorCategory.PERMANENT);
      expect(result.recoverable).toBe(false);
    });

    it('should categorize validation errors', () => {
      const error = new Error('Invalid parameter: name is required');
      const result = categorizeError(error);

      expect(result.category).toBe(ErrorCategory.VALIDATION);
      expect(result.recoverable).toBe(false);
    });
  });

  describe('wrapError', () => {
    it('should return AgentError as-is', () => {
      const original = new AgentError('Test', ErrorCategory.TRANSIENT, true);
      const wrapped = wrapError(original);

      expect(wrapped).toBe(original);
    });

    it('should wrap generic Error', () => {
      const original = new Error('Generic error');
      const wrapped = wrapError(original, { key: 'value' });

      expect(wrapped).toBeInstanceOf(AgentError);
      expect(wrapped.message).toBe('Generic error');
      expect(wrapped.cause).toBe(original);
      expect(wrapped.context.key).toBe('value');
    });

    it('should wrap string as Error', () => {
      const wrapped = wrapError('String error');

      expect(wrapped).toBeInstanceOf(AgentError);
      expect(wrapped.message).toBe('String error');
    });
  });

  describe('Type guards', () => {
    it('isAgentError should identify AgentError', () => {
      expect(isAgentError(new AgentError('Test', ErrorCategory.TRANSIENT, true))).toBe(true);
      expect(isAgentError(new ToolError('Test', ErrorCategory.TRANSIENT, true, 'tool'))).toBe(true);
      expect(isAgentError(new Error('Test'))).toBe(false);
    });

    it('isRecoverable should check recoverability', () => {
      expect(isRecoverable(new AgentError('Test', ErrorCategory.TRANSIENT, true))).toBe(true);
      expect(isRecoverable(new AgentError('Test', ErrorCategory.PERMANENT, false))).toBe(false);
      expect(isRecoverable(new Error('timeout'))).toBe(true);
    });

    it('isTransient should identify transient errors', () => {
      expect(isTransient(new AgentError('Test', ErrorCategory.TRANSIENT, true))).toBe(true);
      expect(isTransient(new AgentError('Test', ErrorCategory.PERMANENT, false))).toBe(false);
      expect(isTransient(new Error('ETIMEDOUT'))).toBe(true);
    });

    it('isRateLimited should identify rate limited errors', () => {
      expect(isRateLimited(new AgentError('Test', ErrorCategory.RATE_LIMITED, true))).toBe(true);
      expect(isRateLimited(new Error('rate limit exceeded'))).toBe(true);
      expect(isRateLimited(new Error('generic error'))).toBe(false);
    });
  });

  describe('formatError', () => {
    it('should format AgentError', () => {
      const error = new ToolError('Tool failed', ErrorCategory.PERMANENT, false, 'bash');
      expect(formatError(error)).toBe('ToolError: Tool failed');
    });

    it('should format generic Error', () => {
      const error = new Error('Generic error');
      expect(formatError(error)).toBe('Generic error');
    });

    it('should format string', () => {
      expect(formatError('String error')).toBe('String error');
    });
  });
});
