/**
 * Skills Management Commands
 *
 * Handles all /skills sub-commands for managing skills:
 * - /skills - List all skills with enhanced formatting
 * - /skills new <name> - Create a new skill scaffold
 * - /skills info <name> - Show detailed skill information
 * - /skills enable <name> - Activate a skill
 * - /skills disable <name> - Deactivate a skill
 * - /skills edit <name> - Open skill file in $EDITOR
 */

import { exec } from 'child_process';
import { promisify } from 'util';
import type { CommandContext } from './types.js';
import {
  type Skill,
  type SkillManager,
  getSkillLocationDisplay,
  getSkillStats,
  createSkillScaffold,
} from '../integrations/index.js';

const execAsync = promisify(exec);

// =============================================================================
// ANSI COLOR UTILITIES
// =============================================================================

const colors = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  magenta: '\x1b[35m',
  cyan: '\x1b[36m',
  white: '\x1b[37m',
};

function c(text: string, color: keyof typeof colors): string {
  return `${colors[color]}${text}${colors.reset}`;
}

// =============================================================================
// ENHANCED SKILL LIST FORMATTER
// =============================================================================

/**
 * Format skills list with categorization and usage hints.
 */
export function formatEnhancedSkillList(skills: Skill[], activeSkillNames: Set<string>): string {
  if (skills.length === 0) {
    return `${c('No skills loaded.', 'dim')}

${c('To add skills:', 'bold')}
  /skills new <name>      Create a new skill in .attocode/skills/

${c('Skill Locations:', 'dim')}
  ~/.attocode/skills/     User-level skills (shared across projects)
  .attocode/skills/       Project-level skills
`;
  }

  const lines: string[] = [];
  const stats = getSkillStats(skills);
  const activeCount = activeSkillNames.size;

  lines.push(`${c(`Skills (${skills.length} loaded, ${activeCount} active)`, 'bold')}`);
  lines.push('');

  // Categorize skills
  const invokable = skills.filter((s) => s.invokable);
  const passive = skills.filter((s) => !s.invokable && s.triggers && s.triggers.length > 0);
  const inactive = skills.filter((s) => !s.invokable && (!s.triggers || s.triggers.length === 0));

  // Invokable skills (can be called with /<name>)
  if (invokable.length > 0) {
    lines.push(`  ${c('INVOKABLE', 'cyan')} ${c('[/name to invoke]:', 'dim')}`);
    lines.push(`  ${c('─'.repeat(60), 'dim')}`);

    for (const skill of invokable) {
      const args = skill.arguments?.map((a) => `--${a.name}`).join(', ') || '';
      const active = activeSkillNames.has(skill.name) ? c(' +', 'green') : '';
      lines.push(
        `    /${c(skill.name.padEnd(12), 'cyan')}${active} ${skill.description.slice(0, 40)}${args ? `  ${c(args, 'dim')}` : ''}`,
      );
    }
    lines.push('');
  }

  // Passive skills (auto-activate on triggers)
  if (passive.length > 0) {
    lines.push(`  ${c('PASSIVE', 'yellow')} ${c('[auto-activate on triggers]:', 'dim')}`);
    lines.push(`  ${c('─'.repeat(60), 'dim')}`);

    for (const skill of passive) {
      const isActive = activeSkillNames.has(skill.name);
      const icon = isActive ? c('+', 'green') : c('o', 'dim');
      const triggers =
        skill.triggers
          ?.map((t) => t.pattern)
          .slice(0, 3)
          .join(', ') || '';
      lines.push(
        `  ${icon} ${c(skill.name.padEnd(14), isActive ? 'green' : 'white')} ${skill.description.slice(0, 30)}  ${c(`triggers: ${triggers}`, 'dim')}`,
      );
    }
    lines.push('');
  }

  // Inactive skills (no triggers, not invokable)
  if (inactive.length > 0) {
    lines.push(`  ${c('AVAILABLE', 'dim')} ${c('[can be enabled manually]:', 'dim')}`);
    lines.push(`  ${c('─'.repeat(60), 'dim')}`);

    for (const skill of inactive) {
      const isActive = activeSkillNames.has(skill.name);
      const icon = isActive ? c('+', 'green') : c('o', 'dim');
      lines.push(
        `  ${icon} ${c(skill.name.padEnd(14), 'white')} ${skill.description.slice(0, 40)}  ${c('/skills enable ' + skill.name, 'dim')}`,
      );
    }
    lines.push('');
  }

  // Location statistics
  lines.push(`  ${c('LOCATIONS:', 'bold')}`);
  if (stats.builtin > 0)
    lines.push(
      `    ${c('built-in', 'cyan').padEnd(30)} ${stats.builtin} skill${stats.builtin > 1 ? 's' : ''}`,
    );
  if (stats.user > 0)
    lines.push(
      `    ${c('~/.attocode/skills/', 'cyan').padEnd(30)} ${stats.user} skill${stats.user > 1 ? 's' : ''}`,
    );
  if (stats.project > 0)
    lines.push(
      `    ${c('.attocode/skills/', 'cyan').padEnd(30)} ${stats.project} skill${stats.project > 1 ? 's' : ''}`,
    );
  if (stats.legacy > 0)
    lines.push(
      `    ${c('.agent/skills/ (legacy)', 'dim').padEnd(30)} ${stats.legacy} skill${stats.legacy > 1 ? 's' : ''}`,
    );
  lines.push('');

  // Commands
  lines.push(`  ${c('COMMANDS:', 'bold')}`);
  lines.push(
    `    ${c('/skills new <name>', 'cyan').padEnd(30)} Create new skill in .attocode/skills/`,
  );
  lines.push(`    ${c('/skills info <name>', 'cyan').padEnd(30)} Show detailed skill info`);
  lines.push(`    ${c('/skills enable <name>', 'cyan').padEnd(30)} Activate a skill`);
  lines.push(`    ${c('/skills disable <name>', 'cyan').padEnd(30)} Deactivate a skill`);
  lines.push(`    ${c('/skills edit <name>', 'cyan').padEnd(30)} Open skill file in $EDITOR`);

  return lines.join('\n');
}

/**
 * Format detailed skill information.
 */
export function formatSkillInfo(skill: Skill, isActive: boolean): string {
  const lines: string[] = [];

  lines.push(`${c(`Skill: ${skill.name}`, 'bold')}`);
  lines.push(c('─'.repeat(60), 'dim'));

  lines.push(`  ${c('Description:', 'cyan').padEnd(20)} ${skill.description}`);
  lines.push(`  ${c('Source:', 'cyan').padEnd(20)} ${getSkillLocationDisplay(skill)}`);
  lines.push(`  ${c('File:', 'cyan').padEnd(20)} ${skill.sourcePath}`);
  lines.push(
    `  ${c('Status:', 'cyan').padEnd(20)} ${isActive ? c('active', 'green') : c('inactive', 'dim')}`,
  );
  lines.push(
    `  ${c('Invokable:', 'cyan').padEnd(20)} ${skill.invokable ? c('yes (/' + skill.name + ')', 'green') : c('no', 'dim')}`,
  );

  if (skill.version) {
    lines.push(`  ${c('Version:', 'cyan').padEnd(20)} ${skill.version}`);
  }

  if (skill.author) {
    lines.push(`  ${c('Author:', 'cyan').padEnd(20)} ${skill.author}`);
  }

  if (skill.arguments && skill.arguments.length > 0) {
    lines.push('');
    lines.push(`  ${c('Arguments:', 'bold')}`);
    for (const arg of skill.arguments) {
      const aliases = arg.aliases ? arg.aliases.join(', ') + ', ' : '';
      const required = arg.required ? c(' (required)', 'red') : '';
      const defaultVal = arg.default !== undefined ? c(` [default: ${arg.default}]`, 'dim') : '';
      lines.push(`    ${aliases}--${arg.name}  ${arg.description}${required}${defaultVal}`);
    }
  }

  if (skill.triggers && skill.triggers.length > 0) {
    lines.push('');
    lines.push(`  ${c('Triggers:', 'bold')}`);
    for (const trigger of skill.triggers) {
      lines.push(`    - "${trigger.pattern}" (${trigger.type})`);
    }
  }

  if (skill.tools && skill.tools.length > 0) {
    lines.push('');
    lines.push(`  ${c('Tools:', 'bold')} ${skill.tools.join(', ')}`);
  }

  if (skill.tags && skill.tags.length > 0) {
    lines.push(`  ${c('Tags:', 'bold')} ${skill.tags.join(', ')}`);
  }

  if (skill.invokable) {
    lines.push('');
    lines.push(`  ${c('Usage:', 'bold')}`);
    const argStr =
      skill.arguments?.map((a) => ` --${a.name} <${a.type || 'value'}>`).join('') || '';
    lines.push(`    /${skill.name}${argStr}`);
  }

  return lines.join('\n');
}

// =============================================================================
// COMMAND HANDLERS
// =============================================================================

/**
 * Handle /skills command and sub-commands.
 */
export async function handleSkillsCommand(
  args: string[],
  ctx: CommandContext,
  skillManager: SkillManager,
): Promise<void> {
  const { output } = ctx;

  if (args.length === 0) {
    // List all skills
    const skills = skillManager.getAllSkills();
    const activeSkills = new Set(skillManager.getActiveSkills().map((s) => s.name));
    output.log(formatEnhancedSkillList(skills, activeSkills));
    return;
  }

  const subCmd = args[0].toLowerCase();

  switch (subCmd) {
    case 'new': {
      if (args.length < 2) {
        output.log(c('Usage: /skills new <name> [--invokable] [--description "..."]', 'yellow'));
        return;
      }

      const name = args[1];

      // Parse optional flags
      let invokable = true;
      let description: string | undefined;

      for (let i = 2; i < args.length; i++) {
        if (args[i] === '--invokable') {
          invokable = true;
        } else if (args[i] === '--passive') {
          invokable = false;
        } else if (args[i] === '--description' && args[i + 1]) {
          description = args[++i];
        }
      }

      output.log(c(`Creating skill: ${name}...`, 'cyan'));

      const result = await createSkillScaffold(name, { invokable, description });

      if (result.success) {
        output.log(c(`+ Created skill: ${result.path}`, 'green'));
        output.log('');
        output.log(c('Edit the file to customize:', 'dim'));
        output.log(c('  - Add description and triggers', 'dim'));
        output.log(
          c(`  - ${invokable ? 'Define arguments if needed' : 'Set trigger patterns'}`, 'dim'),
        );
        output.log('');
        output.log(c(`Open in editor: /skills edit ${name}`, 'cyan'));

        // Reload skills
        await skillManager.loadSkills();
      } else {
        output.log(c(`x ${result.error}`, 'red'));
      }
      break;
    }

    case 'info': {
      if (args.length < 2) {
        output.log(c('Usage: /skills info <name>', 'yellow'));
        return;
      }

      const name = args[1];
      const skill = skillManager.getSkill(name);

      if (!skill) {
        output.log(c(`Skill not found: ${name}`, 'red'));
        output.log(c('Use /skills to see available skills.', 'dim'));
        return;
      }

      const isActive = skillManager.isSkillActive(name);
      output.log(formatSkillInfo(skill, isActive));
      break;
    }

    case 'enable': {
      if (args.length < 2) {
        output.log(c('Usage: /skills enable <name>', 'yellow'));
        return;
      }

      const name = args[1];
      const success = skillManager.activateSkill(name);

      if (success) {
        output.log(c(`+ Activated skill: ${name}`, 'green'));
      } else {
        output.log(c(`Skill not found: ${name}`, 'red'));
      }
      break;
    }

    case 'disable': {
      if (args.length < 2) {
        output.log(c('Usage: /skills disable <name>', 'yellow'));
        return;
      }

      const name = args[1];
      const success = skillManager.deactivateSkill(name);

      if (success) {
        output.log(c(`- Deactivated skill: ${name}`, 'yellow'));
      } else {
        output.log(c(`Skill not active or not found: ${name}`, 'red'));
      }
      break;
    }

    case 'edit': {
      if (args.length < 2) {
        output.log(c('Usage: /skills edit <name>', 'yellow'));
        return;
      }

      const name = args[1];
      const skill = skillManager.getSkill(name);

      if (!skill) {
        output.log(c(`Skill not found: ${name}`, 'red'));
        return;
      }

      const editor = process.env.EDITOR || process.env.VISUAL || 'vim';
      output.log(c(`Opening ${skill.sourcePath} in ${editor}...`, 'cyan'));

      try {
        await execAsync(`${editor} "${skill.sourcePath}"`);
        output.log(c('+ Editor closed. Run /skills to reload.', 'green'));
        // Reload skills after edit
        await skillManager.loadSkills();
      } catch (error) {
        output.log(c(`Failed to open editor: ${(error as Error).message}`, 'red'));
        output.log(c(`File path: ${skill.sourcePath}`, 'dim'));
      }
      break;
    }

    case 'reload': {
      output.log(c('Reloading skills...', 'cyan'));
      const count = await skillManager.loadSkills();
      output.log(c(`+ Loaded ${count} skill(s)`, 'green'));
      break;
    }

    default:
      output.log(c(`Unknown sub-command: ${subCmd}`, 'yellow'));
      output.log(c('Usage:', 'bold'));
      output.log(c('  /skills              - List all skills', 'dim'));
      output.log(c('  /skills new <name>   - Create a new skill', 'dim'));
      output.log(c('  /skills info <name>  - Show skill details', 'dim'));
      output.log(c('  /skills enable <name> - Activate a skill', 'dim'));
      output.log(c('  /skills disable <name> - Deactivate a skill', 'dim'));
      output.log(c('  /skills edit <name>  - Open skill in $EDITOR', 'dim'));
      output.log(c('  /skills reload       - Reload all skills', 'dim'));
  }
}
