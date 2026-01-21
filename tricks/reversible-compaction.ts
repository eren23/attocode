/**
 * Trick R: Reversible Compaction
 *
 * Preserves "reconstruction recipes" during context compaction.
 * Instead of discarding information, store retrieval keys so the model
 * can fetch details when needed.
 *
 * Problem: Traditional compaction loses important details forever.
 * When a file path or URL is summarized away, the model can't recover it.
 *
 * Solution: Extract and preserve references (URLs, file paths, function names)
 * as "reconstruction recipes" - minimal keys that enable re-retrieval.
 *
 * @example
 * ```typescript
 * import { createReversibleCompactor, extractReferences } from './reversible-compaction';
 *
 * const compactor = createReversibleCompactor({
 *   preserveTypes: ['file', 'url', 'function', 'error'],
 *   maxReferences: 50,
 * });
 *
 * // Compact with reference preservation
 * const result = compactor.compact(messages, {
 *   summarize: async (msgs) => summarizeLLM(msgs),
 * });
 *
 * console.log(result.summary);       // Condensed summary
 * console.log(result.references);    // Preserved references for retrieval
 * ```
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * Types of references that can be preserved.
 */
export type ReferenceType =
  | 'file'       // File paths
  | 'url'        // URLs (docs, issues, etc.)
  | 'function'   // Function/method names
  | 'class'      // Class/type names
  | 'error'      // Error messages/stack traces
  | 'command'    // Shell commands
  | 'snippet'    // Code snippets (abbreviated)
  | 'decision'   // Key decisions made
  | 'custom';    // Custom reference type

/**
 * A preserved reference that can be used for retrieval.
 */
export interface Reference {
  /** Unique ID for this reference */
  id: string;

  /** Type of reference */
  type: ReferenceType;

  /** The actual value (path, URL, name, etc.) */
  value: string;

  /** Brief context about this reference */
  context?: string;

  /** When this reference was encountered */
  timestamp: string;

  /** Source message index (before compaction) */
  sourceIndex?: number;

  /** Relevance score (0-1) for prioritization */
  relevance?: number;
}

/**
 * Configuration for reversible compaction.
 */
export interface ReversibleCompactionConfig {
  /** Types of references to preserve */
  preserveTypes: ReferenceType[];

  /** Maximum references to keep */
  maxReferences?: number;

  /** Whether to deduplicate references */
  deduplicate?: boolean;

  /** Custom extractors for specific reference types */
  customExtractors?: Map<ReferenceType, ReferenceExtractor>;

  /** Minimum relevance score to preserve (0-1) */
  minRelevance?: number;
}

/**
 * Result of compaction.
 */
export interface CompactionResult {
  /** The summarized content */
  summary: string;

  /** Preserved references for retrieval */
  references: Reference[];

  /** Statistics about the compaction */
  stats: CompactionStats;
}

/**
 * Statistics about compaction.
 */
export interface CompactionStats {
  /** Original message count */
  originalMessages: number;

  /** Original estimated tokens */
  originalTokens: number;

  /** Compacted token count */
  compactedTokens: number;

  /** References extracted */
  referencesExtracted: number;

  /** References preserved (after dedup/limits) */
  referencesPreserved: number;

  /** Compression ratio */
  compressionRatio: number;
}

/**
 * Message for compaction.
 */
export interface CompactionMessage {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  name?: string;
}

/**
 * Custom reference extractor function.
 */
export type ReferenceExtractor = (content: string, index: number) => Reference[];

/**
 * Options for compact operation.
 */
export interface CompactOptions {
  /** Function to summarize messages */
  summarize: (messages: CompactionMessage[]) => Promise<string>;

  /** Additional context to preserve */
  additionalContext?: string;
}

/**
 * Events emitted during compaction.
 */
export type CompactionEvent =
  | { type: 'compaction.started'; messageCount: number }
  | { type: 'reference.extracted'; reference: Reference }
  | { type: 'reference.deduplicated'; kept: number; removed: number }
  | { type: 'compaction.completed'; stats: CompactionStats };

export type CompactionEventListener = (event: CompactionEvent) => void;

// =============================================================================
// REFERENCE EXTRACTION
// =============================================================================

/**
 * Extract file path references from content.
 */
export function extractFileReferences(content: string, sourceIndex?: number): Reference[] {
  const references: Reference[] = [];
  const timestamp = new Date().toISOString();

  // Unix-style paths
  const unixPaths = content.match(/(?:\/[\w.-]+)+(?:\/[\w.-]*)?/g) || [];

  // Windows-style paths
  const windowsPaths = content.match(/[A-Za-z]:\\(?:[\w.-]+\\)*[\w.-]*/g) || [];

  // Relative paths with extensions
  const relativePaths = content.match(/(?:\.\.?\/)?[\w-]+(?:\/[\w.-]+)*\.\w+/g) || [];

  const allPaths = [...new Set([...unixPaths, ...windowsPaths, ...relativePaths])];

  for (const path of allPaths) {
    // Filter out obvious non-paths
    if (path.length < 3 || path === '/' || path.match(/^\/\d+$/)) continue;

    references.push({
      id: `file-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      type: 'file',
      value: path,
      timestamp,
      sourceIndex,
    });
  }

  return references;
}

/**
 * Extract URL references from content.
 */
export function extractUrlReferences(content: string, sourceIndex?: number): Reference[] {
  const references: Reference[] = [];
  const timestamp = new Date().toISOString();

  // Full URLs
  const urlPattern = /https?:\/\/[^\s<>"{}|\\^`\[\]]+/g;
  const urls = content.match(urlPattern) || [];

  for (const url of urls) {
    // Clean trailing punctuation
    const cleanUrl = url.replace(/[.,;:!?)]+$/, '');

    // Extract context from URL
    let context: string | undefined;
    if (cleanUrl.includes('github.com')) {
      context = 'GitHub';
      if (cleanUrl.includes('/issues/')) context += ' Issue';
      if (cleanUrl.includes('/pull/')) context += ' PR';
    } else if (cleanUrl.includes('stackoverflow.com')) {
      context = 'Stack Overflow';
    } else if (cleanUrl.includes('docs.')) {
      context = 'Documentation';
    }

    references.push({
      id: `url-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      type: 'url',
      value: cleanUrl,
      context,
      timestamp,
      sourceIndex,
    });
  }

  return references;
}

/**
 * Extract function/method references from content.
 */
export function extractFunctionReferences(content: string, sourceIndex?: number): Reference[] {
  const references: Reference[] = [];
  const timestamp = new Date().toISOString();

  // Function definitions
  const funcDefs = content.match(/(?:function|async function|const|let|var)\s+(\w+)\s*(?:=\s*(?:async\s*)?\([^)]*\)\s*=>|\([^)]*\))/g) || [];

  // Method calls with meaningful names
  const methodCalls = content.match(/\b([a-z][a-zA-Z0-9]*(?:[A-Z][a-zA-Z0-9]*)+)\s*\(/g) || [];

  const seen = new Set<string>();

  for (const match of funcDefs) {
    const name = match.match(/(?:function|const|let|var)\s+(\w+)/)?.[1];
    if (name && !seen.has(name) && name.length > 2) {
      seen.add(name);
      references.push({
        id: `func-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        type: 'function',
        value: name,
        context: 'definition',
        timestamp,
        sourceIndex,
      });
    }
  }

  for (const match of methodCalls) {
    const name = match.replace(/\s*\($/, '');
    if (!seen.has(name) && name.length > 2) {
      seen.add(name);
      references.push({
        id: `func-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        type: 'function',
        value: name,
        context: 'call',
        timestamp,
        sourceIndex,
      });
    }
  }

  return references;
}

/**
 * Extract error references from content.
 */
export function extractErrorReferences(content: string, sourceIndex?: number): Reference[] {
  const references: Reference[] = [];
  const timestamp = new Date().toISOString();

  // Error class names
  const errorClasses = content.match(/\b(\w+Error|\w+Exception)\b/g) || [];

  // Error messages (e.g., "Error: something went wrong")
  const errorMessages = content.match(/(?:Error|Exception|Failed|Failure):\s*[^\n]+/g) || [];

  const seen = new Set<string>();

  for (const errorClass of errorClasses) {
    if (!seen.has(errorClass)) {
      seen.add(errorClass);
      references.push({
        id: `error-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        type: 'error',
        value: errorClass,
        context: 'error type',
        timestamp,
        sourceIndex,
      });
    }
  }

  for (const errorMsg of errorMessages.slice(0, 3)) { // Limit error messages
    const truncated = errorMsg.slice(0, 100);
    if (!seen.has(truncated)) {
      seen.add(truncated);
      references.push({
        id: `error-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        type: 'error',
        value: truncated,
        context: 'error message',
        timestamp,
        sourceIndex,
      });
    }
  }

  return references;
}

/**
 * Extract command references from content.
 */
export function extractCommandReferences(content: string, sourceIndex?: number): Reference[] {
  const references: Reference[] = [];
  const timestamp = new Date().toISOString();

  // Shell commands (common patterns)
  const shellPatterns = [
    /\$\s*([^\n]+)/g,           // $ command
    /```(?:bash|sh|shell)\n([^`]+)```/g,  // Code blocks
    /(?:npm|yarn|pnpm|npx|bun)\s+[^\n]+/g,  // Package managers
    /(?:git)\s+[^\n]+/g,        // Git commands
    /(?:docker|kubectl)\s+[^\n]+/g,  // Container commands
  ];

  const seen = new Set<string>();

  for (const pattern of shellPatterns) {
    const matches = content.match(pattern) || [];
    for (const match of matches) {
      const cleaned = match.replace(/^\$\s*/, '').replace(/```(?:bash|sh|shell)?\n?/g, '').trim();
      if (cleaned.length > 3 && !seen.has(cleaned)) {
        seen.add(cleaned);
        references.push({
          id: `cmd-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          type: 'command',
          value: cleaned.slice(0, 200), // Truncate long commands
          timestamp,
          sourceIndex,
        });
      }
    }
  }

  return references;
}

/**
 * Extract all references from content.
 */
export function extractReferences(
  content: string,
  types: ReferenceType[],
  sourceIndex?: number,
  customExtractors?: Map<ReferenceType, ReferenceExtractor>
): Reference[] {
  const references: Reference[] = [];

  for (const type of types) {
    // Check for custom extractor first
    if (customExtractors?.has(type)) {
      const extractor = customExtractors.get(type)!;
      references.push(...extractor(content, sourceIndex ?? 0));
      continue;
    }

    // Use built-in extractors
    switch (type) {
      case 'file':
        references.push(...extractFileReferences(content, sourceIndex));
        break;
      case 'url':
        references.push(...extractUrlReferences(content, sourceIndex));
        break;
      case 'function':
        references.push(...extractFunctionReferences(content, sourceIndex));
        break;
      case 'error':
        references.push(...extractErrorReferences(content, sourceIndex));
        break;
      case 'command':
        references.push(...extractCommandReferences(content, sourceIndex));
        break;
      // class, snippet, decision, custom require custom extractors
    }
  }

  return references;
}

// =============================================================================
// REVERSIBLE COMPACTOR
// =============================================================================

/**
 * Manages reversible context compaction.
 */
export class ReversibleCompactor {
  private config: Required<ReversibleCompactionConfig>;
  private preservedReferences: Reference[] = [];
  private listeners: CompactionEventListener[] = [];

  constructor(config: ReversibleCompactionConfig) {
    this.config = {
      preserveTypes: config.preserveTypes,
      maxReferences: config.maxReferences ?? 100,
      deduplicate: config.deduplicate ?? true,
      customExtractors: config.customExtractors ?? new Map(),
      minRelevance: config.minRelevance ?? 0,
    };
  }

  /**
   * Compact messages while preserving references.
   */
  async compact(
    messages: CompactionMessage[],
    options: CompactOptions
  ): Promise<CompactionResult> {
    this.emit({ type: 'compaction.started', messageCount: messages.length });

    // Calculate original token estimate
    const originalContent = messages.map(m => m.content).join('\n');
    const originalTokens = Math.ceil(originalContent.length / 4);

    // Extract references from all messages
    const allReferences: Reference[] = [];
    for (let i = 0; i < messages.length; i++) {
      const refs = extractReferences(
        messages[i].content,
        this.config.preserveTypes,
        i,
        this.config.customExtractors
      );

      for (const ref of refs) {
        this.emit({ type: 'reference.extracted', reference: ref });
        allReferences.push(ref);
      }
    }

    // Deduplicate if enabled
    let processedReferences = allReferences;
    if (this.config.deduplicate) {
      processedReferences = this.deduplicateReferences(allReferences);
    }

    // Filter by relevance
    if (this.config.minRelevance > 0) {
      processedReferences = processedReferences.filter(
        r => (r.relevance ?? 1) >= this.config.minRelevance
      );
    }

    // Limit references
    if (processedReferences.length > this.config.maxReferences) {
      // Sort by relevance, keep most relevant
      processedReferences.sort((a, b) => (b.relevance ?? 0.5) - (a.relevance ?? 0.5));
      processedReferences = processedReferences.slice(0, this.config.maxReferences);
    }

    // Generate summary
    const summary = await options.summarize(messages);

    // Calculate compacted token estimate
    const referenceBlock = this.formatReferencesBlock(processedReferences);
    const compactedContent = summary + '\n\n' + referenceBlock;
    const compactedTokens = Math.ceil(compactedContent.length / 4);

    // Store preserved references
    this.preservedReferences = processedReferences;

    const stats: CompactionStats = {
      originalMessages: messages.length,
      originalTokens,
      compactedTokens,
      referencesExtracted: allReferences.length,
      referencesPreserved: processedReferences.length,
      compressionRatio: compactedTokens / originalTokens,
    };

    this.emit({ type: 'compaction.completed', stats });

    return {
      summary,
      references: processedReferences,
      stats,
    };
  }

  /**
   * Format references as a block for inclusion in context.
   */
  formatReferencesBlock(references: Reference[]): string {
    if (references.length === 0) return '';

    const grouped = new Map<ReferenceType, Reference[]>();
    for (const ref of references) {
      const group = grouped.get(ref.type) || [];
      group.push(ref);
      grouped.set(ref.type, group);
    }

    const parts: string[] = ['[Preserved References]'];

    for (const [type, refs] of grouped) {
      parts.push(`\n${type.toUpperCase()}S:`);
      for (const ref of refs) {
        const contextPart = ref.context ? ` (${ref.context})` : '';
        parts.push(`  - ${ref.value}${contextPart}`);
      }
    }

    return parts.join('\n');
  }

  /**
   * Get a reference by ID.
   */
  getReference(id: string): Reference | undefined {
    return this.preservedReferences.find(r => r.id === id);
  }

  /**
   * Get references by type.
   */
  getReferencesByType(type: ReferenceType): Reference[] {
    return this.preservedReferences.filter(r => r.type === type);
  }

  /**
   * Search references by value.
   */
  searchReferences(query: string): Reference[] {
    const lowerQuery = query.toLowerCase();
    return this.preservedReferences.filter(
      r => r.value.toLowerCase().includes(lowerQuery)
    );
  }

  /**
   * Get all preserved references.
   */
  getPreservedReferences(): Reference[] {
    return [...this.preservedReferences];
  }

  /**
   * Clear preserved references.
   */
  clear(): void {
    this.preservedReferences = [];
  }

  /**
   * Subscribe to events.
   */
  on(listener: CompactionEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  // Internal methods

  private deduplicateReferences(references: Reference[]): Reference[] {
    const seen = new Map<string, Reference>();
    let removed = 0;

    for (const ref of references) {
      const key = `${ref.type}:${ref.value}`;
      if (!seen.has(key)) {
        seen.set(key, ref);
      } else {
        removed++;
      }
    }

    this.emit({
      type: 'reference.deduplicated',
      kept: seen.size,
      removed,
    });

    return Array.from(seen.values());
  }

  private emit(event: CompactionEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a reversible compactor.
 *
 * @example
 * ```typescript
 * const compactor = createReversibleCompactor({
 *   preserveTypes: ['file', 'url', 'error'],
 *   maxReferences: 50,
 *   deduplicate: true,
 * });
 *
 * const result = await compactor.compact(messages, {
 *   summarize: async (msgs) => {
 *     // Use LLM to summarize
 *     return await llm.summarize(msgs);
 *   },
 * });
 *
 * // Result includes both summary and preserved references
 * console.log(result.summary);
 * console.log(result.references);
 *
 * // Later, search for specific references
 * const fileRefs = compactor.getReferencesByType('file');
 * const errorRefs = compactor.searchReferences('TypeError');
 * ```
 */
export function createReversibleCompactor(
  config: ReversibleCompactionConfig
): ReversibleCompactor {
  return new ReversibleCompactor(config);
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Quick helper to extract references without full compaction.
 */
export function quickExtract(
  content: string,
  types: ReferenceType[] = ['file', 'url', 'function', 'error']
): Reference[] {
  return extractReferences(content, types);
}

/**
 * Create a reconstruction prompt for re-fetching details.
 */
export function createReconstructionPrompt(references: Reference[]): string {
  if (references.length === 0) {
    return '';
  }

  const lines = [
    'The following references were preserved from earlier context.',
    'Use these to retrieve details if needed:',
    '',
  ];

  const byType = new Map<ReferenceType, Reference[]>();
  for (const ref of references) {
    const group = byType.get(ref.type) || [];
    group.push(ref);
    byType.set(ref.type, group);
  }

  if (byType.has('file')) {
    lines.push('**Files** (can be read with read_file tool):');
    for (const ref of byType.get('file')!) {
      lines.push(`  - ${ref.value}`);
    }
    lines.push('');
  }

  if (byType.has('url')) {
    lines.push('**URLs** (can be fetched for details):');
    for (const ref of byType.get('url')!) {
      const ctx = ref.context ? ` [${ref.context}]` : '';
      lines.push(`  - ${ref.value}${ctx}`);
    }
    lines.push('');
  }

  if (byType.has('function')) {
    lines.push('**Functions** (search codebase if details needed):');
    for (const ref of byType.get('function')!) {
      lines.push(`  - ${ref.value}`);
    }
    lines.push('');
  }

  if (byType.has('error')) {
    lines.push('**Errors encountered**:');
    for (const ref of byType.get('error')!) {
      lines.push(`  - ${ref.value}`);
    }
    lines.push('');
  }

  if (byType.has('command')) {
    lines.push('**Commands used**:');
    for (const ref of byType.get('command')!) {
      lines.push(`  - ${ref.value}`);
    }
  }

  return lines.join('\n');
}

/**
 * Calculate relevance score for a reference based on context.
 */
export function calculateRelevance(
  reference: Reference,
  context: { goal?: string; recentTopics?: string[] }
): number {
  let score = 0.5; // Base score

  const value = reference.value.toLowerCase();

  // Boost if matches goal
  if (context.goal) {
    const goalWords = context.goal.toLowerCase().split(/\s+/);
    for (const word of goalWords) {
      if (word.length > 3 && value.includes(word)) {
        score += 0.1;
      }
    }
  }

  // Boost if matches recent topics
  if (context.recentTopics) {
    for (const topic of context.recentTopics) {
      if (value.includes(topic.toLowerCase())) {
        score += 0.15;
      }
    }
  }

  // Type-based adjustments
  if (reference.type === 'error') score += 0.1; // Errors are usually important
  if (reference.type === 'file') score += 0.05; // Files are often needed

  return Math.min(1, score);
}

/**
 * Format compaction stats for display.
 */
export function formatCompactionStats(stats: CompactionStats): string {
  const compressionPercent = Math.round((1 - stats.compressionRatio) * 100);

  return `Compaction Statistics:
  Original:    ${stats.originalMessages} messages, ~${stats.originalTokens.toLocaleString()} tokens
  Compacted:   ~${stats.compactedTokens.toLocaleString()} tokens
  Compression: ${compressionPercent}% reduction
  References:  ${stats.referencesExtracted} extracted, ${stats.referencesPreserved} preserved`;
}
