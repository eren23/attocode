/**
 * Skills Standard (Crush-inspired)
 *
 * Discoverable skill packages that provide specialized agent capabilities.
 * Skills are defined as markdown files with YAML frontmatter containing
 * metadata like name, description, and required tools.
 *
 * Directory structure:
 * - Built-in skills: 25-production-agent/skills/
 * - User skills: .agent/skills/
 * - Global skills: ~/.agent/skills/
 *
 * Usage:
 *   const skills = createSkillManager({ directories: ['.agent/skills'] });
 *   await skills.loadSkills();
 *   await skills.activateSkill('code-review', context);
 */

import { readFile, readdir, stat } from 'fs/promises';
import { join, basename, dirname } from 'path';
import { homedir } from 'os';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Skill definition from SKILL.md or skill.md file.
 */
export interface Skill {
  /** Unique skill name (derived from directory or frontmatter) */
  name: string;

  /** Human-readable description */
  description: string;

  /** Tools this skill can use */
  tools: string[];

  /** The markdown content (instructions for the agent) */
  content: string;

  /** Source file path */
  sourcePath: string;

  /** Optional version */
  version?: string;

  /** Optional author */
  author?: string;

  /** Optional tags for discovery */
  tags?: string[];

  /** Whether this skill is active */
  active?: boolean;

  /** When to auto-activate this skill */
  triggers?: SkillTrigger[];
}

/**
 * Skill trigger definition.
 */
export interface SkillTrigger {
  /** Trigger type */
  type: 'keyword' | 'file_pattern' | 'context';

  /** Pattern to match */
  pattern: string;
}

/**
 * Skill manager configuration.
 */
export interface SkillsConfig {
  /** Enable/disable skills */
  enabled?: boolean;

  /** Directories to search for skills */
  directories?: string[];

  /** Whether to load built-in skills */
  loadBuiltIn?: boolean;

  /** Auto-activate skills based on triggers */
  autoActivate?: boolean;
}

/**
 * Skill event types.
 */
export type SkillEvent =
  | { type: 'skill.loaded'; name: string; path: string }
  | { type: 'skill.activated'; name: string }
  | { type: 'skill.deactivated'; name: string }
  | { type: 'skill.error'; name: string; error: string };

export type SkillEventListener = (event: SkillEvent) => void;

// =============================================================================
// DEFAULT DIRECTORIES
// =============================================================================

/**
 * Default skill directories.
 */
export function getDefaultSkillDirectories(): string[] {
  return [
    '.agent/skills',                           // Project-specific
    join(homedir(), '.agent', 'skills'),       // User global
  ];
}

// =============================================================================
// YAML FRONTMATTER PARSER
// =============================================================================

/**
 * Parse YAML frontmatter from markdown content.
 * Handles the --- delimited block at the start of the file.
 */
function parseFrontmatter(content: string): { frontmatter: Record<string, unknown>; body: string } {
  const lines = content.split('\n');

  if (lines[0]?.trim() !== '---') {
    return { frontmatter: {}, body: content };
  }

  let endIndex = -1;
  for (let i = 1; i < lines.length; i++) {
    if (lines[i]?.trim() === '---') {
      endIndex = i;
      break;
    }
  }

  if (endIndex === -1) {
    return { frontmatter: {}, body: content };
  }

  const yamlContent = lines.slice(1, endIndex).join('\n');
  const body = lines.slice(endIndex + 1).join('\n').trim();

  // Simple YAML parser for frontmatter
  const frontmatter: Record<string, unknown> = {};

  for (const line of yamlContent.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;

    const colonIndex = trimmed.indexOf(':');
    if (colonIndex === -1) continue;

    const key = trimmed.slice(0, colonIndex).trim();
    let value: unknown = trimmed.slice(colonIndex + 1).trim();

    // Handle arrays (simple format: [item1, item2])
    if (typeof value === 'string' && value.startsWith('[') && value.endsWith(']')) {
      value = value.slice(1, -1).split(',').map(s => s.trim().replace(/^["']|["']$/g, ''));
    }
    // Handle quoted strings
    else if (typeof value === 'string' && (value.startsWith('"') || value.startsWith("'"))) {
      value = value.slice(1, -1);
    }
    // Handle booleans
    else if (value === 'true') {
      value = true;
    }
    else if (value === 'false') {
      value = false;
    }

    frontmatter[key] = value;
  }

  return { frontmatter, body };
}

// =============================================================================
// SKILL MANAGER
// =============================================================================

/**
 * Manages skill discovery, loading, and activation.
 */
export class SkillManager {
  private config: Required<SkillsConfig>;
  private skills: Map<string, Skill> = new Map();
  private activeSkills: Set<string> = new Set();
  private eventListeners: Set<SkillEventListener> = new Set();

  constructor(config: SkillsConfig = {}) {
    this.config = {
      enabled: config.enabled ?? true,
      directories: config.directories ?? getDefaultSkillDirectories(),
      loadBuiltIn: config.loadBuiltIn ?? true,
      autoActivate: config.autoActivate ?? false,
    };
  }

  /**
   * Load skills from all configured directories.
   */
  async loadSkills(): Promise<number> {
    if (!this.config.enabled) return 0;

    let loaded = 0;

    for (const dir of this.config.directories) {
      try {
        const count = await this.loadSkillsFromDirectory(dir);
        loaded += count;
      } catch {
        // Directory may not exist - that's ok
      }
    }

    return loaded;
  }

  /**
   * Load skills from a specific directory.
   */
  async loadSkillsFromDirectory(directory: string): Promise<number> {
    let loaded = 0;

    try {
      const entries = await readdir(directory, { withFileTypes: true });

      for (const entry of entries) {
        const fullPath = join(directory, entry.name);

        if (entry.isDirectory()) {
          // Look for SKILL.md or skill.md in subdirectory
          const skill = await this.loadSkillFromSubdirectory(fullPath);
          if (skill) {
            this.skills.set(skill.name, skill);
            this.emit({ type: 'skill.loaded', name: skill.name, path: fullPath });
            loaded++;
          }
        } else if (entry.isFile() && (entry.name.endsWith('.md') || entry.name.endsWith('.skill'))) {
          // Load skill from standalone file
          const skill = await this.loadSkillFromFile(fullPath);
          if (skill) {
            this.skills.set(skill.name, skill);
            this.emit({ type: 'skill.loaded', name: skill.name, path: fullPath });
            loaded++;
          }
        }
      }
    } catch {
      // Directory doesn't exist or can't be read
    }

    return loaded;
  }

  /**
   * Load a skill from a subdirectory (expects SKILL.md).
   */
  private async loadSkillFromSubdirectory(directory: string): Promise<Skill | null> {
    const possibleFiles = ['SKILL.md', 'skill.md', 'README.md'];

    for (const filename of possibleFiles) {
      const filePath = join(directory, filename);
      try {
        await stat(filePath);
        return this.loadSkillFromFile(filePath);
      } catch {
        // File doesn't exist, try next
      }
    }

    return null;
  }

  /**
   * Load a skill from a markdown file.
   */
  private async loadSkillFromFile(filePath: string): Promise<Skill | null> {
    try {
      const content = await readFile(filePath, 'utf-8');
      const { frontmatter, body } = parseFrontmatter(content);

      // Derive name from frontmatter or file/directory name
      let name = frontmatter.name as string | undefined;
      if (!name) {
        const parent = dirname(filePath);
        const parentName = basename(parent);
        const fileName = basename(filePath, '.md');
        name = parentName !== 'skills' ? parentName : fileName;
      }

      // Extract tools from frontmatter
      let tools: string[] = [];
      if (Array.isArray(frontmatter.tools)) {
        tools = frontmatter.tools as string[];
      }

      // Extract triggers
      let triggers: SkillTrigger[] = [];
      if (Array.isArray(frontmatter.triggers)) {
        triggers = (frontmatter.triggers as unknown[]).map((t) => {
          if (typeof t === 'string') {
            return { type: 'keyword' as const, pattern: t };
          }
          return t as SkillTrigger;
        });
      }

      const skill: Skill = {
        name,
        description: (frontmatter.description as string) || body.split('\n')[0]?.replace(/^#\s*/, '') || name,
        tools,
        content: body,
        sourcePath: filePath,
        version: frontmatter.version as string | undefined,
        author: frontmatter.author as string | undefined,
        tags: frontmatter.tags as string[] | undefined,
        triggers,
      };

      return skill;
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error);
      this.emit({ type: 'skill.error', name: basename(filePath), error: errorMsg });
      return null;
    }
  }

  /**
   * Get a skill by name.
   */
  getSkill(name: string): Skill | undefined {
    return this.skills.get(name);
  }

  /**
   * Get all loaded skills.
   */
  getAllSkills(): Skill[] {
    return Array.from(this.skills.values());
  }

  /**
   * Get active skills.
   */
  getActiveSkills(): Skill[] {
    return Array.from(this.activeSkills)
      .map(name => this.skills.get(name))
      .filter((s): s is Skill => s !== undefined);
  }

  /**
   * Activate a skill.
   */
  activateSkill(name: string): boolean {
    const skill = this.skills.get(name);
    if (!skill) return false;

    this.activeSkills.add(name);
    this.emit({ type: 'skill.activated', name });
    return true;
  }

  /**
   * Deactivate a skill.
   */
  deactivateSkill(name: string): boolean {
    const wasActive = this.activeSkills.delete(name);
    if (wasActive) {
      this.emit({ type: 'skill.deactivated', name });
    }
    return wasActive;
  }

  /**
   * Check if a skill is active.
   */
  isSkillActive(name: string): boolean {
    return this.activeSkills.has(name);
  }

  /**
   * Get the combined system prompt from all active skills.
   */
  getActiveSkillsPrompt(): string {
    const activeSkills = this.getActiveSkills();
    if (activeSkills.length === 0) return '';

    const parts: string[] = ['\n\n## Active Skills\n'];

    for (const skill of activeSkills) {
      parts.push(`### ${skill.name}\n${skill.content}\n`);
    }

    return parts.join('\n');
  }

  /**
   * Get tools required by active skills.
   */
  getActiveSkillTools(): string[] {
    const tools = new Set<string>();

    for (const skill of this.getActiveSkills()) {
      for (const tool of skill.tools) {
        tools.add(tool);
      }
    }

    return Array.from(tools);
  }

  /**
   * Find skills matching keywords in a query.
   */
  findMatchingSkills(query: string): Skill[] {
    if (!this.config.autoActivate) return [];

    const queryLower = query.toLowerCase();
    const matches: Skill[] = [];

    for (const skill of this.skills.values()) {
      // Check triggers
      for (const trigger of skill.triggers || []) {
        if (trigger.type === 'keyword') {
          if (queryLower.includes(trigger.pattern.toLowerCase())) {
            matches.push(skill);
            break;
          }
        }
      }

      // Check tags
      if (skill.tags?.some(tag => queryLower.includes(tag.toLowerCase()))) {
        if (!matches.includes(skill)) {
          matches.push(skill);
        }
      }
    }

    return matches;
  }

  /**
   * Subscribe to skill events.
   */
  subscribe(listener: SkillEventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  /**
   * Cleanup resources.
   */
  cleanup(): void {
    this.skills.clear();
    this.activeSkills.clear();
    this.eventListeners.clear();
  }

  // Internal methods

  private emit(event: SkillEvent): void {
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
 * Create a skill manager.
 */
export function createSkillManager(config?: SkillsConfig): SkillManager {
  return new SkillManager(config);
}

/**
 * Format skills list for display.
 */
export function formatSkillList(skills: Skill[]): string {
  if (skills.length === 0) {
    return 'No skills loaded.';
  }

  const lines: string[] = ['Available skills:'];

  for (const skill of skills) {
    const active = skill.active ? ' (active)' : '';
    const tools = skill.tools.length > 0 ? ` [${skill.tools.join(', ')}]` : '';
    lines.push(`  ${skill.name}${active} - ${skill.description}${tools}`);
  }

  return lines.join('\n');
}

/**
 * Create a sample skill file content.
 */
export function getSampleSkillContent(name: string, description: string): string {
  return `---
name: ${name}
description: ${description}
tools: [read_file, grep, glob]
tags: [example]
---

# ${name}

${description}

## Instructions

When this skill is active:
1. First understand the context
2. Apply specialized knowledge
3. Provide specific, actionable guidance

## Guidelines

- Be thorough but concise
- Focus on the user's specific situation
- Provide examples when helpful
`;
}
