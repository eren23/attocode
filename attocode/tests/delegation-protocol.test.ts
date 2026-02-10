/**
 * Delegation Protocol Tests
 *
 * Tests for structured delegation spec creation, prompt building,
 * and delegation instructions.
 */

import { describe, it, expect } from 'vitest';
import {
  buildDelegationPrompt,
  createMinimalDelegationSpec,
  DELEGATION_INSTRUCTIONS,
  type DelegationSpec,
} from '../src/integrations/delegation-protocol.js';

// =============================================================================
// buildDelegationPrompt TESTS
// =============================================================================

describe('buildDelegationPrompt', () => {
  it('should include the objective section', () => {
    const spec = createMinimalDelegationSpec('Fix the login bug');
    const prompt = buildDelegationPrompt(spec);

    expect(prompt).toContain('## OBJECTIVE');
    expect(prompt).toContain('Fix the login bug');
  });

  it('should include context when provided', () => {
    const spec: DelegationSpec = {
      objective: 'Refactor auth module',
      context: 'The auth module has grown too large and needs splitting',
      outputFormat: { type: 'code_changes' },
      toolGuidance: { recommended: ['edit_file'] },
      boundaries: {
        inScope: ['src/auth/'],
        outOfScope: ['src/database/'],
      },
      successCriteria: ['Auth module is split into smaller files'],
    };
    const prompt = buildDelegationPrompt(spec);

    expect(prompt).toContain('## CONTEXT');
    expect(prompt).toContain('The auth module has grown too large');
  });

  it('should include output format type', () => {
    const spec: DelegationSpec = {
      objective: 'Generate a report',
      context: '',
      outputFormat: { type: 'markdown_report' },
      toolGuidance: { recommended: [] },
      boundaries: { inScope: ['all'], outOfScope: [] },
      successCriteria: ['Report is complete'],
    };
    const prompt = buildDelegationPrompt(spec);

    expect(prompt).toContain('## EXPECTED OUTPUT');
    expect(prompt).toContain('Format: markdown_report');
  });

  it('should include output schema and example when provided', () => {
    const spec: DelegationSpec = {
      objective: 'Analyze dependencies',
      context: '',
      outputFormat: {
        type: 'structured_json',
        schema: '{ "deps": string[] }',
        example: '{ "deps": ["lodash", "express"] }',
      },
      toolGuidance: { recommended: [] },
      boundaries: { inScope: ['package.json'], outOfScope: [] },
      successCriteria: ['All deps listed'],
    };
    const prompt = buildDelegationPrompt(spec);

    expect(prompt).toContain('Schema:');
    expect(prompt).toContain('Example:');
  });

  it('should include recommended tools', () => {
    const spec: DelegationSpec = {
      objective: 'Search codebase',
      context: '',
      outputFormat: { type: 'free_text' },
      toolGuidance: { recommended: ['grep', 'glob', 'read_file'] },
      boundaries: { inScope: ['src/'], outOfScope: [] },
      successCriteria: ['Found results'],
    };
    const prompt = buildDelegationPrompt(spec);

    expect(prompt).toContain('## RECOMMENDED TOOLS');
    expect(prompt).toContain('- grep');
    expect(prompt).toContain('- glob');
    expect(prompt).toContain('- read_file');
  });

  it('should include tools to avoid with reasons', () => {
    const spec: DelegationSpec = {
      objective: 'Read-only analysis',
      context: '',
      outputFormat: { type: 'free_text' },
      toolGuidance: {
        recommended: ['read_file'],
        avoid: [
          { tool: 'write_file', reason: 'This is a read-only task' },
          { tool: 'bash', reason: 'No shell execution needed' },
        ],
      },
      boundaries: { inScope: ['src/'], outOfScope: [] },
      successCriteria: ['Analysis complete'],
    };
    const prompt = buildDelegationPrompt(spec);

    expect(prompt).toContain('## TOOLS TO AVOID');
    expect(prompt).toContain('- write_file: This is a read-only task');
    expect(prompt).toContain('- bash: No shell execution needed');
  });

  it('should include key sources', () => {
    const spec: DelegationSpec = {
      objective: 'Review config',
      context: '',
      outputFormat: { type: 'free_text' },
      toolGuidance: {
        recommended: ['read_file'],
        sources: ['tsconfig.json', 'package.json', '.eslintrc'],
      },
      boundaries: { inScope: ['config files'], outOfScope: [] },
      successCriteria: ['Config reviewed'],
    };
    const prompt = buildDelegationPrompt(spec);

    expect(prompt).toContain('## KEY SOURCES');
    expect(prompt).toContain('- tsconfig.json');
    expect(prompt).toContain('- package.json');
  });

  it('should include scope boundaries', () => {
    const spec: DelegationSpec = {
      objective: 'Fix tests',
      context: '',
      outputFormat: { type: 'code_changes' },
      toolGuidance: { recommended: ['edit_file'] },
      boundaries: {
        inScope: ['tests/', 'src/utils.ts'],
        outOfScope: ['src/main.ts', 'CI configuration'],
        maxExplorationDepth: 'moderate',
      },
      successCriteria: ['Tests pass'],
    };
    const prompt = buildDelegationPrompt(spec);

    expect(prompt).toContain('## SCOPE');
    expect(prompt).toContain('In scope:');
    expect(prompt).toContain('- tests/');
    expect(prompt).toContain('Out of scope:');
    expect(prompt).toContain('- src/main.ts');
    expect(prompt).toContain('Exploration depth: moderate');
  });

  it('should include numbered success criteria', () => {
    const spec: DelegationSpec = {
      objective: 'Implement feature',
      context: '',
      outputFormat: { type: 'code_changes' },
      toolGuidance: { recommended: [] },
      boundaries: { inScope: ['src/'], outOfScope: [] },
      successCriteria: [
        'Feature works as described',
        'Tests are added',
        'No regressions',
      ],
    };
    const prompt = buildDelegationPrompt(spec);

    expect(prompt).toContain('## SUCCESS CRITERIA');
    expect(prompt).toContain('1. Feature works as described');
    expect(prompt).toContain('2. Tests are added');
    expect(prompt).toContain('3. No regressions');
  });

  it('should include sibling context when provided', () => {
    const spec: DelegationSpec = {
      objective: 'Write backend tests',
      context: '',
      outputFormat: { type: 'code_changes' },
      toolGuidance: { recommended: ['write_file', 'bash'] },
      boundaries: { inScope: ['tests/'], outOfScope: [] },
      successCriteria: ['Tests pass'],
      siblingContext: {
        siblingTasks: [
          { agent: 'agent-1', task: 'Writing frontend tests' },
          { agent: 'agent-2', task: 'Refactoring shared utils' },
        ],
        claimedFiles: ['src/utils.ts', 'tests/utils.test.ts'],
      },
    };
    const prompt = buildDelegationPrompt(spec);

    expect(prompt).toContain('## SIBLING AGENTS');
    expect(prompt).toContain('agent-1: Writing frontend tests');
    expect(prompt).toContain('agent-2: Refactoring shared utils');
    expect(prompt).toContain('Claimed files (DO NOT modify)');
    expect(prompt).toContain('- src/utils.ts');
  });

  it('should not include recommended tools section when empty', () => {
    const spec: DelegationSpec = {
      objective: 'Do something',
      context: '',
      outputFormat: { type: 'free_text' },
      toolGuidance: { recommended: [] },
      boundaries: { inScope: ['everything'], outOfScope: [] },
      successCriteria: ['Done'],
    };
    const prompt = buildDelegationPrompt(spec);

    expect(prompt).not.toContain('## RECOMMENDED TOOLS');
  });
});

// =============================================================================
// createMinimalDelegationSpec TESTS
// =============================================================================

describe('createMinimalDelegationSpec', () => {
  it('should create a spec with the task as objective', () => {
    const spec = createMinimalDelegationSpec('Fix the bug in auth.ts');

    expect(spec.objective).toBe('Fix the bug in auth.ts');
  });

  it('should default to free_text output format', () => {
    const spec = createMinimalDelegationSpec('Some task');

    expect(spec.outputFormat.type).toBe('free_text');
  });

  it('should have empty context', () => {
    const spec = createMinimalDelegationSpec('Some task');

    expect(spec.context).toBe('');
  });

  it('should set the task as in-scope', () => {
    const spec = createMinimalDelegationSpec('Update the README');

    expect(spec.boundaries.inScope).toContain('Update the README');
  });

  it('should have a generic out-of-scope boundary', () => {
    const spec = createMinimalDelegationSpec('Some task');

    expect(spec.boundaries.outOfScope.length).toBeGreaterThan(0);
    expect(spec.boundaries.outOfScope[0]).toContain('outside');
  });

  it('should have a generic success criterion', () => {
    const spec = createMinimalDelegationSpec('Some task');

    expect(spec.successCriteria).toContain('Task objective is fully addressed');
  });

  it('should use researcher tools for researcher agent type', () => {
    const spec = createMinimalDelegationSpec('Analyze code', 'researcher');

    expect(spec.toolGuidance.recommended).toContain('read_file');
    expect(spec.toolGuidance.recommended).toContain('glob');
    expect(spec.toolGuidance.recommended).toContain('grep');
    expect(spec.toolGuidance.recommended).not.toContain('write_file');
  });

  it('should use coder tools for coder agent type', () => {
    const spec = createMinimalDelegationSpec('Write code', 'coder');

    expect(spec.toolGuidance.recommended).toContain('write_file');
    expect(spec.toolGuidance.recommended).toContain('edit_file');
    expect(spec.toolGuidance.recommended).toContain('bash');
  });

  it('should use reviewer tools for reviewer agent type', () => {
    const spec = createMinimalDelegationSpec('Review changes', 'reviewer');

    expect(spec.toolGuidance.recommended).toContain('read_file');
    expect(spec.toolGuidance.recommended).not.toContain('write_file');
  });

  it('should use debugger tools for debugger agent type', () => {
    const spec = createMinimalDelegationSpec('Debug issue', 'debugger');

    expect(spec.toolGuidance.recommended).toContain('bash');
    expect(spec.toolGuidance.recommended).toContain('edit_file');
  });

  it('should use default tools for unknown agent type', () => {
    const spec = createMinimalDelegationSpec('Do something', 'unknown_type');

    expect(spec.toolGuidance.recommended).toContain('read_file');
    expect(spec.toolGuidance.recommended).toContain('glob');
    expect(spec.toolGuidance.recommended).toContain('grep');
  });

  it('should use default tools when no agent type provided', () => {
    const spec = createMinimalDelegationSpec('Do something');

    expect(spec.toolGuidance.recommended).toContain('read_file');
    expect(spec.toolGuidance.recommended).toContain('glob');
    expect(spec.toolGuidance.recommended).toContain('grep');
  });
});

// =============================================================================
// DELEGATION_INSTRUCTIONS TESTS
// =============================================================================

describe('DELEGATION_INSTRUCTIONS', () => {
  it('should be a non-empty string', () => {
    expect(typeof DELEGATION_INSTRUCTIONS).toBe('string');
    expect(DELEGATION_INSTRUCTIONS.length).toBeGreaterThan(0);
  });

  it('should mention key delegation concepts', () => {
    expect(DELEGATION_INSTRUCTIONS).toContain('OBJECTIVE');
    expect(DELEGATION_INSTRUCTIONS).toContain('CONTEXT');
    expect(DELEGATION_INSTRUCTIONS).toContain('OUTPUT FORMAT');
    expect(DELEGATION_INSTRUCTIONS).toContain('BOUNDARIES');
    expect(DELEGATION_INSTRUCTIONS).toContain('SUCCESS CRITERIA');
  });

  it('should mention spawn_agent', () => {
    expect(DELEGATION_INSTRUCTIONS).toContain('spawn_agent');
  });

  it('should mention sibling agents', () => {
    expect(DELEGATION_INSTRUCTIONS).toContain('sibling');
  });
});

// =============================================================================
// Integration: buildDelegationPrompt + createMinimalDelegationSpec
// =============================================================================

describe('Integration: minimal spec -> prompt', () => {
  it('should produce a valid prompt from a minimal spec', () => {
    const spec = createMinimalDelegationSpec('Analyze the error handling patterns');
    const prompt = buildDelegationPrompt(spec);

    expect(prompt).toContain('## OBJECTIVE');
    expect(prompt).toContain('Analyze the error handling patterns');
    expect(prompt).toContain('## SCOPE');
    expect(prompt).toContain('## SUCCESS CRITERIA');
    // Minimal spec should not have sibling context
    expect(prompt).not.toContain('## SIBLING AGENTS');
  });

  it('should produce a valid prompt from a coder minimal spec', () => {
    const spec = createMinimalDelegationSpec('Implement a retry mechanism', 'coder');
    const prompt = buildDelegationPrompt(spec);

    expect(prompt).toContain('## RECOMMENDED TOOLS');
    expect(prompt).toContain('- write_file');
    expect(prompt).toContain('- edit_file');
    expect(prompt).toContain('- bash');
  });
});
