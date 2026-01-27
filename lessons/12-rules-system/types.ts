/**
 * Lesson 12: Rules & Instructions System Types
 *
 * Type definitions for the hierarchical rules and instructions system.
 * This enables dynamic system prompts built from multiple sources
 * (global configs, project files, directory-specific rules).
 */

// =============================================================================
// INSTRUCTION SOURCE TYPES
// =============================================================================

/**
 * Where an instruction/rule comes from.
 */
export type SourceType = 'file' | 'url' | 'inline' | 'env';

/**
 * Scope of an instruction (determines priority).
 */
export type Scope = 'global' | 'user' | 'project' | 'directory' | 'session';

/**
 * An instruction source definition.
 */
export interface InstructionSource {
  /** Unique identifier for this source */
  id: string;

  /** Type of source */
  type: SourceType;

  /** Path, URL, or content depending on type */
  location: string;

  /** Scope determines merge priority (more specific = higher priority) */
  scope: Scope;

  /**
   * Priority within scope (lower = higher priority).
   * Default is 100.
   */
  priority: number;

  /** Optional label for display */
  label?: string;

  /** Whether this source is enabled */
  enabled: boolean;

  /** When the source was last loaded */
  loadedAt?: Date;

  /** Optional condition for when to include this source */
  condition?: InstructionCondition;
}

/**
 * Condition for including an instruction source.
 */
export interface InstructionCondition {
  /** Only include if working in these directories (glob patterns) */
  directories?: string[];

  /** Only include for these file types being edited */
  fileTypes?: string[];

  /** Only include if these tools are available */
  requiresTools?: string[];

  /** Custom condition function */
  custom?: (context: ConditionContext) => boolean;
}

/**
 * Context passed to condition functions.
 */
export interface ConditionContext {
  currentDirectory: string;
  currentFile?: string;
  availableTools: string[];
  sessionMetadata: Record<string, unknown>;
}

// =============================================================================
// RULE TYPES
// =============================================================================

/**
 * A parsed rule from an instruction source.
 */
export interface Rule {
  /** Source this rule came from */
  sourceId: string;

  /** Rule content */
  content: string;

  /** Rule type for categorization */
  type: RuleType;

  /** Priority from source */
  priority: number;

  /** Scope from source */
  scope: Scope;

  /** Optional metadata */
  metadata?: RuleMetadata;
}

/**
 * Types of rules that can be defined.
 */
export type RuleType =
  | 'instruction'    // General instruction for the agent
  | 'constraint'     // Something the agent must NOT do
  | 'preference'     // Something the agent SHOULD do
  | 'format'         // Output format specification
  | 'tool-config'    // Tool-specific configuration
  | 'persona'        // Agent personality/role definition
  | 'context';       // Background context information

/**
 * Metadata that can be attached to rules.
 */
export interface RuleMetadata {
  /** Tags for filtering */
  tags?: string[];

  /** When the rule expires */
  expiresAt?: Date;

  /** Author of the rule */
  author?: string;

  /** Version of the rule */
  version?: string;
}

// =============================================================================
// RULE SET TYPES
// =============================================================================

/**
 * A collection of rules from multiple sources, merged and ready to use.
 */
export interface RuleSet {
  /** All sources that were considered */
  sources: InstructionSource[];

  /** Sources that were actually loaded */
  loadedSources: InstructionSource[];

  /** Merged rules in priority order */
  rules: Rule[];

  /** Pre-built system prompt */
  systemPrompt: string;

  /** Metadata about the merge */
  metadata: RuleSetMetadata;
}

/**
 * Metadata about how the rule set was built.
 */
export interface RuleSetMetadata {
  /** When the rule set was built */
  builtAt: Date;

  /** Number of sources processed */
  sourcesProcessed: number;

  /** Number of sources that had errors */
  sourcesWithErrors: number;

  /** Total rules before deduplication */
  totalRules: number;

  /** Rules after deduplication/merging */
  mergedRules: number;

  /** Errors encountered during loading */
  errors: RuleLoadError[];

  /** Build duration in milliseconds */
  buildDurationMs: number;
}

/**
 * Error encountered when loading a rule source.
 */
export interface RuleLoadError {
  sourceId: string;
  error: Error;
  recoverable: boolean;
}

// =============================================================================
// RULE LOADER TYPES
// =============================================================================

/**
 * Configuration for the rule loader.
 */
export interface RuleLoaderConfig {
  /** Base directory for relative paths */
  baseDir: string;

  /** File patterns to search for rules */
  filePatterns: string[];

  /** Whether to search recursively */
  recursive: boolean;

  /** Maximum depth for recursive search */
  maxDepth: number;

  /** Timeout for loading remote sources (ms) */
  timeout: number;

  /** Whether to cache loaded sources */
  cacheEnabled: boolean;

  /** Cache TTL in milliseconds */
  cacheTTL: number;
}

/**
 * Result of loading an instruction source.
 */
export interface LoadResult {
  success: boolean;
  content?: string;
  error?: Error;
  cached: boolean;
  loadTimeMs: number;
}

// =============================================================================
// RULE MERGER TYPES
// =============================================================================

/**
 * Strategy for merging conflicting rules.
 */
export type MergeStrategy =
  | 'priority'      // Higher priority wins
  | 'combine'       // Combine all rules
  | 'latest'        // Most recently loaded wins
  | 'custom';       // Use custom merge function

/**
 * Configuration for the rule merger.
 */
export interface RuleMergerConfig {
  /** Default merge strategy */
  strategy: MergeStrategy;

  /** Strategies per rule type (overrides default) */
  typeStrategies?: Partial<Record<RuleType, MergeStrategy>>;

  /** Custom merge function */
  customMerge?: (rules: Rule[]) => Rule[];

  /** Whether to deduplicate identical rules */
  deduplicate: boolean;

  /** Whether to include source comments in merged output */
  includeSourceComments: boolean;
}

// =============================================================================
// PROMPT BUILDER TYPES
// =============================================================================

/**
 * Sections of the system prompt.
 */
export interface PromptSections {
  /** Core identity/role section */
  persona?: string;

  /** Context and background */
  context?: string;

  /** Main instructions */
  instructions?: string;

  /** Constraints and limitations */
  constraints?: string;

  /** Output format specifications */
  format?: string;

  /** Tool configurations */
  toolConfig?: string;

  /** User preferences */
  preferences?: string;
}

/**
 * Configuration for the prompt builder.
 */
export interface PromptBuilderConfig {
  /** Order of sections in the prompt */
  sectionOrder: (keyof PromptSections)[];

  /** Section separators */
  sectionSeparator: string;

  /** Whether to include section headers */
  includeSectionHeaders: boolean;

  /** Maximum prompt length (characters) */
  maxLength?: number;

  /** What to do if max length exceeded */
  truncationStrategy: 'trim-end' | 'trim-low-priority' | 'error';
}

// =============================================================================
// FILE FORMAT TYPES
// =============================================================================

/**
 * Parsed structure of an instruction file (CLAUDE.md, AGENTS.md, etc.).
 */
export interface InstructionFile {
  /** File path */
  path: string;

  /** Frontmatter metadata (YAML) */
  frontmatter?: InstructionFileFrontmatter;

  /** Main content sections */
  sections: InstructionFileSection[];

  /** Raw content */
  rawContent: string;
}

/**
 * Frontmatter for instruction files.
 */
export interface InstructionFileFrontmatter {
  /** Scope override */
  scope?: Scope;

  /** Priority override */
  priority?: number;

  /** Tags for filtering */
  tags?: string[];

  /** Condition for including */
  condition?: Partial<InstructionCondition>;

  /** Whether the file is enabled */
  enabled?: boolean;
}

/**
 * A section within an instruction file.
 */
export interface InstructionFileSection {
  /** Section heading (if any) */
  heading?: string;

  /** Heading level (1-6) */
  level?: number;

  /** Section content */
  content: string;

  /** Inferred rule type */
  ruleType: RuleType;
}

// =============================================================================
// EVENTS
// =============================================================================

/**
 * Events emitted by the rules system.
 */
export type RulesEvent =
  | { type: 'rules.loading'; sources: string[] }
  | { type: 'rules.loaded'; sourceId: string; ruleCount: number }
  | { type: 'rules.error'; sourceId: string; error: Error }
  | { type: 'rules.merged'; ruleCount: number; durationMs: number }
  | { type: 'rules.changed'; added: number; removed: number; modified: number };

/**
 * Listener for rules events.
 */
export type RulesEventListener = (event: RulesEvent) => void;

// =============================================================================
// DEFAULTS
// =============================================================================

/**
 * Default file patterns to search for instruction files.
 */
export const DEFAULT_FILE_PATTERNS = [
  'CLAUDE.md',
  'CLAUDE.local.md',
  'AGENTS.md',
  '.claude/CLAUDE.md',
  '.claude/instructions.md',
  '.cursorrules',
  '.aider.md',
];

/**
 * Default scope priorities (lower = higher priority in final output).
 */
export const SCOPE_PRIORITIES: Record<Scope, number> = {
  global: 500,
  user: 400,
  project: 300,
  directory: 200,
  session: 100,
};
