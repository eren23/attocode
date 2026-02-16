/**
 * Skill Executor
 *
 * Handles invocation of skills with argument parsing and template substitution.
 * Skills can be invoked like commands: /review --file src/main.ts --focus security
 */

import type { Skill, SkillArgument, SkillManager } from './skills.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Parsed arguments from command line input.
 */
export interface ParsedArgs {
  /** Named arguments (--name value or -n value) */
  named: Record<string, unknown>;

  /** Positional arguments (remaining after named) */
  positional: string[];

  /** Any parsing errors */
  errors: string[];
}

/**
 * Context provided during skill execution.
 */
export interface SkillExecutionContext {
  /** Current working directory */
  cwd: string;

  /** Session ID */
  sessionId?: string;

  /** Current conversation context (for prompt injection) */
  conversationContext?: string;

  /** Callback to run agent with injected prompt */
  runWithPrompt?: (prompt: string) => Promise<SkillExecutionResult>;
}

/**
 * Result of skill execution.
 */
export interface SkillExecutionResult {
  /** Whether execution succeeded */
  success: boolean;

  /** Result message or output */
  output: string;

  /** Injected prompt for the agent (if prompt-injection mode) */
  injectedPrompt?: string;

  /** Error message if failed */
  error?: string;
}

/**
 * Skill execution event types.
 */
export type SkillExecutorEvent =
  | { type: 'skill.invoke.start'; skillName: string; args: string[] }
  | { type: 'skill.invoke.parsed'; skillName: string; parsed: ParsedArgs }
  | { type: 'skill.invoke.complete'; skillName: string; result: SkillExecutionResult }
  | { type: 'skill.invoke.error'; skillName: string; error: string };

export type SkillExecutorEventListener = (event: SkillExecutorEvent) => void;

// =============================================================================
// SKILL EXECUTOR
// =============================================================================

/**
 * Executes invokable skills with argument parsing and template substitution.
 */
export class SkillExecutor {
  private skillManager: SkillManager;
  private eventListeners: Set<SkillExecutorEventListener> = new Set();

  constructor(skillManager: SkillManager) {
    this.skillManager = skillManager;
  }

  /**
   * Check if an input string is a potential skill invocation.
   * Returns the skill name if it matches, null otherwise.
   */
  isSkillInvocation(input: string): string | null {
    if (!input.startsWith('/')) return null;

    const parts = input.split(/\s+/);
    const cmdName = parts[0].slice(1); // Remove leading /

    const skill = this.skillManager.getSkill(cmdName);
    if (skill && skill.invokable) {
      return cmdName;
    }

    return null;
  }

  /**
   * Parse command-line style arguments.
   */
  parseArguments(skill: Skill, rawArgs: string[]): ParsedArgs {
    const result: ParsedArgs = {
      named: {},
      positional: [],
      errors: [],
    };

    const argDefs = skill.arguments || [];

    // Build alias map
    const aliasMap = new Map<string, SkillArgument>();
    for (const arg of argDefs) {
      aliasMap.set(`--${arg.name}`, arg);
      if (arg.aliases) {
        for (const alias of arg.aliases) {
          aliasMap.set(alias, arg);
        }
      }
    }

    // Parse arguments
    let i = 0;
    while (i < rawArgs.length) {
      const token = rawArgs[i];

      if (token.startsWith('-')) {
        // Check for --flag=value syntax
        const eqIndex = token.indexOf('=');
        let key: string;
        let value: string | undefined;

        if (eqIndex !== -1) {
          key = token.slice(0, eqIndex);
          value = token.slice(eqIndex + 1);
        } else {
          key = token;
        }

        const argDef = aliasMap.get(key);
        if (argDef) {
          // Get value
          if (argDef.type === 'boolean') {
            result.named[argDef.name] = value !== undefined ? value === 'true' : true;
          } else {
            if (value === undefined) {
              i++;
              if (i < rawArgs.length && !rawArgs[i].startsWith('-')) {
                value = rawArgs[i];
              } else {
                result.errors.push(`Missing value for argument: ${key}`);
                continue;
              }
            }

            // Type conversion
            if (argDef.type === 'number') {
              const num = parseFloat(value);
              if (isNaN(num)) {
                result.errors.push(`Invalid number for ${argDef.name}: ${value}`);
              } else {
                result.named[argDef.name] = num;
              }
            } else {
              result.named[argDef.name] = value;
            }
          }
        } else {
          // Unknown argument - treat as positional? Or error?
          result.errors.push(`Unknown argument: ${key}`);
        }
      } else {
        result.positional.push(token);
      }

      i++;
    }

    // Apply defaults
    for (const arg of argDefs) {
      if (result.named[arg.name] === undefined && arg.default !== undefined) {
        result.named[arg.name] = arg.default;
      }
    }

    // Check required arguments
    for (const arg of argDefs) {
      if (arg.required && result.named[arg.name] === undefined) {
        result.errors.push(`Missing required argument: --${arg.name}`);
      }
    }

    return result;
  }

  /**
   * Substitute template variables in skill content.
   * Variables are in the form {{name}} or {{name|default}}.
   */
  substituteTemplate(content: string, args: ParsedArgs): string {
    return content.replace(/\{\{(\w+)(?:\|([^}]*))?\}\}/g, (match, name, defaultVal) => {
      if (args.named[name] !== undefined) {
        return String(args.named[name]);
      }
      if (defaultVal !== undefined) {
        return defaultVal;
      }
      return match; // Keep original if no value
    });
  }

  /**
   * Execute a skill by name with arguments.
   */
  async executeSkill(
    skillName: string,
    rawArgs: string[],
    ctx: SkillExecutionContext
  ): Promise<SkillExecutionResult> {
    this.emit({ type: 'skill.invoke.start', skillName, args: rawArgs });

    const skill = this.skillManager.getSkill(skillName);
    if (!skill) {
      const error = `Skill not found: ${skillName}`;
      this.emit({ type: 'skill.invoke.error', skillName, error });
      return { success: false, output: '', error };
    }

    if (!skill.invokable) {
      const error = `Skill "${skillName}" is not invokable. It can only be activated passively.`;
      this.emit({ type: 'skill.invoke.error', skillName, error });
      return { success: false, output: '', error };
    }

    // Parse arguments
    const parsed = this.parseArguments(skill, rawArgs);
    this.emit({ type: 'skill.invoke.parsed', skillName, parsed });

    if (parsed.errors.length > 0) {
      const error = `Argument errors:\n${parsed.errors.map(e => `  - ${e}`).join('\n')}\n\n${this.formatSkillHelp(skill)}`;
      this.emit({ type: 'skill.invoke.error', skillName, error });
      return { success: false, output: '', error };
    }

    // Add positional args as a special variable
    if (parsed.positional.length > 0) {
      parsed.named['_positional'] = parsed.positional.join(' ');
      parsed.named['_args'] = parsed.positional;
    }

    // Add context variables
    parsed.named['_cwd'] = ctx.cwd;
    if (ctx.sessionId) {
      parsed.named['_sessionId'] = ctx.sessionId;
    }

    // Substitute template variables in content
    const processedContent = this.substituteTemplate(skill.content, parsed);

    // For prompt-injection mode, create the injected prompt
    if (skill.executionMode === 'prompt-injection' || !skill.executionMode) {
      const injectedPrompt = this.buildInjectedPrompt(skill, processedContent, parsed);

      const result: SkillExecutionResult = {
        success: true,
        output: `Skill "${skillName}" activated with injected prompt.`,
        injectedPrompt,
      };

      this.emit({ type: 'skill.invoke.complete', skillName, result });
      return result;
    }

    // Workflow mode would require running multiple steps
    // For now, treat it like prompt-injection
    const injectedPrompt = this.buildInjectedPrompt(skill, processedContent, parsed);

    const result: SkillExecutionResult = {
      success: true,
      output: `Skill "${skillName}" activated in workflow mode.`,
      injectedPrompt,
    };

    this.emit({ type: 'skill.invoke.complete', skillName, result });
    return result;
  }

  /**
   * Build the prompt to inject based on skill content and arguments.
   */
  private buildInjectedPrompt(skill: Skill, content: string, args: ParsedArgs): string {
    const parts: string[] = [];

    parts.push(`<skill name="${skill.name}">`);
    parts.push(content);

    // Add argument context if any were provided
    const namedArgs = Object.entries(args.named)
      .filter(([k]) => !k.startsWith('_'))
      .map(([k, v]) => `  ${k}: ${JSON.stringify(v)}`)
      .join('\n');

    if (namedArgs) {
      parts.push(`\n<arguments>\n${namedArgs}\n</arguments>`);
    }

    parts.push('</skill>');

    return parts.join('\n');
  }

  /**
   * Format help text for a skill.
   */
  formatSkillHelp(skill: Skill): string {
    const lines: string[] = [
      `Usage: /${skill.name} [options]`,
      '',
      skill.description,
    ];

    if (skill.arguments && skill.arguments.length > 0) {
      lines.push('', 'Options:');
      for (const arg of skill.arguments) {
        const aliases = arg.aliases ? arg.aliases.join(', ') + ', ' : '';
        const required = arg.required ? ' (required)' : '';
        const defaultVal = arg.default !== undefined ? ` [default: ${arg.default}]` : '';
        lines.push(`  ${aliases}--${arg.name}  ${arg.description}${required}${defaultVal}`);
      }
    }

    return lines.join('\n');
  }

  /**
   * Get all invokable skills.
   */
  getInvokableSkills(): Skill[] {
    return this.skillManager.getAllSkills().filter(s => s.invokable);
  }

  /**
   * Subscribe to executor events.
   */
  subscribe(listener: SkillExecutorEventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  private emit(event: SkillExecutorEvent): void {
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
 * Create a skill executor.
 */
export function createSkillExecutor(skillManager: SkillManager): SkillExecutor {
  return new SkillExecutor(skillManager);
}
