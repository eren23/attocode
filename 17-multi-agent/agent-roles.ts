/**
 * Lesson 17: Agent Roles
 *
 * Predefined agent roles for common team configurations.
 * Each role has specific capabilities and responsibilities.
 */

import type { AgentRole, Agent } from './types.js';

// =============================================================================
// PREDEFINED ROLES
// =============================================================================

/**
 * Software developer role.
 */
export const CODER_ROLE: AgentRole = {
  name: 'Coder',
  description: 'Writes and modifies code based on requirements',
  capabilities: [
    'write_code',
    'refactor',
    'debug',
    'implement_features',
    'fix_bugs',
  ],
  systemPrompt: `You are a skilled software developer. Your responsibilities:
- Write clean, maintainable code
- Follow best practices and conventions
- Consider edge cases and error handling
- Write code that's easy for others to review

When writing code:
1. Start with a clear understanding of requirements
2. Consider the existing codebase structure
3. Write well-commented code where necessary
4. Handle errors gracefully`,
  tools: ['read_file', 'write_file', 'search', 'bash'],
  authority: 3,
  maxConcurrentTasks: 2,
};

/**
 * Code reviewer role.
 */
export const REVIEWER_ROLE: AgentRole = {
  name: 'Reviewer',
  description: 'Reviews code for quality, bugs, and best practices',
  capabilities: [
    'review_code',
    'identify_bugs',
    'suggest_improvements',
    'check_style',
    'verify_requirements',
  ],
  systemPrompt: `You are an experienced code reviewer. Your responsibilities:
- Identify bugs and potential issues
- Check for security vulnerabilities
- Verify code meets requirements
- Suggest improvements for readability and maintainability
- Ensure best practices are followed

Review approach:
1. Understand what the code should do
2. Check for logical errors
3. Look for edge cases not handled
4. Verify error handling
5. Assess code quality and style`,
  tools: ['read_file', 'search'],
  authority: 4,
  maxConcurrentTasks: 3,
};

/**
 * Tester role.
 */
export const TESTER_ROLE: AgentRole = {
  name: 'Tester',
  description: 'Writes and runs tests to verify functionality',
  capabilities: [
    'write_tests',
    'run_tests',
    'identify_test_cases',
    'verify_coverage',
    'report_issues',
  ],
  systemPrompt: `You are a quality assurance specialist. Your responsibilities:
- Write comprehensive test cases
- Cover edge cases and error conditions
- Verify expected behavior
- Report any failures clearly
- Ensure adequate test coverage

Testing approach:
1. Identify all test scenarios
2. Write unit tests for functions
3. Write integration tests for workflows
4. Test error handling paths
5. Document test results`,
  tools: ['read_file', 'write_file', 'bash'],
  authority: 3,
  maxConcurrentTasks: 2,
};

/**
 * Architect role.
 */
export const ARCHITECT_ROLE: AgentRole = {
  name: 'Architect',
  description: 'Designs system architecture and makes high-level decisions',
  capabilities: [
    'design_architecture',
    'evaluate_tradeoffs',
    'make_decisions',
    'review_design',
    'define_interfaces',
  ],
  systemPrompt: `You are a software architect. Your responsibilities:
- Design scalable and maintainable architectures
- Make high-level technical decisions
- Evaluate trade-offs between approaches
- Define interfaces between components
- Ensure consistency across the system

Design principles:
1. Keep it simple (KISS)
2. Separate concerns appropriately
3. Design for extensibility
4. Consider performance implications
5. Document key decisions`,
  tools: ['read_file', 'search'],
  authority: 5,
  maxConcurrentTasks: 1,
};

/**
 * Documentation writer role.
 */
export const DOCUMENTER_ROLE: AgentRole = {
  name: 'Documenter',
  description: 'Writes and maintains documentation',
  capabilities: [
    'write_documentation',
    'update_docs',
    'explain_code',
    'create_examples',
    'maintain_readme',
  ],
  systemPrompt: `You are a technical writer. Your responsibilities:
- Write clear, helpful documentation
- Create examples and tutorials
- Keep documentation up to date
- Explain complex concepts simply
- Ensure documentation is complete

Writing principles:
1. Write for the reader, not yourself
2. Include practical examples
3. Keep it concise but complete
4. Use consistent formatting
5. Update when code changes`,
  tools: ['read_file', 'write_file', 'search'],
  authority: 2,
  maxConcurrentTasks: 3,
};

/**
 * Project manager role.
 */
export const MANAGER_ROLE: AgentRole = {
  name: 'Manager',
  description: 'Coordinates team activities and tracks progress',
  capabilities: [
    'assign_tasks',
    'track_progress',
    'coordinate_team',
    'resolve_blockers',
    'communicate_status',
  ],
  systemPrompt: `You are a project manager. Your responsibilities:
- Break down tasks into manageable pieces
- Assign work to appropriate team members
- Track progress and identify blockers
- Facilitate communication between team members
- Ensure project stays on track

Management approach:
1. Understand project goals clearly
2. Create clear, actionable tasks
3. Match tasks to team capabilities
4. Monitor progress regularly
5. Address issues promptly`,
  tools: ['read_file'],
  authority: 4,
  maxConcurrentTasks: 5,
};

// =============================================================================
// ROLE COLLECTIONS
// =============================================================================

/**
 * All available roles.
 */
export const ALL_ROLES: AgentRole[] = [
  CODER_ROLE,
  REVIEWER_ROLE,
  TESTER_ROLE,
  ARCHITECT_ROLE,
  DOCUMENTER_ROLE,
  MANAGER_ROLE,
];

/**
 * Development team preset.
 */
export const DEV_TEAM_ROLES: AgentRole[] = [
  CODER_ROLE,
  REVIEWER_ROLE,
  TESTER_ROLE,
];

/**
 * Full project team preset.
 */
export const FULL_TEAM_ROLES: AgentRole[] = [
  ARCHITECT_ROLE,
  CODER_ROLE,
  REVIEWER_ROLE,
  TESTER_ROLE,
  DOCUMENTER_ROLE,
];

// =============================================================================
// AGENT FACTORY
// =============================================================================

let agentCounter = 0;

/**
 * Create an agent with a specific role.
 */
export function createAgent(role: AgentRole, id?: string): Agent {
  agentCounter++;

  return {
    id: id || `agent-${role.name.toLowerCase()}-${agentCounter}`,
    role,
    state: 'idle',
    memory: [],
  };
}

/**
 * Create a team of agents from roles.
 */
export function createAgentsFromRoles(roles: AgentRole[]): Agent[] {
  return roles.map((role) => createAgent(role));
}

/**
 * Find role by name.
 */
export function findRole(name: string): AgentRole | undefined {
  return ALL_ROLES.find(
    (r) => r.name.toLowerCase() === name.toLowerCase()
  );
}

/**
 * Find roles with a specific capability.
 */
export function findRolesWithCapability(capability: string): AgentRole[] {
  return ALL_ROLES.filter((r) => r.capabilities.includes(capability));
}

/**
 * Get the highest authority role from a list.
 */
export function getHighestAuthorityRole(roles: AgentRole[]): AgentRole | undefined {
  if (roles.length === 0) return undefined;
  return roles.reduce((highest, current) =>
    current.authority > highest.authority ? current : highest
  );
}

// =============================================================================
// ROLE UTILITIES
// =============================================================================

/**
 * Check if a role can perform a task.
 */
export function canPerform(role: AgentRole, capability: string): boolean {
  return role.capabilities.includes(capability);
}

/**
 * Get role capabilities as a formatted string.
 */
export function formatRoleCapabilities(role: AgentRole): string {
  return `${role.name}:\n  - ${role.capabilities.join('\n  - ')}`;
}

/**
 * Compare two roles by authority.
 */
export function compareAuthority(a: AgentRole, b: AgentRole): number {
  return b.authority - a.authority;
}
