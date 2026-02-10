/**
 * Structured Delegation Protocol
 *
 * Provides a structured interface for delegating tasks to subagents,
 * inspired by Anthropic's multi-agent research system.
 *
 * Instead of passing freeform task strings, the orchestrator creates
 * a DelegationSpec that explicitly communicates:
 * - Clear objective and success criteria
 * - Expected output format
 * - Tool guidance (what to use, what to avoid)
 * - Task boundaries (in-scope vs out-of-scope)
 * - Sibling context (what other agents are doing)
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * Structured delegation spec for subagent tasks.
 * Every field is intentionally explicit to prevent vague delegations.
 */
export interface DelegationSpec {
  /** One-sentence objective: what the subagent must accomplish */
  objective: string;

  /** Detailed context: why this task matters, how it fits the bigger picture */
  context: string;

  /** Expected output format */
  outputFormat: OutputFormatSpec;

  /** Tools and sources guidance */
  toolGuidance: ToolGuidance;

  /** Explicit task boundaries */
  boundaries: TaskBoundaries;

  /** How to know when done */
  successCriteria: string[];

  /** What other agents are doing (prevents duplicate work) */
  siblingContext?: SiblingContext;
}

export interface OutputFormatSpec {
  /** Format type */
  type: 'structured_json' | 'markdown_report' | 'code_changes' | 'free_text';
  /** Schema or template for expected output */
  schema?: string;
  /** Example of good output */
  example?: string;
}

export interface ToolGuidance {
  /** Tools the agent should use */
  recommended: string[];
  /** Tools the agent should avoid (with reason) */
  avoid?: Array<{ tool: string; reason: string }>;
  /** Specific sources/files to consult */
  sources?: string[];
}

export interface TaskBoundaries {
  /** What to include in scope */
  inScope: string[];
  /** What to explicitly exclude */
  outOfScope: string[];
  /** Maximum depth of exploration */
  maxExplorationDepth?: 'shallow' | 'moderate' | 'deep';
}

export interface SiblingContext {
  /** Brief description of what other agents are working on */
  siblingTasks: Array<{ agent: string; task: string }>;
  /** Files claimed by other agents (do not modify) */
  claimedFiles?: string[];
}

// =============================================================================
// BUILDER
// =============================================================================

/**
 * Convert a DelegationSpec into a structured prompt for a subagent.
 * The output is injected into the subagent's system prompt or task description.
 */
export function buildDelegationPrompt(spec: DelegationSpec): string {
  const sections: string[] = [];

  // Objective
  sections.push(`## OBJECTIVE\n${spec.objective}`);

  // Context
  if (spec.context) {
    sections.push(`## CONTEXT\n${spec.context}`);
  }

  // Output Format
  sections.push(`## EXPECTED OUTPUT\nFormat: ${spec.outputFormat.type}`);
  if (spec.outputFormat.schema) {
    sections.push(`Schema:\n\`\`\`\n${spec.outputFormat.schema}\n\`\`\``);
  }
  if (spec.outputFormat.example) {
    sections.push(`Example:\n\`\`\`\n${spec.outputFormat.example}\n\`\`\``);
  }

  // Tool Guidance
  if (spec.toolGuidance.recommended.length > 0) {
    sections.push(`## RECOMMENDED TOOLS\n${spec.toolGuidance.recommended.map(t => `- ${t}`).join('\n')}`);
  }
  if (spec.toolGuidance.avoid && spec.toolGuidance.avoid.length > 0) {
    sections.push(`## TOOLS TO AVOID\n${spec.toolGuidance.avoid.map(a => `- ${a.tool}: ${a.reason}`).join('\n')}`);
  }
  if (spec.toolGuidance.sources && spec.toolGuidance.sources.length > 0) {
    sections.push(`## KEY SOURCES\n${spec.toolGuidance.sources.map(s => `- ${s}`).join('\n')}`);
  }

  // Boundaries
  sections.push(`## SCOPE`);
  sections.push(`In scope:\n${spec.boundaries.inScope.map(s => `- ${s}`).join('\n')}`);
  sections.push(`Out of scope:\n${spec.boundaries.outOfScope.map(s => `- ${s}`).join('\n')}`);
  if (spec.boundaries.maxExplorationDepth) {
    sections.push(`Exploration depth: ${spec.boundaries.maxExplorationDepth}`);
  }

  // Success Criteria
  sections.push(`## SUCCESS CRITERIA\n${spec.successCriteria.map((c, i) => `${i + 1}. ${c}`).join('\n')}`);

  // Sibling Context
  if (spec.siblingContext) {
    sections.push(`## SIBLING AGENTS (avoid duplicate work)`);
    for (const sibling of spec.siblingContext.siblingTasks) {
      sections.push(`- ${sibling.agent}: ${sibling.task}`);
    }
    if (spec.siblingContext.claimedFiles && spec.siblingContext.claimedFiles.length > 0) {
      sections.push(`\nClaimed files (DO NOT modify):\n${spec.siblingContext.claimedFiles.map(f => `- ${f}`).join('\n')}`);
    }
  }

  return sections.join('\n\n');
}

/**
 * Create a minimal DelegationSpec from a task string.
 * Used as a fallback when the orchestrator doesn't provide a full spec.
 */
export function createMinimalDelegationSpec(
  task: string,
  agentType?: string,
): DelegationSpec {
  return {
    objective: task,
    context: '',
    outputFormat: { type: 'free_text' },
    toolGuidance: {
      recommended: getDefaultToolsForAgent(agentType),
    },
    boundaries: {
      inScope: [task],
      outOfScope: ['Changes outside the immediate task scope'],
    },
    successCriteria: ['Task objective is fully addressed'],
  };
}

/**
 * Get default recommended tools based on agent type.
 */
function getDefaultToolsForAgent(agentType?: string): string[] {
  switch (agentType) {
    case 'researcher':
      return ['read_file', 'glob', 'grep', 'list_files'];
    case 'coder':
      return ['read_file', 'write_file', 'edit_file', 'bash', 'glob', 'grep'];
    case 'reviewer':
      return ['read_file', 'glob', 'grep'];
    case 'architect':
      return ['read_file', 'glob', 'grep', 'list_files'];
    case 'debugger':
      return ['read_file', 'bash', 'glob', 'grep', 'edit_file'];
    default:
      return ['read_file', 'glob', 'grep'];
  }
}

/**
 * Delegation protocol instructions for the orchestrator's system prompt.
 * Teaches the lead agent HOW to delegate effectively.
 */
export const DELEGATION_INSTRUCTIONS = `
## Delegation Protocol

When using spawn_agent, provide structured delegation:

1. **OBJECTIVE**: One clear sentence of what the agent must accomplish
2. **CONTEXT**: Why this matters and how it fits the bigger picture
3. **OUTPUT FORMAT**: What the result should look like (JSON/markdown/code)
4. **TOOLS**: Which tools to use and which to avoid
5. **BOUNDARIES**: What is in-scope vs out-of-scope
6. **SUCCESS CRITERIA**: How to know when done

Include a delegationSpec in the spawn_agent call for best results.
When spawning multiple agents, describe what siblings are working on
to prevent duplicate effort.
`;
