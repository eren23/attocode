/**
 * Thinking Strategy Tests
 *
 * Tests for thinking/reflection directives that guide LLMs
 * to use their internal reasoning for better planning and self-assessment.
 */

import { describe, it, expect } from 'vitest';
import {
  generateThinkingDirectives,
  getThinkingSystemPrompt,
  getSubagentQualityPrompt,
  createThinkingStrategy,
} from '../src/integrations/thinking-strategy.js';
import type { ComplexityTier } from '../src/integrations/complexity-classifier.js';

// =============================================================================
// generateThinkingDirectives
// =============================================================================

describe('generateThinkingDirectives', () => {
  it('returns empty directives for simple tier (below default minComplexityTier)', () => {
    const directive = generateThinkingDirectives('simple');
    expect(directive).toEqual({});
    expect(directive.preActionPrompt).toBeUndefined();
    expect(directive.postToolPrompt).toBeUndefined();
    expect(directive.qualityCheckPrompt).toBeUndefined();
  });

  it('returns all directive fields for medium tier', () => {
    const directive = generateThinkingDirectives('medium');
    expect(directive.preActionPrompt).toBeDefined();
    expect(directive.postToolPrompt).toBeDefined();
    expect(directive.qualityCheckPrompt).toBeDefined();
  });

  it('returns all directive fields for complex tier', () => {
    const directive = generateThinkingDirectives('complex');
    expect(directive.preActionPrompt).toBeDefined();
    expect(directive.postToolPrompt).toBeDefined();
    expect(directive.qualityCheckPrompt).toBeDefined();
  });

  it('returns all directive fields for deep_research tier', () => {
    const directive = generateThinkingDirectives('deep_research');
    expect(directive.preActionPrompt).toBeDefined();
    expect(directive.postToolPrompt).toBeDefined();
    expect(directive.qualityCheckPrompt).toBeDefined();
  });

  it('complex/deep_research tiers have more detailed pre-action prompt than medium', () => {
    const medium = generateThinkingDirectives('medium');
    const complex = generateThinkingDirectives('complex');
    const deep = generateThinkingDirectives('deep_research');

    expect(complex.preActionPrompt).toContain('subagent');
    expect(deep.preActionPrompt).toContain('subagent');
    expect(medium.preActionPrompt!.length).toBeLessThan(complex.preActionPrompt!.length);
  });

  it('respects custom minComplexityTier config', () => {
    const directive = generateThinkingDirectives('simple', { minComplexityTier: 'simple' });
    expect(directive.preActionPrompt).toBeDefined();
    expect(directive.postToolPrompt).toBeDefined();
    expect(directive.qualityCheckPrompt).toBeDefined();
  });

  it('returns empty when tier is below custom minComplexityTier', () => {
    const directive = generateThinkingDirectives('medium', { minComplexityTier: 'complex' });
    expect(directive).toEqual({});
  });

  it('respects enablePreTaskPlanning=false', () => {
    const directive = generateThinkingDirectives('complex', {
      enablePreTaskPlanning: false,
    });
    expect(directive.preActionPrompt).toBeUndefined();
    expect(directive.postToolPrompt).toBeDefined();
    expect(directive.qualityCheckPrompt).toBeDefined();
  });

  it('respects enablePostToolEvaluation=false', () => {
    const directive = generateThinkingDirectives('complex', {
      enablePostToolEvaluation: false,
    });
    expect(directive.preActionPrompt).toBeDefined();
    expect(directive.postToolPrompt).toBeUndefined();
    expect(directive.qualityCheckPrompt).toBeDefined();
  });

  it('respects enableQualityAssessment=false', () => {
    const directive = generateThinkingDirectives('complex', {
      enableQualityAssessment: false,
    });
    expect(directive.preActionPrompt).toBeDefined();
    expect(directive.postToolPrompt).toBeDefined();
    expect(directive.qualityCheckPrompt).toBeUndefined();
  });

  it('returns empty when all features are disabled', () => {
    const directive = generateThinkingDirectives('complex', {
      enablePreTaskPlanning: false,
      enablePostToolEvaluation: false,
      enableQualityAssessment: false,
    });
    expect(directive).toEqual({});
  });
});

// =============================================================================
// getThinkingSystemPrompt
// =============================================================================

describe('getThinkingSystemPrompt', () => {
  it('returns null for simple tier (no directives generated)', () => {
    const prompt = getThinkingSystemPrompt('simple');
    expect(prompt).toBeNull();
  });

  it('returns a string for medium tier', () => {
    const prompt = getThinkingSystemPrompt('medium');
    expect(prompt).not.toBeNull();
    expect(typeof prompt).toBe('string');
  });

  it('includes Thinking Guidelines header', () => {
    const prompt = getThinkingSystemPrompt('complex')!;
    expect(prompt).toContain('## Thinking Guidelines');
  });

  it('includes Before Acting section when preTaskPlanning is enabled', () => {
    const prompt = getThinkingSystemPrompt('complex')!;
    expect(prompt).toContain('### Before Acting');
  });

  it('includes After Tool Results section when postToolEvaluation is enabled', () => {
    const prompt = getThinkingSystemPrompt('complex')!;
    expect(prompt).toContain('### After Tool Results');
  });

  it('returns null when both pre-action and post-tool are disabled', () => {
    const prompt = getThinkingSystemPrompt('complex', {
      enablePreTaskPlanning: false,
      enablePostToolEvaluation: false,
    });
    expect(prompt).toBeNull();
  });

  it('returns null for tier below minComplexityTier', () => {
    const prompt = getThinkingSystemPrompt('medium', { minComplexityTier: 'complex' });
    expect(prompt).toBeNull();
  });
});

// =============================================================================
// getSubagentQualityPrompt
// =============================================================================

describe('getSubagentQualityPrompt', () => {
  it('returns a non-empty string', () => {
    const prompt = getSubagentQualityPrompt();
    expect(prompt).toBeTruthy();
    expect(typeof prompt).toBe('string');
    expect(prompt.length).toBeGreaterThan(50);
  });

  it('mentions evaluating work and addressing the objective', () => {
    const prompt = getSubagentQualityPrompt();
    expect(prompt).toContain('objective');
    expect(prompt).toContain('evaluate');
  });

  it('mentions flagging gaps or unresolved issues', () => {
    const prompt = getSubagentQualityPrompt();
    expect(prompt).toContain('gaps');
  });
});

// =============================================================================
// createThinkingStrategy
// =============================================================================

describe('createThinkingStrategy', () => {
  it('returns an object with all three methods', () => {
    const strategy = createThinkingStrategy();
    expect(strategy.generateDirectives).toBeTypeOf('function');
    expect(strategy.getSystemPrompt).toBeTypeOf('function');
    expect(strategy.getSubagentPrompt).toBeTypeOf('function');
  });

  it('generateDirectives respects config passed at creation', () => {
    const strategy = createThinkingStrategy({ minComplexityTier: 'complex' });
    const directive = strategy.generateDirectives('medium');
    expect(directive).toEqual({});
  });

  it('getSystemPrompt respects config passed at creation', () => {
    const strategy = createThinkingStrategy({ minComplexityTier: 'complex' });
    const prompt = strategy.getSystemPrompt('medium');
    expect(prompt).toBeNull();
  });

  it('getSubagentPrompt returns the quality prompt', () => {
    const strategy = createThinkingStrategy();
    const prompt = strategy.getSubagentPrompt();
    expect(prompt).toBe(getSubagentQualityPrompt());
  });
});

// =============================================================================
// Tier ordering
// =============================================================================

describe('complexity tier ordering', () => {
  const tiers: ComplexityTier[] = ['simple', 'medium', 'complex', 'deep_research'];

  it('each higher tier generates directives when lower tiers do not', () => {
    for (const tier of tiers) {
      const directive = generateThinkingDirectives(tier, { minComplexityTier: 'complex' });
      if (tier === 'complex' || tier === 'deep_research') {
        expect(directive.preActionPrompt).toBeDefined();
      } else {
        expect(directive).toEqual({});
      }
    }
  });

  it('deep_research tier always generates directives with any minComplexityTier', () => {
    for (const minTier of tiers) {
      const directive = generateThinkingDirectives('deep_research', { minComplexityTier: minTier });
      expect(directive.preActionPrompt).toBeDefined();
    }
  });
});
