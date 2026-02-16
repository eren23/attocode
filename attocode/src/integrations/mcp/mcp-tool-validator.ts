/**
 * MCP Tool Description Validator
 *
 * Validates MCP tool descriptions for quality, helping ensure
 * that LLMs can understand and correctly use the tools.
 *
 * Quality checks:
 * 1. Description length (minimum useful length)
 * 2. Input schema has property descriptions
 * 3. Required parameters are marked
 * 4. Description contains usage patterns
 * 5. Naming conventions (snake_case, prefixed)
 */

// =============================================================================
// TYPES
// =============================================================================

export interface ToolValidationResult {
  /** Tool name */
  toolName: string;
  /** Quality score (0-100) */
  score: number;
  /** Specific problems found */
  issues: string[];
  /** Improvement suggestions */
  suggestions: string[];
}

export interface ToolValidationConfig {
  /** Minimum description length (default: 20) */
  minDescriptionLength: number;
  /** Require input schema property descriptions (default: true) */
  requirePropertyDescriptions: boolean;
  /** Require at least one example in description (default: false) */
  requireExamples: boolean;
  /** Minimum quality score to pass (default: 40) */
  minimumPassScore: number;
}

interface ValidatableToolInfo {
  name: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const DEFAULT_CONFIG: ToolValidationConfig = {
  minDescriptionLength: 20,
  requirePropertyDescriptions: true,
  requireExamples: false,
  minimumPassScore: 40,
};

// =============================================================================
// VALIDATOR
// =============================================================================

/**
 * Validate a single tool's description quality.
 */
export function validateToolDescription(
  tool: ValidatableToolInfo,
  config?: Partial<ToolValidationConfig>,
): ToolValidationResult {
  const cfg = { ...DEFAULT_CONFIG, ...config };
  const issues: string[] = [];
  const suggestions: string[] = [];
  let score = 100;

  const description = tool.description || '';

  // Check 1: Description exists and has minimum length
  if (!description) {
    issues.push('No description provided');
    score -= 40;
  } else if (description.length < cfg.minDescriptionLength) {
    issues.push(`Description too short (${description.length} chars, min: ${cfg.minDescriptionLength})`);
    suggestions.push('Add more detail about what this tool does and when to use it');
    score -= 20;
  }

  // Check 2: Description is informative (not just tool name restated)
  if (description && tool.name) {
    const nameWords = tool.name.replace(/[_-]/g, ' ').toLowerCase().split(/\s+/);
    const descWords = description.toLowerCase().split(/\s+/);
    const overlap = nameWords.filter(w => descWords.includes(w)).length;
    if (overlap === nameWords.length && description.split(/\s+/).length < 5) {
      issues.push('Description merely restates the tool name');
      suggestions.push('Explain what the tool does, its purpose, and any important behavior');
      score -= 15;
    }
  }

  // Check 3: Input schema has property descriptions
  if (cfg.requirePropertyDescriptions && tool.inputSchema) {
    const properties = (tool.inputSchema as Record<string, unknown>).properties as Record<string, Record<string, unknown>> | undefined;
    if (properties) {
      const undocumented: string[] = [];
      for (const [propName, propSchema] of Object.entries(properties)) {
        if (!propSchema.description) {
          undocumented.push(propName);
        }
      }
      if (undocumented.length > 0) {
        issues.push(`Properties missing descriptions: ${undocumented.join(', ')}`);
        suggestions.push('Add "description" to each property in the input schema');
        score -= Math.min(undocumented.length * 5, 20);
      }
    }
  }

  // Check 4: Required parameters are specified
  if (tool.inputSchema) {
    const required = (tool.inputSchema as Record<string, unknown>).required as string[] | undefined;
    const properties = (tool.inputSchema as Record<string, unknown>).properties as Record<string, unknown> | undefined;
    if (properties && Object.keys(properties).length > 0 && (!required || required.length === 0)) {
      suggestions.push('Consider marking required parameters in the schema');
      score -= 5;
    }
  }

  // Check 5: Description mentions examples or usage patterns
  if (cfg.requireExamples && description) {
    const hasExample = /example|e\.g\.|for instance|usage:|such as/i.test(description);
    if (!hasExample) {
      suggestions.push('Add a usage example to the description');
      score -= 10;
    }
  }

  // Check 6: Naming conventions
  if (tool.name) {
    const isSnakeCase = /^[a-z][a-z0-9_]*$/.test(tool.name);
    const hasMCPPrefix = tool.name.startsWith('mcp_');
    if (!isSnakeCase && !hasMCPPrefix) {
      suggestions.push('Consider using snake_case for tool names');
      score -= 5;
    }
  }

  return {
    toolName: tool.name,
    score: Math.max(0, score),
    issues,
    suggestions,
  };
}

/**
 * Validate all tools and return results sorted by score (worst first).
 */
export function validateAllTools(
  tools: ValidatableToolInfo[],
  config?: Partial<ToolValidationConfig>,
): ToolValidationResult[] {
  return tools
    .map(tool => validateToolDescription(tool, config))
    .sort((a, b) => a.score - b.score);
}

/**
 * Get a summary of validation results.
 */
export function formatValidationSummary(results: ToolValidationResult[]): string {
  const passed = results.filter(r => r.score >= (DEFAULT_CONFIG.minimumPassScore));
  const failed = results.filter(r => r.score < (DEFAULT_CONFIG.minimumPassScore));

  const lines: string[] = [
    `Tool Description Quality: ${passed.length}/${results.length} passed`,
  ];

  if (failed.length > 0) {
    lines.push('', 'Failed:');
    for (const r of failed) {
      lines.push(`  ${r.toolName} (score: ${r.score}): ${r.issues.join('; ')}`);
    }
  }

  return lines.join('\n');
}

/**
 * Create a tool validator.
 */
export function createToolValidator(config?: Partial<ToolValidationConfig>) {
  return {
    validate: (tool: ValidatableToolInfo) => validateToolDescription(tool, config),
    validateAll: (tools: ValidatableToolInfo[]) => validateAllTools(tools, config),
    formatSummary: formatValidationSummary,
  };
}
