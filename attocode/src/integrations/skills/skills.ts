/**
 * Skills Standard (Crush-inspired)
 *
 * Discoverable skill packages that provide specialized agent capabilities.
 * Skills are defined as markdown files with YAML frontmatter containing
 * metadata like name, description, and required tools.
 *
 * Directory structure (priority: later overrides earlier):
 * - Built-in skills: attocode/skills/
 * - User skills: ~/.attocode/skills/
 * - Project skills: .attocode/skills/
 * - Legacy paths (.agent/) supported for backward compatibility
 *
 * Usage:
 *   const skills = createSkillManager({ directories: getDefaultSkillDirectories() });
 *   await skills.loadSkills();
 *   await skills.activateSkill('code-review', context);
 */

import { readFile, readdir, stat, mkdir, writeFile } from 'fs/promises';
import { existsSync } from 'fs';
import { join, basename, dirname } from 'path';
import { homedir } from 'os';
import { fileURLToPath } from 'url';

// ES Module __dirname equivalent
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// =============================================================================
// TYPES
// =============================================================================

/**
 * Skill argument definition for invokable skills.
 */
export interface SkillArgument {
  /** Argument name (used in templates as {{name}}) */
  name: string;

  /** Human-readable description shown in help */
  description: string;

  /** Argument type for validation */
  type: 'string' | 'boolean' | 'file' | 'number';

  /** Whether this argument is required */
  required?: boolean;

  /** Default value if not provided */
  default?: unknown;

  /** CLI aliases (e.g., ['-f', '--file']) */
  aliases?: string[];
}

/**
 * Skill source type for display and management.
 */
export type SkillSourceType = 'builtin' | 'user' | 'project' | 'legacy';

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

  /** Source type (builtin, user, project, legacy) */
  sourceType?: SkillSourceType;

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

  /** Whether this skill can be invoked via /skillname command */
  invokable?: boolean;

  /** Arguments for invokable skills */
  arguments?: SkillArgument[];

  /** Execution mode: prompt-injection (default) or workflow (multi-step) */
  executionMode?: 'prompt-injection' | 'workflow';
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
 * Default skill directories with priority hierarchy:
 * built-in < ~/.attocode/ < .attocode/ (later entries override earlier)
 *
 * Legacy paths (.agent/) are included for backward compatibility.
 */
export function getDefaultSkillDirectories(): string[] {
  const homeDir = homedir();
  return [
    // Built-in skills (lowest priority) - relative to this file's location
    join(__dirname, '../../skills'),

    // User-level skills (medium priority)
    join(homeDir, '.attocode', 'skills'),

    // Legacy user path (backward compat)
    join(homeDir, '.agent', 'skills'),

    // Project-level skills (highest priority)
    join(process.cwd(), '.attocode', 'skills'),

    // Legacy project path (backward compat)
    join(process.cwd(), '.agent', 'skills'),
  ];
}

/**
 * Get the directory where new skills should be created.
 * Prefers .attocode/skills/ in the project root.
 */
export function getSkillCreationDirectory(): string {
  return join(process.cwd(), '.attocode', 'skills');
}

/**
 * Get the user-level skill directory.
 */
export function getUserSkillDirectory(): string {
  return join(homedir(), '.attocode', 'skills');
}

/**
 * Determine the source type of a skill based on its path.
 */
export function getSkillSourceType(skillPath: string): SkillSourceType {
  const homeDir = homedir();
  const cwd = process.cwd();

  // Check for built-in (in the package's skills/ directory)
  if (skillPath.includes(join(__dirname, '../../skills'))) {
    return 'builtin';
  }

  // Check for project-level (.attocode/skills/)
  if (skillPath.startsWith(join(cwd, '.attocode', 'skills'))) {
    return 'project';
  }

  // Check for user-level (~/.attocode/skills/)
  if (skillPath.startsWith(join(homeDir, '.attocode', 'skills'))) {
    return 'user';
  }

  // Legacy paths (.agent/)
  if (skillPath.includes('.agent')) {
    return 'legacy';
  }

  return 'project'; // Default to project
}

/**
 * Get a human-readable location string for a skill.
 */
export function getSkillLocationDisplay(skill: Skill): string {
  const sourceType = skill.sourceType || getSkillSourceType(skill.sourcePath);

  switch (sourceType) {
    case 'builtin':
      return 'built-in';
    case 'user':
      return '~/.attocode/skills/';
    case 'project':
      return '.attocode/skills/';
    case 'legacy':
      return skill.sourcePath.includes(homedir())
        ? '~/.agent/skills/ (legacy)'
        : '.agent/skills/ (legacy)';
    default:
      return skill.sourcePath;
  }
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
  const body = lines
    .slice(endIndex + 1)
    .join('\n')
    .trim();

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
      value = value
        .slice(1, -1)
        .split(',')
        .map((s) => s.trim().replace(/^["']|["']$/g, ''));
    }
    // Handle quoted strings
    else if (typeof value === 'string' && (value.startsWith('"') || value.startsWith("'"))) {
      value = value.slice(1, -1);
    }
    // Handle booleans
    else if (value === 'true') {
      value = true;
    } else if (value === 'false') {
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
        } else if (
          entry.isFile() &&
          (entry.name.endsWith('.md') || entry.name.endsWith('.skill'))
        ) {
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

      // Extract arguments for invokable skills
      let skillArguments: SkillArgument[] | undefined;
      if (Array.isArray(frontmatter.arguments)) {
        skillArguments = (frontmatter.arguments as unknown[]).map((arg) => {
          const a = arg as Record<string, unknown>;
          return {
            name: String(a.name || ''),
            description: String(a.description || ''),
            type: (a.type as SkillArgument['type']) || 'string',
            required: Boolean(a.required),
            default: a.default,
            aliases: Array.isArray(a.aliases) ? (a.aliases as string[]) : undefined,
          };
        });
      }

      const skill: Skill = {
        name,
        description:
          (frontmatter.description as string) || body.split('\n')[0]?.replace(/^#\s*/, '') || name,
        tools,
        content: body,
        sourcePath: filePath,
        sourceType: getSkillSourceType(filePath),
        version: frontmatter.version as string | undefined,
        author: frontmatter.author as string | undefined,
        tags: frontmatter.tags as string[] | undefined,
        triggers,
        invokable: frontmatter.invokable === true,
        arguments: skillArguments,
        executionMode: (frontmatter.executionMode as Skill['executionMode']) || 'prompt-injection',
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
      .map((name) => this.skills.get(name))
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
      if (skill.tags?.some((tag) => queryLower.includes(tag.toLowerCase()))) {
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
    const invokable = skill.invokable ? ' [/]' : '';
    const tools = skill.tools.length > 0 ? ` [${skill.tools.join(', ')}]` : '';
    lines.push(`  ${invokable ? '/' : ' '}${skill.name}${active} - ${skill.description}${tools}`);
  }

  lines.push('\n  Legend: / = invokable skill (use /skillname to invoke)');

  return lines.join('\n');
}

/**
 * Create a sample skill file content (basic).
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

/**
 * Get a skill scaffold template with all options.
 */
export function getSkillScaffold(
  name: string,
  options: {
    invokable?: boolean;
    description?: string;
    args?: Array<{ name: string; description: string; type?: string; required?: boolean }>;
    triggers?: string[];
  } = {},
): string {
  const {
    invokable = true,
    description = '[Add description here]',
    args = [],
    triggers = [],
  } = options;

  const argLines =
    args.length > 0
      ? `arguments:
${args
  .map(
    (a) => `  - name: ${a.name}
    description: ${a.description}
    type: ${a.type || 'string'}
    required: ${a.required ?? false}`,
  )
  .join('\n')}`
      : '';

  const triggerLines =
    triggers.length > 0
      ? `triggers:
${triggers.map((t) => `  - ${t}`).join('\n')}`
      : '';

  return `---
name: ${name}
description: ${description}
invokable: ${invokable}
${argLines}
${triggerLines}
---

# ${name}

${description}

## Instructions

[Add instructions for the agent when this skill is active]

${
  invokable
    ? `## Usage

\`\`\`
/${name}${args.map((a) => ` --${a.name} <${a.type || 'value'}>`).join('')}
\`\`\`
`
    : ''
}
## Guidelines

- Be thorough but concise
- Focus on the user's specific situation
- Provide examples when helpful
`;
}

/**
 * Result of creating a skill scaffold.
 */
export interface SkillScaffoldResult {
  success: boolean;
  path?: string;
  error?: string;
}

/**
 * Create a skill scaffold in the .attocode/skills/ directory.
 */
export async function createSkillScaffold(
  name: string,
  options: {
    invokable?: boolean;
    description?: string;
    args?: Array<{ name: string; description: string; type?: string; required?: boolean }>;
    triggers?: string[];
    userLevel?: boolean; // Create in ~/.attocode/skills/ instead of project
  } = {},
): Promise<SkillScaffoldResult> {
  try {
    // Validate name
    if (!/^[a-z][a-z0-9-]*$/.test(name)) {
      return {
        success: false,
        error:
          'Skill name must start with a letter and contain only lowercase letters, numbers, and hyphens',
      };
    }

    // Determine target directory
    const baseDir = options.userLevel ? getUserSkillDirectory() : getSkillCreationDirectory();

    const skillDir = join(baseDir, name);
    const skillPath = join(skillDir, 'SKILL.md');

    // Check if skill already exists
    if (existsSync(skillPath)) {
      return {
        success: false,
        error: `Skill "${name}" already exists at ${skillPath}`,
      };
    }

    // Create directory structure
    await mkdir(skillDir, { recursive: true });

    // Write skill file
    const content = getSkillScaffold(name, options);
    await writeFile(skillPath, content, 'utf-8');

    return {
      success: true,
      path: skillPath,
    };
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

/**
 * Get statistics about loaded skills by source.
 */
export function getSkillStats(skills: Skill[]): Record<SkillSourceType, number> {
  const stats: Record<SkillSourceType, number> = {
    builtin: 0,
    user: 0,
    project: 0,
    legacy: 0,
  };

  for (const skill of skills) {
    const sourceType = skill.sourceType || getSkillSourceType(skill.sourcePath);
    stats[sourceType]++;
  }

  return stats;
}
