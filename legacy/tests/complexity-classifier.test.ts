/**
 * Complexity Classifier Tests
 *
 * Tests for heuristic-based task complexity assessment,
 * scaling guidance, and configurable classifiers.
 */

import { describe, it, expect } from 'vitest';
import {
  classifyComplexity,
  getScalingGuidance,
  createComplexityClassifier,
  type ComplexityAssessment,
} from '../src/integrations/agents/complexity-classifier.js';

// =============================================================================
// classifyComplexity TESTS
// =============================================================================

describe('classifyComplexity', () => {
  describe('simple tasks', () => {
    it('should classify a typo fix as simple', () => {
      const result = classifyComplexity('fix typo in README');

      expect(result.tier).toBe('simple');
    });

    it('should classify a rename as simple', () => {
      const result = classifyComplexity('rename the variable');

      expect(result.tier).toBe('simple');
    });

    it('should classify a question as simple', () => {
      const result = classifyComplexity('what is the purpose of utils.ts?');

      expect(result.tier).toBe('simple');
    });

    it('should classify removing unused imports as simple', () => {
      const result = classifyComplexity('remove unused imports');

      expect(result.tier).toBe('simple');
    });
  });

  describe('medium tasks', () => {
    it('should classify a moderate implementation task as medium', () => {
      const result = classifyComplexity('Add a new endpoint for user authentication with proper error handling');

      expect(['medium', 'complex']).toContain(result.tier);
    });
  });

  describe('complex tasks', () => {
    it('should classify a refactoring task as complex', () => {
      const result = classifyComplexity(
        'Refactor the entire authentication module across all files to use a new token-based system. ' +
        'First analyze the current implementation, then design the new approach, after that implement changes.'
      );

      expect(['complex', 'deep_research']).toContain(result.tier);
    });

    it('should classify a codebase-wide migration as medium or higher', () => {
      const result = classifyComplexity(
        'Migrate the entire codebase from CommonJS to ESM modules, updating every import and export statement'
      );

      expect(['medium', 'complex', 'deep_research']).toContain(result.tier);
    });
  });

  describe('deep research tasks', () => {
    it('should classify a comprehensive audit as high complexity', () => {
      const result = classifyComplexity(
        'Perform a comprehensive security audit across the entire codebase. First investigate all authentication flows, ' +
        'then analyze authorization patterns, after that review all API endpoints for vulnerabilities. ' +
        'Compare against OWASP top 10 and benchmark performance of each security layer.'
      );

      expect(['complex', 'deep_research']).toContain(result.tier);
    });
  });

  describe('assessment structure', () => {
    it('should return all required fields', () => {
      const result = classifyComplexity('some task');

      expect(result).toHaveProperty('tier');
      expect(result).toHaveProperty('confidence');
      expect(result).toHaveProperty('reasoning');
      expect(result).toHaveProperty('recommendation');
      expect(result).toHaveProperty('signals');
    });

    it('should have confidence between 0 and 1', () => {
      const result = classifyComplexity('fix a typo in the readme');

      expect(result.confidence).toBeGreaterThanOrEqual(0);
      expect(result.confidence).toBeLessThanOrEqual(1);
    });

    it('should have non-empty reasoning', () => {
      const result = classifyComplexity('refactor the auth module');

      expect(result.reasoning.length).toBeGreaterThan(0);
      expect(result.reasoning).toContain('Classified as');
    });

    it('should include signals array with expected properties', () => {
      const result = classifyComplexity('analyze the codebase');

      expect(result.signals.length).toBeGreaterThan(0);
      for (const signal of result.signals) {
        expect(signal).toHaveProperty('name');
        expect(signal).toHaveProperty('value');
        expect(signal).toHaveProperty('weight');
        expect(signal).toHaveProperty('description');
      }
    });
  });

  describe('recommendation structure', () => {
    it('should have agentCount with min and max', () => {
      const result = classifyComplexity('some task');

      expect(result.recommendation.agentCount).toHaveProperty('min');
      expect(result.recommendation.agentCount).toHaveProperty('max');
      expect(result.recommendation.agentCount.min).toBeLessThanOrEqual(result.recommendation.agentCount.max);
    });

    it('should have toolCallsPerAgent with min and max', () => {
      const result = classifyComplexity('some task');

      expect(result.recommendation.toolCallsPerAgent).toHaveProperty('min');
      expect(result.recommendation.toolCallsPerAgent).toHaveProperty('max');
    });

    it('should recommend swarm mode for complex tasks', () => {
      const result = classifyComplexity(
        'Redesign and refactor the entire system architecture across all modules. ' +
        'First investigate the current design, then plan the migration, after that implement step by step.'
      );

      if (result.tier === 'complex' || result.tier === 'deep_research') {
        expect(result.recommendation.useSwarmMode).toBe(true);
      }
    });

    it('should not recommend swarm mode for simple tasks', () => {
      const result = classifyComplexity('fix typo');

      expect(result.recommendation.useSwarmMode).toBe(false);
    });

    it('should have budgetMultiplier that scales with complexity', () => {
      const simple = classifyComplexity('fix typo');
      const complex = classifyComplexity(
        'Refactor the entire codebase and restructure all modules. First analyze, then redesign.'
      );

      expect(simple.recommendation.budgetMultiplier).toBeLessThanOrEqual(
        complex.recommendation.budgetMultiplier
      );
    });
  });

  describe('signal-specific tests', () => {
    it('should detect complex keywords', () => {
      const result = classifyComplexity('refactor the authentication system');
      const complexSignal = result.signals.find(s => s.name === 'complex_keywords');

      expect(complexSignal).toBeDefined();
      expect(complexSignal!.value).toBeGreaterThan(0);
    });

    it('should detect simple keywords', () => {
      const result = classifyComplexity('fix typo in the docs');
      const simpleSignal = result.signals.find(s => s.name === 'simple_keywords');

      expect(simpleSignal).toBeDefined();
      expect(simpleSignal!.value).toBeLessThan(0);
    });

    it('should detect dependency patterns', () => {
      const result = classifyComplexity('First analyze the code, then refactor the module');
      const depSignal = result.signals.find(s => s.name === 'dependency_patterns');

      expect(depSignal).toBeDefined();
      expect(depSignal!.value).toBeGreaterThan(0);
    });

    it('should detect questions vs actions', () => {
      const question = classifyComplexity('What is the purpose of this function?');
      const action = classifyComplexity('Implement a new caching layer');

      const qSignal = question.signals.find(s => s.name === 'question_vs_action');
      const aSignal = action.signals.find(s => s.name === 'question_vs_action');

      expect(qSignal!.value).toBeLessThan(aSignal!.value);
    });

    it('should detect file references', () => {
      const result = classifyComplexity('Update auth.ts and config.ts in src/');
      const scopeSignal = result.signals.find(s => s.name === 'scope_indicators');

      expect(scopeSignal).toBeDefined();
      expect(scopeSignal!.value).toBeGreaterThan(0);
    });

    it('should score longer tasks higher for task_length', () => {
      const short = classifyComplexity('fix bug');
      const long = classifyComplexity(
        'Analyze the entire authentication flow including session management, token refresh, ' +
        'password reset functionality, and two-factor authentication setup across all service modules'
      );

      const shortLen = short.signals.find(s => s.name === 'task_length')!;
      const longLen = long.signals.find(s => s.name === 'task_length')!;

      expect(longLen.value).toBeGreaterThan(shortLen.value);
    });
  });
});

// =============================================================================
// getScalingGuidance TESTS
// =============================================================================

describe('getScalingGuidance', () => {
  it('should return guidance for simple tasks', () => {
    const assessment = classifyComplexity('fix typo');
    const guidance = getScalingGuidance(assessment);

    expect(guidance).toContain('SIMPLE TASK');
    expect(guidance).toContain('no subagents');
  });

  it('should return guidance for medium tasks', () => {
    const assessment: ComplexityAssessment = {
      tier: 'medium',
      confidence: 0.8,
      reasoning: 'test',
      recommendation: {
        agentCount: { min: 1, max: 4 },
        toolCallsPerAgent: { min: 10, max: 20 },
        useSwarmMode: false,
        suggestedAgents: ['researcher', 'coder'],
        budgetMultiplier: 1.0,
        useExtendedThinking: false,
      },
      signals: [],
    };
    const guidance = getScalingGuidance(assessment);

    expect(guidance).toContain('MEDIUM TASK');
    expect(guidance).toContain('subagent');
  });

  it('should return guidance for complex tasks', () => {
    const assessment: ComplexityAssessment = {
      tier: 'complex',
      confidence: 0.7,
      reasoning: 'test',
      recommendation: {
        agentCount: { min: 3, max: 8 },
        toolCallsPerAgent: { min: 15, max: 30 },
        useSwarmMode: true,
        suggestedAgents: ['researcher', 'coder', 'reviewer'],
        budgetMultiplier: 2.0,
        useExtendedThinking: true,
      },
      signals: [],
    };
    const guidance = getScalingGuidance(assessment);

    expect(guidance).toContain('COMPLEX TASK');
    expect(guidance).toContain('delegation');
  });

  it('should return guidance for deep research tasks', () => {
    const assessment: ComplexityAssessment = {
      tier: 'deep_research',
      confidence: 0.6,
      reasoning: 'test',
      recommendation: {
        agentCount: { min: 5, max: 15 },
        toolCallsPerAgent: { min: 20, max: 50 },
        useSwarmMode: true,
        suggestedAgents: ['researcher', 'coder', 'reviewer', 'architect'],
        budgetMultiplier: 3.0,
        useExtendedThinking: true,
      },
      signals: [],
    };
    const guidance = getScalingGuidance(assessment);

    expect(guidance).toContain('DEEP RESEARCH');
    expect(guidance).toContain('swarm');
  });

  it('should include tool call ranges in guidance', () => {
    const assessment = classifyComplexity('fix typo');
    const guidance = getScalingGuidance(assessment);

    // Should mention the tool call range
    expect(guidance).toMatch(/\d+-\d+/);
  });
});

// =============================================================================
// createComplexityClassifier TESTS
// =============================================================================

describe('createComplexityClassifier', () => {
  it('should create a classifier with default config', () => {
    const classifier = createComplexityClassifier();

    expect(classifier).toHaveProperty('classify');
    expect(classifier).toHaveProperty('getScalingGuidance');
    expect(classifier).toHaveProperty('thresholds');
  });

  it('should classify tasks using the classify method', () => {
    const classifier = createComplexityClassifier();
    const result = classifier.classify('fix typo in readme');

    expect(result.tier).toBe('simple');
    expect(result).toHaveProperty('confidence');
    expect(result).toHaveProperty('recommendation');
  });

  it('should generate scaling guidance via the classifier', () => {
    const classifier = createComplexityClassifier();
    const assessment = classifier.classify('fix a typo');
    const guidance = classifier.getScalingGuidance(assessment);

    expect(typeof guidance).toBe('string');
    expect(guidance.length).toBeGreaterThan(0);
  });

  it('should accept custom thresholds', () => {
    const classifier = createComplexityClassifier({
      simpleThreshold: 1.0,
      mediumThreshold: 2.0,
      complexThreshold: 3.0,
    });

    expect(classifier.thresholds.simple).toBe(1.0);
    expect(classifier.thresholds.medium).toBe(2.0);
    expect(classifier.thresholds.complex).toBe(3.0);
  });

  it('should use default thresholds when not specified', () => {
    const classifier = createComplexityClassifier();

    expect(classifier.thresholds.simple).toBe(0.5);
    expect(classifier.thresholds.medium).toBe(1.5);
    expect(classifier.thresholds.complex).toBe(2.5);
  });
});

// =============================================================================
// Edge Cases
// =============================================================================

describe('Edge cases', () => {
  it('should handle empty task string', () => {
    const result = classifyComplexity('');

    expect(result.tier).toBeDefined();
    expect(result.signals.length).toBeGreaterThan(0);
  });

  it('should handle very long task strings', () => {
    const longTask = 'Refactor '.repeat(100) + 'all the things';
    const result = classifyComplexity(longTask);

    expect(result.tier).toBeDefined();
    expect(result.confidence).toBeGreaterThan(0);
  });

  it('should handle tasks with mixed signals', () => {
    // Contains both simple keywords and complex keywords
    const result = classifyComplexity('fix typo and then refactor the entire codebase');

    expect(result.tier).toBeDefined();
    // Should have both signal types
    const simpleSignal = result.signals.find(s => s.name === 'simple_keywords');
    const complexSignal = result.signals.find(s => s.name === 'complex_keywords');
    expect(simpleSignal).toBeDefined();
    expect(complexSignal).toBeDefined();
  });

  it('should produce deterministic results for same input', () => {
    const result1 = classifyComplexity('refactor the auth module');
    const result2 = classifyComplexity('refactor the auth module');

    expect(result1.tier).toBe(result2.tier);
    expect(result1.confidence).toBe(result2.confidence);
  });
});
