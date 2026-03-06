/**
 * Tests for environment-facts.ts
 *
 * Verifies the core grounding module that provides temporal, platform,
 * and project context to all agents.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import {
  getEnvironmentFacts,
  refreshEnvironmentFacts,
  formatFactsBlock,
  formatFactsCompact,
} from '../src/integrations/utilities/environment-facts.js';

describe('getEnvironmentFacts', () => {
  beforeEach(() => {
    // Force refresh to avoid stale singleton
    refreshEnvironmentFacts();
  });

  it('returns object with required fields', () => {
    const facts = getEnvironmentFacts();

    expect(facts.currentDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(facts.currentYear).toBeGreaterThanOrEqual(2025);
    expect(facts.currentMonth).toBeTruthy();
    expect(facts.workingDirectory).toBeTruthy();
    expect(facts.platform).toBeTruthy();
    expect(facts.arch).toBeTruthy();
    expect(facts.nodeVersion).toMatch(/^v\d+/);
    expect(facts.custom).toEqual([]);
  });

  it('returns correct year and month', () => {
    const facts = getEnvironmentFacts();
    const now = new Date();

    expect(facts.currentYear).toBe(now.getFullYear());
    // Month name should be valid
    const validMonths = [
      'January', 'February', 'March', 'April', 'May', 'June',
      'July', 'August', 'September', 'October', 'November', 'December',
    ];
    expect(validMonths).toContain(facts.currentMonth);
  });

  it('includes custom facts when provided', () => {
    const customFacts = ['Project uses React 19', 'TypeScript strict mode'];
    const facts = getEnvironmentFacts(customFacts);

    expect(facts.custom).toEqual(customFacts);
    expect(facts.custom).toHaveLength(2);
  });

  it('caches result on subsequent calls without customFacts', () => {
    const first = getEnvironmentFacts();
    const second = getEnvironmentFacts();

    // Should be the same reference (cached singleton)
    expect(first).toBe(second);
  });

  it('refreshes when customFacts provided', () => {
    getEnvironmentFacts();
    const second = getEnvironmentFacts(['new fact']);

    // Custom facts should update
    expect(second.custom).toEqual(['new fact']);
  });
});

describe('refreshEnvironmentFacts', () => {
  it('clears cache and returns fresh facts', () => {
    getEnvironmentFacts(['old fact']);
    const refreshed = refreshEnvironmentFacts();

    // Refreshed should have empty custom (no custom facts passed)
    expect(refreshed.custom).toEqual([]);
  });

  it('accepts custom facts on refresh', () => {
    const refreshed = refreshEnvironmentFacts(['refreshed fact']);
    expect(refreshed.custom).toEqual(['refreshed fact']);
  });
});

describe('formatFactsBlock', () => {
  it('produces multiline block with headers', () => {
    const facts = getEnvironmentFacts();
    const block = formatFactsBlock(facts);

    expect(block).toContain('ENVIRONMENT FACTS');
    expect(block).toContain("Today's date:");
    expect(block).toContain('Working directory:');
    expect(block).toContain('Platform:');
    expect(block).toContain(String(facts.currentYear));
    expect(block).toContain('IMPORTANT:');
  });

  it('includes custom facts when present', () => {
    const facts = getEnvironmentFacts(['Custom context line']);
    const block = formatFactsBlock(facts);

    expect(block).toContain('Additional context:');
    expect(block).toContain('Custom context line');
  });

  it('omits custom section when no custom facts', () => {
    refreshEnvironmentFacts();
    const facts = getEnvironmentFacts();
    const block = formatFactsBlock(facts);

    expect(block).not.toContain('Additional context:');
  });

  it('uses auto-populated facts when called without arguments', () => {
    refreshEnvironmentFacts();
    const block = formatFactsBlock();

    expect(block).toContain('ENVIRONMENT FACTS');
    expect(block).toContain("Today's date:");
  });
});

describe('formatFactsCompact', () => {
  it('produces single-line summary', () => {
    const facts = getEnvironmentFacts();
    const compact = formatFactsCompact(facts);

    // Should be a single line (no newlines)
    expect(compact.includes('\n')).toBe(false);

    expect(compact).toContain('Current date:');
    expect(compact).toContain('Current year:');
    expect(compact).toContain('Working directory:');
    expect(compact).toContain(String(facts.currentYear));
  });

  it('uses auto-populated facts when called without arguments', () => {
    refreshEnvironmentFacts();
    const compact = formatFactsCompact();

    expect(compact).toContain('Current date:');
  });
});
