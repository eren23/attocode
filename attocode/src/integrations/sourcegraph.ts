/**
 * Sourcegraph Integration
 *
 * Cross-repository code search using Sourcegraph API.
 * Enables searching across multiple codebases for patterns, references, and definitions.
 *
 * @example
 * ```typescript
 * const sg = createSourcegraphClient();
 * const results = await sg.search('context:global repo:^github.com/org func:handleAuth');
 * ```
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * Sourcegraph client configuration.
 */
export interface SourcegraphConfig {
  /** Sourcegraph instance URL (default: sourcegraph.com) */
  endpoint?: string;
  /** Access token (from SOURCEGRAPH_ACCESS_TOKEN env or explicit) */
  accessToken?: string;
  /** Default search context */
  defaultContext?: string;
  /** Request timeout in ms (default: 30000) */
  timeout?: number;
}

/**
 * Search query options.
 */
export interface SearchOptions {
  /** Search context (e.g., 'global', '@myorg') */
  context?: string;
  /** Maximum number of results */
  maxResults?: number;
  /** Pattern type: literal, regexp, structural */
  patternType?: 'literal' | 'regexp' | 'structural';
  /** Case sensitivity */
  caseSensitive?: boolean;
  /** Repository filter pattern */
  repoFilter?: string;
  /** File filter pattern */
  fileFilter?: string;
  /** Language filter */
  language?: string;
}

/**
 * A single search result.
 */
export interface SearchResult {
  /** Repository name */
  repository: string;
  /** File path within repository */
  filePath: string;
  /** File URL on Sourcegraph */
  fileUrl: string;
  /** Matching line numbers */
  lineNumbers: number[];
  /** Preview content (with highlights) */
  preview: string;
  /** Match type */
  matchType: 'content' | 'path' | 'symbol' | 'commit';
  /** Match score/rank */
  score?: number;
}

/**
 * Search response.
 */
export interface SearchResponse {
  /** Search results */
  results: SearchResult[];
  /** Total match count */
  matchCount: number;
  /** Search duration in ms */
  durationMs: number;
  /** Whether results were limited */
  limitHit: boolean;
  /** Alert messages (e.g., query suggestions) */
  alerts?: string[];
}

/**
 * Symbol information.
 */
export interface SymbolInfo {
  /** Symbol name */
  name: string;
  /** Symbol kind (function, class, variable, etc.) */
  kind: string;
  /** Container name (parent class/module) */
  containerName?: string;
  /** File path */
  filePath: string;
  /** Repository */
  repository: string;
  /** Line range */
  range: {
    start: { line: number; character: number };
    end: { line: number; character: number };
  };
}

// =============================================================================
// GRAPHQL QUERIES
// =============================================================================

const SEARCH_QUERY = `
query Search($query: String!, $patternType: SearchPatternType) {
  search(query: $query, patternType: $patternType) {
    results {
      matchCount
      limitHit
      alert {
        title
        description
      }
      results {
        __typename
        ... on FileMatch {
          repository {
            name
          }
          file {
            path
            url
          }
          lineMatches {
            lineNumber
            preview
            offsetAndLengths
          }
        }
        ... on CommitSearchResult {
          commit {
            repository {
              name
            }
            oid
            message
          }
        }
        ... on Repository {
          name
          url
        }
      }
    }
  }
}
`;

const SYMBOL_QUERY = `
query Symbols($query: String!, $first: Int) {
  search(query: $query) {
    results {
      results {
        __typename
        ... on FileMatch {
          symbols {
            name
            kind
            containerName
            location {
              resource {
                path
                repository {
                  name
                }
              }
              range {
                start { line character }
                end { line character }
              }
            }
          }
        }
      }
    }
  }
}
`;

// =============================================================================
// SOURCEGRAPH CLIENT
// =============================================================================

/**
 * Sourcegraph API client.
 */
export class SourcegraphClient {
  private config: Required<SourcegraphConfig>;

  constructor(config: SourcegraphConfig = {}) {
    this.config = {
      endpoint: config.endpoint || 'https://sourcegraph.com',
      accessToken: config.accessToken || process.env.SOURCEGRAPH_ACCESS_TOKEN || '',
      defaultContext: config.defaultContext || 'global',
      timeout: config.timeout || 30000,
    };
  }

  /**
   * Check if the client is configured with valid credentials.
   */
  isConfigured(): boolean {
    return !!this.config.accessToken;
  }

  /**
   * Search code across repositories.
   */
  async search(query: string, options: SearchOptions = {}): Promise<SearchResponse> {
    if (!this.isConfigured()) {
      throw new Error('Sourcegraph access token not configured. Set SOURCEGRAPH_ACCESS_TOKEN environment variable.');
    }

    // Build full query with options
    const fullQuery = this.buildQuery(query, options);

    const startTime = Date.now();

    const response = await this.graphql(SEARCH_QUERY, {
      query: fullQuery,
      patternType: options.patternType?.toUpperCase() || 'LITERAL',
    });

    const data = response.search?.results;
    if (!data) {
      return {
        results: [],
        matchCount: 0,
        durationMs: Date.now() - startTime,
        limitHit: false,
      };
    }

    const results: SearchResult[] = [];

    for (const result of data.results || []) {
      if (result.__typename === 'FileMatch') {
        const repository = result.repository?.name || '';
        const filePath = result.file?.path || '';
        const fileUrl = `${this.config.endpoint}${result.file?.url || ''}`;

        for (const lineMatch of result.lineMatches || []) {
          results.push({
            repository,
            filePath,
            fileUrl,
            lineNumbers: [lineMatch.lineNumber],
            preview: lineMatch.preview,
            matchType: 'content',
          });
        }
      } else if (result.__typename === 'Repository') {
        results.push({
          repository: result.name,
          filePath: '',
          fileUrl: `${this.config.endpoint}${result.url || ''}`,
          lineNumbers: [],
          preview: result.name,
          matchType: 'path',
        });
      }
    }

    return {
      results: options.maxResults ? results.slice(0, options.maxResults) : results,
      matchCount: data.matchCount || results.length,
      durationMs: Date.now() - startTime,
      limitHit: data.limitHit || false,
      alerts: data.alert ? [data.alert.description || data.alert.title] : undefined,
    };
  }

  /**
   * Search for symbols (functions, classes, etc.).
   */
  async searchSymbols(query: string, options: SearchOptions = {}): Promise<SymbolInfo[]> {
    if (!this.isConfigured()) {
      throw new Error('Sourcegraph access token not configured');
    }

    const fullQuery = this.buildQuery(`type:symbol ${query}`, options);

    const response = await this.graphql(SYMBOL_QUERY, {
      query: fullQuery,
      first: options.maxResults || 50,
    });

    const results = response.search?.results?.results || [];
    const symbols: SymbolInfo[] = [];

    for (const result of results) {
      if (result.__typename === 'FileMatch' && result.symbols) {
        for (const symbol of result.symbols) {
          symbols.push({
            name: symbol.name,
            kind: symbol.kind,
            containerName: symbol.containerName,
            filePath: symbol.location?.resource?.path || '',
            repository: symbol.location?.resource?.repository?.name || '',
            range: {
              start: {
                line: symbol.location?.range?.start?.line || 0,
                character: symbol.location?.range?.start?.character || 0,
              },
              end: {
                line: symbol.location?.range?.end?.line || 0,
                character: symbol.location?.range?.end?.character || 0,
              },
            },
          });
        }
      }
    }

    return symbols;
  }

  /**
   * Find references to a symbol.
   */
  async findReferences(
    symbolName: string,
    options: SearchOptions = {}
  ): Promise<SearchResponse> {
    const query = `\\b${this.escapeRegex(symbolName)}\\b`;
    return this.search(query, { ...options, patternType: 'regexp' });
  }

  /**
   * Find definition of a symbol.
   */
  async findDefinition(
    symbolName: string,
    language?: string
  ): Promise<SymbolInfo[]> {
    const query = language
      ? `${symbolName} lang:${language}`
      : symbolName;
    return this.searchSymbols(query, { maxResults: 10 });
  }

  /**
   * Search for files by path pattern.
   */
  async searchFiles(
    pathPattern: string,
    options: SearchOptions = {}
  ): Promise<SearchResponse> {
    const query = `file:${pathPattern}`;
    return this.search(query, options);
  }

  /**
   * Get repository information.
   */
  async getRepository(repoName: string): Promise<{
    name: string;
    description?: string;
    url: string;
    defaultBranch?: string;
  } | null> {
    const query = `
      query Repository($name: String!) {
        repository(name: $name) {
          name
          description
          url
          defaultBranch {
            name
          }
        }
      }
    `;

    const response = await this.graphql(query, { name: repoName });
    const repo = response.repository;

    if (!repo) return null;

    return {
      name: repo.name,
      description: repo.description,
      url: `${this.config.endpoint}${repo.url || ''}`,
      defaultBranch: repo.defaultBranch?.name,
    };
  }

  // ===========================================================================
  // PRIVATE METHODS
  // ===========================================================================

  /**
   * Build a full query string with options.
   */
  private buildQuery(baseQuery: string, options: SearchOptions): string {
    const parts: string[] = [];

    // Context
    const context = options.context || this.config.defaultContext;
    if (context && context !== 'global') {
      parts.push(`context:${context}`);
    }

    // Repository filter
    if (options.repoFilter) {
      parts.push(`repo:${options.repoFilter}`);
    }

    // File filter
    if (options.fileFilter) {
      parts.push(`file:${options.fileFilter}`);
    }

    // Language filter
    if (options.language) {
      parts.push(`lang:${options.language}`);
    }

    // Case sensitivity
    if (options.caseSensitive) {
      parts.push('case:yes');
    }

    // Add base query
    parts.push(baseQuery);

    return parts.join(' ');
  }

  /**
   * Execute a GraphQL query.
   */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private async graphql(query: string, variables: Record<string, unknown>): Promise<any> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.config.timeout);

    try {
      const response = await fetch(`${this.config.endpoint}/.api/graphql`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `token ${this.config.accessToken}`,
        },
        body: JSON.stringify({ query, variables }),
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`Sourcegraph API error: ${response.status} ${response.statusText}`);
      }

      const json = await response.json() as { data?: Record<string, unknown>; errors?: Array<{ message: string }> };

      if (json.errors?.length) {
        throw new Error(`Sourcegraph query error: ${json.errors[0].message}`);
      }

      return json.data || {};
    } finally {
      clearTimeout(timeoutId);
    }
  }

  /**
   * Escape special regex characters.
   */
  private escapeRegex(str: string): string {
    return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create a Sourcegraph client.
 */
export function createSourcegraphClient(config?: SourcegraphConfig): SourcegraphClient {
  return new SourcegraphClient(config);
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Format search results for display.
 */
export function formatSearchResults(response: SearchResponse, maxPreviewLines = 3): string {
  const lines: string[] = [];

  lines.push(`Found ${response.matchCount} matches in ${response.durationMs}ms`);
  if (response.limitHit) {
    lines.push('(results truncated)');
  }
  lines.push('');

  for (const result of response.results) {
    lines.push(`${result.repository}/${result.filePath}`);
    if (result.lineNumbers.length > 0) {
      lines.push(`  Line ${result.lineNumbers.join(', ')}`);
    }
    if (result.preview) {
      const previewLines = result.preview.split('\n').slice(0, maxPreviewLines);
      for (const line of previewLines) {
        lines.push(`    ${line}`);
      }
    }
    lines.push('');
  }

  if (response.alerts?.length) {
    lines.push('Alerts:');
    for (const alert of response.alerts) {
      lines.push(`  - ${alert}`);
    }
  }

  return lines.join('\n');
}

/**
 * Check if Sourcegraph is configured.
 */
export function isSourcegraphConfigured(): boolean {
  return !!process.env.SOURCEGRAPH_ACCESS_TOKEN;
}
