/**
 * Lesson 12: Rule Merger
 *
 * Combines rules from multiple sources into a unified rule set.
 * Handles priority ordering, deduplication, and conflict resolution.
 *
 * USER CONTRIBUTION OPPORTUNITY:
 * The merge strategy determines how conflicting rules are resolved.
 * You could implement strategies like:
 * - Weighted combination based on source trust
 * - Semantic deduplication (rules that mean the same thing)
 * - Context-aware merging (different rules for different scenarios)
 */

import type {
  Rule,
  RuleSet,
  RuleSetMetadata,
  RuleMergerConfig,
  MergeStrategy,
  InstructionSource,
  InstructionFile,
  RuleType,
  RuleLoadError,
  Scope,
} from './types.js';

// =============================================================================
// DEFAULT CONFIGURATION
// =============================================================================

const DEFAULT_CONFIG: RuleMergerConfig = {
  strategy: 'combine',
  deduplicate: true,
  includeSourceComments: true,
};

// =============================================================================
// RULE MERGER
// =============================================================================

/**
 * Merges rules from multiple sources into a unified rule set.
 */
export class RuleMerger {
  private config: RuleMergerConfig;

  constructor(config: Partial<RuleMergerConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  // =============================================================================
  // MAIN MERGE METHOD
  // =============================================================================

  /**
   * Merge rules from multiple parsed instruction files.
   *
   * @param files - Parsed instruction files with their sources
   * @returns Merged rule set
   */
  merge(
    files: Array<{ source: InstructionSource; file: InstructionFile }>,
    errors: RuleLoadError[] = []
  ): RuleSet {
    const startTime = performance.now();

    // Extract rules from all files
    const allRules: Rule[] = [];

    for (const { source, file } of files) {
      const rules = this.extractRules(source, file);
      allRules.push(...rules);
    }

    // Apply merge strategy
    let mergedRules = this.applyStrategy(allRules);

    // Deduplicate if enabled
    if (this.config.deduplicate) {
      mergedRules = this.deduplicateRules(mergedRules);
    }

    // Sort by priority
    mergedRules = this.sortByPriority(mergedRules);

    // Build system prompt
    const systemPrompt = this.buildPrompt(mergedRules);

    const metadata: RuleSetMetadata = {
      builtAt: new Date(),
      sourcesProcessed: files.length,
      sourcesWithErrors: errors.length,
      totalRules: allRules.length,
      mergedRules: mergedRules.length,
      errors,
      buildDurationMs: performance.now() - startTime,
    };

    return {
      sources: files.map((f) => f.source),
      loadedSources: files.map((f) => f.source),
      rules: mergedRules,
      systemPrompt,
      metadata,
    };
  }

  // =============================================================================
  // RULE EXTRACTION
  // =============================================================================

  /**
   * Extract rules from a parsed instruction file.
   */
  private extractRules(source: InstructionSource, file: InstructionFile): Rule[] {
    const rules: Rule[] = [];

    // Apply frontmatter overrides
    const scope = file.frontmatter?.scope ?? source.scope;
    const priority = file.frontmatter?.priority ?? source.priority;

    for (const section of file.sections) {
      // Skip empty sections
      if (!section.content.trim()) continue;

      rules.push({
        sourceId: source.id,
        content: section.content.trim(),
        type: section.ruleType,
        priority,
        scope,
        metadata: {
          tags: file.frontmatter?.tags,
        },
      });
    }

    return rules;
  }

  // =============================================================================
  // MERGE STRATEGIES
  // =============================================================================

  /**
   * Apply the configured merge strategy.
   */
  private applyStrategy(rules: Rule[]): Rule[] {
    switch (this.config.strategy) {
      case 'priority':
        return this.mergeByPriority(rules);

      case 'combine':
        return this.mergeCombine(rules);

      case 'latest':
        return this.mergeByLatest(rules);

      case 'custom':
        if (this.config.customMerge) {
          return this.config.customMerge(rules);
        }
        return rules;

      default:
        return rules;
    }
  }

  /**
   * Priority-based merge: higher priority rules override lower priority.
   * Rules of the same type from higher priority sources replace lower ones.
   */
  private mergeByPriority(rules: Rule[]): Rule[] {
    const byType = new Map<RuleType, Rule[]>();

    // Group by type
    for (const rule of rules) {
      const existing = byType.get(rule.type) ?? [];
      existing.push(rule);
      byType.set(rule.type, existing);
    }

    // Keep highest priority for each type
    const merged: Rule[] = [];
    for (const [type, typeRules] of byType) {
      // Sort by priority (lower number = higher priority)
      typeRules.sort((a, b) => a.priority - b.priority);

      // Apply type-specific strategy if configured
      const typeStrategy = this.config.typeStrategies?.[type];

      if (typeStrategy === 'combine') {
        merged.push(...typeRules);
      } else {
        // Take highest priority
        if (typeRules.length > 0) {
          merged.push(typeRules[0]);
        }
      }
    }

    return merged;
  }

  /**
   * Combine merge: include all rules, sorted by priority.
   */
  private mergeCombine(rules: Rule[]): Rule[] {
    return [...rules];
  }

  /**
   * Latest merge: rules loaded later override earlier ones.
   * (Assumes rules are already in load order)
   */
  private mergeByLatest(rules: Rule[]): Rule[] {
    const byType = new Map<RuleType, Rule>();

    // Later rules overwrite earlier ones
    for (const rule of rules) {
      byType.set(rule.type, rule);
    }

    return [...byType.values()];
  }

  // =============================================================================
  // DEDUPLICATION
  // =============================================================================

  /**
   * Remove duplicate rules based on content similarity.
   */
  private deduplicateRules(rules: Rule[]): Rule[] {
    const seen = new Set<string>();
    const deduplicated: Rule[] = [];

    for (const rule of rules) {
      // Normalize content for comparison
      const normalized = this.normalizeForComparison(rule.content);

      if (!seen.has(normalized)) {
        seen.add(normalized);
        deduplicated.push(rule);
      }
    }

    return deduplicated;
  }

  /**
   * Normalize content for duplicate detection.
   */
  private normalizeForComparison(content: string): string {
    return content
      .toLowerCase()
      .replace(/\s+/g, ' ')
      .replace(/[^\w\s]/g, '')
      .trim();
  }

  // =============================================================================
  // SORTING
  // =============================================================================

  /**
   * Sort rules by priority and scope.
   */
  private sortByPriority(rules: Rule[]): Rule[] {
    const scopeOrder: Record<Scope, number> = {
      global: 0,
      user: 1,
      project: 2,
      directory: 3,
      session: 4,
    };

    return [...rules].sort((a, b) => {
      // First by scope (more specific scopes come later)
      const scopeDiff = scopeOrder[a.scope] - scopeOrder[b.scope];
      if (scopeDiff !== 0) return scopeDiff;

      // Then by priority (lower number = earlier)
      return a.priority - b.priority;
    });
  }

  // =============================================================================
  // PROMPT BUILDING
  // =============================================================================

  /**
   * Build a system prompt from merged rules.
   */
  private buildPrompt(rules: Rule[]): string {
    const sections: Record<RuleType, string[]> = {
      persona: [],
      context: [],
      instruction: [],
      constraint: [],
      preference: [],
      format: [],
      'tool-config': [],
    };

    // Group rules by type
    for (const rule of rules) {
      if (this.config.includeSourceComments) {
        const scopeLabel = rule.scope.charAt(0).toUpperCase() + rule.scope.slice(1);
        sections[rule.type].push(`<!-- Source: ${rule.sourceId} (${scopeLabel}) -->`);
      }
      sections[rule.type].push(rule.content);
    }

    // Build prompt in order
    const promptParts: string[] = [];

    // Persona first (who is the agent?)
    if (sections.persona.length > 0) {
      promptParts.push('## Identity\n\n' + sections.persona.join('\n\n'));
    }

    // Context next (what should the agent know?)
    if (sections.context.length > 0) {
      promptParts.push('## Context\n\n' + sections.context.join('\n\n'));
    }

    // Main instructions
    if (sections.instruction.length > 0) {
      promptParts.push('## Instructions\n\n' + sections.instruction.join('\n\n'));
    }

    // Constraints (what NOT to do)
    if (sections.constraint.length > 0) {
      promptParts.push('## Constraints\n\n' + sections.constraint.join('\n\n'));
    }

    // Preferences (what to PREFER)
    if (sections.preference.length > 0) {
      promptParts.push('## Preferences\n\n' + sections.preference.join('\n\n'));
    }

    // Format specifications
    if (sections.format.length > 0) {
      promptParts.push('## Output Format\n\n' + sections.format.join('\n\n'));
    }

    // Tool configurations
    if (sections['tool-config'].length > 0) {
      promptParts.push('## Tool Configuration\n\n' + sections['tool-config'].join('\n\n'));
    }

    return promptParts.join('\n\n---\n\n');
  }

  // =============================================================================
  // CONFIGURATION
  // =============================================================================

  /**
   * Update merge configuration.
   */
  setConfig(config: Partial<RuleMergerConfig>): void {
    this.config = { ...this.config, ...config };
  }

  /**
   * Get current configuration.
   */
  getConfig(): RuleMergerConfig {
    return { ...this.config };
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export const defaultRuleMerger = new RuleMerger();
