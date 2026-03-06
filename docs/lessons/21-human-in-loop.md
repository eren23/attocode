---
title: "Lesson 21: Human-in-the-Loop Patterns"
---

!!! info "Source Code"
    The runnable TypeScript source for this lesson is in
    [`lessons/21-human-in-loop/`](https://github.com/eren23/attocode/tree/main/lessons/21-human-in-loop/)

# Lesson 21: Human-in-the-Loop Patterns

> Approval workflows, escalation policies, audit trails, and rollback capabilities

## What You'll Learn

1. **Risk Assessment**: Evaluate action danger levels
2. **Approval Workflows**: Queue and process pending actions
3. **Escalation Policies**: Handle timeouts and high-risk scenarios
4. **Audit Logging**: Track all activities for compliance
5. **Rollback**: Safely undo executed actions

## Why This Matters

Agents can make mistakes with serious consequences:

```
Without Human-in-the-Loop:
  Agent: "Deleting /var/* to free up space..."
  User: (discovers 2 hours later)
  Result: Production database gone

With Human-in-the-Loop:
  Agent: "Permission to delete /var/*?"
  Risk: CRITICAL (system directory)
  Status: BLOCKED by policy

  Agent: "Permission to delete /tmp/cache?"
  Risk: LOW (temporary files)
  User: Approved
```

## Key Concepts

### Risk Levels

```typescript
type RiskLevel = 'none' | 'low' | 'medium' | 'high' | 'critical';

interface RiskAssessment {
  level: RiskLevel;
  score: number; // 0-100
  factors: RiskFactor[];
  recommendation: 'auto_approve' | 'require_approval' | 'block';
}
```

### Approval Flow

```
Action Proposed
      |
      v
+--------------+
| Assess Risk  |
+--------------+
      |
      v
+--------------+    Block     +----------------+
| Apply Policy | -----------> | Auto-Rejected  |
+--------------+              +----------------+
      |
      | Allow
      v
+--------------+    Low Risk  +----------------+
| Check Rules  | -----------> | Auto-Approved  |
+--------------+              +----------------+
      |
      | Requires Approval
      v
+--------------+
| Queue Pending |
+--------------+
      |
      v
+--------------+    Timeout   +----------------+
| Wait Human   | -----------> |   Escalate     |
+--------------+              +----------------+
      |
      | Decision
      v
+--------------+
|   Execute    | --> Audit Log --> Rollback Data
+--------------+
```

## Files in This Lesson

| File | Purpose |
|------|---------|
| `types.ts` | Core type definitions |
| `approval-workflow.ts` | Approval queue and policy |
| `escalation.ts` | Escalation rules and triggers |
| `audit-log.ts` | Action audit trail |
| `rollback.ts` | Undo capabilities |
| `main.ts` | Demonstration of all concepts |

## Running This Lesson

```bash
npm run lesson:21
```

## Code Examples

### Risk Assessment

```typescript
import { assessRisk, ActionBuilder } from './approval-workflow.js';

const action = new ActionBuilder()
  .ofType('file_delete', { path: '/tmp/cache', recursive: true })
  .describe('Delete temporary cache files')
  .withContext({
    sessionId: 'session-123',
    requestor: 'cleanup-agent',
    reason: 'Free disk space',
  })
  .build();

const risk = action.risk;
console.log(`Risk: ${risk.level} (score: ${risk.score})`);
console.log(`Recommendation: ${risk.recommendation}`);
```

### Approval Policy

```typescript
import { ApprovalQueue } from './approval-workflow.js';

const policy = {
  name: 'production-policy',
  autoApproveThreshold: 'low',
  autoRejectThreshold: 'critical',
  allowPatterns: [
    { name: 'temp-files', pathPattern: '/tmp/*' },
    { name: 'logs', pathPattern: '/var/log/*' },
  ],
  requirePatterns: [
    { name: 'deployments', actionType: 'deployment' },
    { name: 'database', actionType: 'database_modify' },
  ],
  blockPatterns: [
    { name: 'system', pathPattern: '/etc/*' },
    { name: 'root', pathPattern: '/root/*' },
  ],
  escalationRules: [],
  defaultTimeout: 300000, // 5 minutes
};

const queue = new ApprovalQueue(policy);

// Request approval
const pending = await queue.requestApproval({
  action,
  urgency: 'normal',
});

if (pending.status === 'pending') {
  console.log('Waiting for human approval...');
}
```

### Processing Approvals

```typescript
// Human approves
await queue.processAction(pending.id, {
  decision: 'approved',
  decidedBy: 'admin@example.com',
  decidedAt: new Date(),
  reason: 'Reviewed and approved',
  conditions: ['Only during maintenance window'],
});

// Or rejects
await queue.processAction(pending.id, {
  decision: 'rejected',
  decidedBy: 'admin@example.com',
  decidedAt: new Date(),
  reason: 'Too risky',
});
```

### Escalation Rules

```typescript
import { EscalationManager, EscalationRuleBuilder } from './escalation.js';

const escalation = new EscalationManager([
  // Escalate high-risk to security team
  new EscalationRuleBuilder()
    .name('high-risk-security')
    .whenRiskAtLeast('high')
    .escalateTo('security-team')
    .notifySlack('#security-alerts')
    .build(),

  // Escalate stale requests after 5 minutes
  new EscalationRuleBuilder()
    .name('stale-requests')
    .afterTimeout(5 * 60 * 1000)
    .escalateTo('manager')
    .notifyEmail('manager@example.com')
    .build(),
]);

// Check if action needs escalation
const rule = escalation.shouldEscalate(action);
if (rule) {
  await escalation.escalate(action, rule);
}
```

### Audit Logging

```typescript
import { AuditLogger, AuditReportGenerator } from './audit-log.js';

const audit = new AuditLogger();

// Log session
await audit.logSessionStart(sessionId, {
  type: 'human',
  id: 'user-123',
  name: 'John Doe',
});

// Log action flow
const requestEntry = await audit.logActionRequested(action, {
  type: 'agent',
  id: 'my-agent',
});

const approvalEntry = await audit.logApprovalDecision(action, result, requestEntry.id);

const executeEntry = await audit.logActionExecuted(
  action,
  { success: true, duration: 150 },
  { type: 'file_restore', path: '/app/config.json', originalContent: '...' },
  approvalEntry.id
);

// Generate reports
const summary = await AuditReportGenerator.sessionSummary(audit, sessionId);
const timeline = await AuditReportGenerator.timeline(audit, { sessionId });
```

### Rollback

```typescript
import { RollbackManager } from './rollback.js';

const rollback = new RollbackManager(audit);

// Check if rollback is possible
if (rollback.canRollback(executeEntry)) {
  // Preview what will happen
  const preview = await rollback.preview(executeEntry.id);
  console.log(`Rollback will: ${preview.description}`);
  console.log(`Affects: ${preview.affectedResources}`);

  // Execute rollback
  const result = await rollback.rollback(
    {
      entryId: executeEntry.id,
      reason: 'Reverting due to issue',
      requestedBy: 'user-123',
    },
    { type: 'human', id: 'user-123' }
  );

  if (result.success) {
    console.log('Rollback successful');
  }
}
```

## Risk Assessment Factors

| Factor | Weight | Description |
|--------|--------|-------------|
| file_deletion | 30 | Deleting files (recursive = higher) |
| system_command | 25 | Executing shell commands |
| database_modification | 20 | Modifying database records |
| deployment | 25 | Deploying to environments |
| user_data | 15 | Accessing user data |

## Rollback Types

| Type | Description |
|------|-------------|
| file_restore | Restore file content or delete created file |
| command_undo | Execute an undo command |
| database_restore | Execute restore SQL query |
| config_restore | Restore configuration value |
| custom | Custom rollback handler function |

## Best Practices

### 1. Start Restrictive, Then Loosen
```typescript
const policy = {
  autoApproveThreshold: 'none', // Start with manual approval
  autoRejectThreshold: 'high',   // Block high-risk immediately
};
```

### 2. Log Everything
```typescript
// Every action should be logged
await audit.logActionRequested(action, actor);
await audit.logApprovalDecision(action, result);
await audit.logActionExecuted(action, outcome, rollbackData);
```

### 3. Always Capture Rollback Data
```typescript
const executeEntry = await audit.logActionExecuted(
  action,
  outcome,
  {
    type: 'file_restore',
    path: filePath,
    originalContent: originalContent, // Capture before modification!
  }
);
```

### 4. Set Appropriate Timeouts
```typescript
// Critical actions: short timeout, quick escalation
const criticalAction = new ActionBuilder()
  .ofType('deployment', { environment: 'production', ... })
  .withTimeout(60000) // 1 minute
  .escalateTo('oncall-engineer')
  .build();
```

### 5. Use Meaningful Reasons
```typescript
await queue.processAction(actionId, {
  decision: 'approved',
  decidedBy: 'admin@example.com',
  reason: 'Reviewed changeset, verified no customer impact',
  conditions: ['Deploy after 10 PM EST'],
});
```

## Next Steps

In **Lesson 22: Model Routing & Fallbacks**, we'll learn:
- Intelligent model selection
- Cost optimization
- Fallback chains for reliability
