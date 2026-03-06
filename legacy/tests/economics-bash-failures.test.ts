/**
 * Tests for bash failure cascade detection and production-parity test-fix cycle.
 */
import { describe, it, expect } from 'vitest';
import { createEconomicsManager, extractBashResult, STANDARD_BUDGET } from '../src/integrations/budget/economics.js';

describe('extractBashResult', () => {
  it('extracts success/output from bash tool result object', () => {
    const result = extractBashResult({ success: false, output: 'command not found', metadata: { exitCode: 127 } });
    expect(result.success).toBe(false);
    expect(result.output).toBe('command not found');
  });

  it('extracts success from truthy object', () => {
    const result = extractBashResult({ success: true, output: 'ok' });
    expect(result.success).toBe(true);
    expect(result.output).toBe('ok');
  });

  it('treats missing success as true', () => {
    const result = extractBashResult({ output: 'some output' });
    expect(result.success).toBe(true);
    expect(result.output).toBe('some output');
  });

  it('handles string result (legacy/test compatibility)', () => {
    const result = extractBashResult('FAILED: 3 tests');
    expect(result.success).toBe(true);
    expect(result.output).toBe('FAILED: 3 tests');
  });

  it('handles undefined result', () => {
    const result = extractBashResult(undefined);
    expect(result.success).toBe(true);
    expect(result.output).toBe('');
  });

  it('handles null result', () => {
    const result = extractBashResult(null);
    expect(result.success).toBe(true);
    expect(result.output).toBe('');
  });

  it('handles object with non-string output', () => {
    const result = extractBashResult({ success: false, output: 42 });
    expect(result.success).toBe(false);
    expect(result.output).toBe('');
  });
});

describe('Bash Failure Cascade', () => {
  it('3 consecutive bash failures → injected prompt', () => {
    const econ = createEconomicsManager({ ...STANDARD_BUDGET, softTokenLimit: 999999, softCostLimit: 999 });
    econ.recordToolCall('bash', { command: 'npm install foo' }, { success: false, output: 'ERR! 404' });
    econ.recordToolCall('bash', { command: 'yarn add foo' }, { success: false, output: 'Not found' });
    econ.recordToolCall('bash', { command: 'pnpm add foo' }, { success: false, output: 'Not found' });

    const phase = econ.getPhaseState();
    expect(phase.consecutiveBashFailures).toBe(3);

    const result = econ.checkBudget();
    expect(result.injectedPrompt).toContain('consecutive bash commands have failed');
  });

  it('successful bash resets failure count', () => {
    const econ = createEconomicsManager(STANDARD_BUDGET);
    econ.recordToolCall('bash', { command: 'ls bad' }, { success: false, output: 'No such file' });
    econ.recordToolCall('bash', { command: 'ls bad2' }, { success: false, output: 'No such file' });
    econ.recordToolCall('bash', { command: 'ls .' }, { success: true, output: 'file.ts' });

    expect(econ.getPhaseState().consecutiveBashFailures).toBe(0);
  });

  it('non-bash tool calls do not affect bash failure count', () => {
    const econ = createEconomicsManager(STANDARD_BUDGET);
    econ.recordToolCall('bash', { command: 'bad1' }, { success: false, output: '' });
    econ.recordToolCall('read_file', { path: '/x.ts' }); // Not bash — should not reset
    econ.recordToolCall('bash', { command: 'bad2' }, { success: false, output: '' });

    expect(econ.getPhaseState().consecutiveBashFailures).toBe(2);
  });

  it('interleaved bash success resets even with non-bash between', () => {
    const econ = createEconomicsManager(STANDARD_BUDGET);
    econ.recordToolCall('bash', { command: 'bad1' }, { success: false, output: '' });
    econ.recordToolCall('read_file', { path: '/x.ts' });
    econ.recordToolCall('bash', { command: 'good' }, { success: true, output: 'ok' });

    expect(econ.getPhaseState().consecutiveBashFailures).toBe(0);
  });

  it('does not count failures when result is undefined', () => {
    const econ = createEconomicsManager(STANDARD_BUDGET);
    // No result passed — shouldn't affect the count
    econ.recordToolCall('bash', { command: 'something' });
    expect(econ.getPhaseState().consecutiveBashFailures).toBe(0);
  });

  it('resets after cascade prompt is triggered', () => {
    const econ = createEconomicsManager({ ...STANDARD_BUDGET, softTokenLimit: 999999, softCostLimit: 999 });
    econ.recordToolCall('bash', { command: 'a' }, { success: false, output: '' });
    econ.recordToolCall('bash', { command: 'b' }, { success: false, output: '' });
    econ.recordToolCall('bash', { command: 'c' }, { success: false, output: '' });

    // Verify cascade detected
    expect(econ.checkBudget().injectedPrompt).toContain('consecutive bash commands have failed');

    // Successful command resets
    econ.recordToolCall('bash', { command: 'good' }, { success: true, output: 'ok' });
    expect(econ.getPhaseState().consecutiveBashFailures).toBe(0);
  });
});

describe('Test-Fix Cycle with object results (production parity)', () => {
  it('detects test failures from bash result objects', () => {
    const econ = createEconomicsManager({ ...STANDARD_BUDGET, softTokenLimit: 999999, softCostLimit: 999 });
    econ.recordToolCall('write_file', { path: '/fix.ts', content: 'fix' });

    // Pass bash result objects matching real bash.ts output
    econ.recordToolCall('bash', { command: 'npm test' },
      { success: false, output: 'FAILED: 3 tests\n1 failed, 2 passed', metadata: { exitCode: 1 } });
    econ.recordToolCall('edit_file', { path: '/fix.ts', content: 'fix2' });
    econ.recordToolCall('bash', { command: 'npm test --verbose' },
      { success: false, output: 'FAILED: 2 tests', metadata: { exitCode: 1 } });
    econ.recordToolCall('edit_file', { path: '/fix.ts', content: 'fix3' });
    econ.recordToolCall('bash', { command: 'npx jest' },
      { success: false, output: 'FAILED: 1 test', metadata: { exitCode: 1 } });

    const phase = econ.getPhaseState();
    expect(phase.consecutiveTestFailures).toBe(3);
    expect(phase.inTestFixCycle).toBe(true);

    const result = econ.checkBudget();
    expect(result.injectedPrompt).toContain('consecutive test failures');
  });

  it('passes test with object result containing PASSED', () => {
    const econ = createEconomicsManager(STANDARD_BUDGET);
    econ.recordToolCall('bash', { command: 'npm test' },
      { success: true, output: '10 passed\nAll tests PASSED', metadata: { exitCode: 0 } });

    const phase = econ.getPhaseState();
    expect(phase.lastTestPassed).toBe(true);
    expect(phase.consecutiveTestFailures).toBe(0);
    expect(phase.inTestFixCycle).toBe(false);
  });

  it('handles mixed pass/fail from object result', () => {
    const econ = createEconomicsManager(STANDARD_BUDGET);
    econ.recordToolCall('bash', { command: 'npm test' },
      { success: false, output: '5 passed, 2 failed', metadata: { exitCode: 1 } });

    const phase = econ.getPhaseState();
    expect(phase.lastTestPassed).toBe(false);
    expect(phase.consecutiveTestFailures).toBe(1);
  });

  it('string results still work for backward compatibility', () => {
    const econ = createEconomicsManager(STANDARD_BUDGET);
    econ.recordToolCall('bash', { command: 'npm test' }, 'FAILED: 3 tests');

    const phase = econ.getPhaseState();
    expect(phase.lastTestPassed).toBe(false);
    expect(phase.consecutiveTestFailures).toBe(1);
  });
});
