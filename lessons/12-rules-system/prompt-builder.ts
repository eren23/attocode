/**
 * Lesson 12: Prompt Builder
 *
 * Constructs dynamic system prompts from rule sets.
 * Handles template expansion, length management, and formatting.
 */

import type {
  RuleSet,
  Rule,
  RuleType,
  PromptSections,
  PromptBuilderConfig,
} from './types.js';

// =============================================================================
// DEFAULT CONFIGURATION
// =============================================================================

const DEFAULT_CONFIG: PromptBuilderConfig = {
  sectionOrder: ['persona', 'context', 'instructions', 'constraints', 'format', 'toolConfig', 'preferences'],
  sectionSeparator: '\n\n---\n\n',
  includeSectionHeaders: true,
  truncationStrategy: 'trim-low-priority',
};

// =============================================================================
// SECTION HEADERS
// =============================================================================

const SECTION_HEADERS: Record<keyof PromptSections, string> = {
  persona: '## Identity & Role',
  context: '## Background Context',
  instructions: '## Instructions',
  constraints: '## Constraints',
  format: '## Output Format',
  toolConfig: '## Tool Configuration',
  preferences: '## Preferences',
};

// =============================================================================
// PROMPT BUILDER
// =============================================================================

/**
 * Builds system prompts from rule sets.
 */
export class PromptBuilder {
  private config: PromptBuilderConfig;

  constructor(config: Partial<PromptBuilderConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  // =============================================================================
  // MAIN BUILD METHOD
  // =============================================================================

  /**
   * Build a system prompt from a rule set.
   */
  build(ruleSet: RuleSet): string {
    // Group rules by section
    const sections = this.groupBySection(ruleSet.rules);

    // Build each section
    const builtSections: string[] = [];

    for (const sectionKey of this.config.sectionOrder) {
      const content = sections[sectionKey];

      if (content && content.trim()) {
        let section = '';

        if (this.config.includeSectionHeaders) {
          section += SECTION_HEADERS[sectionKey] + '\n\n';
        }

        section += content;
        builtSections.push(section);
      }
    }

    // Join sections
    let prompt = builtSections.join(this.config.sectionSeparator);

    // Handle max length
    if (this.config.maxLength && prompt.length > this.config.maxLength) {
      prompt = this.truncate(prompt, ruleSet.rules, this.config.maxLength);
    }

    return prompt;
  }

  /**
   * Build a prompt with custom sections.
   */
  buildWithSections(sections: PromptSections): string {
    const builtSections: string[] = [];

    for (const sectionKey of this.config.sectionOrder) {
      const content = sections[sectionKey];

      if (content && content.trim()) {
        let section = '';

        if (this.config.includeSectionHeaders) {
          section += SECTION_HEADERS[sectionKey] + '\n\n';
        }

        section += content;
        builtSections.push(section);
      }
    }

    return builtSections.join(this.config.sectionSeparator);
  }

  // =============================================================================
  // SECTION GROUPING
  // =============================================================================

  /**
   * Group rules by prompt section.
   */
  private groupBySection(rules: Rule[]): PromptSections {
    const sections: PromptSections = {};
    const contentBySection: Record<keyof PromptSections, string[]> = {
      persona: [],
      context: [],
      instructions: [],
      constraints: [],
      format: [],
      toolConfig: [],
      preferences: [],
    };

    // Map rule types to sections
    const typeToSection: Record<RuleType, keyof PromptSections> = {
      persona: 'persona',
      context: 'context',
      instruction: 'instructions',
      constraint: 'constraints',
      format: 'format',
      'tool-config': 'toolConfig',
      preference: 'preferences',
    };

    for (const rule of rules) {
      const section = typeToSection[rule.type];
      contentBySection[section].push(rule.content);
    }

    // Build section content
    for (const [key, contents] of Object.entries(contentBySection)) {
      if (contents.length > 0) {
        sections[key as keyof PromptSections] = contents.join('\n\n');
      }
    }

    return sections;
  }

  // =============================================================================
  // TRUNCATION
  // =============================================================================

  /**
   * Truncate prompt to max length.
   */
  private truncate(prompt: string, rules: Rule[], maxLength: number): string {
    switch (this.config.truncationStrategy) {
      case 'trim-end':
        return this.truncateEnd(prompt, maxLength);

      case 'trim-low-priority':
        return this.truncateLowPriority(prompt, rules, maxLength);

      case 'error':
        throw new Error(
          `Prompt exceeds max length: ${prompt.length} > ${maxLength}`
        );

      default:
        return this.truncateEnd(prompt, maxLength);
    }
  }

  /**
   * Simple truncation from the end.
   */
  private truncateEnd(prompt: string, maxLength: number): string {
    if (prompt.length <= maxLength) return prompt;

    const truncated = prompt.slice(0, maxLength - 50);
    const lastNewline = truncated.lastIndexOf('\n\n');

    if (lastNewline > maxLength * 0.8) {
      return truncated.slice(0, lastNewline) + '\n\n[Content truncated due to length limits]';
    }

    return truncated + '\n\n[Content truncated due to length limits]';
  }

  /**
   * Remove lowest priority rules until under limit.
   */
  private truncateLowPriority(prompt: string, rules: Rule[], maxLength: number): string {
    // Sort rules by priority (highest priority = lowest number = keep)
    const sortedRules = [...rules].sort((a, b) => b.priority - a.priority);

    // Remove rules one by one until we're under the limit
    let currentRules = [...sortedRules];

    while (currentRules.length > 0) {
      const sections = this.groupBySection(currentRules);
      const newPrompt = this.buildWithSections(sections);

      if (newPrompt.length <= maxLength) {
        return newPrompt + '\n\n[Some low-priority rules omitted due to length limits]';
      }

      // Remove the lowest priority rule
      currentRules.shift();
    }

    return '[Unable to fit any rules within length limit]';
  }

  // =============================================================================
  // TEMPLATE EXPANSION
  // =============================================================================

  /**
   * Expand templates in prompt content.
   */
  expandTemplates(content: string, variables: Record<string, unknown>): string {
    return content.replace(/\{\{(\w+)\}\}/g, (match, key) => {
      const value = variables[key];
      if (value === undefined) {
        return match; // Keep original if variable not found
      }
      return String(value);
    });
  }

  /**
   * Build a prompt with template variables.
   */
  buildWithVariables(ruleSet: RuleSet, variables: Record<string, unknown>): string {
    const prompt = this.build(ruleSet);
    return this.expandTemplates(prompt, variables);
  }

  // =============================================================================
  // CONFIGURATION
  // =============================================================================

  /**
   * Update configuration.
   */
  setConfig(config: Partial<PromptBuilderConfig>): void {
    this.config = { ...this.config, ...config };
  }

  /**
   * Get current configuration.
   */
  getConfig(): PromptBuilderConfig {
    return { ...this.config };
  }
}

// =============================================================================
// CONVENIENCE FUNCTIONS
// =============================================================================

/**
 * Build a simple prompt from rules.
 */
export function buildPrompt(rules: Rule[]): string {
  const builder = new PromptBuilder();
  return builder.build({
    sources: [],
    loadedSources: [],
    rules,
    systemPrompt: '',
    metadata: {
      builtAt: new Date(),
      sourcesProcessed: 0,
      sourcesWithErrors: 0,
      totalRules: rules.length,
      mergedRules: rules.length,
      errors: [],
      buildDurationMs: 0,
    },
  });
}

/**
 * Build a prompt from sections directly.
 */
export function buildFromSections(sections: PromptSections): string {
  const builder = new PromptBuilder();
  return builder.buildWithSections(sections);
}

// =============================================================================
// EXPORTS
// =============================================================================

export const defaultPromptBuilder = new PromptBuilder();
