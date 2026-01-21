/**
 * Lesson 17: Multi-Agent Coordination
 *
 * This lesson demonstrates how multiple specialized agents
 * can work together to complete complex tasks.
 *
 * Key concepts:
 * 1. Agent roles and specialization
 * 2. Inter-agent communication
 * 3. Consensus protocols
 * 4. Task orchestration
 *
 * Run: npm run lesson:17
 */

import chalk from 'chalk';
import {
  CODER_ROLE,
  REVIEWER_ROLE,
  TESTER_ROLE,
  ARCHITECT_ROLE,
  DEV_TEAM_ROLES,
  createAgent,
  createAgentsFromRoles,
  formatRoleCapabilities,
} from './agent-roles.js';
import {
  createChannel,
  formatHistory,
  createTaskAssignment,
  createOpinion as createOpinionMessage,
} from './communication.js';
import {
  ConsensusEngine,
  createOpinion,
  formatDecision,
  analyzeDecision,
} from './consensus.js';
import {
  TeamOrchestrator,
  TeamBuilder,
  createTeamTask,
  createOrchestrator,
} from './orchestrator.js';
import type { Opinion, CoordinationEvent } from './types.js';

// =============================================================================
// DEMO SETUP
// =============================================================================

console.log(chalk.bold.cyan('╔════════════════════════════════════════════════════════════╗'));
console.log(chalk.bold.cyan('║        Lesson 17: Multi-Agent Coordination                 ║'));
console.log(chalk.bold.cyan('╚════════════════════════════════════════════════════════════╝'));
console.log();

// =============================================================================
// PART 1: WHY MULTI-AGENT?
// =============================================================================

console.log(chalk.bold.yellow('Part 1: Why Multi-Agent?'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nWhen multi-agent beats single-agent:'));
console.log(chalk.gray(`
  Single Agent:
  ┌─────────────────────────────────────────────────────────┐
  │  One agent tries to be an expert at everything          │
  │  - Writes code                                          │
  │  - Reviews its own code                                 │
  │  - Tests its own code                                   │
  │  Problem: Self-review bias, context switching overhead  │
  └─────────────────────────────────────────────────────────┘

  Multi-Agent Team:
  ┌─────────────────────────────────────────────────────────┐
  │  Specialized agents collaborate                         │
  │  Architect ──► Coder ──► Reviewer ──► Tester            │
  │                                                         │
  │  Benefits:                                              │
  │  • Fresh perspectives (no self-review bias)             │
  │  • Specialized prompts for each role                    │
  │  • Parallel execution possible                          │
  │  • Checks and balances                                  │
  └─────────────────────────────────────────────────────────┘
`));

console.log(chalk.white('Trade-offs:'));
console.log(chalk.gray('  + Better quality through specialization'));
console.log(chalk.gray('  + Catches mistakes through multiple perspectives'));
console.log(chalk.gray('  - Communication overhead'));
console.log(chalk.gray('  - Coordination complexity'));
console.log(chalk.gray('  - Higher resource usage'));

// =============================================================================
// PART 2: AGENT ROLES
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 2: Agent Roles'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.green('\nPredefined roles:'));

const roles = [CODER_ROLE, REVIEWER_ROLE, TESTER_ROLE, ARCHITECT_ROLE];
for (const role of roles) {
  console.log(chalk.white(`\n  ${role.name} (authority: ${role.authority})`));
  console.log(chalk.gray(`    "${role.description}"`));
  console.log(chalk.gray(`    Capabilities: ${role.capabilities.slice(0, 3).join(', ')}...`));
  console.log(chalk.gray(`    Tools: ${role.tools.join(', ')}`));
}

// =============================================================================
// PART 3: COMMUNICATION
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 3: Inter-Agent Communication'));
console.log(chalk.gray('─'.repeat(60)));

const channel = createChannel('demo-channel');

// Create some agents
const coder = createAgent(CODER_ROLE);
const reviewer = createAgent(REVIEWER_ROLE);

// Subscribe to messages
channel.subscribe((msg) => {
  console.log(chalk.gray(`    [${msg.type}] ${msg.from} → ${msg.to}: ${msg.content.slice(0, 40)}...`));
});

console.log(chalk.green('\nSimulating agent communication:'));

// Simulate communication
await channel.send(createTaskAssignment('orchestrator', coder.id, 'task-1', 'Implement login function'));
await channel.send(createOpinionMessage(coder.id, 'I suggest using JWT for authentication', 'It is more secure', 0.8));
await channel.send(createOpinionMessage(reviewer.id, 'JWT is good, but consider session tokens for simpler cases', 'Simpler to implement', 0.7));

console.log(chalk.white('\n  Message history:'));
console.log(chalk.gray('  ' + formatHistory(channel.messages, 5).split('\n').join('\n  ')));

// =============================================================================
// PART 4: CONSENSUS PROTOCOLS
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 4: Consensus Protocols'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nAvailable strategies:'));
console.log(chalk.gray(`
  Authority  - Highest authority agent decides
  Voting     - Majority vote wins
  Unanimous  - All must agree (or fail)
  Debate     - Discuss until agreement
  Weighted   - Votes weighted by confidence × authority
`));

// Create agents for consensus demo
const agents = createAgentsFromRoles([CODER_ROLE, REVIEWER_ROLE, TESTER_ROLE, ARCHITECT_ROLE]);

// Create conflicting opinions
const opinions: Opinion[] = [
  createOpinion(agents[0].id, 'Use React', 'Popular and well-supported', 0.7),
  createOpinion(agents[1].id, 'Use Vue', 'Simpler learning curve', 0.8),
  createOpinion(agents[2].id, 'Use React', 'Better testing ecosystem', 0.6),
  createOpinion(agents[3].id, 'Use React', 'Architecture considerations', 0.9),
];

console.log(chalk.green('\nReaching consensus on: "Which framework to use?"'));
console.log(chalk.gray('\n  Opinions:'));
for (const op of opinions) {
  const agent = agents.find((a) => a.id === op.agentId);
  console.log(chalk.gray(`    ${agent?.role.name}: "${op.position}" (${(op.confidence * 100).toFixed(0)}% confidence)`));
}

// Test different strategies
const strategies: Array<'authority' | 'voting' | 'weighted'> = ['authority', 'voting', 'weighted'];

for (const strategy of strategies) {
  const engine = new ConsensusEngine(strategy);
  const decision = await engine.decide(opinions, agents);

  console.log(chalk.white(`\n  ${strategy.toUpperCase()} strategy:`));
  console.log(chalk.gray(`    Decision: ${decision.decision}`));
  console.log(chalk.gray(`    Support: ${(decision.support * 100).toFixed(0)}%`));
  console.log(chalk.gray(`    Dissent: ${decision.dissent.length} agent(s)`));
}

// =============================================================================
// PART 5: TEAM ORCHESTRATION
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 5: Team Orchestration'));
console.log(chalk.gray('─'.repeat(60)));

// Build a team
const team = new TeamBuilder()
  .setName('Development Team')
  .addAgents(createAgentsFromRoles(DEV_TEAM_ROLES))
  .setConsensusStrategy('voting')
  .setParallelExecution(true)
  .build();

console.log(chalk.green(`\nCreated team: "${team.name}"`));
console.log(chalk.gray(`  Agents: ${team.agents.map((a) => a.role.name).join(', ')}`));
console.log(chalk.gray(`  Consensus: ${team.config.consensusStrategy}`));
console.log(chalk.gray(`  Parallel: ${team.config.parallelExecution}`));

// Create orchestrator
const orchestrator = createOrchestrator(team.config.consensusStrategy);

// Subscribe to events
orchestrator.on((event: CoordinationEvent) => {
  switch (event.type) {
    case 'task.assigned':
      console.log(chalk.blue(`    ▶ Task assigned to ${event.agentIds.length} agent(s)`));
      break;
    case 'task.started':
      console.log(chalk.blue(`    ▶ Task started`));
      break;
    case 'task.completed':
      console.log(chalk.green(`    ✓ Task completed: ${event.result.summary.slice(0, 50)}...`));
      break;
  }
});

// Create a task with subtasks
const task = createTeamTask('Implement user authentication', {
  requiredCapabilities: ['write_code', 'review_code', 'write_tests'],
  priority: 'high',
  subtasks: [
    'Design authentication flow',
    'Implement login endpoint',
    'Write unit tests',
    'Review implementation',
  ],
});

console.log(chalk.green(`\nExecuting task: "${task.description}"`));
console.log(chalk.gray(`  Subtasks: ${task.subtasks.length}`));

// Assign and execute
await orchestrator.assignTask(task, team);
const result = await orchestrator.coordinate(task, team);

console.log(chalk.white('\n  Task Result:'));
console.log(chalk.gray(`    Success: ${result.success ? chalk.green('Yes') : chalk.red('No')}`));
console.log(chalk.gray(`    Duration: ${result.durationMs.toFixed(0)}ms`));
console.log(chalk.gray(`    Agent contributions: ${result.agentResults.length}`));

// Show progress
const progress = orchestrator.getProgress(task);
console.log(chalk.white('\n  Final Progress:'));
console.log(chalk.gray(`    Completed: ${progress.subtasks.completed}/${progress.subtasks.total} subtasks`));
console.log(chalk.gray(`    Overall: ${progress.percentage}%`));

// =============================================================================
// PART 6: CONFLICT RESOLUTION
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 6: Conflict Resolution'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nWhen agents disagree:'));
console.log(chalk.gray(`
  1. Collect all opinions with reasoning
  2. Apply consensus strategy
  3. Generate decision with support level
  4. Document dissenting views
  5. Proceed with decision (or escalate if support too low)
`));

// Demonstrate conflict resolution
const conflictOpinions: Opinion[] = [
  createOpinion('agent-1', 'Use MongoDB', 'Better for flexible schemas', 0.75, ['Document-oriented', 'Scalable']),
  createOpinion('agent-2', 'Use PostgreSQL', 'Better for data integrity', 0.85, ['ACID compliance', 'Mature ecosystem']),
  createOpinion('agent-3', 'Use MongoDB', 'Faster development', 0.65),
];

console.log(chalk.green('\nResolving database choice conflict:'));

const decision = await orchestrator.resolveConflict(conflictOpinions, team);
const analysis = analyzeDecision(decision);

console.log(chalk.white('\n  Decision Analysis:'));
console.log(chalk.gray(`    Result: ${decision.decision}`));
console.log(chalk.gray(`    Consensus: ${analysis.consensus}`));
console.log(chalk.gray(`    Dissent level: ${analysis.dissentLevel}`));

if (analysis.recommendations.length > 0) {
  console.log(chalk.gray('    Recommendations:'));
  for (const rec of analysis.recommendations) {
    console.log(chalk.gray(`      • ${rec}`));
  }
}

// =============================================================================
// PART 7: COORDINATION PATTERNS
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 7: Coordination Patterns'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nCommon patterns:'));
console.log(chalk.gray(`
  Pipeline (Sequential):
  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
  │ Architect│───►│  Coder   │───►│ Reviewer │───►│  Tester  │
  └──────────┘    └──────────┘    └──────────┘    └──────────┘

  Parallel with Merge:
  ┌──────────┐
  │ Coder A  │───┐
  └──────────┘   │    ┌──────────┐
                 ├───►│ Reviewer │
  ┌──────────┐   │    └──────────┘
  │ Coder B  │───┘
  └──────────┘

  Hub and Spoke:
                  ┌──────────┐
              ┌───│  Coder   │
              │   └──────────┘
  ┌──────────┐│   ┌──────────┐
  │ Manager  │├───│ Reviewer │
  └──────────┘│   └──────────┘
              │   ┌──────────┐
              └───│  Tester  │
                  └──────────┘
`));

// =============================================================================
// SUMMARY
// =============================================================================

console.log();
console.log(chalk.bold.cyan('═'.repeat(60)));
console.log(chalk.bold.cyan('Summary'));
console.log(chalk.bold.cyan('═'.repeat(60)));
console.log();
console.log(chalk.white('What we learned:'));
console.log(chalk.gray('  1. Specialized roles improve quality'));
console.log(chalk.gray('  2. Communication channels enable collaboration'));
console.log(chalk.gray('  3. Consensus protocols handle disagreement'));
console.log(chalk.gray('  4. Orchestrators coordinate complex tasks'));
console.log(chalk.gray('  5. Different patterns suit different tasks'));
console.log();
console.log(chalk.white('Key components:'));
console.log(chalk.gray('  • AgentRole - Defines capabilities and authority'));
console.log(chalk.gray('  • CommunicationChannel - Message passing'));
console.log(chalk.gray('  • ConsensusEngine - Reaches agreement'));
console.log(chalk.gray('  • TeamOrchestrator - Coordinates execution'));
console.log();
console.log(chalk.bold.green('Next: Lesson 18 - ReAct Pattern'));
console.log(chalk.gray('Structured reasoning with explicit thought traces!'));
console.log();
