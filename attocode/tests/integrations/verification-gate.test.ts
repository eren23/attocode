/**
 * Tests for VerificationGate - Opt-in Completion Verification
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { VerificationGate, createVerificationGate } from '../../src/integrations/tasks/verification-gate.js';

describe('VerificationGate', () => {
  describe('createVerificationGate', () => {
    it('should return null when no criteria provided', () => {
      expect(createVerificationGate(null)).toBeNull();
      expect(createVerificationGate(undefined)).toBeNull();
    });

    it('should return null when criteria are empty', () => {
      expect(createVerificationGate({})).toBeNull();
      expect(createVerificationGate({ requireFileChanges: false })).toBeNull();
    });

    it('should return a gate when tests are required', () => {
      const gate = createVerificationGate({ requiredTests: ['test_foo.py'] });
      expect(gate).toBeInstanceOf(VerificationGate);
    });

    it('should return a gate when file changes are required', () => {
      const gate = createVerificationGate({ requireFileChanges: true });
      expect(gate).toBeInstanceOf(VerificationGate);
    });
  });

  describe('check', () => {
    let gate: VerificationGate;

    beforeEach(() => {
      gate = new VerificationGate({
        requiredTests: ['tests/test_fix.py::test_regression'],
        requireFileChanges: true,
        maxAttempts: 2,
      });
    });

    it('should not be satisfied initially', () => {
      const result = gate.check();
      expect(result.satisfied).toBe(false);
      expect(result.forceAllow).toBe(false);
      expect(result.nudge).toBeDefined();
      expect(result.missing.length).toBeGreaterThan(0);
    });

    it('should require file changes', () => {
      gate.recordBashExecution('python -m pytest tests/test_fix.py::test_regression -xvs', '1 passed', 0);
      const result = gate.check();
      expect(result.satisfied).toBe(false);
      expect(result.missing).toContain('No file changes made');
    });

    it('should require test execution', () => {
      gate.recordFileChange();
      const result = gate.check();
      expect(result.satisfied).toBe(false);
      expect(result.missing).toContain('Required tests have not been run');
    });

    it('should be satisfied when all criteria met', () => {
      gate.recordFileChange();
      gate.recordBashExecution(
        'python -m pytest tests/test_fix.py::test_regression -xvs',
        '1 passed',
        0,
      );
      const result = gate.check();
      expect(result.satisfied).toBe(true);
      expect(result.forceAllow).toBe(false);
    });

    it('should detect test failures', () => {
      gate.recordFileChange();
      gate.recordBashExecution(
        'python -m pytest tests/test_fix.py -xvs',
        '1 failed',
        1,
      );
      const result = gate.check();
      expect(result.satisfied).toBe(false);
      expect(result.missing).toContain('Tests ran but none passed');
    });

    it('should force allow after max attempts', () => {
      // First nudge
      const r1 = gate.check();
      expect(r1.forceAllow).toBe(false);
      expect(r1.nudge).toBeDefined();

      // Second nudge
      const r2 = gate.check();
      expect(r2.forceAllow).toBe(false);
      expect(r2.nudge).toBeDefined();

      // Third check - should force allow (maxAttempts=2)
      const r3 = gate.check();
      expect(r3.forceAllow).toBe(true);
    });

    it('should include test command in nudge', () => {
      const result = gate.check();
      expect(result.nudge).toContain('python -m pytest');
      expect(result.nudge).toContain('test_regression');
    });
  });

  describe('getState', () => {
    it('should track state correctly', () => {
      const gate = new VerificationGate({
        requiredTests: ['test.py'],
        maxAttempts: 3,
      });

      expect(gate.getState().testsRun).toBe(0);
      expect(gate.getState().anyTestPassed).toBe(false);
      expect(gate.getState().maxAttempts).toBe(3);

      gate.recordBashExecution('python -m pytest test.py', '1 passed', 0);
      expect(gate.getState().testsRun).toBeGreaterThan(0);
      expect(gate.getState().anyTestPassed).toBe(true);
    });
  });

  describe('incrementCompilationNudge', () => {
    it('should increment compilationNudgeCount', () => {
      const gate = new VerificationGate({ requireCompilation: true });
      expect(gate.getState().compilationNudgeCount).toBe(0);

      gate.incrementCompilationNudge();
      expect(gate.getState().compilationNudgeCount).toBe(1);

      gate.incrementCompilationNudge();
      gate.incrementCompilationNudge();
      expect(gate.getState().compilationNudgeCount).toBe(3);
    });

    it('should cause forceAllow after reaching compilationMaxAttempts', () => {
      const gate = new VerificationGate({
        requireCompilation: true,
        compilationMaxAttempts: 3,
      });
      gate.recordCompilationResult(false, 5);

      // Nudge via incrementCompilationNudge (simulating TSC gate path)
      gate.incrementCompilationNudge();
      gate.incrementCompilationNudge();
      gate.incrementCompilationNudge();

      // Now check() should forceAllow since compilationNudgeCount >= 3
      const result = gate.check();
      expect(result.forceAllow).toBe(true);
    });
  });

  describe('reset', () => {
    it('should clear all state', () => {
      const gate = new VerificationGate({
        requiredTests: ['test.py'],
        requireFileChanges: true,
      });

      gate.recordFileChange();
      gate.recordBashExecution('python -m pytest test.py', '1 passed', 0);
      gate.check(); // Increment nudge count

      gate.reset();
      const state = gate.getState();
      expect(state.testsRun).toBe(0);
      expect(state.anyTestPassed).toBe(false);
      expect(state.hasFileChanges).toBe(false);
      expect(state.nudgeCount).toBe(0);
    });
  });
});
