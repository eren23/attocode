/**
 * Lesson 25: Extensible Agent Registry
 *
 * Allows users to define custom agents that can be spawned on demand.
 * Supports:
 * - Built-in agents (researcher, coder, reviewer, architect)
 * - User-defined agents from .agents/ directory (YAML/JSON)
 * - Hot-reload of agent definitions
 * - NL-based agent selection
 */

import { readFile, readdir, writeFile, mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { join, extname, dirname } from 'node:path';
import { homedir } from 'node:os';
import { fileURLToPath } from 'node:url';
import type { LLMProvider, ToolDefinition } from '../types.js';

// ES Module __dirname equivalent
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// =============================================================================
// TYPES
// =============================================================================

/**
 * Agent definition - describes a spawnable agent.
 */
export interface AgentDefinition {
  name: string;
  description: string;
  systemPrompt: string;
  tools?: string[];              // Whitelist of tool names (all if omitted)
  model?: 'fast' | 'balanced' | 'quality' | string;
  maxTokenBudget?: number;
  maxIterations?: number;
  capabilities?: string[];       // Used for NL matching
  tags?: string[];               // Additional tags for discovery
}

/**
 * Agent source type for display and management.
 */
export type AgentSourceType = 'builtin' | 'user' | 'project' | 'legacy';

/**
 * Loaded agent with source info.
 */
export interface LoadedAgent extends AgentDefinition {
  source: AgentSourceType;
  filePath?: string;
  loadedAt: Date;
}

/**
 * Agent spawn options.
 */
export interface SpawnOptions {
  task: string;
  provider: LLMProvider;
  tools: ToolDefinition[];
  onProgress?: (message: string) => void;
}

/**
 * Agent spawn result.
 */
export interface SpawnResult {
  success: boolean;
  output: string;
  metrics: {
    tokens: number;
    duration: number;
    toolCalls: number;
  };
}

/**
 * Registry events.
 */
export type RegistryEvent =
  | { type: 'agent.loaded'; name: string; source: string }
  | { type: 'agent.reloaded'; name: string }
  | { type: 'agent.removed'; name: string }
  | { type: 'agent.error'; name: string; error: string }
  | { type: 'agent.spawned'; name: string; task: string }
  | { type: 'agent.completed'; name: string; success: boolean };

export type RegistryEventListener = (event: RegistryEvent) => void;

// =============================================================================
// BUILT-IN AGENTS
// =============================================================================

const BUILTIN_AGENTS: AgentDefinition[] = [
  {
    name: 'researcher',
    description: 'Explores codebases and gathers information. Good for finding files, understanding structure, and summarizing code.',
    systemPrompt: `You are a code researcher. Your job is to:
- Explore codebases thoroughly
- Find relevant files and functions
- Summarize code structure and patterns
- Answer questions about the codebase

IMPORTANT:
- Return your findings as TEXT OUTPUT in the conversation, not as files
- Do NOT spawn documenter agents or create documentation files
- Do NOT write reports or markdown files unless explicitly asked
- Your analysis should be verbal - the user will see it in the conversation

Be thorough but concise. Focus on finding the specific information requested.
Explain what you found and why it matters.`,
    tools: ['read_file', 'list_files', 'glob', 'grep'],
    model: 'fast',
    maxTokenBudget: 50000,
    maxIterations: 30,
    capabilities: ['explore', 'search', 'find', 'understand', 'analyze'],
    tags: ['research', 'exploration', 'analysis'],
  },
  {
    name: 'coder',
    description: 'Writes and modifies code. Good for implementing features, fixing bugs, and making changes.',
    systemPrompt: `You are a skilled coder. Your job is to:
- Write clean, well-documented code
- Follow existing code patterns and conventions
- Make focused, minimal changes
- Test your changes when possible

Always explain what you're changing and why.`,
    tools: ['read_file', 'write_file', 'edit_file', 'list_files', 'glob', 'grep', 'bash'],
    model: 'balanced',
    maxTokenBudget: 100000,
    maxIterations: 50,
    capabilities: ['write', 'implement', 'fix', 'code', 'create', 'modify'],
    tags: ['coding', 'implementation', 'development'],
  },
  {
    name: 'reviewer',
    description: 'Reviews code for quality, bugs, and security issues. Good for code reviews and quality checks.',
    systemPrompt: `You are a code reviewer. Your job is to:
- Find bugs and potential issues
- Identify security vulnerabilities
- Check for code quality and style
- Suggest improvements

Be constructive and specific in your feedback. Prioritize serious issues.`,
    tools: ['read_file', 'list_files', 'glob', 'grep'],
    model: 'quality',
    maxTokenBudget: 80000,
    maxIterations: 30,
    capabilities: ['review', 'check', 'audit', 'verify', 'security'],
    tags: ['review', 'quality', 'security', 'audit'],
  },
  {
    name: 'architect',
    description: 'Designs system architecture and structure. Good for planning features and making design decisions.',
    systemPrompt: `You are a software architect. Your job is to:
- Design scalable, maintainable systems
- Consider trade-offs and alternatives
- Document architectural decisions
- Plan implementation approaches

Think holistically about the system and its evolution.`,
    tools: ['read_file', 'list_files', 'glob', 'grep'],
    model: 'quality',
    maxTokenBudget: 100000,
    maxIterations: 20,
    capabilities: ['design', 'plan', 'architect', 'structure', 'organize'],
    tags: ['architecture', 'design', 'planning'],
  },
  {
    name: 'debugger',
    description: 'Debugs and troubleshoots issues. Good for finding root causes and fixing bugs.',
    systemPrompt: `You are a debugger. Your job is to:
- Analyze error messages and stack traces
- Find the root cause of issues
- Test hypotheses systematically
- Propose and verify fixes

Be methodical. Test assumptions before making changes.`,
    tools: ['read_file', 'list_files', 'glob', 'grep', 'bash'],
    model: 'balanced',
    maxTokenBudget: 80000,
    maxIterations: 40,
    capabilities: ['debug', 'troubleshoot', 'fix', 'diagnose', 'error'],
    tags: ['debugging', 'troubleshooting', 'errors'],
  },
  {
    name: 'documenter',
    description: 'Writes documentation and comments. Good for adding docs, README files, and code comments.',
    systemPrompt: `You are a technical writer. Your job is to:
- Write clear, helpful documentation
- Add meaningful code comments
- Create README files and guides
- Explain complex concepts simply

Focus on clarity and usefulness. Write for your audience.`,
    tools: ['read_file', 'write_file', 'edit_file', 'list_files', 'glob'],
    model: 'balanced',
    maxTokenBudget: 50000,
    maxIterations: 20,
    capabilities: ['document', 'explain', 'comment', 'readme', 'guide'],
    tags: ['documentation', 'writing', 'comments'],
  },
];

// =============================================================================
// DEFAULT DIRECTORIES
// =============================================================================

/**
 * Default agent directories with priority hierarchy:
 * built-in < ~/.attocode/ < .attocode/ (later entries override earlier)
 *
 * Legacy paths (.agents/) are included for backward compatibility.
 */
export function getDefaultAgentDirectories(): string[] {
  const homeDir = homedir();
  return [
    // User-level agents (medium priority)
    join(homeDir, '.attocode', 'agents'),

    // Project-level agents (highest priority)
    join(process.cwd(), '.attocode', 'agents'),

    // Legacy project path (backward compat)
    join(process.cwd(), '.agents'),
  ];
}

/**
 * Get the directory where new agents should be created.
 * Prefers .attocode/agents/ in the project root.
 */
export function getAgentCreationDirectory(): string {
  return join(process.cwd(), '.attocode', 'agents');
}

/**
 * Get the user-level agent directory.
 */
export function getUserAgentDirectory(): string {
  return join(homedir(), '.attocode', 'agents');
}

/**
 * Determine the source type of an agent based on its path.
 */
export function getAgentSourceType(agentPath: string): AgentSourceType {
  const homeDir = homedir();
  const cwd = process.cwd();

  // Check for project-level (.attocode/agents/)
  if (agentPath.startsWith(join(cwd, '.attocode', 'agents'))) {
    return 'project';
  }

  // Check for user-level (~/.attocode/agents/)
  if (agentPath.startsWith(join(homeDir, '.attocode', 'agents'))) {
    return 'user';
  }

  // Legacy paths (.agents/)
  if (agentPath.includes('.agents')) {
    return 'legacy';
  }

  return 'project'; // Default to project
}

/**
 * Get a human-readable location string for an agent.
 */
export function getAgentLocationDisplay(agent: LoadedAgent): string {
  switch (agent.source) {
    case 'builtin':
      return 'built-in';
    case 'user':
      return '~/.attocode/agents/';
    case 'project':
      return '.attocode/agents/';
    case 'legacy':
      return '.agents/ (legacy)';
    default:
      return agent.filePath || 'unknown';
  }
}

// =============================================================================
// AGENT REGISTRY
// =============================================================================

/**
 * AgentRegistry manages agent definitions and spawning.
 */
export class AgentRegistry {
  private agents = new Map<string, LoadedAgent>();
  private listeners: RegistryEventListener[] = [];
  private watchController?: AbortController;
  private baseDir: string;

  constructor(baseDir?: string) {
    this.baseDir = baseDir || process.cwd();

    // Load built-in agents
    for (const agent of BUILTIN_AGENTS) {
      this.agents.set(agent.name, {
        ...agent,
        source: 'builtin',
        loadedAt: new Date(),
      });
    }
  }

  /**
   * Load user-defined agents from all configured directories.
   * Loads in priority order: user-level, project-level, legacy.
   * Later entries with the same name override earlier ones.
   */
  async loadUserAgents(): Promise<void> {
    const directories = getDefaultAgentDirectories();

    for (const agentsDir of directories) {
      if (!existsSync(agentsDir)) {
        continue; // Directory doesn't exist, skip
      }

      try {
        const files = await readdir(agentsDir);

        for (const file of files) {
          const ext = extname(file).toLowerCase();
          if (!['.json', '.yaml', '.yml'].includes(ext)) continue;

          const filePath = join(agentsDir, file);
          await this.loadAgentFile(filePath);
        }

        // Also check for subdirectories with AGENT.yaml
        for (const file of files) {
          const fullPath = join(agentsDir, file);
          try {
            const stat = await import('node:fs/promises').then(m => m.stat(fullPath));
            if (stat.isDirectory()) {
              const agentFile = await this.findAgentFileInDir(fullPath);
              if (agentFile) {
                await this.loadAgentFile(agentFile);
              }
            }
          } catch {
            // Not a directory or can't stat
          }
        }
      } catch (err) {
        // Directory read failed, continue to next
      }
    }
  }

  /**
   * Find an agent definition file in a directory.
   */
  private async findAgentFileInDir(dir: string): Promise<string | null> {
    const possibleFiles = ['AGENT.yaml', 'AGENT.yml', 'agent.yaml', 'agent.yml', 'agent.json'];

    for (const filename of possibleFiles) {
      const filePath = join(dir, filename);
      if (existsSync(filePath)) {
        return filePath;
      }
    }

    return null;
  }

  /**
   * Load an agent from a file.
   */
  private async loadAgentFile(filePath: string): Promise<void> {
    try {
      const content = await readFile(filePath, 'utf-8');
      const ext = extname(filePath).toLowerCase();

      let definition: AgentDefinition;

      if (ext === '.json') {
        definition = JSON.parse(content);
      } else if (ext === '.yaml' || ext === '.yml') {
        // Simple YAML parsing (for basic structures)
        definition = this.parseSimpleYaml(content);
      } else {
        return;
      }

      // Validate required fields
      if (!definition.name || !definition.description || !definition.systemPrompt) {
        throw new Error('Missing required fields: name, description, systemPrompt');
      }

      // Determine source type from path
      const sourceType = getAgentSourceType(filePath);

      // Store as loaded agent
      const loaded: LoadedAgent = {
        ...definition,
        source: sourceType,
        filePath,
        loadedAt: new Date(),
      };

      this.agents.set(definition.name, loaded);
      this.emit({ type: 'agent.loaded', name: definition.name, source: filePath });
    } catch (err) {
      const error = err instanceof Error ? err.message : String(err);
      this.emit({ type: 'agent.error', name: filePath, error });
    }
  }

  /**
   * Simple YAML parser for basic agent definitions.
   */
  private parseSimpleYaml(content: string): AgentDefinition {
    const result: Record<string, unknown> = {};
    let currentKey = '';
    let inMultiline = false;
    let multilineContent: string[] = [];

    const lines = content.split('\n');

    for (const line of lines) {
      // Skip comments and empty lines
      if (line.trim().startsWith('#') || line.trim() === '') {
        if (inMultiline) multilineContent.push('');
        continue;
      }

      // Check for multiline continuation
      if (inMultiline) {
        if (line.startsWith('  ') || line.startsWith('\t')) {
          multilineContent.push(line.trim());
          continue;
        } else {
          // End of multiline
          result[currentKey] = multilineContent.join('\n');
          inMultiline = false;
          multilineContent = [];
        }
      }

      // Parse key: value
      const match = line.match(/^(\w+):\s*(.*)$/);
      if (match) {
        const [, key, value] = match;
        currentKey = key;

        if (value === '|' || value === '>') {
          // Start multiline
          inMultiline = true;
          multilineContent = [];
        } else if (value.startsWith('[')) {
          // Array
          const arrayMatch = value.match(/\[(.*)\]/);
          if (arrayMatch) {
            result[key] = arrayMatch[1].split(',').map(s => s.trim().replace(/['"]/g, ''));
          }
        } else if (value === 'true' || value === 'false') {
          result[key] = value === 'true';
        } else if (!isNaN(Number(value))) {
          result[key] = Number(value);
        } else {
          result[key] = value.replace(/^['"]|['"]$/g, '');
        }
      }
    }

    // Handle final multiline
    if (inMultiline) {
      result[currentKey] = multilineContent.join('\n');
    }

    return result as unknown as AgentDefinition;
  }

  /**
   * Watch .agents/ directory for changes.
   */
  startWatching(): void {
    const agentsDir = join(this.baseDir, '.agents');

    if (!existsSync(agentsDir)) return;

    this.watchController = new AbortController();

    // Note: Using a polling approach since fs.watch has platform inconsistencies
    const checkForChanges = async () => {
      await this.loadUserAgents();
    };

    // Check every 5 seconds
    const interval = setInterval(checkForChanges, 5000);

    // Clean up on abort
    this.watchController.signal.addEventListener('abort', () => {
      clearInterval(interval);
    });
  }

  /**
   * Stop watching for changes.
   */
  stopWatching(): void {
    this.watchController?.abort();
    this.watchController = undefined;
  }

  /**
   * Get an agent by name.
   */
  getAgent(name: string): LoadedAgent | undefined {
    return this.agents.get(name);
  }

  /**
   * Get all agents.
   */
  getAllAgents(): LoadedAgent[] {
    return Array.from(this.agents.values());
  }

  /**
   * Get agents by source.
   */
  getAgentsBySource(source: 'builtin' | 'user'): LoadedAgent[] {
    return this.getAllAgents().filter(a => a.source === source);
  }

  /**
   * Find agents matching a query (for NL routing).
   */
  findMatchingAgents(query: string, limit: number = 3): LoadedAgent[] {
    const queryLower = query.toLowerCase();
    const scored: Array<{ agent: LoadedAgent; score: number }> = [];

    for (const agent of this.agents.values()) {
      let score = 0;

      // Check name match
      if (queryLower.includes(agent.name)) {
        score += 10;
      }

      // Check description match
      const descWords = agent.description.toLowerCase().split(/\s+/);
      for (const word of descWords) {
        if (queryLower.includes(word) && word.length > 3) {
          score += 2;
        }
      }

      // Check capabilities match
      for (const cap of agent.capabilities || []) {
        if (queryLower.includes(cap)) {
          score += 5;
        }
      }

      // Check tags match
      for (const tag of agent.tags || []) {
        if (queryLower.includes(tag)) {
          score += 3;
        }
      }

      if (score > 0) {
        scored.push({ agent, score });
      }
    }

    // Sort by score descending
    scored.sort((a, b) => b.score - a.score);

    return scored.slice(0, limit).map(s => s.agent);
  }

  /**
   * Register a runtime agent.
   */
  registerAgent(definition: AgentDefinition): void {
    const loaded: LoadedAgent = {
      ...definition,
      source: 'user',
      loadedAt: new Date(),
    };

    this.agents.set(definition.name, loaded);
    this.emit({ type: 'agent.loaded', name: definition.name, source: 'runtime' });
  }

  /**
   * Unregister an agent.
   */
  unregisterAgent(name: string): boolean {
    const existed = this.agents.delete(name);
    if (existed) {
      this.emit({ type: 'agent.removed', name });
    }
    return existed;
  }

  /**
   * Subscribe to events.
   */
  on(listener: RegistryEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  /**
   * Emit an event.
   */
  private emit(event: RegistryEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }

  /**
   * Cleanup.
   */
  cleanup(): void {
    this.stopWatching();
    this.listeners = [];
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create an agent registry and load user agents.
 */
export async function createAgentRegistry(baseDir?: string): Promise<AgentRegistry> {
  const registry = new AgentRegistry(baseDir);
  await registry.loadUserAgents();
  return registry;
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Filter tools based on agent's tool whitelist.
 * MCP tools (prefixed with 'mcp_') are always included to enable external integrations.
 */
export function filterToolsForAgent(
  agent: AgentDefinition,
  allTools: ToolDefinition[]
): ToolDefinition[] {
  if (!agent.tools || agent.tools.length === 0) {
    return allTools; // No whitelist = all tools
  }

  return allTools.filter(t =>
    agent.tools!.includes(t.name) || t.name.startsWith('mcp_')
  );
}

/**
 * Get a formatted list of agents for display.
 */
export function formatAgentList(agents: LoadedAgent[]): string {
  const lines: string[] = [];

  const builtIn = agents.filter(a => a.source === 'builtin');
  const userOrProject = agents.filter(a => a.source === 'user' || a.source === 'project');
  const legacy = agents.filter(a => a.source === 'legacy');

  if (builtIn.length > 0) {
    lines.push('Built-in Agents:');
    for (const agent of builtIn) {
      lines.push(`  ${agent.name} - ${agent.description.split('.')[0]}`);
    }
  }

  if (userOrProject.length > 0) {
    lines.push('\nCustom Agents:');
    for (const agent of userOrProject) {
      const location = getAgentLocationDisplay(agent);
      lines.push(`  ${agent.name} - ${agent.description.split('.')[0]} (${location})`);
    }
  }

  if (legacy.length > 0) {
    lines.push('\nLegacy Agents (.agents/):');
    for (const agent of legacy) {
      lines.push(`  ${agent.name} - ${agent.description.split('.')[0]}`);
    }
  }

  return lines.join('\n');
}

/**
 * Get an agent scaffold template in YAML format.
 */
export function getAgentScaffold(name: string, options: {
  description?: string;
  model?: 'fast' | 'balanced' | 'quality';
  capabilities?: string[];
  tools?: string[];
} = {}): string {
  const {
    description = '[Add description here]',
    model = 'balanced',
    capabilities = [],
    tools = [],
  } = options;

  return `name: ${name}
description: ${description}
model: ${model}
maxIterations: 30
maxTokenBudget: 80000

capabilities:
${capabilities.length > 0 ? capabilities.map(c => `  - ${c}`).join('\n') : '  - # Add capabilities for NL matching'}

tools:
${tools.length > 0 ? tools.map(t => `  - ${t}`).join('\n') : '  - read_file\n  - list_files\n  - glob\n  - grep'}

systemPrompt: |
  You are ${name}. Your job is to:
  - [Add primary responsibilities]
  - [Add secondary tasks]

  Guidelines:
  - Be thorough but concise
  - Focus on the user's specific needs
  - Ask clarifying questions when needed

tags:
  - ${name}
`;
}

/**
 * Result of creating an agent scaffold.
 */
export interface AgentScaffoldResult {
  success: boolean;
  path?: string;
  error?: string;
}

/**
 * Create an agent scaffold in the .attocode/agents/ directory.
 */
export async function createAgentScaffold(
  name: string,
  options: {
    description?: string;
    model?: 'fast' | 'balanced' | 'quality';
    capabilities?: string[];
    tools?: string[];
    userLevel?: boolean;  // Create in ~/.attocode/agents/ instead of project
  } = {}
): Promise<AgentScaffoldResult> {
  try {
    // Validate name
    if (!/^[a-z][a-z0-9-]*$/.test(name)) {
      return {
        success: false,
        error: 'Agent name must start with a letter and contain only lowercase letters, numbers, and hyphens',
      };
    }

    // Determine target directory
    const baseDir = options.userLevel
      ? getUserAgentDirectory()
      : getAgentCreationDirectory();

    const agentDir = join(baseDir, name);
    const agentPath = join(agentDir, 'AGENT.yaml');

    // Check if agent already exists
    if (existsSync(agentPath)) {
      return {
        success: false,
        error: `Agent "${name}" already exists at ${agentPath}`,
      };
    }

    // Create directory structure
    await mkdir(agentDir, { recursive: true });

    // Write agent file
    const content = getAgentScaffold(name, options);
    await writeFile(agentPath, content, 'utf-8');

    return {
      success: true,
      path: agentPath,
    };
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

/**
 * Get statistics about loaded agents by source.
 */
export function getAgentStats(agents: LoadedAgent[]): Record<AgentSourceType, number> {
  const stats: Record<AgentSourceType, number> = {
    builtin: 0,
    user: 0,
    project: 0,
    legacy: 0,
  };

  for (const agent of agents) {
    stats[agent.source]++;
  }

  return stats;
}
