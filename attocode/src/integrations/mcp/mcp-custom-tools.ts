/**
 * MCP Custom Tools
 *
 * Factory for creating standalone API wrapper tools that can be
 * registered alongside MCP tools. Provides a simple interface
 * for adding web search, API calls, and other external integrations.
 *
 * Key features:
 * - createSerperSearchTool() - Web search via SerperAPI
 * - createCustomTool() - Generic factory for any API wrapper
 * - Consistent tool interface (name, description, inputSchema, execute)
 */

// =============================================================================
// TYPES
// =============================================================================

export interface CustomToolDefinition {
  /** Tool name (snake_case recommended) */
  name: string;
  /** Human-readable description for the LLM */
  description: string;
  /** JSON Schema for input parameters */
  inputSchema: Record<string, unknown>;
  /** Tool execution function */
  execute: (args: Record<string, unknown>) => Promise<CustomToolResult>;
  /** Danger level for permission system */
  dangerLevel?: 'safe' | 'moderate' | 'dangerous';
  /** Category for organization */
  category?: string;
}

export interface CustomToolResult {
  /** Whether the tool call succeeded */
  success: boolean;
  /** Result content (shown to LLM) */
  content: string;
  /** Structured data (optional, for programmatic use) */
  data?: unknown;
  /** Error message if failed */
  error?: string;
}

export interface CustomToolConfig {
  /** Request timeout in ms (default: 30000) */
  timeout?: number;
  /** Retry count on failure (default: 1) */
  retries?: number;
  /** Custom headers for API calls */
  headers?: Record<string, string>;
}

export interface SerperSearchConfig {
  /** SerperAPI key (defaults to SERPER_API_KEY env var) */
  apiKey?: string;
  /** Number of results to return (default: 5) */
  numResults?: number;
  /** Country code for localized results (default: 'us') */
  country?: string;
  /** Language code (default: 'en') */
  language?: string;
  /** Request timeout in ms (default: 10000) */
  timeout?: number;
}

interface SerperSearchResult {
  title: string;
  link: string;
  snippet: string;
  position: number;
}

interface SerperResponse {
  organic?: SerperSearchResult[];
  answerBox?: {
    title?: string;
    answer?: string;
    snippet?: string;
  };
  knowledgeGraph?: {
    title?: string;
    type?: string;
    description?: string;
  };
}

// =============================================================================
// SERPER SEARCH TOOL
// =============================================================================

/**
 * Create a web search tool using the Serper API.
 * Requires SERPER_API_KEY environment variable or explicit config.
 */
export function createSerperSearchTool(config?: SerperSearchConfig): CustomToolDefinition {
  const apiKey = config?.apiKey ?? process.env.SERPER_API_KEY;
  const numResults = config?.numResults ?? 5;
  const country = config?.country ?? 'us';
  const language = config?.language ?? 'en';
  const timeout = config?.timeout ?? 10000;

  return {
    name: 'web_search',
    description: `Search the web using Serper API. Returns top ${numResults} results with titles, URLs, and snippets. Use this to find current information, documentation, or answers not in your training data.`,
    dangerLevel: 'safe',
    category: 'search',
    inputSchema: {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description: 'The search query. Be specific for better results.',
        },
        num_results: {
          type: 'number',
          description: `Number of results to return (default: ${numResults}, max: 10)`,
        },
      },
      required: ['query'],
    },
    execute: async (args: Record<string, unknown>): Promise<CustomToolResult> => {
      if (!apiKey) {
        return {
          success: false,
          content:
            'SERPER_API_KEY not configured. Set the environment variable or pass apiKey in config.',
          error: 'Missing API key',
        };
      }

      const query = String(args.query ?? '');
      if (!query) {
        return {
          success: false,
          content: 'Search query is required.',
          error: 'Missing query',
        };
      }

      const resultCount = Math.min(Number(args.num_results ?? numResults), 10);

      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeout);

        const response = await fetch('https://google.serper.dev/search', {
          method: 'POST',
          headers: {
            'X-API-KEY': apiKey,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            q: query,
            num: resultCount,
            gl: country,
            hl: language,
          }),
          signal: controller.signal,
        });

        clearTimeout(timeoutId);

        if (!response.ok) {
          return {
            success: false,
            content: `Serper API error: ${response.status} ${response.statusText}`,
            error: `HTTP ${response.status}`,
          };
        }

        const data = (await response.json()) as SerperResponse;
        const lines: string[] = [];

        // Answer box (direct answer)
        if (data.answerBox) {
          lines.push('## Direct Answer');
          if (data.answerBox.title) lines.push(`**${data.answerBox.title}**`);
          if (data.answerBox.answer) lines.push(data.answerBox.answer);
          else if (data.answerBox.snippet) lines.push(data.answerBox.snippet);
          lines.push('');
        }

        // Knowledge graph
        if (data.knowledgeGraph) {
          lines.push('## Knowledge Graph');
          if (data.knowledgeGraph.title) lines.push(`**${data.knowledgeGraph.title}**`);
          if (data.knowledgeGraph.type) lines.push(`Type: ${data.knowledgeGraph.type}`);
          if (data.knowledgeGraph.description) lines.push(data.knowledgeGraph.description);
          lines.push('');
        }

        // Organic results
        if (data.organic && data.organic.length > 0) {
          lines.push('## Search Results');
          for (const result of data.organic.slice(0, resultCount)) {
            lines.push(`### ${result.position}. ${result.title}`);
            lines.push(`URL: ${result.link}`);
            lines.push(result.snippet);
            lines.push('');
          }
        }

        if (lines.length === 0) {
          lines.push('No results found for this query.');
        }

        return {
          success: true,
          content: lines.join('\n'),
          data,
        };
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        return {
          success: false,
          content: `Search failed: ${message}`,
          error: message,
        };
      }
    },
  };
}

// =============================================================================
// GENERIC CUSTOM TOOL FACTORY
// =============================================================================

export interface GenericToolSpec {
  /** Tool name */
  name: string;
  /** Description for the LLM */
  description: string;
  /** JSON Schema for input parameters */
  inputSchema: Record<string, unknown>;
  /** API endpoint URL */
  url: string;
  /** HTTP method (default: POST) */
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  /** Static headers */
  headers?: Record<string, string>;
  /** How to format the request body from args (default: JSON body) */
  bodyFormatter?: (args: Record<string, unknown>) => string;
  /** How to format the response for the LLM (default: JSON.stringify) */
  responseFormatter?: (data: unknown) => string;
  /** Danger level */
  dangerLevel?: 'safe' | 'moderate' | 'dangerous';
  /** Category */
  category?: string;
}

/**
 * Create a custom tool from a specification.
 * Wraps an HTTP API call with proper error handling and formatting.
 */
export function createCustomTool(
  spec: GenericToolSpec,
  config?: CustomToolConfig,
): CustomToolDefinition {
  const timeout = config?.timeout ?? 30000;
  const retries = config?.retries ?? 1;
  const extraHeaders = config?.headers ?? {};

  return {
    name: spec.name,
    description: spec.description,
    inputSchema: spec.inputSchema,
    dangerLevel: spec.dangerLevel ?? 'moderate',
    category: spec.category,
    execute: async (args: Record<string, unknown>): Promise<CustomToolResult> => {
      let lastError: string | undefined;

      for (let attempt = 0; attempt <= retries; attempt++) {
        try {
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), timeout);

          const requestHeaders: Record<string, string> = {
            'Content-Type': 'application/json',
            ...spec.headers,
            ...extraHeaders,
          };

          const fetchOptions: RequestInit = {
            method: spec.method ?? 'POST',
            headers: requestHeaders,
            signal: controller.signal,
          };

          if (spec.method !== 'GET') {
            fetchOptions.body = spec.bodyFormatter
              ? spec.bodyFormatter(args)
              : JSON.stringify(args);
          }

          const response = await fetch(spec.url, fetchOptions);
          clearTimeout(timeoutId);

          if (!response.ok) {
            lastError = `HTTP ${response.status}: ${response.statusText}`;
            if (attempt < retries) continue;
            return {
              success: false,
              content: `API error: ${lastError}`,
              error: lastError,
            };
          }

          const data = await response.json();
          const formatted = spec.responseFormatter
            ? spec.responseFormatter(data)
            : JSON.stringify(data, null, 2);

          return {
            success: true,
            content: formatted,
            data,
          };
        } catch (err) {
          lastError = err instanceof Error ? err.message : String(err);
          if (attempt < retries) continue;
        }
      }

      return {
        success: false,
        content: `Tool "${spec.name}" failed after ${retries + 1} attempts: ${lastError}`,
        error: lastError,
      };
    },
  };
}

// =============================================================================
// TOOL REGISTRY HELPERS
// =============================================================================

/**
 * Convert a CustomToolDefinition to the format expected by the tool registry.
 */
export function customToolToRegistryFormat(tool: CustomToolDefinition): {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  dangerLevel: string;
} {
  return {
    name: tool.name,
    description: tool.description,
    inputSchema: tool.inputSchema,
    dangerLevel: tool.dangerLevel ?? 'moderate',
  };
}

/**
 * Create multiple custom tools from specs.
 */
export function createCustomTools(
  specs: GenericToolSpec[],
  config?: CustomToolConfig,
): CustomToolDefinition[] {
  return specs.map((spec) => createCustomTool(spec, config));
}
