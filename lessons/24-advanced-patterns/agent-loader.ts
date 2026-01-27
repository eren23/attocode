/**
 * Lesson 24: Agent Loader
 *
 * Loads agent definitions from markdown files with YAML frontmatter.
 * This enables configuration-driven agents where behavior is defined
 * in human-readable files rather than code.
 *
 * Inspired by OpenCode's agent definition pattern.
 */

import * as fs from 'fs';
import * as path from 'path';
import type {
  AgentDefinition,
  AgentFrontmatter,
  AdvancedPatternEvent,
  AdvancedPatternEventListener,
} from './types.js';

// =============================================================================
// AGENT LOADER
// =============================================================================

/**
 * Loads and manages agent definitions from markdown files.
 */
export class AgentLoader {
  private agents: Map<string, AgentDefinition> = new Map();
  private watchedPaths: Set<string> = new Set();
  private fileWatchers: Map<string, fs.FSWatcher> = new Map();
  private eventListeners: Set<AdvancedPatternEventListener> = new Set();

  // ===========================================================================
  // LOADING
  // ===========================================================================

  /**
   * Load an agent definition from a markdown file.
   */
  loadFromFile(filePath: string): AgentDefinition | null {
    try {
      const content = fs.readFileSync(filePath, 'utf-8');
      const agent = this.parseAgentMarkdown(content, filePath);

      if (agent) {
        this.agents.set(agent.name, agent);
        this.emit({ type: 'agent.loaded', agent });
      }

      return agent;
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error);
      this.emit({
        type: 'agent.error',
        name: path.basename(filePath, '.md'),
        error: errorMsg,
      });
      return null;
    }
  }

  /**
   * Load all agent definitions from a directory.
   */
  loadFromDirectory(dirPath: string): AgentDefinition[] {
    const loaded: AgentDefinition[] = [];

    if (!fs.existsSync(dirPath)) {
      return loaded;
    }

    const files = fs.readdirSync(dirPath);
    for (const file of files) {
      if (file.endsWith('.md')) {
        const agent = this.loadFromFile(path.join(dirPath, file));
        if (agent) {
          loaded.push(agent);
        }
      }
    }

    return loaded;
  }

  /**
   * Load an agent from a string (useful for testing).
   */
  loadFromString(content: string, name?: string): AgentDefinition | null {
    const agent = this.parseAgentMarkdown(content);
    if (agent) {
      if (name) {
        agent.name = name;
      }
      this.agents.set(agent.name, agent);
      this.emit({ type: 'agent.loaded', agent });
    }
    return agent;
  }

  // ===========================================================================
  // PARSING
  // ===========================================================================

  /**
   * Parse agent markdown with YAML frontmatter.
   */
  private parseAgentMarkdown(
    content: string,
    sourceFile?: string
  ): AgentDefinition | null {
    // Extract frontmatter
    const frontmatterMatch = content.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);

    if (!frontmatterMatch) {
      // No frontmatter, treat entire content as system prompt
      return {
        name: sourceFile ? path.basename(sourceFile, '.md') : 'unnamed',
        systemPrompt: content.trim(),
        sourceFile,
        loadedAt: new Date(),
      };
    }

    const [, frontmatterStr, bodyContent] = frontmatterMatch;

    // Parse YAML frontmatter (simple implementation)
    const frontmatter = this.parseYaml(frontmatterStr);

    if (!frontmatter.name) {
      frontmatter.name = sourceFile
        ? path.basename(sourceFile, '.md')
        : 'unnamed';
    }

    // Build agent definition
    const agent: AgentDefinition = {
      name: frontmatter.name,
      displayName: frontmatter.displayName,
      description: frontmatter.description as string | undefined,
      model: frontmatter.model,
      tools: this.parseTools(frontmatter.tools),
      systemPrompt: bodyContent.trim(),
      authority: frontmatter.authority,
      maxConcurrentTasks: frontmatter.maxConcurrentTasks,
      settings: this.extractSettings(frontmatter),
      sourceFile,
      loadedAt: new Date(),
    };

    return agent;
  }

  /**
   * Simple YAML parser for frontmatter.
   * Handles basic key-value pairs and arrays.
   */
  private parseYaml(yaml: string): AgentFrontmatter {
    const result: Record<string, unknown> = {};
    const lines = yaml.split('\n');

    let currentKey: string | null = null;
    let currentArray: string[] | null = null;

    for (const line of lines) {
      // Skip empty lines and comments
      if (!line.trim() || line.trim().startsWith('#')) {
        continue;
      }

      // Check for array item
      if (line.match(/^\s*-\s/)) {
        if (currentArray) {
          const value = line.replace(/^\s*-\s*/, '').trim();
          currentArray.push(value);
        }
        continue;
      }

      // Key-value pair
      const kvMatch = line.match(/^(\w+):\s*(.*)$/);
      if (kvMatch) {
        // Save previous array if any
        if (currentKey && currentArray) {
          result[currentKey] = currentArray;
        }

        currentKey = kvMatch[1];
        const value = kvMatch[2].trim();

        if (value === '') {
          // Start of array
          currentArray = [];
        } else if (value.startsWith('[') && value.endsWith(']')) {
          // Inline array
          result[currentKey] = value
            .slice(1, -1)
            .split(',')
            .map(s => s.trim());
          currentKey = null;
          currentArray = null;
        } else {
          // Scalar value
          result[currentKey] = this.parseScalar(value);
          currentKey = null;
          currentArray = null;
        }
      }
    }

    // Save final array if any
    if (currentKey && currentArray) {
      result[currentKey] = currentArray;
    }

    return result as AgentFrontmatter;
  }

  /**
   * Parse a scalar YAML value.
   */
  private parseScalar(value: string): unknown {
    // Boolean
    if (value === 'true') return true;
    if (value === 'false') return false;

    // Number
    if (/^-?\d+(\.\d+)?$/.test(value)) {
      return parseFloat(value);
    }

    // Quoted string
    if ((value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))) {
      return value.slice(1, -1);
    }

    // Plain string
    return value;
  }

  /**
   * Parse tools list (handles both string array and comma-separated).
   */
  private parseTools(tools: unknown): string[] | undefined {
    if (!tools) return undefined;

    if (Array.isArray(tools)) {
      return tools.map(t => String(t).trim());
    }

    if (typeof tools === 'string') {
      return tools.split(',').map(t => t.trim());
    }

    return undefined;
  }

  /**
   * Extract custom settings from frontmatter.
   */
  private extractSettings(
    frontmatter: AgentFrontmatter
  ): Record<string, unknown> | undefined {
    const reserved = [
      'name',
      'displayName',
      'description',
      'model',
      'tools',
      'authority',
      'maxConcurrentTasks',
    ];

    const settings: Record<string, unknown> = {};
    let hasSettings = false;

    for (const [key, value] of Object.entries(frontmatter)) {
      if (!reserved.includes(key)) {
        settings[key] = value;
        hasSettings = true;
      }
    }

    return hasSettings ? settings : undefined;
  }

  // ===========================================================================
  // AGENT ACCESS
  // ===========================================================================

  /**
   * Get an agent by name.
   */
  getAgent(name: string): AgentDefinition | undefined {
    return this.agents.get(name);
  }

  /**
   * Get all loaded agents.
   */
  getAllAgents(): AgentDefinition[] {
    return Array.from(this.agents.values());
  }

  /**
   * Get agent names.
   */
  getAgentNames(): string[] {
    return Array.from(this.agents.keys());
  }

  /**
   * Check if an agent is loaded.
   */
  hasAgent(name: string): boolean {
    return this.agents.has(name);
  }

  /**
   * Remove an agent.
   */
  removeAgent(name: string): boolean {
    return this.agents.delete(name);
  }

  /**
   * Clear all agents.
   */
  clearAgents(): void {
    this.agents.clear();
  }

  // ===========================================================================
  // FILE WATCHING
  // ===========================================================================

  /**
   * Watch a directory for agent changes.
   */
  watchDirectory(dirPath: string): () => void {
    if (this.watchedPaths.has(dirPath)) {
      return () => this.unwatchDirectory(dirPath);
    }

    this.watchedPaths.add(dirPath);

    // Initial load
    this.loadFromDirectory(dirPath);

    // Set up watcher
    try {
      const watcher = fs.watch(dirPath, (eventType, filename) => {
        if (filename && filename.endsWith('.md')) {
          const filePath = path.join(dirPath, filename);

          if (eventType === 'change' || eventType === 'rename') {
            if (fs.existsSync(filePath)) {
              const agent = this.loadFromFile(filePath);
              if (agent) {
                this.emit({ type: 'agent.reloaded', agent });
              }
            }
          }
        }
      });

      this.fileWatchers.set(dirPath, watcher);
    } catch (error) {
      console.error(`Failed to watch directory ${dirPath}:`, error);
    }

    return () => this.unwatchDirectory(dirPath);
  }

  /**
   * Stop watching a directory.
   */
  unwatchDirectory(dirPath: string): void {
    const watcher = this.fileWatchers.get(dirPath);
    if (watcher) {
      watcher.close();
      this.fileWatchers.delete(dirPath);
    }
    this.watchedPaths.delete(dirPath);
  }

  /**
   * Stop all file watchers.
   */
  unwatchAll(): void {
    for (const [dirPath] of this.fileWatchers) {
      this.unwatchDirectory(dirPath);
    }
  }

  // ===========================================================================
  // AGENT CREATION HELPERS
  // ===========================================================================

  /**
   * Create agent definition programmatically.
   */
  createAgent(definition: Partial<AgentDefinition> & { name: string }): AgentDefinition {
    const agent: AgentDefinition = {
      name: definition.name,
      displayName: definition.displayName,
      description: definition.description,
      model: definition.model,
      tools: definition.tools,
      systemPrompt: definition.systemPrompt || '',
      authority: definition.authority,
      maxConcurrentTasks: definition.maxConcurrentTasks,
      settings: definition.settings,
      loadedAt: new Date(),
    };

    this.agents.set(agent.name, agent);
    this.emit({ type: 'agent.loaded', agent });

    return agent;
  }

  /**
   * Generate markdown for an agent definition.
   */
  toMarkdown(agent: AgentDefinition): string {
    const frontmatter: string[] = ['---'];

    frontmatter.push(`name: ${agent.name}`);
    if (agent.displayName) frontmatter.push(`displayName: ${agent.displayName}`);
    if (agent.model) frontmatter.push(`model: ${agent.model}`);
    if (agent.tools && agent.tools.length > 0) {
      frontmatter.push(`tools: [${agent.tools.join(', ')}]`);
    }
    if (agent.authority !== undefined) frontmatter.push(`authority: ${agent.authority}`);
    if (agent.maxConcurrentTasks !== undefined) {
      frontmatter.push(`maxConcurrentTasks: ${agent.maxConcurrentTasks}`);
    }

    if (agent.settings) {
      for (const [key, value] of Object.entries(agent.settings)) {
        frontmatter.push(`${key}: ${JSON.stringify(value)}`);
      }
    }

    frontmatter.push('---');
    frontmatter.push('');
    frontmatter.push(agent.systemPrompt);

    return frontmatter.join('\n');
  }

  /**
   * Save agent to file.
   */
  saveAgent(agent: AgentDefinition, filePath: string): boolean {
    try {
      const markdown = this.toMarkdown(agent);
      fs.writeFileSync(filePath, markdown);
      agent.sourceFile = filePath;
      return true;
    } catch (error) {
      console.error(`Failed to save agent to ${filePath}:`, error);
      return false;
    }
  }

  // ===========================================================================
  // EVENTS
  // ===========================================================================

  /**
   * Subscribe to events.
   */
  subscribe(listener: AdvancedPatternEventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  /**
   * Emit an event.
   */
  private emit(event: AdvancedPatternEvent): void {
    for (const listener of this.eventListeners) {
      try {
        listener(event);
      } catch (error) {
        console.error('Event listener error:', error);
      }
    }
  }

  // ===========================================================================
  // CLEANUP
  // ===========================================================================

  /**
   * Cleanup all resources.
   */
  cleanup(): void {
    this.unwatchAll();
    this.agents.clear();
    this.eventListeners.clear();
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create an agent loader.
 */
export function createAgentLoader(): AgentLoader {
  return new AgentLoader();
}

/**
 * Create an agent loader and load from a directory.
 */
export function createAgentLoaderWithDirectory(
  dirPath: string,
  watch: boolean = false
): AgentLoader {
  const loader = new AgentLoader();
  loader.loadFromDirectory(dirPath);
  if (watch) {
    loader.watchDirectory(dirPath);
  }
  return loader;
}

// =============================================================================
// BUILT-IN AGENT TEMPLATES
// =============================================================================

/**
 * Built-in agent templates.
 */
export const AGENT_TEMPLATES = {
  coder: `---
name: coder
displayName: Code Writer
model: claude-3-5-sonnet
tools: [read_file, write_file, search, bash]
authority: 5
---

# Code Writer Agent

You are an expert software developer. Your role is to write clean,
efficient, and well-documented code.

## Guidelines

1. Follow established coding conventions
2. Write comprehensive tests
3. Document your code clearly
4. Consider edge cases
5. Optimize for readability first
`,

  reviewer: `---
name: reviewer
displayName: Code Reviewer
model: claude-3-5-haiku
tools: [read_file, search]
authority: 3
---

# Code Reviewer Agent

You are a thorough code reviewer focused on quality and security.

## Review Focus

1. **Security**: Look for vulnerabilities
2. **Performance**: Identify bottlenecks
3. **Style**: Ensure consistency
4. **Logic**: Verify correctness
5. **Tests**: Check coverage

## Output Format

For each issue found:
- Severity: critical/high/medium/low
- Location: file:line
- Issue: description
- Suggestion: how to fix
`,

  researcher: `---
name: researcher
displayName: Research Assistant
model: claude-3-5-sonnet
tools: [search, read_file, web_search]
authority: 2
---

# Research Assistant Agent

You help gather and synthesize information.

## Approach

1. Understand the research question
2. Search for relevant sources
3. Analyze and synthesize findings
4. Present clear conclusions
5. Cite your sources

## Output

Provide structured research summaries with:
- Key findings
- Supporting evidence
- Limitations
- Recommendations
`,
};
