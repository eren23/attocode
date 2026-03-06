/**
 * Swarm Quality Gate Tests
 *
 * Tests for parseQualityResponse, checkArtifacts, evaluateWorkerOutput,
 * and buildQualityPrompt.
 */

import { describe, it, expect, vi } from 'vitest';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { evaluateWorkerOutput, runPreFlightChecks, runConcreteChecks, checkArtifacts } from '../../src/integrations/swarm/swarm-quality-gate.js';
import type { SwarmTask, SwarmTaskResult } from '../../src/integrations/swarm/types.js';
import type { LLMProvider } from '../../src/providers/types.js';

// =============================================================================
// Helpers
// =============================================================================

/**
 * Access the private parseQualityResponse function indirectly through evaluateWorkerOutput.
 * We test it by providing a mock LLM that returns formatted strings.
 */
function createMockProvider(responseContent: string): LLMProvider {
  return {
    chat: vi.fn().mockResolvedValue({ content: responseContent }),
    // Minimal stubs for the rest of the interface
    name: 'mock',
    listModels: vi.fn(),
    supportsStreaming: false,
    chatStream: vi.fn(),
  } as unknown as LLMProvider;
}

function makeTask(overrides: Partial<SwarmTask> = {}): SwarmTask {
  return {
    id: 'task-1',
    description: 'Implement login feature',
    type: 'implement',
    dependencies: [],
    status: 'dispatched',
    complexity: 5,
    wave: 0,
    attempts: 1,
    ...overrides,
  };
}

function makeResult(overrides: Partial<SwarmTaskResult> = {}): SwarmTaskResult {
  return {
    success: true,
    output: 'Implemented the login feature with OAuth2.',
    tokensUsed: 500,
    costUsed: 0.01,
    durationMs: 5000,
    model: 'test-model',
    toolCalls: 5,
    ...overrides,
  };
}

// =============================================================================
// parseQualityResponse tests (via evaluateWorkerOutput with mock provider)
// =============================================================================

describe('parseQualityResponse (via evaluateWorkerOutput)', () => {
  it('SCORE: 4 with FEEDBACK → score 4, passed true', async () => {
    const provider = createMockProvider('SCORE: 4\nFEEDBACK: Good work, covers requirements');
    const result = await evaluateWorkerOutput(provider, 'test-model', makeTask(), makeResult());

    expect(result.score).toBe(4);
    expect(result.passed).toBe(true);
    expect(result.feedback).toContain('Good work');
  });

  it('SCORE: 2 with FEEDBACK → score 2, passed false', async () => {
    const provider = createMockProvider('SCORE: 2\nFEEDBACK: Incomplete implementation');
    const result = await evaluateWorkerOutput(provider, 'test-model', makeTask(), makeResult());

    expect(result.score).toBe(2);
    expect(result.passed).toBe(false);
    expect(result.feedback).toContain('Incomplete');
  });

  it('score clamped to 1-5 range (SCORE: 0 → 1)', async () => {
    const provider = createMockProvider('SCORE: 0\nFEEDBACK: Terrible');
    const result = await evaluateWorkerOutput(provider, 'test-model', makeTask(), makeResult());

    expect(result.score).toBe(1);
    expect(result.passed).toBe(false);
  });

  it('score clamped to 1-5 range (SCORE: 10 → 5)', async () => {
    const provider = createMockProvider('SCORE: 10\nFEEDBACK: Perfect');
    const result = await evaluateWorkerOutput(provider, 'test-model', makeTask(), makeResult());

    expect(result.score).toBe(5);
    expect(result.passed).toBe(true);
  });

  it('missing SCORE → defaults to 3 (passes)', async () => {
    const provider = createMockProvider('The output looks acceptable overall.');
    const result = await evaluateWorkerOutput(provider, 'test-model', makeTask(), makeResult());

    expect(result.score).toBe(3);
    expect(result.passed).toBe(true);
  });

  it('missing FEEDBACK → falls back to content.slice(0, 200)', async () => {
    const provider = createMockProvider('SCORE: 4');
    const result = await evaluateWorkerOutput(provider, 'test-model', makeTask(), makeResult());

    expect(result.score).toBe(4);
    expect(result.passed).toBe(true);
    // Feedback falls back to content.slice(0, 200) which is "SCORE: 4"
    expect(result.feedback).toBe('SCORE: 4');
  });
});

// =============================================================================
// checkArtifacts tests (via evaluateWorkerOutput with real filesystem)
// =============================================================================

describe('checkArtifacts (via evaluateWorkerOutput)', () => {
  it('no target files → LLM is called (not auto-failed)', async () => {
    const provider = createMockProvider('SCORE: 4\nFEEDBACK: Good');
    const task = makeTask({ targetFiles: undefined });
    const result = await evaluateWorkerOutput(provider, 'test-model', task, makeResult());

    expect(result.score).toBe(4);
    expect(provider.chat).toHaveBeenCalled();
  });

  it('missing file → auto-fail score 1, no LLM call', async () => {
    const provider = createMockProvider('SCORE: 5\nFEEDBACK: Perfect');
    const task = makeTask({
      targetFiles: ['/tmp/nonexistent-quality-gate-test-file-12345.ts'],
    });

    const result = await evaluateWorkerOutput(provider, 'test-model', task, makeResult());

    expect(result.score).toBe(1);
    expect(result.passed).toBe(false);
    expect(result.feedback).toContain('empty or missing');
    // Should NOT have called the LLM since artifact check auto-failed
    expect(provider.chat).not.toHaveBeenCalled();
  });

  it('empty file (0 bytes) → auto-fail score 1', async () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'qg-test-'));
    const emptyFile = path.join(tmpDir, 'empty.ts');
    fs.writeFileSync(emptyFile, '');

    try {
      const provider = createMockProvider('SCORE: 5\nFEEDBACK: Perfect');
      const task = makeTask({ targetFiles: [emptyFile] });

      const result = await evaluateWorkerOutput(provider, 'test-model', task, makeResult());

      expect(result.score).toBe(1);
      expect(result.passed).toBe(false);
      expect(provider.chat).not.toHaveBeenCalled();
    } finally {
      fs.rmSync(tmpDir, { recursive: true });
    }
  });

  it('file with content → LLM is called (not auto-failed)', async () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'qg-test-'));
    const goodFile = path.join(tmpDir, 'good.ts');
    fs.writeFileSync(goodFile, 'export function login() { return true; }');

    try {
      const provider = createMockProvider('SCORE: 4\nFEEDBACK: Good implementation');
      const task = makeTask({ targetFiles: [goodFile] });

      const result = await evaluateWorkerOutput(provider, 'test-model', task, makeResult());

      expect(result.score).toBe(4);
      expect(result.passed).toBe(true);
      expect(provider.chat).toHaveBeenCalled();

      // Verify the prompt includes artifact info
      const chatCall = (provider.chat as ReturnType<typeof vi.fn>).mock.calls[0];
      const userMessage = chatCall[0].find((m: { role: string }) => m.role === 'user');
      expect(userMessage.content).toContain('ARTIFACT VERIFICATION');
      expect(userMessage.content).toContain('good.ts');
    } finally {
      fs.rmSync(tmpDir, { recursive: true });
    }
  });

  it('mixed files (some exist, some missing) → LLM is called', async () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'qg-test-'));
    const existingFile = path.join(tmpDir, 'exists.ts');
    fs.writeFileSync(existingFile, 'content here');
    const missingFile = path.join(tmpDir, 'missing.ts');

    try {
      const provider = createMockProvider('SCORE: 3\nFEEDBACK: Partial');
      const task = makeTask({ targetFiles: [existingFile, missingFile] });

      const result = await evaluateWorkerOutput(provider, 'test-model', task, makeResult());

      // Not auto-failed because not ALL empty — existingFile has content
      expect(provider.chat).toHaveBeenCalled();
      expect(result.score).toBe(3);
    } finally {
      fs.rmSync(tmpDir, { recursive: true });
    }
  });
});

// =============================================================================
// artifactAutoFail flag
// =============================================================================

describe('artifactAutoFail flag', () => {
  it('missing file → artifactAutoFail: true', async () => {
    const provider = createMockProvider('SCORE: 5\nFEEDBACK: Perfect');
    const task = makeTask({
      targetFiles: ['/tmp/nonexistent-quality-gate-autofail-test-12345.ts'],
    });

    const result = await evaluateWorkerOutput(provider, 'test-model', task, makeResult());

    expect(result.score).toBe(1);
    expect(result.passed).toBe(false);
    expect(result.artifactAutoFail).toBe(true);
  });

  it('no target files → artifactAutoFail is undefined (not auto-failed)', async () => {
    const provider = createMockProvider('SCORE: 4\nFEEDBACK: Good');
    const task = makeTask({ targetFiles: undefined });

    const result = await evaluateWorkerOutput(provider, 'test-model', task, makeResult());

    expect(result.artifactAutoFail).toBeUndefined();
  });

  it('file with content → artifactAutoFail is undefined', async () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'qg-autofail-'));
    const goodFile = path.join(tmpDir, 'good.ts');
    fs.writeFileSync(goodFile, 'export function login() { return true; }');

    try {
      const provider = createMockProvider('SCORE: 4\nFEEDBACK: Good');
      const task = makeTask({ targetFiles: [goodFile] });

      const result = await evaluateWorkerOutput(provider, 'test-model', task, makeResult());

      expect(result.artifactAutoFail).toBeUndefined();
      expect(result.score).toBe(4);
    } finally {
      fs.rmSync(tmpDir, { recursive: true });
    }
  });
});

// =============================================================================
// configurable qualityThreshold
// =============================================================================

describe('configurable qualityThreshold', () => {
  it('threshold=4 → score 3 fails', async () => {
    const provider = createMockProvider('SCORE: 3\nFEEDBACK: Acceptable');
    const result = await evaluateWorkerOutput(
      provider, 'test-model', makeTask(), makeResult(), undefined, 4,
    );

    expect(result.score).toBe(3);
    expect(result.passed).toBe(false);
  });

  it('threshold=4 → score 4 passes', async () => {
    const provider = createMockProvider('SCORE: 4\nFEEDBACK: Good');
    const result = await evaluateWorkerOutput(
      provider, 'test-model', makeTask(), makeResult(), undefined, 4,
    );

    expect(result.score).toBe(4);
    expect(result.passed).toBe(true);
  });

  it('threshold=2 → score 2 passes', async () => {
    const provider = createMockProvider('SCORE: 2\nFEEDBACK: Partial');
    const result = await evaluateWorkerOutput(
      provider, 'test-model', makeTask(), makeResult(), undefined, 2,
    );

    expect(result.score).toBe(2);
    expect(result.passed).toBe(true);
  });

  it('default threshold (3) → score 3 passes', async () => {
    const provider = createMockProvider('SCORE: 3\nFEEDBACK: OK');
    const result = await evaluateWorkerOutput(
      provider, 'test-model', makeTask(), makeResult(),
    );

    expect(result.score).toBe(3);
    expect(result.passed).toBe(true);
  });
});

// =============================================================================
// evaluateWorkerOutput error handling
// =============================================================================

describe('evaluateWorkerOutput error handling', () => {
  it('F7: LLM provider throws → default FAIL score 3 with gateError flag', async () => {
    const provider = {
      chat: vi.fn().mockRejectedValue(new Error('API timeout')),
      name: 'mock',
      listModels: vi.fn(),
      supportsStreaming: false,
      chatStream: vi.fn(),
    } as unknown as LLMProvider;

    const result = await evaluateWorkerOutput(provider, 'test-model', makeTask(), makeResult());

    expect(result.score).toBe(3);
    expect(result.passed).toBe(false);  // F7: was true, now false
    expect(result.gateError).toBe(true);
    expect(result.gateErrorMessage).toContain('API timeout');
    expect(result.feedback).toContain('failed');
  });
});

// =============================================================================
// buildQualityPrompt content
// =============================================================================

describe('buildQualityPrompt', () => {
  it('includes task description, type, output, and artifact report', async () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'qg-test-'));
    const file = path.join(tmpDir, 'impl.ts');
    fs.writeFileSync(file, 'export const x = 1;');

    try {
      const provider = createMockProvider('SCORE: 4\nFEEDBACK: Good');
      const task = makeTask({
        description: 'Build the auth module',
        type: 'implement',
        targetFiles: [file],
      });
      const taskResult = makeResult({ output: 'Created auth module with JWT' });

      await evaluateWorkerOutput(provider, 'test-model', task, taskResult);

      const chatCall = (provider.chat as ReturnType<typeof vi.fn>).mock.calls[0];
      const userMessage = chatCall[0].find((m: { role: string }) => m.role === 'user');
      const prompt = userMessage.content as string;

      expect(prompt).toContain('Build the auth module');
      expect(prompt).toContain('implement');
      expect(prompt).toContain('Created auth module with JWT');
      expect(prompt).toContain('ARTIFACT VERIFICATION');
      expect(prompt).toContain('impl.ts');
    } finally {
      fs.rmSync(tmpDir, { recursive: true });
    }
  });

  it('includes closure report when present', async () => {
    const provider = createMockProvider('SCORE: 5\nFEEDBACK: Excellent');
    const taskResult = makeResult({
      output: 'Done',
      closureReport: {
        findings: ['Found the bug in auth.ts'],
        actionsTaken: ['Fixed the null check'],
        failures: [],
        remainingWork: [],
        exitReason: 'completed',
        suggestedNextSteps: [],
      },
    });

    await evaluateWorkerOutput(provider, 'test-model', makeTask(), taskResult);

    const chatCall = (provider.chat as ReturnType<typeof vi.fn>).mock.calls[0];
    const userMessage = chatCall[0].find((m: { role: string }) => m.role === 'user');
    const prompt = userMessage.content as string;

    expect(prompt).toContain('Found the bug in auth.ts');
    expect(prompt).toContain('Fixed the null check');
  });

  it('uses judgeConfig model and persona when provided', async () => {
    const provider = createMockProvider('SCORE: 4\nFEEDBACK: Good');

    await evaluateWorkerOutput(
      provider,
      'default-model',
      makeTask(),
      makeResult(),
      { model: 'judge-model', persona: 'You are a strict code reviewer.' },
    );

    const chatCall = (provider.chat as ReturnType<typeof vi.fn>).mock.calls[0];
    const options = chatCall[1];
    expect(options.model).toBe('judge-model');

    const systemMessage = chatCall[0].find((m: { role: string }) => m.role === 'system');
    expect(systemMessage.content).toContain('strict code reviewer');
  });
});

// =============================================================================
// runPreFlightChecks (direct tests)
// =============================================================================

describe('runPreFlightChecks', () => {
  it('returns null when all checks pass (no target files, has tool calls)', () => {
    const task = makeTask({ targetFiles: undefined });
    const result = makeResult({ toolCalls: 5 });
    expect(runPreFlightChecks(task, result)).toBeNull();
  });

  it('V4: rejects when all target files are missing', () => {
    const task = makeTask({
      targetFiles: ['/tmp/nonexistent-preflight-test-12345.ts'],
    });
    const result = makeResult();
    const preflight = runPreFlightChecks(task, result);

    expect(preflight).not.toBeNull();
    expect(preflight!.passed).toBe(false);
    expect(preflight!.score).toBe(1);
    expect(preflight!.preFlightReject).toBe(true);
    expect(preflight!.artifactAutoFail).toBe(true);
  });

  it('V9: rejects action task with zero tool calls', () => {
    const task = makeTask({ type: 'implement' });
    const result = makeResult({ toolCalls: 0 });
    const preflight = runPreFlightChecks(task, result);

    expect(preflight).not.toBeNull();
    expect(preflight!.passed).toBe(false);
    expect(preflight!.score).toBe(0);
    expect(preflight!.preFlightReject).toBe(true);
  });

  it('V9: passes non-action task with zero tool calls', () => {
    const task = makeTask({ type: 'research' });
    const result = makeResult({ toolCalls: 0 });
    expect(runPreFlightChecks(task, result)).toBeNull();
  });

  it('V10: rejects file-creation intent with no files and no tool calls', () => {
    const task = makeTask({
      type: 'research',
      description: 'Write to report/analysis.md',
    });
    const result = makeResult({ toolCalls: 0, filesModified: [] });
    const preflight = runPreFlightChecks(task, result);

    expect(preflight).not.toBeNull();
    expect(preflight!.passed).toBe(false);
    expect(preflight!.score).toBe(1);
    expect(preflight!.artifactAutoFail).toBe(true);
  });

  it('V6: rejects when closure report admits failure', () => {
    const task = makeTask({ type: 'research' });
    const result = makeResult({
      toolCalls: 3,
      closureReport: {
        findings: ['Unable to complete due to budget constraint'],
        actionsTaken: [],
        failures: ['no search performed'],
        remainingWork: [],
        exitReason: 'budget_exceeded',
        suggestedNextSteps: [],
      },
    });
    const preflight = runPreFlightChecks(task, result);

    expect(preflight).not.toBeNull();
    expect(preflight!.passed).toBe(false);
    expect(preflight!.score).toBe(1);
    expect(preflight!.preFlightReject).toBe(true);
  });
});

// =============================================================================
// F2: runConcreteChecks
// =============================================================================

describe('F2: runConcreteChecks', () => {
  it('passes when no files modified', () => {
    const task = makeTask({ type: 'implement' });
    const result = makeResult({ filesModified: [] });
    const concrete = runConcreteChecks(task, result);
    expect(concrete.passed).toBe(true);
    expect(concrete.issues).toHaveLength(0);
  });

  it('passes when modified files exist and are valid', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'concrete-test-'));
    const tsFile = path.join(tmpDir, 'valid.ts');
    fs.writeFileSync(tsFile, 'export const x = 1;\nfunction foo() {\n  return x;\n}\n');

    try {
      const task = makeTask({ type: 'implement' });
      const result = makeResult({ filesModified: [tsFile] });
      const concrete = runConcreteChecks(task, result);
      expect(concrete.passed).toBe(true);
    } finally {
      fs.rmSync(tmpDir, { recursive: true });
    }
  });

  it('fails when modified file is missing', () => {
    const task = makeTask({ type: 'implement' });
    const result = makeResult({ filesModified: ['/tmp/nonexistent-concrete-test-99999.ts'] });
    const concrete = runConcreteChecks(task, result);
    expect(concrete.passed).toBe(false);
    expect(concrete.issues[0]).toContain('missing');
  });

  it('fails when modified file is empty', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'concrete-test-'));
    const emptyFile = path.join(tmpDir, 'empty.ts');
    fs.writeFileSync(emptyFile, '');

    try {
      const task = makeTask({ type: 'implement' });
      const result = makeResult({ filesModified: [emptyFile] });
      const concrete = runConcreteChecks(task, result);
      expect(concrete.passed).toBe(false);
      expect(concrete.issues[0]).toContain('empty');
    } finally {
      fs.rmSync(tmpDir, { recursive: true });
    }
  });

  it('fails when JSON file has invalid syntax', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'concrete-test-'));
    const jsonFile = path.join(tmpDir, 'bad.json');
    fs.writeFileSync(jsonFile, '{ invalid json }');

    try {
      const task = makeTask({ type: 'implement' });
      const result = makeResult({ filesModified: [jsonFile] });
      const concrete = runConcreteChecks(task, result);
      expect(concrete.passed).toBe(false);
      expect(concrete.issues[0]).toContain('Invalid JSON');
    } finally {
      fs.rmSync(tmpDir, { recursive: true });
    }
  });

  it('fails when TS file has grossly unbalanced braces', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'concrete-test-'));
    const tsFile = path.join(tmpDir, 'unbalanced.ts');
    fs.writeFileSync(tsFile, 'function foo() {\n  if (true) {\n    if (false) {\n      if (true) {\n');

    try {
      const task = makeTask({ type: 'implement' });
      const result = makeResult({ filesModified: [tsFile] });
      const concrete = runConcreteChecks(task, result);
      expect(concrete.passed).toBe(false);
      expect(concrete.issues[0]).toContain('Unbalanced braces');
    } finally {
      fs.rmSync(tmpDir, { recursive: true });
    }
  });

  it('skips concrete checks for non-code task types', () => {
    const task = makeTask({ type: 'research' });
    const result = makeResult({ filesModified: ['/tmp/nonexistent-concrete-test-99999.ts'] });
    const concrete = runConcreteChecks(task, result);
    // Research tasks don't check file syntax
    expect(concrete.passed).toBe(true);
  });
});

// =============================================================================
// F9: checkArtifacts returns 2000-char previews
// =============================================================================

describe('F9: checkArtifacts preview length', () => {
  it('returns up to 2000 chars in preview for large files', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'f9-test-'));
    const largeFile = path.join(tmpDir, 'large.ts');
    // Create a file with 3000 chars of content
    const content = 'x'.repeat(3000);
    fs.writeFileSync(largeFile, content);

    try {
      const task = makeTask({ targetFiles: [largeFile] });
      const report = checkArtifacts(task);

      expect(report.files).toHaveLength(1);
      expect(report.files[0].preview.length).toBe(2000);
      expect(report.allEmpty).toBe(false);
    } finally {
      fs.rmSync(tmpDir, { recursive: true });
    }
  });

  it('returns full content when file is smaller than 2000 chars', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'f9-test-'));
    const smallFile = path.join(tmpDir, 'small.ts');
    const content = 'export const x = 1;';
    fs.writeFileSync(smallFile, content);

    try {
      const task = makeTask({ targetFiles: [smallFile] });
      const report = checkArtifacts(task);

      expect(report.files).toHaveLength(1);
      expect(report.files[0].preview).toBe(content);
    } finally {
      fs.rmSync(tmpDir, { recursive: true });
    }
  });

  it('judge prompt says "First 2000 chars" not "First 500 chars"', async () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'f9-prompt-'));
    const file = path.join(tmpDir, 'impl.ts');
    fs.writeFileSync(file, 'export const x = 1;');

    try {
      const provider = createMockProvider('SCORE: 4\nFEEDBACK: Good');
      const task = makeTask({ targetFiles: [file] });
      await evaluateWorkerOutput(provider, 'test-model', task, makeResult());

      const chatCall = (provider.chat as ReturnType<typeof vi.fn>).mock.calls[0];
      const userMessage = chatCall[0].find((m: { role: string }) => m.role === 'user');
      expect(userMessage.content).toContain('First 2000 chars');
      expect(userMessage.content).not.toContain('First 500 chars');
    } finally {
      fs.rmSync(tmpDir, { recursive: true });
    }
  });
});
