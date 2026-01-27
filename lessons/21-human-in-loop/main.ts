/**
 * Lesson 21: Human-in-the-Loop Patterns
 *
 * This lesson demonstrates how to implement approval workflows,
 * escalation policies, audit logging, and rollback capabilities.
 *
 * Run: npm run lesson:21
 */

import chalk from 'chalk';
import {
  type ApprovalPolicy,
  type PendingAction,
  type ApprovalResult,
  type AuditEntry,
  generateId,
  DEFAULT_POLICY,
} from './types.js';
import {
  ApprovalQueue,
  ActionBuilder,
  assessRisk,
  matchesPattern,
} from './approval-workflow.js';
import {
  EscalationManager,
  EscalationRuleBuilder,
  COMMON_ESCALATION_RULES,
} from './escalation.js';
import {
  AuditLogger,
  AuditReportGenerator,
} from './audit-log.js';
import {
  RollbackManager,
  RollbackPlanBuilder,
} from './rollback.js';

// =============================================================================
// DEMO SETUP
// =============================================================================

console.log(chalk.bold.cyan('╔════════════════════════════════════════════════════════════╗'));
console.log(chalk.bold.cyan('║        Lesson 21: Human-in-the-Loop Patterns               ║'));
console.log(chalk.bold.cyan('╚════════════════════════════════════════════════════════════╝'));
console.log();

// =============================================================================
// PART 1: WHY HUMAN-IN-THE-LOOP?
// =============================================================================

console.log(chalk.bold.yellow('Part 1: Why Human-in-the-Loop?'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nAgents can make mistakes with serious consequences:'));
console.log(chalk.gray(`
  ┌─────────────────────────────────────────────────────────┐
  │  Without Human-in-the-Loop:                             │
  │                                                         │
  │  Agent: "Deleting /var/* to free up space..."           │
  │  User: 😱 (discovers 2 hours later)                     │
  │                                                         │
  │  With Human-in-the-Loop:                                │
  │                                                         │
  │  Agent: "Permission to delete /var/*?"                  │
  │  User: "NO! Delete temp files only"                     │
  │  Agent: "Permission to delete /tmp/*?"                  │
  │  User: ✓ Approved                                       │
  └─────────────────────────────────────────────────────────┘
`));

// =============================================================================
// PART 2: RISK ASSESSMENT
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 2: Risk Assessment'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.green('\nAssessing risk for different actions:'));

const testActions: Partial<PendingAction>[] = [
  {
    id: '1',
    type: 'file_write',
    description: 'Update config file',
    data: { type: 'file_write', path: '/app/config.json', content: '{}', overwrite: true },
    context: { sessionId: 's1', requestor: 'agent', reason: 'Update settings' },
    requestedAt: new Date(),
    status: 'pending',
  },
  {
    id: '2',
    type: 'file_delete',
    description: 'Delete temporary files',
    data: { type: 'file_delete', path: '/tmp/cache', recursive: true },
    context: { sessionId: 's1', requestor: 'agent', reason: 'Clean up' },
    requestedAt: new Date(),
    status: 'pending',
  },
  {
    id: '3',
    type: 'command_execute',
    description: 'Run backup script',
    data: { type: 'command_execute', command: 'sudo rm -rf /old_backup', args: [], cwd: '/' },
    context: { sessionId: 's1', requestor: 'agent', reason: 'Remove old backup' },
    requestedAt: new Date(),
    status: 'pending',
  },
  {
    id: '4',
    type: 'deployment',
    description: 'Deploy to production',
    data: { type: 'deployment', environment: 'production', version: '2.0', services: ['api'] },
    context: { sessionId: 's1', requestor: 'agent', reason: 'Release v2.0' },
    requestedAt: new Date(),
    status: 'pending',
  },
];

for (const action of testActions) {
  const pendingAction = action as PendingAction;
  pendingAction.risk = assessRisk(pendingAction);

  const levelColors: Record<string, (text: string) => string> = {
    none: chalk.green,
    low: chalk.blue,
    medium: chalk.yellow,
    high: chalk.red,
    critical: chalk.magenta,
  };

  const colorFn = levelColors[pendingAction.risk.level] || chalk.white;

  console.log(chalk.white(`\n  ${action.description}`));
  console.log(chalk.gray(`    Type: ${action.type}`));
  console.log(`    Risk: ${colorFn(`${pendingAction.risk.level.toUpperCase()} (score: ${pendingAction.risk.score})`)}`);
  console.log(chalk.gray(`    Recommendation: ${pendingAction.risk.recommendation}`));

  if (pendingAction.risk.factors.length > 0) {
    console.log(chalk.gray('    Factors:'));
    for (const factor of pendingAction.risk.factors) {
      console.log(chalk.gray(`      - ${factor.description}`));
    }
  }
}

// =============================================================================
// PART 3: APPROVAL WORKFLOW
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 3: Approval Workflow'));
console.log(chalk.gray('─'.repeat(60)));

const policy: ApprovalPolicy = {
  ...DEFAULT_POLICY,
  name: 'demo-policy',
  autoApproveThreshold: 'low',
  autoRejectThreshold: 'critical',
  allowPatterns: [
    { name: 'temp-files', actionType: 'file_delete', pathPattern: '/tmp/*' },
  ],
  requirePatterns: [
    { name: 'production-deployment', actionType: 'deployment' },
  ],
  blockPatterns: [
    { name: 'system-files', pathPattern: '/etc/*' },
  ],
};

const approvalQueue = new ApprovalQueue(policy);

// Listen for events
approvalQueue.on((event) => {
  switch (event.type) {
    case 'approval.requested':
      console.log(chalk.blue(`    📝 Approval requested: ${event.action.description}`));
      break;
    case 'policy.matched':
      console.log(chalk.gray(`    📋 Policy matched: ${event.pattern.name}`));
      break;
  }
});

console.log(chalk.green('\nProcessing actions through approval workflow:'));

for (const action of testActions) {
  const pendingAction = action as PendingAction;
  pendingAction.risk = assessRisk(pendingAction);

  console.log(chalk.white(`\n  Processing: ${action.description}`));

  const result = await approvalQueue.requestApproval({
    action: pendingAction,
    urgency: 'normal',
  });

  const statusColors: Record<string, (text: string) => string> = {
    auto_approved: chalk.green,
    auto_rejected: chalk.red,
    pending: chalk.yellow,
  };

  const colorFn = statusColors[result.status] || chalk.white;
  console.log(`    Status: ${colorFn(result.status)}`);
}

// Manually approve a pending action
const pending = approvalQueue.getPendingActions();
if (pending.length > 0) {
  console.log(chalk.yellow(`\n  ${pending.length} action(s) pending approval`));

  // Simulate human approval
  const toApprove = pending[0];
  console.log(chalk.white(`\n  Human reviews: "${toApprove.description}"`));

  await approvalQueue.processAction(toApprove.id, {
    decision: 'approved',
    decidedBy: 'human-reviewer',
    decidedAt: new Date(),
    reason: 'Reviewed and approved',
    conditions: ['Only in maintenance window'],
  });

  console.log(chalk.green(`    ✓ Approved by human-reviewer`));
}

// =============================================================================
// PART 4: ESCALATION
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 4: Escalation'));
console.log(chalk.gray('─'.repeat(60)));

const escalationManager = new EscalationManager([
  COMMON_ESCALATION_RULES.highRiskToSecurity,
  COMMON_ESCALATION_RULES.deploymentsToOps,
]);

// Add a custom rule
escalationManager.addRule(
  new EscalationRuleBuilder()
    .name('critical-actions')
    .whenRiskAtLeast('critical')
    .escalateTo('senior-engineer')
    .notifyConsole()
    .withPriority(5)
    .build()
);

escalationManager.on((event) => {
  if (event.type === 'approval.escalated') {
    console.log(chalk.red(`    📢 ESCALATED to ${event.escalateTo}`));
  }
});

console.log(chalk.green('\nChecking escalation rules:'));

for (const action of testActions) {
  const pendingAction = action as PendingAction;
  pendingAction.risk = assessRisk(pendingAction);

  const rule = escalationManager.shouldEscalate(pendingAction);

  console.log(chalk.white(`\n  ${action.description}`));
  if (rule) {
    console.log(chalk.yellow(`    Needs escalation: ${rule.name}`));
    console.log(chalk.gray(`    Escalate to: ${rule.escalateTo}`));

    // Actually escalate (will trigger notification)
    await escalationManager.escalate(pendingAction, rule);
  } else {
    console.log(chalk.gray('    No escalation needed'));
  }
}

// =============================================================================
// PART 5: AUDIT LOGGING
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 5: Audit Logging'));
console.log(chalk.gray('─'.repeat(60)));

const auditLogger = new AuditLogger();
const sessionId = `session-${generateId()}`;

// Log session start
await auditLogger.logSessionStart(sessionId, {
  type: 'human',
  id: 'user-123',
  name: 'Demo User',
});

console.log(chalk.green('\nLogging actions:'));

// Log some actions
const sampleAction = testActions[0] as PendingAction;
sampleAction.risk = assessRisk(sampleAction);

const requestEntry = await auditLogger.logActionRequested(sampleAction, {
  type: 'agent',
  id: 'demo-agent',
});
console.log(chalk.gray(`  Logged: action_requested (${requestEntry.id})`));

const approvalEntry = await auditLogger.logApprovalDecision(
  sampleAction,
  {
    decision: 'approved',
    decidedBy: 'human-reviewer',
    decidedAt: new Date(),
    reason: 'Looks good',
  },
  requestEntry.id
);
console.log(chalk.gray(`  Logged: action_approved (${approvalEntry.id})`));

const executeEntry = await auditLogger.logActionExecuted(
  sampleAction,
  { success: true, message: 'File updated', duration: 45 },
  { type: 'file_restore', path: '/app/config.json', originalContent: '{"old": true}' },
  approvalEntry.id
);
console.log(chalk.gray(`  Logged: action_executed (${executeEntry.id})`));

// Log session end
await auditLogger.logSessionEnd(
  sessionId,
  { type: 'human', id: 'user-123' },
  { actionsExecuted: 1, duration: 5000 }
);
console.log(chalk.gray('  Logged: session_ended'));

// Generate report
console.log(chalk.white('\n  Session Summary:'));
const summary = await AuditReportGenerator.sessionSummary(auditLogger, sessionId);
console.log(chalk.gray(summary.split('\n').map((l) => '  ' + l).join('\n')));

// =============================================================================
// PART 6: ROLLBACK
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 6: Rollback'));
console.log(chalk.gray('─'.repeat(60)));

const rollbackManager = new RollbackManager(auditLogger);

console.log(chalk.green('\nRollback capabilities:'));

// Check if we can rollback
console.log(chalk.white('\n  Checking rollback for executed action:'));
console.log(chalk.gray(`    Entry ID: ${executeEntry.id}`));
console.log(chalk.gray(`    Reversible: ${executeEntry.reversible}`));

if (rollbackManager.canRollback(executeEntry)) {
  // Get preview
  const preview = await rollbackManager.preview(executeEntry.id);
  if (preview) {
    console.log(chalk.gray(`    Rollback will: ${preview.description}`));
    console.log(chalk.gray(`    Affected: ${preview.affectedResources.join(', ')}`));
  }

  // Execute rollback
  console.log(chalk.yellow('\n  Executing rollback...'));

  const rollbackResult = await rollbackManager.rollback(
    {
      entryId: executeEntry.id,
      reason: 'Reverting for demo',
      requestedBy: 'user-123',
    },
    { type: 'human', id: 'user-123', name: 'Demo User' }
  );

  if (rollbackResult.success) {
    console.log(chalk.green(`    ✓ ${rollbackResult.message}`));
  } else {
    console.log(chalk.red(`    ✗ ${rollbackResult.message}`));
  }
}

// =============================================================================
// PART 7: BUILDING ROLLBACK PLANS
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 7: Building Rollback Plans'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.green('\nBuilding a complex rollback plan:'));

const rollbackPlan = new RollbackPlanBuilder()
  .fileRestore('/app/config.json', '{"version": 1}')
  .configRestore('app.version', '1.0.0')
  .commandUndo('git revert HEAD')
  .databaseRestore('UPDATE settings SET value = ? WHERE key = ?', ['old', 'version'])
  .build();

console.log(chalk.white(`\n  Rollback plan has ${rollbackPlan.totalSteps} steps:`));
for (let i = 0; i < rollbackPlan.steps.length; i++) {
  const step = rollbackPlan.steps[i];
  console.log(chalk.gray(`    ${i + 1}. ${step.type}`));
}

// =============================================================================
// PART 8: WORKFLOW INTEGRATION
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 8: Complete Workflow'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nComplete human-in-the-loop flow:'));
console.log(chalk.gray(`
  ┌─────────────────────────────────────────────────────────┐
  │  1. Agent proposes action                               │
  │              ▼                                          │
  │  2. Risk assessment evaluates danger                    │
  │              ▼                                          │
  │  3. Policy determines: auto-approve/reject/pending      │
  │              ▼                                          │
  │  4. If pending: queue for human approval                │
  │              ▼                                          │
  │  5. If timeout: escalate to higher authority            │
  │              ▼                                          │
  │  6. Human approves/rejects                              │
  │              ▼                                          │
  │  7. If approved: execute with rollback data             │
  │              ▼                                          │
  │  8. Audit log records everything                        │
  │              ▼                                          │
  │  9. If problems: rollback to previous state             │
  └─────────────────────────────────────────────────────────┘
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
console.log(chalk.gray('  1. Risk assessment evaluates action danger'));
console.log(chalk.gray('  2. Approval policies control auto-decisions'));
console.log(chalk.gray('  3. Queues manage pending approvals'));
console.log(chalk.gray('  4. Escalation handles timeouts and high-risk'));
console.log(chalk.gray('  5. Audit logs track everything'));
console.log(chalk.gray('  6. Rollback enables safe recovery'));
console.log();
console.log(chalk.white('Key components:'));
console.log(chalk.gray('  • RiskAssessment - Evaluates action danger'));
console.log(chalk.gray('  • ApprovalQueue - Manages pending approvals'));
console.log(chalk.gray('  • EscalationManager - Handles escalation rules'));
console.log(chalk.gray('  • AuditLogger - Records all activities'));
console.log(chalk.gray('  • RollbackManager - Enables undo operations'));
console.log();
console.log(chalk.bold.green('Next: Lesson 22 - Model Routing & Fallbacks'));
console.log(chalk.gray('Intelligent model selection and graceful degradation!'));
console.log();

// Cleanup
approvalQueue.destroy();
