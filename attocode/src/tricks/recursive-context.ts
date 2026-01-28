/**
 * Trick U: Recursive Language Model Context (RLM)
 *
 * Instead of cramming everything into context or summarizing, let the model
 * "browse" the context as an external environment through recursive self-calls.
 *
 * Inspired by arXiv:2512.24601 - Recursive Language Models.
 *
 * Problem: Traditional approaches either:
 * - Stuff everything in context → hits limits, loses attention
 * - Summarize → loses critical details
 *
 * Solution: Let the model decide what parts of context to examine, then
 * recursively call itself with focused snippets, synthesizing across calls.
 *
 * @example
 * ```typescript
 * const rlm = createRecursiveContext({
 *   maxDepth: 3,
 *   snippetTokens: 2000,
 *   synthesisTokens: 1000,
 * });
 *
 * // Register context sources
 * rlm.registerSource('files', {
 *   describe: () => 'Project source files',
 *   list: async () => ['src/main.ts', 'src/agent.ts', ...],
 *   fetch: async (key) => readFile(key),
 * });
 *
 * // Process a query with recursive context access
 * const result = await rlm.process(query, llmCall, {
 *   depth: 0,
 *   budget: 10000,
 * });
 * ```
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * A context source that can be browsed.
 */
export interface ContextSource {
  /** Brief description of this source */
  describe: () => string;

  /** List available items in this source */
  list: (filter?: string) => Promise<string[]>;

  /** Fetch a specific item */
  fetch: (key: string) => Promise<string>;

  /** Optional: search within this source */
  search?: (query: string) => Promise<Array<{ key: string; snippet: string; score: number }>>;
}

/**
 * A navigation command from the model.
 */
export interface NavigationCommand {
  /** Type of navigation */
  type: 'list' | 'fetch' | 'search' | 'synthesize' | 'done';

  /** Source to navigate (for list/fetch/search) */
  source?: string;

  /** Key to fetch or query to search */
  key?: string;

  /** Reason for this navigation */
  reason?: string;
}

/**
 * Result of a recursive call.
 */
export interface RecursiveResult {
  /** Final synthesized answer */
  answer: string;

  /** Breadcrumb trail of navigation */
  path: NavigationStep[];

  /** Statistics */
  stats: RecursiveStats;
}

/**
 * A step in the navigation path.
 */
export interface NavigationStep {
  /** Depth in the recursion tree */
  depth: number;

  /** Command executed */
  command: NavigationCommand;

  /** Result (truncated if large) */
  result: string;

  /** Tokens used */
  tokens: number;
}

/**
 * Statistics about recursive processing.
 */
export interface RecursiveStats {
  /** Total LLM calls made */
  totalCalls: number;

  /** Maximum depth reached */
  maxDepthReached: number;

  /** Total tokens used */
  totalTokens: number;

  /** Context sources accessed */
  sourcesAccessed: string[];

  /** Items fetched */
  itemsFetched: number;

  /** Processing time in ms */
  duration: number;
}

/**
 * Configuration for recursive context.
 */
export interface RecursiveContextConfig {
  /** Maximum recursion depth */
  maxDepth?: number;

  /** Maximum tokens per snippet */
  snippetTokens?: number;

  /** Maximum tokens for synthesis */
  synthesisTokens?: number;

  /** Token budget for entire process */
  totalBudget?: number;

  /** Whether to cache fetched items */
  cacheResults?: boolean;

  /** Timeout per LLM call in ms */
  callTimeout?: number;
}

/**
 * Options for a recursive process call.
 */
export interface ProcessOptions {
  /** Current depth (for recursive calls) */
  depth?: number;

  /** Remaining token budget */
  budget?: number;

  /** Previous navigation context (for recursive calls) */
  navigationContext?: string;

  /** Cancel token */
  cancelToken?: { isCancelled: boolean };
}

/**
 * LLM call function signature.
 */
export type LLMCallFunction = (
  systemPrompt: string,
  userMessage: string,
  options?: { maxTokens?: number }
) => Promise<{ content: string; tokens: number }>;

/**
 * Events emitted during recursive processing.
 */
export type RecursiveContextEvent =
  | { type: 'process.started'; query: string; depth: number }
  | { type: 'navigation.command'; command: NavigationCommand; depth: number }
  | { type: 'source.accessed'; source: string; command: string }
  | { type: 'synthesis.started'; depth: number; itemCount: number }
  | { type: 'process.completed'; stats: RecursiveStats }
  | { type: 'budget.warning'; remaining: number; total: number }
  | { type: 'depth.warning'; current: number; max: number };

export type RecursiveContextEventListener = (event: RecursiveContextEvent) => void;

// =============================================================================
// PROMPTS
// =============================================================================

const NAVIGATOR_SYSTEM_PROMPT = `You are a context navigator. Your job is to explore available context sources to answer questions.

You can navigate using these commands (respond with ONLY the JSON):

1. List items in a source:
   {"type": "list", "source": "<source_name>", "reason": "why"}

2. Fetch a specific item:
   {"type": "fetch", "source": "<source_name>", "key": "<item_key>", "reason": "why"}

3. Search within a source:
   {"type": "search", "source": "<source_name>", "key": "<search_query>", "reason": "why"}

4. Synthesize findings into an answer:
   {"type": "synthesize", "reason": "ready because..."}

5. Mark as done (have enough info):
   {"type": "done", "reason": "why done"}

Available sources:
{SOURCES}

Current context:
{CONTEXT}

Be strategic - only fetch what you need. Explain your reasoning briefly.`;

const SYNTHESIS_SYSTEM_PROMPT = `You are synthesizing information gathered from multiple sources.

Gathered information:
{GATHERED}

Provide a comprehensive answer based on the gathered information.
If information is incomplete, note what's missing.
Focus on accuracy over completeness.`;

// =============================================================================
// RECURSIVE CONTEXT MANAGER
// =============================================================================

/**
 * Manages recursive context navigation.
 */
export class RecursiveContextManager {
  private config: Required<RecursiveContextConfig>;
  private sources: Map<string, ContextSource> = new Map();
  private cache: Map<string, string> = new Map();
  private listeners: RecursiveContextEventListener[] = [];

  constructor(config: RecursiveContextConfig = {}) {
    this.config = {
      maxDepth: config.maxDepth ?? 3,
      snippetTokens: config.snippetTokens ?? 2000,
      synthesisTokens: config.synthesisTokens ?? 1000,
      totalBudget: config.totalBudget ?? 50000,
      cacheResults: config.cacheResults ?? true,
      callTimeout: config.callTimeout ?? 30000,
    };
  }

  /**
   * Register a context source.
   */
  registerSource(name: string, source: ContextSource): void {
    this.sources.set(name, source);
  }

  /**
   * Unregister a context source.
   */
  unregisterSource(name: string): void {
    this.sources.delete(name);
  }

  /**
   * Get registered source names.
   */
  getSourceNames(): string[] {
    return Array.from(this.sources.keys());
  }

  /**
   * Process a query with recursive context navigation.
   */
  async process(
    query: string,
    llmCall: LLMCallFunction,
    options: ProcessOptions = {}
  ): Promise<RecursiveResult> {
    const {
      depth = 0,
      budget = this.config.totalBudget,
      navigationContext = '',
      cancelToken,
    } = options;

    const startTime = Date.now();
    const path: NavigationStep[] = [];
    const gathered: string[] = [];
    const sourcesAccessed = new Set<string>();
    let totalTokens = 0;
    let itemsFetched = 0;
    let maxDepthReached = depth;

    this.emit({ type: 'process.started', query, depth });

    // Build source descriptions
    const sourceDescriptions = this.buildSourceDescriptions();

    // Main navigation loop
    let iterations = 0;
    const maxIterations = 10; // Prevent infinite loops

    while (iterations < maxIterations) {
      iterations++;

      // Check cancellation
      if (cancelToken?.isCancelled) {
        break;
      }

      // Check budget
      if (totalTokens > budget * 0.9) {
        this.emit({ type: 'budget.warning', remaining: budget - totalTokens, total: budget });
        break;
      }

      // Check depth
      if (depth >= this.config.maxDepth) {
        this.emit({ type: 'depth.warning', current: depth, max: this.config.maxDepth });
        break;
      }

      // Build context for navigation
      const contextSummary = this.buildContextSummary(gathered, path);

      const systemPrompt = NAVIGATOR_SYSTEM_PROMPT
        .replace('{SOURCES}', sourceDescriptions)
        .replace('{CONTEXT}', contextSummary || 'No context gathered yet.');

      const userMessage = depth === 0
        ? `Question: ${query}\n\nWhat would you like to explore first?`
        : `Continue exploring to answer: ${query}\n\n${navigationContext}`;

      // Get navigation command from LLM
      const navResponse = await llmCall(systemPrompt, userMessage, {
        maxTokens: 200,
      });

      totalTokens += navResponse.tokens;

      // Parse navigation command
      const command = this.parseNavigationCommand(navResponse.content);
      this.emit({ type: 'navigation.command', command, depth });

      // Execute command
      if (command.type === 'done' || command.type === 'synthesize') {
        // Ready to synthesize
        this.emit({ type: 'synthesis.started', depth, itemCount: gathered.length });

        const answer = await this.synthesize(query, gathered, llmCall);
        totalTokens += answer.tokens;

        return {
          answer: answer.content,
          path,
          stats: {
            totalCalls: iterations + 1,
            maxDepthReached,
            totalTokens,
            sourcesAccessed: Array.from(sourcesAccessed),
            itemsFetched,
            duration: Date.now() - startTime,
          },
        };
      }

      // Execute navigation command
      const stepResult = await this.executeCommand(command, sourcesAccessed);

      if (stepResult) {
        path.push({
          depth,
          command,
          result: this.truncate(stepResult, 500),
          tokens: this.estimateTokens(stepResult),
        });

        gathered.push(this.formatGatheredItem(command, stepResult));
        itemsFetched++;
        maxDepthReached = Math.max(maxDepthReached, depth);
      }
    }

    // Reached iteration limit - synthesize what we have
    this.emit({ type: 'synthesis.started', depth, itemCount: gathered.length });

    const finalAnswer = await this.synthesize(query, gathered, llmCall);
    totalTokens += finalAnswer.tokens;

    const stats: RecursiveStats = {
      totalCalls: iterations + 1,
      maxDepthReached,
      totalTokens,
      sourcesAccessed: Array.from(sourcesAccessed),
      itemsFetched,
      duration: Date.now() - startTime,
    };

    this.emit({ type: 'process.completed', stats });

    return {
      answer: finalAnswer.content,
      path,
      stats,
    };
  }

  /**
   * Clear the results cache.
   */
  clearCache(): void {
    this.cache.clear();
  }

  /**
   * Subscribe to events.
   */
  on(listener: RecursiveContextEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  // ===========================================================================
  // PRIVATE METHODS
  // ===========================================================================

  private buildSourceDescriptions(): string {
    const lines: string[] = [];

    for (const [name, source] of this.sources) {
      lines.push(`- ${name}: ${source.describe()}`);
      if (source.search) {
        lines.push(`  (supports search)`);
      }
    }

    return lines.join('\n');
  }

  private buildContextSummary(gathered: string[], path: NavigationStep[]): string {
    if (gathered.length === 0) {
      return '';
    }

    const summary = [
      `Gathered ${gathered.length} items:`,
      '',
      ...gathered.slice(-5).map((g, i) => `${i + 1}. ${this.truncate(g, 200)}`),
    ];

    if (gathered.length > 5) {
      summary.unshift(`(${gathered.length - 5} earlier items not shown)`);
    }

    return summary.join('\n');
  }

  private parseNavigationCommand(content: string): NavigationCommand {
    try {
      // Try to extract JSON from response
      const jsonMatch = content.match(/\{[\s\S]*\}/);
      if (jsonMatch) {
        const parsed = JSON.parse(jsonMatch[0]);
        return {
          type: parsed.type || 'done',
          source: parsed.source,
          key: parsed.key,
          reason: parsed.reason,
        };
      }
    } catch {
      // Parse failed
    }

    // Default to done if can't parse
    return { type: 'done', reason: 'Could not parse navigation command' };
  }

  private async executeCommand(
    command: NavigationCommand,
    sourcesAccessed: Set<string>
  ): Promise<string | null> {
    if (!command.source) {
      return null;
    }

    const source = this.sources.get(command.source);
    if (!source) {
      return `Source "${command.source}" not found`;
    }

    sourcesAccessed.add(command.source);
    this.emit({ type: 'source.accessed', source: command.source, command: command.type });

    try {
      switch (command.type) {
        case 'list': {
          const items = await source.list(command.key);
          return `Items in ${command.source}:\n${items.slice(0, 20).join('\n')}${
            items.length > 20 ? `\n...and ${items.length - 20} more` : ''
          }`;
        }

        case 'fetch': {
          if (!command.key) {
            return 'No key specified for fetch';
          }

          // Check cache
          const cacheKey = `${command.source}:${command.key}`;
          if (this.config.cacheResults && this.cache.has(cacheKey)) {
            return this.cache.get(cacheKey)!;
          }

          const content = await source.fetch(command.key);
          const truncated = this.truncate(content, this.config.snippetTokens * 4); // ~4 chars per token

          if (this.config.cacheResults) {
            this.cache.set(cacheKey, truncated);
          }

          return `Content of ${command.key}:\n${truncated}`;
        }

        case 'search': {
          if (!source.search || !command.key) {
            return 'Search not available for this source or no query specified';
          }

          const results = await source.search(command.key);
          return `Search results for "${command.key}":\n${
            results.slice(0, 10).map(r => `- ${r.key}: ${r.snippet}`).join('\n')
          }`;
        }

        default:
          return null;
      }
    } catch (error) {
      const err = error instanceof Error ? error : new Error(String(error));
      return `Error accessing ${command.source}: ${err.message}`;
    }
  }

  private async synthesize(
    query: string,
    gathered: string[],
    llmCall: LLMCallFunction
  ): Promise<{ content: string; tokens: number }> {
    if (gathered.length === 0) {
      return {
        content: 'No information gathered to answer the question.',
        tokens: 0,
      };
    }

    const systemPrompt = SYNTHESIS_SYSTEM_PROMPT.replace(
      '{GATHERED}',
      gathered.map((g, i) => `[${i + 1}] ${g}`).join('\n\n')
    );

    const userMessage = `Based on the gathered information, answer: ${query}`;

    return llmCall(systemPrompt, userMessage, {
      maxTokens: this.config.synthesisTokens,
    });
  }

  private formatGatheredItem(command: NavigationCommand, result: string): string {
    const prefix = command.source ? `[${command.source}${command.key ? ':' + command.key : ''}]` : '';
    return `${prefix} ${this.truncate(result, 500)}`;
  }

  private truncate(text: string, maxChars: number): string {
    if (text.length <= maxChars) {
      return text;
    }
    return text.slice(0, maxChars - 3) + '...';
  }

  private estimateTokens(text: string): number {
    // Rough estimate: ~4 characters per token
    return Math.ceil(text.length / 4);
  }

  private emit(event: RecursiveContextEvent): void {
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
 * Create a recursive context manager.
 *
 * @example
 * ```typescript
 * const rlm = createRecursiveContext({
 *   maxDepth: 3,
 *   snippetTokens: 2000,
 *   totalBudget: 50000,
 * });
 *
 * // Register file system source
 * rlm.registerSource('files', {
 *   describe: () => 'Project source files',
 *   list: async () => glob('src/*.ts'),
 *   fetch: async (path) => fs.readFile(path, 'utf-8'),
 *   search: async (query) => grep(query),
 * });
 *
 * // Process a complex query
 * const result = await rlm.process(
 *   'How does authentication work in this codebase?',
 *   async (system, user, opts) => {
 *     const response = await provider.chat([
 *       { role: 'system', content: system },
 *       { role: 'user', content: user },
 *     ], opts);
 *     return { content: response.content, tokens: response.usage.totalTokens };
 *   }
 * );
 *
 * console.log(result.answer);
 * console.log(`Used ${result.stats.totalTokens} tokens across ${result.stats.totalCalls} calls`);
 * ```
 */
export function createRecursiveContext(
  config: RecursiveContextConfig = {}
): RecursiveContextManager {
  return new RecursiveContextManager(config);
}

/**
 * Create a minimal recursive context manager for testing.
 */
export function createMinimalRecursiveContext(): RecursiveContextManager {
  return new RecursiveContextManager({
    maxDepth: 2,
    snippetTokens: 1000,
    synthesisTokens: 500,
    totalBudget: 10000,
    cacheResults: false,
  });
}

// =============================================================================
// BUILT-IN SOURCES
// =============================================================================

/**
 * Create a file system context source.
 */
export function createFileSystemSource(options: {
  basePath: string;
  glob: (pattern: string) => Promise<string[]>;
  readFile: (path: string) => Promise<string>;
  grep?: (query: string, path?: string) => Promise<Array<{ file: string; line: number; content: string }>>;
}): ContextSource {
  return {
    describe: () => `Files in ${options.basePath}`,

    list: async (filter) => {
      const pattern = filter || '**/*';
      return options.glob(pattern);
    },

    fetch: async (key) => {
      return options.readFile(key);
    },

    search: options.grep
      ? async (query) => {
          const results = await options.grep!(query);
          return results.map((r) => ({
            key: `${r.file}:${r.line}`,
            snippet: r.content,
            score: 1,
          }));
        }
      : undefined,
  };
}

/**
 * Create a conversation history context source.
 */
export function createConversationSource(options: {
  getMessages: () => Array<{ role: string; content: string; timestamp?: string }>;
}): ContextSource {
  return {
    describe: () => 'Previous conversation messages',

    list: async () => {
      const messages = options.getMessages();
      return messages.map((m, i) => `msg-${i}: [${m.role}] ${m.content.slice(0, 50)}...`);
    },

    fetch: async (key) => {
      const messages = options.getMessages();
      const match = key.match(/msg-(\d+)/);
      if (match) {
        const idx = parseInt(match[1], 10);
        if (messages[idx]) {
          return `[${messages[idx].role}]: ${messages[idx].content}`;
        }
      }
      return 'Message not found';
    },

    search: async (query) => {
      const messages = options.getMessages();
      const queryLower = query.toLowerCase();

      return messages
        .map((m, i) => ({
          key: `msg-${i}`,
          snippet: m.content.slice(0, 100),
          score: m.content.toLowerCase().includes(queryLower) ? 1 : 0,
        }))
        .filter((r) => r.score > 0);
    },
  };
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Format recursive result for display.
 */
export function formatRecursiveResult(result: RecursiveResult): string {
  const lines = [
    '=== Recursive Context Result ===',
    '',
    'Answer:',
    result.answer,
    '',
    'Navigation Path:',
    ...result.path.map(
      (step) =>
        `  [${step.depth}] ${step.command.type}${step.command.source ? `:${step.command.source}` : ''} - ${step.command.reason || 'no reason'}`
    ),
    '',
    'Statistics:',
    `  Total LLM calls: ${result.stats.totalCalls}`,
    `  Max depth: ${result.stats.maxDepthReached}`,
    `  Total tokens: ${result.stats.totalTokens}`,
    `  Items fetched: ${result.stats.itemsFetched}`,
    `  Duration: ${result.stats.duration}ms`,
    `  Sources: ${result.stats.sourcesAccessed.join(', ')}`,
  ];

  return lines.join('\n');
}

/**
 * Format statistics for display.
 */
export function formatRecursiveStats(stats: RecursiveStats): string {
  return [
    `Calls: ${stats.totalCalls}`,
    `Tokens: ${stats.totalTokens}`,
    `Items: ${stats.itemsFetched}`,
    `Time: ${stats.duration}ms`,
  ].join(' | ');
}
