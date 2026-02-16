/**
 * Capabilities Registry
 *
 * Unified view of all agent capabilities: tools, skills, agents, MCP tools, and commands.
 * Enables discovery through /powers command and semantic search.
 */

import type { ToolDefinition } from '../../types.js';
import type { SkillManager } from '../skills/skills.js';
import type { AgentRegistry } from '../agents/agent-registry.js';
import type { MCPClient } from '../mcp/mcp-client.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Capability types in the system.
 */
export type CapabilityType = 'tool' | 'skill' | 'agent' | 'mcp_tool' | 'command';

/**
 * A capability represents any action the agent can perform.
 */
export interface Capability {
  /** Unique identifier (e.g., "tool:read_file", "skill:review") */
  id: string;

  /** Display name */
  name: string;

  /** Type of capability */
  type: CapabilityType;

  /** Human-readable description */
  description: string;

  /** Whether this capability is currently active/available */
  active: boolean;

  /** Source of the capability (e.g., "built-in", "mcp:github", "skills/review.md") */
  source: string;

  /** Tags for discovery */
  tags: string[];

  /** Additional metadata */
  metadata?: Record<string, unknown>;
}

/**
 * Search result with relevance score.
 */
export interface CapabilitySearchResult {
  capability: Capability;
  score: number;
  matches: string[];
}

/**
 * Counts by capability type.
 */
export interface CapabilityCounts {
  total: number;
  active: number;
}

/**
 * Command definition for discovery.
 */
export interface CommandDefinition {
  name: string;
  description: string;
  category?: string;
  aliases?: string[];
}

/**
 * Registry event types.
 */
export type CapabilitiesEvent =
  | { type: 'capability.added'; capability: Capability }
  | { type: 'capability.removed'; id: string }
  | { type: 'capability.updated'; capability: Capability }
  | { type: 'registry.refreshed'; counts: Record<CapabilityType, CapabilityCounts> };

export type CapabilitiesEventListener = (event: CapabilitiesEvent) => void;

// =============================================================================
// BUILT-IN COMMANDS
// =============================================================================

const BUILT_IN_COMMANDS: CommandDefinition[] = [
  // General
  { name: '/help', description: 'Show help and available commands', category: 'general', aliases: ['/h', '/?'] },
  { name: '/status', description: 'Show session stats, metrics & token usage', category: 'general' },
  { name: '/clear', description: 'Clear the screen', category: 'general' },
  { name: '/reset', description: 'Reset agent state (clears conversation)', category: 'general' },
  { name: '/quit', description: 'Exit attocode', category: 'general', aliases: ['/exit', '/q'] },

  // Modes
  { name: '/mode', description: 'Show/change current mode (build, plan, review, debug)', category: 'modes' },
  { name: '/plan', description: 'Toggle plan mode (writes queued for approval)', category: 'modes' },

  // Plan approval
  { name: '/show-plan', description: 'Show pending plan with proposed changes', category: 'plan' },
  { name: '/approve', description: 'Approve and execute pending changes', category: 'plan' },
  { name: '/reject', description: 'Reject and discard pending changes', category: 'plan' },

  // Sessions
  { name: '/save', description: 'Save current session to disk', category: 'sessions' },
  { name: '/load', description: 'Load a previous session by ID', category: 'sessions' },
  { name: '/sessions', description: 'List all saved sessions', category: 'sessions' },
  { name: '/resume', description: 'Resume most recent session', category: 'sessions' },

  // Context
  { name: '/context', description: 'Show context window usage', category: 'context' },
  { name: '/compact', description: 'Summarize & compress context', category: 'context' },

  // Checkpoints
  { name: '/checkpoint', description: 'Create a named checkpoint', category: 'checkpoints', aliases: ['/cp'] },
  { name: '/checkpoints', description: 'List all checkpoints', category: 'checkpoints', aliases: ['/cps'] },
  { name: '/restore', description: 'Restore to a checkpoint', category: 'checkpoints' },
  { name: '/rollback', description: 'Rollback n steps', category: 'checkpoints', aliases: ['/rb'] },

  // Subagents
  { name: '/agents', description: 'List available agents', category: 'subagents' },
  { name: '/spawn', description: 'Spawn a specific agent', category: 'subagents' },
  { name: '/find', description: 'Find agents by keyword', category: 'subagents' },
  { name: '/suggest', description: 'AI-powered agent suggestion', category: 'subagents' },
  { name: '/auto', description: 'Auto-route task to best agent', category: 'subagents' },

  // MCP
  { name: '/mcp', description: 'Manage MCP servers and tools', category: 'mcp' },

  // Budget
  { name: '/budget', description: 'Show token/cost budget', category: 'budget' },
  { name: '/extend', description: 'Extend budget limit', category: 'budget' },

  // Security
  { name: '/grants', description: 'Show active permission grants', category: 'security' },
  { name: '/audit', description: 'Show security audit log', category: 'security' },

  // Debugging
  { name: '/skills', description: 'List loaded skills', category: 'debugging' },
  { name: '/sandbox', description: 'Show sandbox modes', category: 'debugging' },
  { name: '/shell', description: 'Show PTY shell info', category: 'debugging' },
  { name: '/powers', description: 'Show all agent capabilities', category: 'debugging' },
];

// =============================================================================
// CAPABILITIES REGISTRY
// =============================================================================

/**
 * Unified registry for all agent capabilities.
 */
export class CapabilitiesRegistry {
  private capabilities: Map<string, Capability> = new Map();
  private eventListeners: Set<CapabilitiesEventListener> = new Set();

  // Registered sources
  private toolRegistry?: { getTools(): ToolDefinition[] };
  private skillManager?: SkillManager;
  private agentRegistry?: AgentRegistry;
  private mcpClient?: MCPClient;

  /**
   * Register the tool registry as a capability source.
   */
  registerToolRegistry(registry: { getTools(): ToolDefinition[] }): void {
    this.toolRegistry = registry;
    this.refreshTools();
  }

  /**
   * Register the skill manager as a capability source.
   */
  registerSkillManager(manager: SkillManager): void {
    this.skillManager = manager;
    this.refreshSkills();
  }

  /**
   * Register the agent registry as a capability source.
   */
  registerAgentRegistry(registry: AgentRegistry): void {
    this.agentRegistry = registry;
    this.refreshAgents();
  }

  /**
   * Register the MCP client as a capability source.
   */
  registerMCPClient(client: MCPClient): void {
    this.mcpClient = client;
    this.refreshMCPTools();
  }

  /**
   * Refresh all capabilities from registered sources.
   */
  refresh(): void {
    this.refreshTools();
    this.refreshSkills();
    this.refreshAgents();
    this.refreshMCPTools();
    this.refreshCommands();
    this.emit({ type: 'registry.refreshed', counts: this.getCounts() });
  }

  private refreshTools(): void {
    if (!this.toolRegistry) return;

    // Remove old tools
    for (const [id, cap] of this.capabilities) {
      if (cap.type === 'tool') {
        this.capabilities.delete(id);
      }
    }

    // Add current tools
    for (const tool of this.toolRegistry.getTools()) {
      // Skip MCP tools (they're handled separately)
      if (tool.name.startsWith('mcp_')) continue;

      const capability: Capability = {
        id: `tool:${tool.name}`,
        name: tool.name,
        type: 'tool',
        description: tool.description,
        active: true,
        source: 'built-in',
        tags: this.extractTags(tool.description),
        metadata: {
          dangerLevel: tool.dangerLevel,
          parameters: tool.parameters,
        },
      };
      this.capabilities.set(capability.id, capability);
    }
  }

  private refreshSkills(): void {
    if (!this.skillManager) return;

    // Remove old skills
    for (const [id, cap] of this.capabilities) {
      if (cap.type === 'skill') {
        this.capabilities.delete(id);
      }
    }

    // Add current skills
    for (const skill of this.skillManager.getAllSkills()) {
      const capability: Capability = {
        id: `skill:${skill.name}`,
        name: skill.name,
        type: 'skill',
        description: skill.description,
        active: this.skillManager.isSkillActive(skill.name),
        source: skill.sourcePath,
        tags: [...(skill.tags || []), ...(skill.invokable ? ['invokable'] : [])],
        metadata: {
          invokable: skill.invokable,
          arguments: skill.arguments,
          tools: skill.tools,
        },
      };
      this.capabilities.set(capability.id, capability);
    }
  }

  private refreshAgents(): void {
    if (!this.agentRegistry) return;

    // Remove old agents
    for (const [id, cap] of this.capabilities) {
      if (cap.type === 'agent') {
        this.capabilities.delete(id);
      }
    }

    // Add current agents
    for (const agent of this.agentRegistry.getAllAgents()) {
      const capability: Capability = {
        id: `agent:${agent.name}`,
        name: agent.name,
        type: 'agent',
        description: agent.description,
        active: true,
        source: agent.source || 'built-in',
        tags: agent.capabilities || [],
        metadata: {
          model: agent.model,
          maxIterations: agent.maxIterations,
        },
      };
      this.capabilities.set(capability.id, capability);
    }
  }

  private refreshMCPTools(): void {
    if (!this.mcpClient) return;

    // Remove old MCP tools
    for (const [id, cap] of this.capabilities) {
      if (cap.type === 'mcp_tool') {
        this.capabilities.delete(id);
      }
    }

    // Add current MCP tools
    for (const tool of this.mcpClient.getAllTools()) {
      const capability: Capability = {
        id: `mcp_tool:${tool.name}`,
        name: tool.name,
        type: 'mcp_tool',
        description: tool.description || 'No description',
        active: this.mcpClient.isToolLoaded(tool.name),
        source: `mcp:${tool.name.split('_')[1] || 'unknown'}`,
        tags: this.extractTags(tool.description || ''),
      };
      this.capabilities.set(capability.id, capability);
    }
  }

  private refreshCommands(): void {
    // Remove old commands
    for (const [id, cap] of this.capabilities) {
      if (cap.type === 'command') {
        this.capabilities.delete(id);
      }
    }

    // Add built-in commands
    for (const cmd of BUILT_IN_COMMANDS) {
      const capability: Capability = {
        id: `command:${cmd.name}`,
        name: cmd.name,
        type: 'command',
        description: cmd.description,
        active: true,
        source: 'built-in',
        tags: [cmd.category || 'general'],
        metadata: {
          aliases: cmd.aliases,
          category: cmd.category,
        },
      };
      this.capabilities.set(capability.id, capability);
    }
  }

  /**
   * Extract tags from description text.
   */
  private extractTags(text: string): string[] {
    const tags: string[] = [];
    const keywords = ['file', 'search', 'edit', 'read', 'write', 'bash', 'git', 'code', 'test', 'debug'];

    const lowerText = text.toLowerCase();
    for (const keyword of keywords) {
      if (lowerText.includes(keyword)) {
        tags.push(keyword);
      }
    }

    return tags;
  }

  /**
   * Get all capabilities.
   */
  getAll(): Capability[] {
    return Array.from(this.capabilities.values());
  }

  /**
   * Get capabilities by type.
   */
  getByType(type: CapabilityType): Capability[] {
    return this.getAll().filter(c => c.type === type);
  }

  /**
   * Search capabilities by query.
   */
  search(query: string): CapabilitySearchResult[] {
    const queryLower = query.toLowerCase();
    const queryTerms = queryLower.split(/\s+/);
    const results: CapabilitySearchResult[] = [];

    for (const capability of this.capabilities.values()) {
      let score = 0;
      const matches: string[] = [];

      // Check name match
      const nameLower = capability.name.toLowerCase();
      if (nameLower.includes(queryLower)) {
        score += 10;
        matches.push('name');
      }
      for (const term of queryTerms) {
        if (nameLower.includes(term)) {
          score += 3;
        }
      }

      // Check description match
      const descLower = capability.description.toLowerCase();
      for (const term of queryTerms) {
        if (descLower.includes(term)) {
          score += 2;
          if (!matches.includes('description')) {
            matches.push('description');
          }
        }
      }

      // Check tags match
      for (const tag of capability.tags) {
        const tagLower = tag.toLowerCase();
        if (tagLower.includes(queryLower) || queryLower.includes(tagLower)) {
          score += 5;
          matches.push(`tag:${tag}`);
        }
      }

      // Boost active capabilities
      if (capability.active) {
        score *= 1.2;
      }

      if (score > 0) {
        results.push({ capability, score, matches });
      }
    }

    return results.sort((a, b) => b.score - a.score);
  }

  /**
   * Get counts by type.
   */
  getCounts(): Record<CapabilityType, CapabilityCounts> {
    const counts: Record<CapabilityType, CapabilityCounts> = {
      tool: { total: 0, active: 0 },
      skill: { total: 0, active: 0 },
      agent: { total: 0, active: 0 },
      mcp_tool: { total: 0, active: 0 },
      command: { total: 0, active: 0 },
    };

    for (const capability of this.capabilities.values()) {
      counts[capability.type].total++;
      if (capability.active) {
        counts[capability.type].active++;
      }
    }

    return counts;
  }

  /**
   * Get a specific capability by ID.
   */
  get(id: string): Capability | undefined {
    return this.capabilities.get(id);
  }

  /**
   * Subscribe to registry events.
   */
  subscribe(listener: CapabilitiesEventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  private emit(event: CapabilitiesEvent): void {
    for (const listener of this.eventListeners) {
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
 * Create a capabilities registry.
 */
export function createCapabilitiesRegistry(): CapabilitiesRegistry {
  return new CapabilitiesRegistry();
}

/**
 * Format capabilities summary for display.
 */
export function formatCapabilitiesSummary(counts: Record<CapabilityType, CapabilityCounts>): string {
  const lines: string[] = [
    'Agent Capabilities:',
    `  Tools:     ${counts.tool.active}/${counts.tool.total}`,
    `  Skills:    ${counts.skill.active}/${counts.skill.total}`,
    `  Agents:    ${counts.agent.active}/${counts.agent.total}`,
    `  MCP Tools: ${counts.mcp_tool.active}/${counts.mcp_tool.total}`,
    `  Commands:  ${counts.command.active}/${counts.command.total}`,
  ];

  const total = Object.values(counts).reduce((sum, c) => sum + c.total, 0);
  const active = Object.values(counts).reduce((sum, c) => sum + c.active, 0);
  lines.push(`  Total:     ${active}/${total}`);

  return lines.join('\n');
}

/**
 * Format capabilities list for a specific type.
 */
export function formatCapabilitiesList(capabilities: Capability[], type: CapabilityType): string {
  if (capabilities.length === 0) {
    return `No ${type}s available.`;
  }

  const lines: string[] = [`${capitalize(type)}s (${capabilities.length}):`];

  for (const cap of capabilities) {
    const status = cap.active ? '+' : 'o';
    const tags = cap.tags.length > 0 ? ` [${cap.tags.slice(0, 3).join(', ')}]` : '';
    lines.push(`  ${status} ${cap.name} - ${cap.description.slice(0, 60)}${cap.description.length > 60 ? '...' : ''}${tags}`);
  }

  return lines.join('\n');
}

/**
 * Format search results for display.
 */
export function formatSearchResults(results: CapabilitySearchResult[], limit = 10): string {
  if (results.length === 0) {
    return 'No matching capabilities found.';
  }

  const lines: string[] = [`Found ${results.length} result(s):`];
  const shown = results.slice(0, limit);

  for (const { capability, score, matches } of shown) {
    const type = capability.type.replace('_', ' ');
    const matchInfo = matches.slice(0, 2).join(', ');
    lines.push(`  [${type}] ${capability.name} (score: ${score.toFixed(1)})`);
    lines.push(`    ${capability.description.slice(0, 70)}${capability.description.length > 70 ? '...' : ''}`);
    lines.push(`    Matched: ${matchInfo}`);
  }

  if (results.length > limit) {
    lines.push(`  ... and ${results.length - limit} more`);
  }

  return lines.join('\n');
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
