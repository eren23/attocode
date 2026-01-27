/**
 * Exercise Tests: Lesson 23 - Policy Matcher
 */
import { describe, it, expect } from 'vitest';
import { PolicyMatcher } from './exercises/answers/exercise-1.js';

describe('PolicyMatcher', () => {
  it('should return default policy for unknown tools', () => {
    const matcher = new PolicyMatcher('prompt');
    const result = matcher.evaluate({ name: 'unknown_tool', args: {} });
    expect(result.decision).toBe('prompt');
  });

  it('should apply rule default policy', () => {
    const matcher = new PolicyMatcher();
    matcher.addRule({ tool: 'read_file', defaultPolicy: 'allow' });

    const result = matcher.evaluate({ name: 'read_file', args: { path: '/tmp/file' } });
    expect(result.decision).toBe('allow');
  });

  it('should match conditions with exact strings', () => {
    const matcher = new PolicyMatcher();
    matcher.addRule({
      tool: 'bash',
      defaultPolicy: 'prompt',
      conditions: [
        { argMatch: { command: 'ls' }, policy: 'allow', reason: 'Safe list command' },
      ],
    });

    const result = matcher.evaluate({ name: 'bash', args: { command: 'ls' } });
    expect(result.decision).toBe('allow');
    expect(result.reason).toBe('Safe list command');
  });

  it('should match conditions with regex', () => {
    const matcher = new PolicyMatcher();
    matcher.addRule({
      tool: 'write_file',
      defaultPolicy: 'prompt',
      conditions: [
        { argMatch: { path: /^\/etc\// }, policy: 'forbidden', reason: 'System files protected' },
      ],
    });

    const result = matcher.evaluate({ name: 'write_file', args: { path: '/etc/passwd' } });
    expect(result.decision).toBe('forbidden');
  });

  it('should return default when no conditions match', () => {
    const matcher = new PolicyMatcher();
    matcher.addRule({
      tool: 'write_file',
      defaultPolicy: 'prompt',
      conditions: [
        { argMatch: { path: /^\/etc\// }, policy: 'forbidden', reason: 'System files' },
      ],
    });

    const result = matcher.evaluate({ name: 'write_file', args: { path: '/tmp/file' } });
    expect(result.decision).toBe('prompt');
  });
});
