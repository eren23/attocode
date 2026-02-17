/**
 * Self-Improvement Protocol Tests
 */

import { describe, it, expect } from 'vitest';
import {
  SelfImprovementProtocol,
  createSelfImprovementProtocol,
} from '../src/integrations/quality/self-improvement.js';

describe('SelfImprovementProtocol', () => {
  describe('diagnoseToolFailure', () => {
    it('should diagnose file not found errors', () => {
      const p = new SelfImprovementProtocol();
      const d = p.diagnoseToolFailure('read_file', { path: '/x.ts' }, 'ENOENT: no such file or directory');
      expect(d.category).toBe('file_not_found');
      expect(d.diagnosis).toContain('does not exist');
    });

    it('should diagnose permission errors', () => {
      const p = new SelfImprovementProtocol();
      const d = p.diagnoseToolFailure('write_file', { path: '/etc/hosts' }, 'EACCES: permission denied');
      expect(d.category).toBe('permission');
    });

    it('should diagnose timeout errors', () => {
      const p = new SelfImprovementProtocol();
      const d = p.diagnoseToolFailure('bash', { command: 'x' }, 'operation timed out');
      expect(d.category).toBe('timeout');
    });

    it('should diagnose syntax errors', () => {
      const p = new SelfImprovementProtocol();
      const d = p.diagnoseToolFailure('bash', {}, 'syntax error near unexpected token');
      expect(d.category).toBe('syntax_error');
    });

    it('should diagnose missing args', () => {
      const p = new SelfImprovementProtocol();
      const d = p.diagnoseToolFailure('write_file', {}, 'required parameter "path" is missing');
      expect(d.category).toBe('missing_args');
    });

    it('should diagnose wrong args', () => {
      const p = new SelfImprovementProtocol();
      const d = p.diagnoseToolFailure('read_file', {}, 'invalid type: expected string, got number');
      expect(d.category).toBe('wrong_args');
    });

    it('should diagnose state errors', () => {
      const p = new SelfImprovementProtocol();
      const d = p.diagnoseToolFailure('edit_file', { old_text: 'x' }, 'not found in file, no match');
      expect(d.category).toBe('state_error');
      expect(d.suggestedFix).toContain('Re-read');
    });

    it('should return unknown for unrecognized errors', () => {
      const p = new SelfImprovementProtocol();
      const d = p.diagnoseToolFailure('tool', {}, 'totally random error');
      expect(d.category).toBe('unknown');
    });

    it('should track failure count', () => {
      const p = new SelfImprovementProtocol();
      p.diagnoseToolFailure('bash', {}, 'e1');
      p.diagnoseToolFailure('bash', {}, 'e2');
      p.diagnoseToolFailure('bash', {}, 'e3');
      expect(p.getFailureCount('bash')).toBe(3);
    });

    it('should bound the diagnosis cache', () => {
      const p = new SelfImprovementProtocol({ maxDiagnosisCache: 5 });
      for (let i = 0; i < 20; i++) {
        p.diagnoseToolFailure('t', {}, `error ${i}`);
      }
      expect(p.getFailureCount('t')).toBe(20);
    });
  });

  describe('recordSuccess', () => {
    it('should reset failure count', () => {
      const p = new SelfImprovementProtocol();
      p.diagnoseToolFailure('bash', {}, 'err');
      p.diagnoseToolFailure('bash', {}, 'err');
      p.recordSuccess('bash', { command: 'ls' }, 'ok');
      expect(p.getFailureCount('bash')).toBe(0);
    });

    it('should track patterns', () => {
      const p = new SelfImprovementProtocol();
      p.recordSuccess('read_file', { path: '/a' }, 'ctx');
      p.recordSuccess('read_file', { path: '/b' }, 'ctx');
      const patterns = p.getSuccessPatterns('read_file');
      expect(patterns.length).toBeGreaterThan(0);
      expect(patterns[0].count).toBe(2);
    });
  });

  describe('isRepeatedlyFailing', () => {
    it('should return false below threshold', () => {
      const p = new SelfImprovementProtocol();
      p.diagnoseToolFailure('t', {}, 'e');
      p.diagnoseToolFailure('t', {}, 'e');
      expect(p.isRepeatedlyFailing('t')).toBe(false);
    });

    it('should return true at 3+ failures', () => {
      const p = new SelfImprovementProtocol();
      for (let i = 0; i < 3; i++) p.diagnoseToolFailure('t', {}, 'e');
      expect(p.isRepeatedlyFailing('t')).toBe(true);
    });
  });

  describe('enhanceErrorMessage', () => {
    it('should add diagnosis info', () => {
      const p = new SelfImprovementProtocol();
      const msg = p.enhanceErrorMessage('read_file', 'ENOENT: no such file', { path: '/x' });
      expect(msg).toContain('ENOENT');
      expect(msg).toContain('Diagnosis');
      expect(msg).toContain('Suggested fix');
    });

    it('should skip when disabled', () => {
      const p = new SelfImprovementProtocol({ enableDiagnosis: false });
      expect(p.enhanceErrorMessage('t', 'error', {})).toBe('error');
    });

    it('should warn on repeated failures', () => {
      const p = new SelfImprovementProtocol();
      p.diagnoseToolFailure('t', {}, 'e');
      p.diagnoseToolFailure('t', {}, 'e');
      const msg = p.enhanceErrorMessage('t', 'e again', {});
      expect(msg).toContain('failed 3 times');
    });
  });
});

describe('createSelfImprovementProtocol', () => {
  it('should create with defaults', () => {
    expect(createSelfImprovementProtocol()).toBeInstanceOf(SelfImprovementProtocol);
  });
});
