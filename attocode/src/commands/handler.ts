/**
 * Unified Command Handler
 *
 * Handles all slash commands for both REPL and TUI modes.
 * Uses CommandContext.output for all output, making it mode-agnostic.
 */

import type { CommandContext, CommandResult } from './types.js';
import type { SQLiteStore } from '../integrations/index.js';
import {
  persistenceDebug,
  saveCheckpointToStore,
  type CheckpointData,
} from '../integrations/persistence/persistence.js';
import {
  formatServerList,
  getContextUsage,
  formatCompactionResult,
  formatCapabilitiesSummary,
  formatCapabilitiesList,
  formatSearchResults,
} from '../integrations/index.js';
import { formatSessionsTable } from '../session-picker.js';
import { handleSkillsCommand } from './skills-commands.js';
import { handleAgentsCommand } from './agents-commands.js';
import { handleInitCommand } from './init-commands.js';
import { logger } from '../integrations/utilities/logger.js';
import { estimateTokenCount } from '../integrations/utilities/token-estimate.js';

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

/**
 * Apply ANSI color to text.
 */
function c(text: string, color: keyof typeof colors): string {
  return `${colors[color]}${text}${colors.reset}`;
}

// =============================================================================
// HELP TEXT
// =============================================================================

function getHelpText(): string {
  return `
${c('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'dim')}
${c('                           ATTOCODE HELP', 'bold')}
${c('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'dim')}

${c('GENERAL', 'bold')}
  ${c('/help', 'cyan')}              Show this help (alias: /h, /?)
  ${c('/status', 'cyan')}            Show session stats, metrics & token usage
  ${c('/clear', 'cyan')}             Clear the screen
  ${c('/reset', 'cyan')}             Reset agent state (clears conversation)
  ${c('/quit', 'cyan')}              Exit attocode (alias: /exit, /q)

${c('AGENT MODES', 'bold')}
  ${c('/mode', 'cyan')}              Show current mode and available modes
  ${c('/mode <name>', 'cyan')}       Switch to mode (build, plan, review, debug)
  ${c('/plan', 'cyan')}              Toggle plan mode (writes queued for approval)

${c('PLAN APPROVAL (in Plan Mode)', 'bold')}
  ${c('/show-plan', 'cyan')}         Show pending plan with proposed changes
  ${c('/approve', 'cyan')}           Approve and execute all pending changes
  ${c('/approve <n>', 'cyan')}       Approve and execute first n changes only
  ${c('/reject', 'cyan')}            Reject and discard all pending changes

${c('SESSIONS & PERSISTENCE', 'bold')}
  ${c('/save', 'cyan')}              Save current session to disk
  ${c('/load <id>', 'cyan')}         Load a previous session by ID
  ${c('/sessions', 'cyan')}          List all saved sessions with timestamps
  ${c('/resume', 'cyan')}            Resume most recent session (auto-loads last checkpoint)

${c('CONTEXT MANAGEMENT', 'bold')}
  ${c('/context', 'cyan')}           Show context window usage (tokens used/available)
  ${c('/context breakdown', 'cyan')} Detailed token breakdown by category
  ${c('/compact', 'cyan')}           Summarize & compress context to free tokens
  ${c('/compact status', 'cyan')}    Check if compaction is recommended

${c('CHECKPOINTS & THREADS', 'bold')}
  ${c('/checkpoint [label]', 'cyan')} Create a named checkpoint (alias: /cp)
  ${c('/checkpoints', 'cyan')}       List all checkpoints (alias: /cps)
  ${c('/restore <id>', 'cyan')}      Restore conversation to a checkpoint
  ${c('/rollback [n]', 'cyan')}      Rollback n steps (default: 1) (alias: /rb)
  ${c('/fork <name>', 'cyan')}       Fork conversation into a new thread
  ${c('/threads', 'cyan')}           List all conversation threads
  ${c('/switch <id>', 'cyan')}       Switch to a different thread

${c('REASONING MODES', 'bold')}
  ${c('/react <task>', 'cyan')}      Run with ReAct (Reason + Act) pattern
  ${c('/team <task>', 'cyan')}       Run with multi-agent team coordination

${c('SUBAGENTS', 'bold')}
  ${c('/agents', 'cyan')}            List all available agents with descriptions
  ${c('/spawn <agent> <task>', 'cyan')} Spawn a specific agent to handle task
  ${c('/find <query>', 'cyan')}      Find agents by keyword search
  ${c('/suggest <task>', 'cyan')}    AI-powered agent suggestion for task
  ${c('/auto <task>', 'cyan')}       Auto-route task to best agent

${c('MCP INTEGRATION', 'bold')}
  ${c('/mcp', 'cyan')}               List MCP servers and connection status
  ${c('/mcp connect <name>', 'cyan')} Connect to an MCP server
  ${c('/mcp disconnect <name>', 'cyan')} Disconnect from server
  ${c('/mcp tools', 'cyan')}         List all available MCP tools
  ${c('/mcp search <query>', 'cyan')} Search & lazy-load MCP tools
  ${c('/mcp stats', 'cyan')}         Show MCP context usage statistics

${c('BUDGET & ECONOMICS', 'bold')}
  ${c('/budget', 'cyan')}            Show token/cost budget and usage
  ${c('/extend <type> <n>', 'cyan')} Extend budget limit

${c('PERMISSIONS & SECURITY', 'bold')}
  ${c('/grants', 'cyan')}            Show active permission grants
  ${c('/audit', 'cyan')}             Show security audit log

${c('SKILLS & AGENTS', 'bold')}
  ${c('/skills', 'cyan')}            List all skills with usage hints
  ${c('/skills new <name>', 'cyan')} Create a new skill in .attocode/skills/
  ${c('/skills info <name>', 'cyan')} Show detailed skill information
  ${c('/skills enable/disable', 'cyan')} Activate or deactivate a skill
  ${c('/agents', 'cyan')}            List all available agents
  ${c('/agents new <name>', 'cyan')} Create a new agent in .attocode/agents/
  ${c('/agents info <name>', 'cyan')} Show detailed agent information

${c('INITIALIZATION', 'bold')}
  ${c('/init', 'cyan')}              Initialize .attocode/ directory structure

${c('TRACE ANALYSIS', 'bold')}
  ${c('/trace', 'cyan')}             Show current session trace summary
  ${c('/trace --analyze', 'cyan')}   Run efficiency analysis on trace
  ${c('/trace issues', 'cyan')}      List detected inefficiencies
  ${c('/trace fixes', 'cyan')}       List pending improvements
  ${c('/trace export', 'cyan')}      Export trace JSON for LLM analysis

${c('CAPABILITIES & DEBUGGING', 'bold')}
  ${c('/powers', 'cyan')}            Show all agent capabilities
  ${c('/powers <type>', 'cyan')}     List by type (tools, skills, agents, mcp, commands)
  ${c('/powers search <q>', 'cyan')} Search capabilities
  ${c('/sandbox', 'cyan')}           Show sandbox modes available
  ${c('/shell', 'cyan')}             Show PTY shell integration info
  ${c('/lsp', 'cyan')}               Show LSP integration status
  ${c('/tui', 'cyan')}               Show TUI features & capabilities

${c('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'dim')}
${c('SHORTCUTS', 'bold')}
  ${c('Ctrl+C', 'yellow')}  Exit          ${c('Ctrl+L', 'yellow')}  Clear screen
${c('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'dim')}
`;
}

// =============================================================================
// MAIN COMMAND HANDLER
// =============================================================================

/**
 * Handle a slash command.
 *
 * @param cmd - Command string (with leading slash)
 * @param args - Command arguments
 * @param ctx - Command context with agent, output, integrations
 * @returns 'quit' to exit, void otherwise
 */
export async function handleCommand(
  cmd: string,
  args: string[],
  ctx: CommandContext,
): Promise<CommandResult> {
  const { agent, sessionId, output, integrations } = ctx;
  const { sessionStore, mcpClient, compactor, skillExecutor } = integrations;

  // Check for skill invocation before built-in commands
  if (skillExecutor) {
    const skillName = skillExecutor.isSkillInvocation(cmd);
    if (skillName) {
      const result = await skillExecutor.executeSkill(skillName, args, {
        cwd: process.cwd(),
        sessionId,
      });

      if (result.success) {
        if (result.injectedPrompt) {
          output.log(c(`Invoking skill: /${skillName}`, 'cyan'));
          // Return skill invocation for the caller to handle
          return {
            type: 'skill' as const,
            skillName,
            injectedPrompt: result.injectedPrompt,
          };
        }
        output.log(c(result.output, 'green'));
      } else {
        output.log(c(`Skill error: ${result.error}`, 'red'));
      }
      return;
    }
  }

  switch (cmd) {
    // =========================================================================
    // GENERAL COMMANDS
    // =========================================================================

    case '/quit':
    case '/exit':
    case '/q':
      return 'quit';

    case '/help':
    case '/h':
    case '/?':
      output.log(getHelpText());
      break;

    case '/status': {
      const metrics = agent.getMetrics();
      const state = agent.getState();

      // Get goals summary if SQLite store
      let goalsSummary = '';
      if ('listActiveGoals' in sessionStore) {
        const sqlStore = sessionStore as SQLiteStore;
        const activeGoals = sqlStore.listActiveGoals();
        if (activeGoals.length > 0) {
          let totalCurrent = 0;
          let totalExpected = 0;
          const goalLines: string[] = [];

          for (const goal of activeGoals) {
            if (goal.progressTotal) {
              totalCurrent += goal.progressCurrent;
              totalExpected += goal.progressTotal;
              const pct = Math.round((goal.progressCurrent / goal.progressTotal) * 100);
              goalLines.push(
                `  - ${goal.goalText} (${goal.progressCurrent}/${goal.progressTotal} - ${pct}%)`,
              );
            } else {
              goalLines.push(`  - ${goal.goalText}`);
            }
          }

          goalsSummary = `\n${c('Active Goals:', 'bold')} (${activeGoals.length})`;
          if (totalExpected > 0) {
            const overallPct = Math.round((totalCurrent / totalExpected) * 100);
            goalsSummary += c(` [Overall: ${overallPct}%]`, 'cyan');
          }
          goalsSummary += '\n' + goalLines.slice(0, 5).join('\n');
          if (activeGoals.length > 5) {
            goalsSummary += c(`\n  ... and ${activeGoals.length - 5} more`, 'dim');
          }
        }
      }

      output.log(`
${c('Session Status:', 'bold')}
  Session ID:      ${sessionId}
  Status:          ${state.status}
  Iteration:       ${state.iteration}
  Messages:        ${state.messages.length}

${c('Token Usage:', 'bold')}
  Input tokens:    ${metrics.inputTokens.toLocaleString()}
  Output tokens:   ${metrics.outputTokens.toLocaleString()}
  Total tokens:    ${metrics.totalTokens.toLocaleString()}

${c('Activity:', 'bold')}
  LLM calls:       ${metrics.llmCalls}
  Tool calls:      ${metrics.toolCalls}
  Retries:         ${metrics.retryCount ?? 0}
  Duration:        ${metrics.duration}ms
  Est. Cost:       $${metrics.estimatedCost.toFixed(4)}

${c('Outcomes:', 'bold')}
  Success:         ${metrics.successCount ?? 0}
  Failed:          ${metrics.failureCount ?? 0}
  Cancelled:       ${metrics.cancelCount ?? 0}
${(() => {
  const shared = agent.getSharedStats();
  if (!shared) return '';
  return `\n${c('Shared State:', 'bold')}
  Context:         ${shared.context.failures} failures, ${shared.context.references} refs
  Economics:       ${shared.economics.fingerprints} fingerprints, ${shared.economics.globalLoops.length} doom loops`;
})()}${goalsSummary}`);
      break;
    }

    case '/clear':
      output.clear();
      output.log(c(`Production Agent - Session: ${sessionId}`, 'cyan'));
      break;

    case '/reset':
      agent.reset();
      output.log(c('+ Agent state reset', 'green'));
      break;

    // =========================================================================
    // MODE MANAGEMENT
    // =========================================================================

    case '/mode': {
      if (args.length === 0) {
        const modeInfo = agent.getModeInfo();
        const hasPlan = agent.hasPendingPlan();
        const pendingCount = agent.getPendingChangeCount();

        output.log(`
${c('Current Mode:', 'bold')} ${modeInfo.color}${modeInfo.icon} ${modeInfo.name}\x1b[0m
${hasPlan ? c(`  Pending Plan: ${pendingCount} change(s) awaiting approval`, 'yellow') : ''}

${agent.getAvailableModes()}

${c('Usage:', 'dim')} /mode <name> to switch, /plan to toggle plan mode`);
      } else {
        const newMode = args[0].toLowerCase();
        agent.setMode(newMode);
        const modeInfo = agent.getModeInfo();
        output.log(
          `${c('Mode changed to:', 'green')} ${modeInfo.color}${modeInfo.icon} ${modeInfo.name}\x1b[0m`,
        );

        if (newMode !== 'plan' && agent.hasPendingPlan()) {
          output.log(
            c(
              'Warning: You have a pending plan. Use /show-plan to view, /approve or /reject to resolve.',
              'yellow',
            ),
          );
        }
      }
      break;
    }

    case '/plan': {
      const newMode = agent.togglePlanMode();
      const modeInfo = agent.getModeInfo();
      output.log(
        `${c('Mode toggled to:', 'green')} ${modeInfo.color}${modeInfo.icon} ${modeInfo.name}\x1b[0m`,
      );

      if (newMode === 'plan') {
        output.log(
          c(
            `
In Plan Mode:
  - You can explore the codebase and use all tools
  - Write operations will be QUEUED for approval
  - Use /show-plan to see queued changes
  - Use /approve to execute, /reject to discard
`,
            'dim',
          ),
        );
      } else if (agent.hasPendingPlan()) {
        output.log(
          c('Note: You have a pending plan. Use /show-plan, /approve, or /reject.', 'yellow'),
        );
      }
      break;
    }

    // =========================================================================
    // PLAN APPROVAL COMMANDS
    // =========================================================================

    case '/show-plan': {
      if (!agent.hasPendingPlan()) {
        output.log(
          c(
            'No pending plan. Enter plan mode with /plan and make requests that would modify files.',
            'dim',
          ),
        );
      } else {
        output.log(`\n${agent.formatPendingPlan()}`);
      }
      break;
    }

    case '/approve': {
      if (!agent.hasPendingPlan()) {
        output.log(c('No pending plan to approve.', 'dim'));
        break;
      }

      const count = args[0] ? parseInt(args[0], 10) : undefined;
      if (args[0] && (isNaN(count!) || count! < 1)) {
        output.log(c('Invalid count. Use /approve or /approve <number>', 'red'));
        break;
      }

      const pendingCount = agent.getPendingChangeCount();
      const toApprove = count ?? pendingCount;
      output.log(c(`Approving ${toApprove} of ${pendingCount} change(s)...`, 'yellow'));

      const result = await agent.approvePlan(count);

      if (result.success) {
        output.log(c(`\n+ Successfully executed ${result.executed} change(s)`, 'green'));
      } else {
        output.log(
          c(
            `\n! Executed ${result.executed} change(s) with ${result.errors.length} error(s):`,
            'yellow',
          ),
        );
        for (const err of result.errors) {
          output.log(c(`  - ${err}`, 'red'));
        }
      }

      if (agent.getMode() === 'plan') {
        agent.setMode('build');
        output.log(c('\nSwitched to Build mode.', 'dim'));
      }
      break;
    }

    case '/reject': {
      if (!agent.hasPendingPlan()) {
        output.log(c('No pending plan to reject.', 'dim'));
        break;
      }

      const pendingCount = agent.getPendingChangeCount();
      agent.rejectPlan();
      output.log(
        c(
          `x Rejected plan with ${pendingCount} change(s). All proposed changes discarded.`,
          'yellow',
        ),
      );

      if (agent.getMode() === 'plan') {
        agent.setMode('build');
        output.log(c('Switched to Build mode.', 'dim'));
      }
      break;
    }

    // =========================================================================
    // GOALS
    // =========================================================================

    case '/goals':
      if ('listActiveGoals' in sessionStore) {
        const sqliteStore = sessionStore as SQLiteStore;
        const subCmd = args[0]?.toLowerCase();

        if (!subCmd || subCmd === 'list') {
          const goals = sqliteStore.listActiveGoals();
          if (goals.length === 0) {
            output.log(c('No active goals. Use /goals add <text> to create one.', 'dim'));
          } else {
            output.log(c('\nActive Goals:', 'bold'));
            for (const goal of goals) {
              const progress = goal.progressTotal
                ? ` (${goal.progressCurrent}/${goal.progressTotal})`
                : '';
              const priority =
                goal.priority === 1
                  ? c(' [HIGH]', 'red')
                  : goal.priority === 3
                    ? c(' [low]', 'dim')
                    : '';
              output.log(`  - ${goal.goalText}${progress}${priority}`);
              output.log(c(`    ID: ${goal.id}`, 'dim'));
            }
          }
        } else if (subCmd === 'add' && args.length > 1) {
          const goalText = args.slice(1).join(' ');
          const goalId = sqliteStore.createGoal(goalText);
          output.log(c(`+ Goal created: ${goalId}`, 'green'));
        } else if (subCmd === 'done' && args[1]) {
          sqliteStore.completeGoal(args[1]);
          output.log(c(`+ Goal completed: ${args[1]}`, 'green'));
        } else if (subCmd === 'progress' && args[1] && args[2] && args[3]) {
          sqliteStore.updateGoal(args[1], {
            progressCurrent: parseInt(args[2], 10),
            progressTotal: parseInt(args[3], 10),
          });
          output.log(c(`+ Progress updated: ${args[2]}/${args[3]}`, 'green'));
        } else if (subCmd === 'all') {
          const goals = sqliteStore.listGoals();
          output.log(c('\nAll Goals:', 'bold'));
          for (const goal of goals) {
            const status =
              goal.status === 'completed'
                ? c('+', 'green')
                : goal.status === 'abandoned'
                  ? c('x', 'red')
                  : ' ';
            output.log(`  ${status} ${goal.goalText} [${goal.status}]`);
          }
        } else if (subCmd === 'junctures') {
          const junctures = sqliteStore.listJunctures(undefined, 10);
          if (junctures.length === 0) {
            output.log(c('No junctures logged yet.', 'dim'));
          } else {
            output.log(c('\nRecent Key Moments:', 'bold'));
            for (const j of junctures) {
              const icon =
                j.type === 'failure'
                  ? c('x', 'red')
                  : j.type === 'breakthrough'
                    ? c('*', 'yellow')
                    : j.type === 'decision'
                      ? c('>', 'cyan')
                      : c('~', 'magenta');
              output.log(`  ${icon} [${j.type}] ${j.description}`);
              if (j.outcome) output.log(c(`     -> ${j.outcome}`, 'dim'));
            }
          }
        } else {
          output.log(c('Usage:', 'bold'));
          output.log(c('  /goals              - List active goals', 'dim'));
          output.log(c('  /goals add <text>   - Create a new goal', 'dim'));
          output.log(c('  /goals done <id>    - Mark goal as completed', 'dim'));
          output.log(c('  /goals progress <id> <current> <total> - Update progress', 'dim'));
          output.log(c('  /goals all          - List all goals (including completed)', 'dim'));
          output.log(c('  /goals junctures    - Show recent key moments', 'dim'));
        }
      } else {
        output.log(c('Goals require SQLite store (not available with JSONL fallback)', 'yellow'));
      }
      break;

    case '/handoff':
      if ('exportSessionManifest' in sessionStore) {
        const sqliteStore = sessionStore as SQLiteStore;
        const format = args[0]?.toLowerCase() || 'markdown';

        if (format === 'json') {
          const manifest = sqliteStore.exportSessionManifest();
          if (manifest) {
            output.log(JSON.stringify(manifest, null, 2));
          } else {
            output.log(c('No active session to export', 'yellow'));
          }
        } else {
          const markdown = sqliteStore.exportSessionMarkdown();
          output.log(markdown);
        }
      } else {
        output.log(
          c('Handoff requires SQLite store (not available with JSONL fallback)', 'yellow'),
        );
      }
      break;

    // =========================================================================
    // REASONING MODES
    // =========================================================================

    case '/react':
      if (args.length === 0) {
        output.log(c('Usage: /react <task>', 'yellow'));
      } else {
        const task = args.join(' ');
        output.log(c(`\nRunning with ReAct pattern: ${task}`, 'cyan'));
        try {
          const trace = await agent.runWithReAct(task);
          output.log(c('\n--- ReAct Trace ---', 'magenta'));
          output.log(agent.formatReActTrace(trace));
          output.log(c('-------------------', 'magenta'));
        } catch (error) {
          output.log(c(`Error: ${(error as Error).message}`, 'red'));
        }
      }
      break;

    case '/team':
      if (args.length === 0) {
        output.log(c('Usage: /team <task>', 'yellow'));
      } else {
        const task = args.join(' ');
        output.log(c(`\nRunning with team: ${task}`, 'cyan'));
        try {
          const { CODER_ROLE, REVIEWER_ROLE, RESEARCHER_ROLE } =
            await import('../integrations/agents/multi-agent.js');
          const result = await agent.runWithTeam(
            { id: `team-${Date.now()}`, goal: task, context: '' },
            [RESEARCHER_ROLE, CODER_ROLE, REVIEWER_ROLE],
          );
          output.log(c('\n--- Team Result ---', 'magenta'));
          output.log(`Success: ${result.success}`);
          output.log(`Coordinator: ${result.coordinator}`);
          if (result.consensus) {
            output.log(
              `Consensus: ${result.consensus.agreed ? 'Agreed' : 'Disagreed'} - ${result.consensus.result}`,
            );
          }
          output.log(c('-------------------', 'magenta'));
        } catch (error) {
          output.log(c(`Error: ${(error as Error).message}`, 'red'));
        }
      }
      break;

    // =========================================================================
    // CHECKPOINTS & THREADS
    // =========================================================================

    case '/checkpoint':
    case '/cp':
      try {
        const label = args.length > 0 ? args.join(' ') : undefined;
        const checkpoint = agent.createCheckpoint(label);
        output.log(
          c(`+ Checkpoint created: ${checkpoint.id}${label ? ` (${label})` : ''}`, 'green'),
        );
      } catch (error) {
        output.log(c(`Error: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/checkpoints':
    case '/cps':
      try {
        const checkpoints = agent.getCheckpoints();
        if (checkpoints.length === 0) {
          output.log(c('No checkpoints.', 'dim'));
        } else {
          output.log(c('\nCheckpoints:', 'bold'));
          checkpoints.forEach((cp) => {
            output.log(`  ${c(cp.id, 'cyan')}${cp.label ? ` - ${cp.label}` : ''}`);
          });
        }
      } catch (error) {
        output.log(c(`Error: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/restore':
      if (args.length === 0) {
        output.log(c('Usage: /restore <checkpoint-id>', 'yellow'));
      } else {
        const success = agent.restoreCheckpoint(args[0]);
        output.log(
          success ? c(`+ Restored: ${args[0]}`, 'green') : c(`x Not found: ${args[0]}`, 'red'),
        );
      }
      break;

    case '/rollback':
    case '/rb': {
      const steps = args.length > 0 ? parseInt(args[0], 10) : 1;
      if (isNaN(steps) || steps < 1) {
        output.log(c('Usage: /rollback <steps>', 'yellow'));
      } else {
        const success = agent.rollback(steps);
        output.log(
          success ? c(`+ Rolled back ${steps} steps`, 'green') : c('x Rollback failed', 'red'),
        );
      }
      break;
    }

    case '/fork':
      if (args.length === 0) {
        output.log(c('Usage: /fork <name>', 'yellow'));
      } else {
        try {
          const threadId = agent.fork(args.join(' '));
          output.log(c(`+ Forked: ${threadId}`, 'green'));
        } catch (error) {
          output.log(c(`Error: ${(error as Error).message}`, 'red'));
        }
      }
      break;

    case '/threads':
      try {
        const threads = agent.getAllThreads();
        if (threads.length === 0) {
          output.log(c('No threads.', 'dim'));
        } else {
          output.log(c('\nThreads:', 'bold'));
          threads.forEach((t: any) => {
            output.log(
              `  ${c(t.id, 'cyan')}${t.name ? ` - ${t.name}` : ''} (${t.messages?.length || 0} messages)`,
            );
          });
        }
      } catch (error) {
        output.log(c(`Error: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/switch':
      if (args.length === 0) {
        output.log(c('Usage: /switch <thread-id>', 'yellow'));
      } else {
        const success = agent.switchThread(args[0]);
        output.log(
          success ? c(`+ Switched to: ${args[0]}`, 'green') : c(`x Not found: ${args[0]}`, 'red'),
        );
      }
      break;

    // =========================================================================
    // SECURITY
    // =========================================================================

    case '/grants':
      try {
        const grants = agent.getActiveGrants();
        if (grants.length === 0) {
          output.log(c('No active permission grants.', 'dim'));
        } else {
          output.log(c('\nActive Grants:', 'bold'));
          grants.forEach((g: any) => {
            output.log(`  ${c(g.id, 'cyan')} - ${g.toolName} (${g.grantedBy})`);
          });
        }
      } catch (error) {
        output.log(c(`Error: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/audit':
      try {
        const log = agent.getAuditLog();
        if (log.length === 0) {
          output.log(c('No audit entries.', 'dim'));
        } else {
          output.log(c('\nAudit Log:', 'bold'));
          log.slice(-10).forEach((entry: any) => {
            const status = entry.approved ? c('+', 'green') : c('x', 'red');
            output.log(`  ${status} ${entry.action} - ${entry.tool || 'n/a'}`);
          });
        }
      } catch (error) {
        output.log(c(`Error: ${(error as Error).message}`, 'red'));
      }
      break;

    // =========================================================================
    // BUDGET
    // =========================================================================

    case '/budget':
      try {
        const usage = agent.getBudgetUsage();
        const limits = agent.getBudgetLimits();
        const progress = agent.getProgress();

        if (!usage || !limits) {
          output.log(c('Economics not available.', 'dim'));
        } else {
          output.log(`
${c('Budget Usage:', 'bold')}
  Tokens:      ${usage.tokens.toLocaleString()} / ${limits.maxTokens.toLocaleString()} (${usage.percentUsed.toFixed(1)}%)
  Cost:        $${usage.cost.toFixed(4)} / $${limits.maxCost.toFixed(2)}
  Duration:    ${Math.round(usage.duration / 1000)}s / ${Math.round(limits.maxDuration / 1000)}s
  Iterations:  ${usage.iterations} / ${limits.maxIterations}

${c('Progress:', 'bold')}
  Files read:     ${progress?.filesRead || 0}
  Files modified: ${progress?.filesModified || 0}
  Commands run:   ${progress?.commandsRun || 0}
  Status:         ${progress?.isStuck ? c('STUCK', 'red') : c('Active', 'green')}
`);
        }
      } catch (error) {
        output.log(c(`Error: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/extend':
      if (args.length === 0) {
        output.log(c('Usage: /extend <tokens|cost|time> <amount>', 'yellow'));
      } else {
        const [what, amount] = args;
        const value = parseFloat(amount);
        if (isNaN(value)) {
          output.log(c('Invalid amount', 'red'));
        } else {
          const limits = agent.getBudgetLimits();
          if (!limits) {
            output.log(c('Economics not available', 'dim'));
          } else {
            switch (what) {
              case 'tokens':
                agent.extendBudget({ maxTokens: limits.maxTokens + value });
                output.log(
                  c(
                    `+ Token budget extended to ${(limits.maxTokens + value).toLocaleString()}`,
                    'green',
                  ),
                );
                break;
              case 'cost':
                agent.extendBudget({ maxCost: limits.maxCost + value });
                output.log(
                  c(`+ Cost budget extended to $${(limits.maxCost + value).toFixed(2)}`, 'green'),
                );
                break;
              case 'time':
                agent.extendBudget({ maxDuration: limits.maxDuration + value * 1000 });
                output.log(
                  c(
                    `+ Time budget extended to ${Math.round((limits.maxDuration + value * 1000) / 1000)}s`,
                    'green',
                  ),
                );
                break;
              default:
                output.log(c('Unknown budget type. Use: tokens, cost, or time', 'yellow'));
            }
          }
        }
      }
      break;

    // =========================================================================
    // SUBAGENTS
    // =========================================================================

    case '/agents':
      try {
        const { agentRegistry } = integrations;
        if (agentRegistry) {
          await handleAgentsCommand(args, ctx, agentRegistry);
        } else {
          // Fallback to legacy display if no agentRegistry
          const agentList = agent.formatAgentList();
          output.log(c('\nAvailable Agents:', 'bold'));
          output.log(agentList);
        }
      } catch (error) {
        output.log(c(`Error: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/spawn':
      if (args.length < 2) {
        output.log(c('Usage: /spawn <agent-name> <task>', 'yellow'));
      } else {
        const agentName = args[0];
        const task = args.slice(1).join(' ');
        output.log(c(`\nSpawning ${agentName}: ${task}`, 'cyan'));
        try {
          const result = await agent.spawnAgent(agentName, task);
          output.log(c('\n--- Agent Result ---', 'magenta'));
          output.log(`Success: ${result.success}`);
          output.log(`Output: ${result.output}`);
          output.log(
            c(
              `\nTokens: ${result.metrics.tokens} | Tools: ${result.metrics.toolCalls} | Duration: ${result.metrics.duration}ms`,
              'dim',
            ),
          );
          output.log(c('--------------------', 'magenta'));
        } catch (error) {
          output.log(c(`Error: ${(error as Error).message}`, 'red'));
        }
      }
      break;

    case '/find':
      if (args.length === 0) {
        output.log(c('Usage: /find <query>', 'yellow'));
      } else {
        const query = args.join(' ');
        output.log(c(`\nFinding agents for: "${query}"`, 'cyan'));
        const matches = agent.findAgentsForTask(query);
        if (matches.length === 0) {
          output.log(c('No matching agents found.', 'dim'));
        } else {
          output.log(c('\nMatching Agents:', 'bold'));
          matches.forEach((a, i) => {
            output.log(`  ${i + 1}. ${c(a.name, 'cyan')} (${a.source})`);
            output.log(`     ${a.description.split('.')[0]}`);
            if (a.capabilities?.length) {
              output.log(c(`     Capabilities: ${a.capabilities.join(', ')}`, 'dim'));
            }
          });
          output.log(c('\nUse /spawn <agent-name> <task> to run an agent.', 'dim'));
        }
      }
      break;

    case '/suggest':
      if (args.length === 0) {
        output.log(c('Usage: /suggest <task description>', 'yellow'));
      } else {
        const taskDesc = args.join(' ');
        output.log(c(`\nAnalyzing task: "${taskDesc}"`, 'cyan'));
        try {
          const { suggestions, shouldDelegate, delegateAgent } =
            await agent.suggestAgentForTask(taskDesc);

          if (suggestions.length === 0) {
            output.log(
              c('\nNo specialized agent recommended. Main agent should handle this task.', 'dim'),
            );
          } else {
            output.log(c('\nAgent Suggestions:', 'bold'));
            suggestions.forEach((s, i) => {
              const confidenceBar =
                '='.repeat(Math.round(s.confidence * 10)) +
                '-'.repeat(10 - Math.round(s.confidence * 10));
              output.log(
                `  ${i + 1}. ${c(s.agent.name, 'cyan')} [${confidenceBar}] ${(s.confidence * 100).toFixed(0)}%`,
              );
              output.log(`     ${s.reason}`);
            });

            if (shouldDelegate && delegateAgent) {
              output.log(c(`\nRecommendation: Delegate to "${delegateAgent}"`, 'green'));
              output.log(c(`   Run: /spawn ${delegateAgent} ${taskDesc}`, 'dim'));
            } else {
              output.log(c('\nRecommendation: Main agent should handle this task.', 'dim'));
            }
          }
        } catch (error) {
          output.log(c(`Error: ${(error as Error).message}`, 'red'));
        }
      }
      break;

    case '/auto':
      if (args.length === 0) {
        output.log(c('Usage: /auto <task>', 'yellow'));
      } else {
        const autoTask = args.join(' ');
        output.log(c(`\nAuto-routing: "${autoTask}"`, 'cyan'));
        try {
          // Create a confirmation callback
          const confirmDelegate = async (suggestedAgent: any, reason: string): Promise<boolean> => {
            output.log(c(`\nSuggested agent: ${suggestedAgent.name}`, 'yellow'));
            output.log(c(`   Reason: ${reason}`, 'dim'));
            if (ctx.confirm) {
              return ctx.confirm('Delegate to this agent?');
            }
            if (ctx.rl) {
              const answer = await ctx.rl.question(
                c('   Delegate to this agent? (y/n): ', 'yellow'),
              );
              return answer.toLowerCase().startsWith('y');
            }
            return false;
          };

          const result = await agent.runWithAutoRouting(autoTask, {
            confidenceThreshold: 0.75,
            confirmDelegate,
          });

          if ('output' in result) {
            output.log(c('\n--- Subagent Result ---', 'magenta'));
            output.log(`Success: ${result.success}`);
            output.log(result.output);
            output.log(
              c(
                `\nTokens: ${result.metrics.tokens} | Duration: ${result.metrics.duration}ms`,
                'dim',
              ),
            );
            output.log(c('-----------------------', 'magenta'));
          } else {
            output.log(c('\n--- Assistant ---', 'magenta'));
            output.log(result.response);
            output.log(c('-----------------', 'magenta'));
            output.log(
              c(
                `\nTokens: ${result.metrics.inputTokens} in / ${result.metrics.outputTokens} out | Tools: ${result.metrics.toolCalls}`,
                'dim',
              ),
            );
          }
        } catch (error) {
          output.log(c(`Error: ${(error as Error).message}`, 'red'));
        }
      }
      break;

    // =========================================================================
    // MCP INTEGRATION
    // =========================================================================

    case '/mcp':
      if (args.length === 0) {
        const servers = mcpClient.listServers();
        output.log(formatServerList(servers));
      } else if (args[0] === 'connect' && args[1]) {
        output.log(c(`Connecting to ${args[1]}...`, 'cyan'));
        try {
          await mcpClient.connectServer(args[1]);
          output.log(c(`+ Connected to ${args[1]}`, 'green'));
          const tools = mcpClient.getAllTools();
          for (const tool of tools) {
            agent.addTool(tool);
          }
          output.log(c(`  Added ${tools.length} tools from MCP servers`, 'dim'));
        } catch (error) {
          output.log(c(`Error: ${(error as Error).message}`, 'red'));
        }
      } else if (args[0] === 'disconnect' && args[1]) {
        await mcpClient.disconnectServer(args[1]);
        output.log(c(`+ Disconnected from ${args[1]}`, 'green'));
      } else if (args[0] === 'tools') {
        const tools = mcpClient.getAllTools();
        if (tools.length === 0) {
          output.log(c('No MCP tools available.', 'dim'));
        } else {
          output.log(c('\nMCP Tools:', 'bold'));
          tools.forEach((t) => {
            const loaded = mcpClient.isToolLoaded(t.name);
            const status = loaded ? c('+', 'green') : c('o', 'dim');
            output.log(
              `  ${status} ${c(t.name, 'cyan')} - ${t.description?.slice(0, 60) || 'No description'}...`,
            );
          });
          const stats = mcpClient.getContextStats();
          output.log(c(`\n  Legend: + = full schema loaded, o = summary only`, 'dim'));
          output.log(c(`  Loaded: ${stats.loadedCount}/${stats.totalTools} tools`, 'dim'));
        }
      } else if (args[0] === 'search') {
        const query = args.slice(1).join(' ');
        if (!query) {
          output.log(c('Usage: /mcp search <query>', 'yellow'));
        } else {
          output.log(c(`Searching for: "${query}"...`, 'cyan'));
          const results = mcpClient.searchTools(query, { limit: 10 });
          if (results.length === 0) {
            output.log(c('No matching tools found.', 'dim'));
          } else {
            output.log(c(`\nFound ${results.length} tool(s):`, 'bold'));
            results.forEach((r) => {
              output.log(`  ${c(r.name, 'cyan')} (${r.serverName})`);
              output.log(`    ${r.description}`);
            });
            const loadedTools = mcpClient.loadTools(results.map((r) => r.name));
            for (const tool of loadedTools) {
              agent.addTool(tool);
            }
            output.log(
              c(
                `\n+ Loaded ${loadedTools.length} tool(s). They are now available for use.`,
                'green',
              ),
            );
          }
        }
      } else if (args[0] === 'stats') {
        const stats = mcpClient.getContextStats();
        const fullLoadEstimate = stats.totalTools * 200;
        const currentTokens = stats.summaryTokens + stats.definitionTokens;
        const savingsPercent =
          fullLoadEstimate > 0 ? Math.round((1 - currentTokens / fullLoadEstimate) * 100) : 0;

        output.log(`
${c('MCP Context Usage:', 'bold')}
  Tool summaries:    ${stats.summaryCount.toString().padStart(3)} tools (~${stats.summaryTokens.toLocaleString()} tokens)
  Full definitions:  ${stats.loadedCount.toString().padStart(3)} tools (~${stats.definitionTokens.toLocaleString()} tokens)
  Total:             ${stats.totalTools.toString().padStart(3)} tools (~${currentTokens.toLocaleString()} tokens)

  Context savings:   ${savingsPercent}% vs loading all full schemas
  ${savingsPercent > 50 ? c('+ Good - lazy loading is saving context', 'green') : c('! Consider using lazy loading more', 'yellow')}

${c('Tip:', 'dim')} Use /mcp search <query> to load specific tools on-demand.
`);
      } else {
        output.log(c('Usage:', 'bold'));
        output.log(c('  /mcp                - List servers', 'dim'));
        output.log(c('  /mcp connect <name> - Connect to server', 'dim'));
        output.log(c('  /mcp disconnect <name> - Disconnect', 'dim'));
        output.log(c('  /mcp tools          - List available tools', 'dim'));
        output.log(c('  /mcp search <query> - Search & load tools', 'dim'));
        output.log(c('  /mcp stats          - Show context usage stats', 'dim'));
      }
      break;

    // =========================================================================
    // SESSION MANAGEMENT
    // =========================================================================

    case '/save':
      try {
        const state = agent.getState();
        const metrics = agent.getMetrics();
        const saveCheckpointId = `ckpt-manual-${Date.now().toString(36)}`;

        persistenceDebug.log('/save command - creating checkpoint', {
          checkpointId: saveCheckpointId,
          messageCount: state.messages?.length ?? 0,
        });

        saveCheckpointToStore(sessionStore, {
          id: saveCheckpointId,
          label: 'manual-save',
          messages: state.messages,
          iteration: state.iteration,
          metrics: metrics,
          plan: state.plan,
          memoryContext: state.memoryContext,
        });

        output.log(c(`+ Session saved: ${sessionId} (checkpoint: ${saveCheckpointId})`, 'green'));
      } catch (error) {
        persistenceDebug.error('/save command failed', error);
        output.log(c(`Error saving session: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/load':
      if (args.length === 0) {
        output.log(c('Usage: /load <session-id>', 'yellow'));
        output.log(c('  Use /sessions to list available sessions', 'dim'));
      } else {
        const loadId = args[0];
        try {
          let checkpointData: CheckpointData | undefined;
          if (
            'loadLatestCheckpoint' in sessionStore &&
            typeof sessionStore.loadLatestCheckpoint === 'function'
          ) {
            const sqliteCheckpoint = sessionStore.loadLatestCheckpoint(loadId);
            if (sqliteCheckpoint?.state) {
              checkpointData = sqliteCheckpoint.state as unknown as CheckpointData;
            }
          }

          if (!checkpointData) {
            const entries = await sessionStore.loadSession(loadId);
            if (entries.length === 0) {
              output.log(c(`No entries found for session: ${loadId}`, 'yellow'));
              break;
            }
            const checkpoint = [...entries].reverse().find((e) => e.type === 'checkpoint');
            checkpointData = checkpoint?.data as CheckpointData | undefined;
          }

          if (checkpointData?.messages) {
            agent.loadState({
              messages: checkpointData.messages as any,
              iteration: checkpointData.iteration,
              metrics: checkpointData.metrics as any,
              plan: checkpointData.plan as any,
              memoryContext: checkpointData.memoryContext,
            });
            output.log(
              c(`+ Loaded ${checkpointData.messages.length} messages from ${loadId}`, 'green'),
            );
          } else {
            output.log(c('No checkpoint found in session', 'yellow'));
          }
        } catch (error) {
          output.log(c(`Error loading session: ${(error as Error).message}`, 'red'));
        }
      }
      break;

    case '/resume':
      try {
        const recentSession = sessionStore.getRecentSession();
        if (!recentSession) {
          output.log(c('No previous sessions found', 'yellow'));
        } else {
          output.log(c(`Found recent session: ${recentSession.id}`, 'dim'));
          output.log(c(`   Created: ${new Date(recentSession.createdAt).toLocaleString()}`, 'dim'));
          output.log(c(`   Messages: ${recentSession.messageCount}`, 'dim'));

          let resumeCheckpointData: CheckpointData | undefined;
          if (
            'loadLatestCheckpoint' in sessionStore &&
            typeof sessionStore.loadLatestCheckpoint === 'function'
          ) {
            const sqliteCheckpoint = sessionStore.loadLatestCheckpoint(recentSession.id);
            if (sqliteCheckpoint?.state) {
              resumeCheckpointData = sqliteCheckpoint.state as unknown as CheckpointData;
            }
          }

          if (!resumeCheckpointData) {
            const entriesResult = sessionStore.loadSession(recentSession.id);
            const entries = Array.isArray(entriesResult) ? entriesResult : await entriesResult;
            const checkpoint = [...entries].reverse().find((e) => e.type === 'checkpoint');
            if (checkpoint?.data) {
              resumeCheckpointData = checkpoint.data as CheckpointData;
            } else {
              const messages = entries
                .filter((e: { type: string }) => e.type === 'message')
                .map((e: { data: unknown }) => e.data);
              if (messages.length > 0) {
                agent.loadState({ messages: messages as any });
                output.log(c(`+ Resumed ${messages.length} messages from last session`, 'green'));
              } else {
                output.log(c('No messages found in last session', 'yellow'));
              }
            }
          }

          if (resumeCheckpointData?.messages) {
            agent.loadState({
              messages: resumeCheckpointData.messages as any,
              iteration: resumeCheckpointData.iteration,
              metrics: resumeCheckpointData.metrics as any,
              plan: resumeCheckpointData.plan as any,
              memoryContext: resumeCheckpointData.memoryContext,
            });
            output.log(
              c(
                `+ Resumed ${resumeCheckpointData.messages.length} messages from last session`,
                'green',
              ),
            );
            if (resumeCheckpointData.iteration) {
              output.log(c(`   Iteration: ${resumeCheckpointData.iteration}`, 'dim'));
            }
            if (resumeCheckpointData.plan) {
              output.log(c(`   Plan restored`, 'dim'));
            }

            if (
              'getPendingPlan' in sessionStore &&
              typeof sessionStore.getPendingPlan === 'function'
            ) {
              const pendingPlan = sessionStore.getPendingPlan(recentSession.id);
              if (pendingPlan && pendingPlan.status === 'pending') {
                output.log(c(`\nFound pending plan: "${pendingPlan.task}"`, 'yellow'));
                output.log(
                  c(
                    `   ${pendingPlan.proposedChanges.length} change(s) awaiting approval`,
                    'yellow',
                  ),
                );
                output.log(
                  c('   Use /show-plan to view, /approve to execute, /reject to discard', 'dim'),
                );
              }
            }
          }
        }
      } catch (error) {
        output.log(c(`Error resuming session: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/sessions':
      try {
        const sessions = await sessionStore.listSessions();
        output.log(formatSessionsTable(sessions));
      } catch (error) {
        output.log(c(`Error: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/load':
      try {
        const targetSessionId = args[0];
        if (!targetSessionId) {
          output.log(c('Usage: /load <session-id>', 'yellow'));
          output.log(c('  Use /sessions to list available sessions', 'dim'));
          break;
        }

        // Check if session exists
        const targetSession = sessionStore.getSessionMetadata(targetSessionId);
        if (!targetSession) {
          output.log(c(`Session not found: ${targetSessionId}`, 'red'));
          output.log(c('  Use /sessions to list available sessions', 'dim'));
          break;
        }

        output.log(c(`Loading session: ${targetSession.id}`, 'dim'));
        output.log(c(`   Created: ${new Date(targetSession.createdAt).toLocaleString()}`, 'dim'));
        output.log(c(`   Messages: ${targetSession.messageCount}`, 'dim'));

        // Try to load from checkpoint first (same as /resume)
        let loadCheckpointData: CheckpointData | undefined;
        if (
          'loadLatestCheckpoint' in sessionStore &&
          typeof sessionStore.loadLatestCheckpoint === 'function'
        ) {
          const sqliteCheckpoint = sessionStore.loadLatestCheckpoint(targetSession.id);
          if (sqliteCheckpoint?.state) {
            loadCheckpointData = sqliteCheckpoint.state as unknown as CheckpointData;
          }
        }

        // Fall back to loading from entries if no checkpoint
        if (!loadCheckpointData) {
          const entriesResult = sessionStore.loadSession(targetSession.id);
          const entries = Array.isArray(entriesResult) ? entriesResult : await entriesResult;
          const checkpoint = [...entries].reverse().find((e) => e.type === 'checkpoint');
          if (checkpoint?.data) {
            loadCheckpointData = checkpoint.data as CheckpointData;
          } else {
            const messages = entries
              .filter((e: { type: string }) => e.type === 'message')
              .map((e: { data: unknown }) => e.data);
            if (messages.length > 0) {
              agent.loadState({ messages: messages as any });
              output.log(c(`+ Loaded ${messages.length} messages from session`, 'green'));
            } else {
              output.log(c('No messages found in session', 'yellow'));
            }
          }
        }

        // Load from checkpoint data if available
        if (loadCheckpointData?.messages) {
          agent.loadState({
            messages: loadCheckpointData.messages as any,
            iteration: loadCheckpointData.iteration,
            metrics: loadCheckpointData.metrics as any,
            plan: loadCheckpointData.plan as any,
            memoryContext: loadCheckpointData.memoryContext,
          });
          output.log(
            c(`+ Loaded ${loadCheckpointData.messages.length} messages from session`, 'green'),
          );
          if (loadCheckpointData.iteration) {
            output.log(c(`   Iteration: ${loadCheckpointData.iteration}`, 'dim'));
          }
          if (loadCheckpointData.plan) {
            output.log(c(`   Plan restored`, 'dim'));
          }

          // Check for pending plans
          if (
            'getPendingPlan' in sessionStore &&
            typeof sessionStore.getPendingPlan === 'function'
          ) {
            const pendingPlan = sessionStore.getPendingPlan(targetSession.id);
            if (pendingPlan && pendingPlan.status === 'pending') {
              output.log(c(`\nFound pending plan: "${pendingPlan.task}"`, 'yellow'));
              output.log(
                c(`   ${pendingPlan.proposedChanges.length} change(s) awaiting approval`, 'yellow'),
              );
              output.log(
                c('   Use /show-plan to view, /approve to execute, /reject to discard', 'dim'),
              );
            }
          }
        }
      } catch (error) {
        output.log(c(`Error loading session: ${(error as Error).message}`, 'red'));
      }
      break;

    // =========================================================================
    // CONTEXT MANAGEMENT
    // =========================================================================

    case '/compact':
      try {
        const state = agent.getState();
        const contextUsage = getContextUsage(state.messages, agent.getMaxContextTokens());

        if (args[0] === 'status') {
          output.log(`
${c('Context Status:', 'bold')}
  Messages:    ${state.messages.length}
  Est. Tokens: ${contextUsage.tokens.toLocaleString()}
  Usage:       ${contextUsage.percent}%
  Threshold:   80%
  Should Compact: ${contextUsage.shouldCompact ? c('Yes', 'yellow') : c('No', 'green')}
`);
        } else {
          if (state.messages.length < 5) {
            output.log(c('Not enough messages to compact.', 'dim'));
          } else {
            output.log(c('Compacting context...', 'cyan'));
            const result = await compactor.compact(state.messages);
            agent.loadMessages(result.preservedMessages);
            output.log(formatCompactionResult(result));
          }
        }
      } catch (error) {
        output.log(c(`Error: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/context':
      try {
        const state = agent.getState();

        if (args[0] === 'breakdown') {
          // Detailed token breakdown
          const mcpStats = mcpClient.getContextStats();
          const systemPrompt = agent.getSystemPromptWithMode();
          const estimateTokens = (str: string) => estimateTokenCount(str);

          const systemTokens = estimateTokens(systemPrompt);
          const mcpTokens = mcpStats.summaryTokens + mcpStats.definitionTokens;
          const agentTools = agent.getTools().filter((t) => !t.name.startsWith('mcp_'));
          const agentToolTokens = agentTools.length * 150;
          const convTokens = state.messages
            .filter((m) => m.role !== 'system')
            .reduce((sum, m) => sum + estimateTokens(m.content), 0);

          const totalTokens = systemTokens + mcpTokens + agentToolTokens + convTokens;
          const messageCount = state.messages.filter((m) => m.role !== 'system').length;

          const sysPct = totalTokens > 0 ? Math.round((systemTokens / totalTokens) * 100) : 0;
          const mcpPct = totalTokens > 0 ? Math.round((mcpTokens / totalTokens) * 100) : 0;
          const agentPct = totalTokens > 0 ? Math.round((agentToolTokens / totalTokens) * 100) : 0;
          const convPct = totalTokens > 0 ? Math.round((convTokens / totalTokens) * 100) : 0;

          output.log(`
${c('Context Token Breakdown', 'bold')} (Total: ~${totalTokens.toLocaleString()} tokens)

${c('  Category             Tokens    % of Total', 'dim')}
  System prompt:     ${systemTokens.toLocaleString().padStart(7)} tokens  ${sysPct.toString().padStart(3)}%
  MCP tools:         ${mcpTokens.toLocaleString().padStart(7)} tokens  ${mcpPct.toString().padStart(3)}%  (${mcpStats.loadedCount} loaded / ${mcpStats.totalTools} total)
  Agent tools:       ${agentToolTokens.toLocaleString().padStart(7)} tokens  ${agentPct.toString().padStart(3)}%  (${agentTools.length} tools)
  Conversation:      ${convTokens.toLocaleString().padStart(7)} tokens  ${convPct.toString().padStart(3)}%  (${messageCount} messages)
`);
        } else {
          // Simple context overview
          const mcpStats = mcpClient.getContextStats();
          const systemPrompt = agent.getSystemPromptWithMode();
          const estimateTokens = (str: string) => estimateTokenCount(str);

          const systemTokens = estimateTokens(systemPrompt);
          const mcpTokens = mcpStats.summaryTokens + mcpStats.definitionTokens;
          const agentTools = agent.getTools().filter((t) => !t.name.startsWith('mcp_'));
          const agentToolTokens = agentTools.length * 150;
          const baseTokens = systemTokens + mcpTokens + agentToolTokens;

          const convTokens = state.messages
            .filter((m) => m.role !== 'system')
            .reduce((sum, m) => sum + estimateTokens(m.content), 0);

          const totalTokens = baseTokens + convTokens;
          const contextLimit = agent.getMaxContextTokens();
          const percent = Math.round((totalTokens / contextLimit) * 100);
          const shouldCompact = percent >= 80;

          const bar =
            '='.repeat(Math.min(20, Math.round(percent / 5))) +
            '-'.repeat(Math.max(0, 20 - Math.round(percent / 5)));
          const color = percent >= 80 ? 'red' : percent >= 60 ? 'yellow' : 'green';

          output.log(`
${c('Context Window:', 'bold')}
  [${c(bar, color)}] ${percent}%
  Base:     ~${baseTokens.toLocaleString()} tokens (system + ${agentTools.length} agent tools)
  MCP:      ~${mcpTokens.toLocaleString()} tokens (${mcpStats.loadedCount}/${mcpStats.totalTools} tools loaded)
  Messages: ${state.messages.filter((m) => m.role !== 'system').length} (~${convTokens.toLocaleString()} tokens)
  Total:    ~${totalTokens.toLocaleString()} / ${(contextLimit / 1000).toFixed(0)}k tokens
  ${shouldCompact ? c('! Consider running /compact', 'yellow') : c('+ Healthy', 'green')}
`);
        }
      } catch (error) {
        output.log(c(`Error: ${(error as Error).message}`, 'red'));
      }
      break;

    // =========================================================================
    // THEME
    // =========================================================================

    case '/theme':
      try {
        const { getThemeNames, getTheme } = await import('../tui/theme/index.js');
        const themes = getThemeNames();

        if (args.length === 0) {
          output.log(`
${c('Available Themes:', 'bold')}
${themes.map((t) => `  ${c(t, 'cyan')}`).join('\n')}

${c('Usage:', 'dim')} /theme <name>
${c('Note:', 'dim')} Theme switching is visual in TUI mode. REPL mode uses fixed ANSI colors.
`);
        } else {
          const themeName = args[0];
          if (themes.includes(themeName)) {
            const selectedTheme = getTheme(
              themeName as 'dark' | 'light' | 'high-contrast' | 'auto',
            );
            output.log(c(`+ Theme set to: ${themeName}`, 'green'));
            output.log(c(`  Primary: ${selectedTheme.colors.primary}`, 'dim'));
            output.log(c(`  Note: Full theme support requires TUI mode`, 'dim'));
          } else {
            output.log(c(`Unknown theme: ${themeName}`, 'red'));
            output.log(c(`Available: ${themes.join(', ')}`, 'dim'));
          }
        }
      } catch (error) {
        output.log(c(`Error loading themes: ${(error as Error).message}`, 'red'));
      }
      break;

    // =========================================================================
    // DEBUGGING & TESTING
    // =========================================================================

    case '/skills':
      try {
        const { skillManager } = integrations;
        if (skillManager) {
          await handleSkillsCommand(args, ctx, skillManager);
        } else {
          // Fallback to legacy display if no skillManager
          const skills = agent.getSkills();
          if (skills.length === 0) {
            output.log(c('No skills loaded.', 'dim'));
            output.log(c('Add .md files to .attocode/skills/ directory to create skills.', 'dim'));
          } else {
            output.log(c('\nLoaded Skills:', 'bold'));
            skills.forEach((skill: any) => {
              const active = skill.active ? c('+', 'green') : c('o', 'dim');
              const invokable = skill.invokable ? c('[/]', 'magenta') : '   ';
              output.log(
                `  ${active} ${invokable} ${c(skill.name, 'cyan')} - ${skill.description || 'No description'}`,
              );
            });
          }
        }
      } catch (error) {
        output.log(c(`Skills not available: ${(error as Error).message}`, 'yellow'));
      }
      break;

    case '/sandbox':
      try {
        const { createSandboxManager } = await import('../integrations/safety/sandbox/index.js');
        const sandboxManager = createSandboxManager({ mode: 'auto', verbose: true });
        const available = await sandboxManager.getAvailableSandboxes();

        output.log(c('\nSandbox Modes:', 'bold'));
        for (const { mode, available: isAvailable } of available) {
          const icon = isAvailable ? c('+', 'green') : c('x', 'red');
          const desc: Record<string, string> = {
            auto: 'Auto-detect best available sandbox',
            seatbelt: 'macOS sandbox-exec with Seatbelt profiles',
            landlock: 'Linux Landlock LSM / bubblewrap / firejail',
            docker: 'Docker container isolation',
            basic: 'Allowlist-based command validation',
            none: 'No sandboxing (passthrough)',
          };
          output.log(`  ${icon} ${c(mode.padEnd(10), 'cyan')} ${desc[mode] || ''}`);
        }

        const sandbox = await sandboxManager.getSandbox();
        output.log(c(`\nActive sandbox: ${sandbox.getType()}`, 'green'));

        if (args[0] === 'test') {
          output.log(c('\nTesting sandbox with "echo hello"...', 'dim'));
          const result = await sandboxManager.execute('echo hello');
          output.log(`  Exit code: ${result.exitCode}`);
          output.log(`  Output: ${result.stdout.trim()}`);
          output.log(`  Sandboxed: ${sandbox.getType() !== 'none' ? 'Yes' : 'No'}`);
        } else {
          output.log(c('\nUse /sandbox test to run a test command.', 'dim'));
        }

        await sandboxManager.cleanup();
      } catch (error) {
        output.log(c(`Sandbox error: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/shell':
      try {
        const { createPTYShell } = await import('../integrations/streaming/pty-shell.js');

        if (args[0] === 'test') {
          output.log(c('\nTesting persistent PTY shell...', 'cyan'));
          const shell = createPTYShell({ timeout: 5000 });
          await shell.start();

          output.log(c('  1. Setting variable: export TEST_VAR="hello"', 'dim'));
          await shell.execute('export TEST_VAR="hello"');

          output.log(c('  2. Reading variable back...', 'dim'));
          const result = await shell.execute('echo $TEST_VAR');
          output.log(`     Result: ${result.output}`);
          output.log(`     Exit code: ${result.exitCode}`);

          output.log(c('  3. Checking state persistence...', 'dim'));
          const state = shell.getState();
          output.log(`     CWD: ${state.cwd}`);
          output.log(`     Commands run: ${state.history.length}`);
          output.log(`     Shell running: ${state.isRunning}`);

          await shell.cleanup();
          output.log(c('\n+ PTY shell test passed!', 'green'));
        } else {
          output.log(`
${c('PTY Shell:', 'bold')}
  The persistent shell maintains state between commands:
  - Working directory persists across cd commands
  - Environment variables are retained
  - Command history is tracked

  ${c('Use /shell test to run a quick test.', 'dim')}
`);
        }
      } catch (error) {
        output.log(c(`Shell error: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/lsp':
      output.log(`
${c('LSP Integration:', 'bold')}
  The LSP-enhanced file tools provide real-time diagnostics:

${c('LSP-Enhanced Tools:', 'bold')}
  - ${c('lsp_edit_file', 'cyan')} - Edit with diagnostics feedback
  - ${c('lsp_write_file', 'cyan')} - Write with diagnostics feedback

${c('How it works:', 'dim')}
  1. After edit/write, LSP server analyzes the file
  2. Returns errors, warnings, and hints inline
  3. Agent can self-correct based on feedback
`);
      break;

    case '/tui':
      output.log(`
${c('TUI (Terminal UI):', 'bold')}
  Status: ${c('Active', 'green')}

${c('Features:', 'bold')}
  - Syntax highlighting for code blocks
  - Colored tool call display
  - Progress spinners
  - Error/success styling

${c('Code Highlighting Languages:', 'dim')}
  Python, JavaScript, TypeScript

${c('Test it:', 'dim')}
  Ask the agent to write code, e.g.:
  "Write a Python function to calculate factorial"
`);
      break;

    // =========================================================================
    // CAPABILITIES DISCOVERY
    // =========================================================================

    case '/powers': {
      const capRegistry = agent.getCapabilitiesRegistry?.();
      if (!capRegistry) {
        output.log(c('Capabilities registry not available.', 'dim'));
        break;
      }

      capRegistry.refresh();
      const counts = capRegistry.getCounts();

      if (args.length === 0) {
        // Show summary
        output.log(c('\n' + formatCapabilitiesSummary(counts), 'reset'));
        output.log(c('\nUsage:', 'bold'));
        output.log(c('  /powers tools      - List all tools', 'dim'));
        output.log(c('  /powers skills     - List all skills', 'dim'));
        output.log(c('  /powers agents     - List all agents', 'dim'));
        output.log(c('  /powers mcp        - List MCP tools', 'dim'));
        output.log(c('  /powers commands   - List commands', 'dim'));
        output.log(c('  /powers search <q> - Search all capabilities', 'dim'));
      } else if (args[0] === 'search' && args.length > 1) {
        const query = args.slice(1).join(' ');
        const results = capRegistry.search(query);
        output.log(c(`\nSearch: "${query}"\n`, 'cyan'));
        output.log(formatSearchResults(results));
      } else {
        // List by type
        const typeMap: Record<string, 'tool' | 'skill' | 'agent' | 'mcp_tool' | 'command'> = {
          tools: 'tool',
          tool: 'tool',
          skills: 'skill',
          skill: 'skill',
          agents: 'agent',
          agent: 'agent',
          mcp: 'mcp_tool',
          'mcp-tools': 'mcp_tool',
          mcp_tools: 'mcp_tool',
          commands: 'command',
          command: 'command',
        };

        const capType = typeMap[args[0]];
        if (capType) {
          const capabilities = capRegistry.getByType(capType);
          output.log(c('\n' + formatCapabilitiesList(capabilities, capType), 'reset'));
        } else {
          output.log(c(`Unknown capability type: ${args[0]}`, 'yellow'));
          output.log(c('Valid types: tools, skills, agents, mcp, commands', 'dim'));
        }
      }
      break;
    }

    // =========================================================================
    // INITIALIZATION
    // =========================================================================

    case '/init':
      await handleInitCommand(args, ctx);
      break;

    // =========================================================================
    // TRACE ANALYSIS
    // =========================================================================

    case '/trace': {
      const traceCollector = agent.getTraceCollector();

      if (args.length === 0) {
        // Show current session trace summary with subagent hierarchy
        if (!traceCollector) {
          output.log(c('Tracing is not enabled. Start agent with --trace to enable.', 'yellow'));
          break;
        }

        const data = traceCollector.getSessionTrace();
        if (!data || !data.iterations || data.iterations.length === 0) {
          output.log(c('No trace data collected yet.', 'dim'));
          break;
        }

        // Get subagent hierarchy from JSONL file
        const hierarchy = await traceCollector.getSubagentHierarchy();

        if (hierarchy && hierarchy.subagents.length > 0) {
          // Show hierarchy view with subagents
          output.log(`
${c('Trace Summary:', 'bold')}
  Session ID:    ${data.sessionId}
  Status:        ${data.status}
  Duration:      ${data.durationMs ? `${Math.round(data.durationMs / 1000)}s` : 'ongoing'}

${c('Main Agent:', 'bold')}
  Iterations:    ${hierarchy.mainAgent.llmCalls}
  Input tokens:  ${hierarchy.mainAgent.inputTokens.toLocaleString()}
  Output tokens: ${hierarchy.mainAgent.outputTokens.toLocaleString()}
  Tool calls:    ${hierarchy.mainAgent.toolCalls}

${c('Subagent Tree:', 'bold')}`);

          // Sort subagents by spawn time
          const sortedSubagents = hierarchy.subagents.sort(
            (a, b) => (a.spawnedAtIteration || 0) - (b.spawnedAtIteration || 0),
          );

          for (const sub of sortedSubagents) {
            const durationSec = Math.round(sub.duration / 1000);
            output.log(
              `  └─ ${c(sub.agentId, 'cyan')} (spawned iter ${sub.spawnedAtIteration || '?'})`,
            );
            output.log(
              `     ├─ ${sub.inputTokens.toLocaleString()} in / ${sub.outputTokens.toLocaleString()} out tokens`,
            );
            output.log(`     ├─ ${sub.toolCalls} tools | ${durationSec}s`);
          }

          output.log(`
${c('TOTALS (all agents):', 'bold')}
  Input tokens:  ${hierarchy.totals.inputTokens.toLocaleString()}
  Output tokens: ${hierarchy.totals.outputTokens.toLocaleString()}
  Tool calls:    ${hierarchy.totals.toolCalls}
  LLM calls:     ${hierarchy.totals.llmCalls}
  Est. Cost:     $${hierarchy.totals.estimatedCost.toFixed(4)}
  Duration:      ${Math.round(hierarchy.totals.duration / 1000)}s
`);
        } else {
          // Original simple view (no subagents)
          output.log(`
${c('Trace Summary:', 'bold')}
  Session ID:    ${data.sessionId}
  Status:        ${data.status}
  Iterations:    ${data.iterations.length}
  Duration:      ${data.durationMs ? `${Math.round(data.durationMs / 1000)}s` : 'ongoing'}

${c('Metrics:', 'bold')}
  Input tokens:  ${data.metrics.inputTokens.toLocaleString()}
  Output tokens: ${data.metrics.outputTokens.toLocaleString()}
  Cache hit:     ${Math.round(data.metrics.avgCacheHitRate * 100)}%
  Tool calls:    ${data.metrics.toolCalls}
  Errors:        ${data.metrics.errors}
  Est. Cost:     $${data.metrics.estimatedCost.toFixed(4)}
`);
        }

        output.log(`${c('Use:', 'dim')} /trace --analyze for efficiency analysis
${c('     ', 'dim')} /trace issues to see detected inefficiencies`);
      } else if (args[0] === '--analyze' || args[0] === 'analyze') {
        // Run efficiency analysis
        if (!traceCollector) {
          output.log(c('Tracing is not enabled.', 'yellow'));
          break;
        }

        const data = traceCollector.getSessionTrace();
        if (!data || !data.iterations || data.iterations.length === 0) {
          output.log(c('No trace data to analyze.', 'dim'));
          break;
        }

        output.log(c('Analyzing trace...', 'cyan'));

        // Import analysis module dynamically
        const { createTraceSummaryGenerator } = await import('../analysis/trace-summary.js');
        const generator = createTraceSummaryGenerator(data);
        const summary = generator.generate();

        // Display analysis results
        output.log(`
${c('Efficiency Analysis:', 'bold')}

${c('Anomalies Detected:', 'bold')} ${summary.anomalies.length}
`);

        if (summary.anomalies.length === 0) {
          output.log(c('  No significant issues detected.', 'green'));
        } else {
          for (const anomaly of summary.anomalies) {
            const severityColor =
              anomaly.severity === 'high'
                ? 'red'
                : anomaly.severity === 'medium'
                  ? 'yellow'
                  : 'dim';
            output.log(
              `  ${c(`[${anomaly.severity.toUpperCase()}]`, severityColor)} ${anomaly.type}`,
            );
            output.log(`       ${anomaly.description}`);
            output.log(c(`       Evidence: ${anomaly.evidence}`, 'dim'));
          }
        }

        output.log(`
${c('Tool Patterns:', 'bold')}
  Unique tools used: ${Object.keys(summary.toolPatterns.frequency).length}
  Redundant calls:   ${summary.toolPatterns.redundantCalls.length}
  Slow tools:        ${summary.toolPatterns.slowTools.length}
`);

        if (summary.codeLocations.length > 0) {
          output.log(c('Related Code Locations:', 'bold'));
          for (const loc of summary.codeLocations) {
            const rel =
              loc.relevance === 'primary'
                ? c('[PRIMARY]', 'cyan')
                : loc.relevance === 'secondary'
                  ? c('[SECONDARY]', 'dim')
                  : '';
            output.log(`  ${rel} ${loc.file} - ${loc.component}`);
            output.log(c(`       ${loc.description}`, 'dim'));
          }
        }
      } else if (args[0] === 'issues') {
        // List detected inefficiencies
        if (!traceCollector) {
          output.log(c('Tracing is not enabled.', 'yellow'));
          break;
        }

        const data = traceCollector.getSessionTrace();
        if (!data || !data.iterations || data.iterations.length === 0) {
          output.log(c('No trace data to analyze.', 'dim'));
          break;
        }

        const { createTraceSummaryGenerator } = await import('../analysis/trace-summary.js');
        const generator = createTraceSummaryGenerator(data);
        const summary = generator.generate();

        if (summary.anomalies.length === 0) {
          output.log(c('No issues detected in current session.', 'green'));
        } else {
          output.log(c('\nDetected Issues:', 'bold'));
          summary.anomalies.forEach((anomaly, i) => {
            const icon =
              anomaly.severity === 'high'
                ? c('!', 'red')
                : anomaly.severity === 'medium'
                  ? c('*', 'yellow')
                  : c('-', 'dim');
            output.log(`  ${icon} ${i + 1}. ${anomaly.type} (${anomaly.severity})`);
            output.log(`       ${anomaly.description}`);
          });
        }
      } else if (args[0] === 'fixes') {
        // List pending improvements from feedback loop
        try {
          const { createFeedbackLoopManager } = await import('../analysis/feedback-loop.js');
          const feedbackManager = createFeedbackLoopManager();

          const pendingFixes = feedbackManager.getPendingFixes();
          const stats = feedbackManager.getSummaryStats();

          output.log(`
${c('Feedback Loop Summary:', 'bold')}
  Total analyses:     ${stats.totalAnalyses}
  Avg efficiency:     ${stats.avgEfficiencyScore}%
  Total fixes:        ${stats.totalFixes}
  Implemented:        ${stats.implementedFixes}
  Verified:           ${stats.verifiedFixes}
  Avg improvement:    ${stats.avgImprovement}%
`);

          if (pendingFixes.length === 0) {
            output.log(c('No pending fixes.', 'dim'));
          } else {
            output.log(c('Pending Fixes:', 'bold'));
            for (const fix of pendingFixes.slice(0, 10)) {
              output.log(`  - ${fix.description}`);
              output.log(
                c(
                  `    ID: ${fix.id} | Created: ${new Date(fix.createdAt).toLocaleDateString()}`,
                  'dim',
                ),
              );
            }
            if (pendingFixes.length > 10) {
              output.log(c(`  ... and ${pendingFixes.length - 10} more`, 'dim'));
            }
          }

          feedbackManager.close();
        } catch (error) {
          output.log(c(`Error loading feedback data: ${(error as Error).message}`, 'red'));
        }
      } else if (args[0] === 'compare' && args.length >= 3) {
        // Compare two sessions
        output.log(c(`Comparing sessions: ${args[1]} vs ${args[2]}`, 'cyan'));
        output.log(c('Use the trace dashboard for session comparison:', 'dim'));
        output.log(c('  npm run dashboard', 'dim'));
        output.log(
          c(`  Then visit: http://localhost:5173/compare?a=${args[1]}&b=${args[2]}`, 'dim'),
        );
      } else if (args[0] === 'export') {
        // Export current trace as JSON for LLM analysis
        if (!traceCollector) {
          output.log(c('Tracing is not enabled.', 'yellow'));
          break;
        }

        const data = traceCollector.getSessionTrace();
        if (!data) {
          output.log(c('No trace data to export.', 'dim'));
          break;
        }

        const { createTraceSummaryGenerator } = await import('../analysis/trace-summary.js');
        const generator = createTraceSummaryGenerator(data);
        const summary = generator.generate();

        const outFile = args[1] || `trace-${sessionId}.json`;
        const { writeFile } = await import('fs/promises');
        await writeFile(outFile, JSON.stringify(summary, null, 2), 'utf-8');
        output.log(c(`+ Trace exported to: ${outFile}`, 'green'));
        output.log(c('  This JSON is optimized for LLM analysis (~4000 tokens)', 'dim'));
      } else {
        output.log(c('Usage:', 'bold'));
        output.log(c('  /trace              - Show current session trace summary', 'dim'));
        output.log(c('  /trace --analyze    - Run efficiency analysis', 'dim'));
        output.log(c('  /trace issues       - List detected inefficiencies', 'dim'));
        output.log(c('  /trace fixes        - List pending improvements', 'dim'));
        output.log(c('  /trace export [file]- Export trace JSON for LLM analysis', 'dim'));
        output.log(c('  /trace compare <a> <b> - Compare two sessions (via dashboard)', 'dim'));
      }
      break;
    }

    // =========================================================================
    // UNKNOWN COMMAND
    // =========================================================================

    default:
      output.log(c(`Unknown command: ${cmd}. Type /help`, 'yellow'));
  }

  output.log('');
}

// =============================================================================
// CONSOLE OUTPUT ADAPTER
// =============================================================================

/**
 * Create a CommandOutput that writes to console.
 * Used by REPL mode.
 */
export function createConsoleOutput(): import('./types.js').CommandOutput {
  return {
    log: (message: string) => logger.info(message),
    error: (message: string) => logger.error(message),
    clear: () => console.clear(),
  };
}
