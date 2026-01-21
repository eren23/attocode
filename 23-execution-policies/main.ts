/**
 * Lesson 23: Execution Policies & Intent Classification - Demo
 *
 * This demo shows how to use execution policies to control
 * tool execution based on rules, conditions, and user intent.
 *
 * Run with: npx tsx 23-execution-policies/main.ts
 */

import {
  PolicyManager,
  createPolicyManager,
  createPermissiveManager,
  createRestrictiveManager,
} from './policy-manager.js';
import {
  IntentClassifier,
  createIntentClassifier,
} from './intent-classifier.js';
import {
  PolicyEvaluator,
  buildContext,
  createPolicyEvaluator,
} from './policy-evaluator.js';
import type {
  ToolCallInfo,
  Message,
  PolicyDecision,
  IntentClassification,
} from './types.js';
import { POLICY_PRESETS } from './types.js';

// =============================================================================
// DEMO UTILITIES
// =============================================================================

function printHeader(title: string): void {
  console.log('\n' + '='.repeat(60));
  console.log(title);
  console.log('='.repeat(60));
}

function printDecision(decision: PolicyDecision): void {
  const status = decision.allowed ? '\u2705 ALLOWED' : '\u274c BLOCKED';
  console.log(`  ${status}`);
  console.log(`  Policy: ${decision.policy}`);
  console.log(`  Reason: ${decision.reason}`);
  console.log(`  Risk: ${decision.riskLevel}`);
  if (decision.promptRequired) {
    console.log('  \u26a0\ufe0f Prompt required');
  }
  if (decision.intent) {
    console.log(`  Intent: ${decision.intent.type} (${(decision.intent.confidence * 100).toFixed(0)}%)`);
  }
  if (decision.suggestions && decision.suggestions.length > 0) {
    console.log('  Suggestions:');
    for (const s of decision.suggestions) {
      console.log(`    - ${s.description}`);
    }
  }
}

function printIntent(intent: IntentClassification): void {
  console.log(`  Type: ${intent.type}`);
  console.log(`  Confidence: ${(intent.confidence * 100).toFixed(0)}%`);
  if (intent.evidence.length > 0) {
    console.log('  Evidence:');
    for (const e of intent.evidence.slice(0, 3)) {
      const sign = e.weight >= 0 ? '+' : '';
      console.log(`    ${sign}${e.weight.toFixed(1)}: ${e.content}`);
    }
  }
}

// =============================================================================
// DEMO 1: BASIC POLICY MANAGEMENT
// =============================================================================

async function demoPolicyManager(): Promise<void> {
  printHeader('Demo 1: Basic Policy Management');

  // Create a policy manager with categorized tools
  const manager = createPolicyManager({
    defaultPolicy: 'prompt',
    readOnlyTools: ['read_file', 'list_files', 'search'],
    writeTools: ['write_file', 'create_file'],
    destructiveTools: ['delete_file', 'rm'],
    shellTools: ['bash'],
  });

  console.log('\nConfigured policies:');
  const policies = manager.getAllPolicies();
  for (const [tool, policy] of Object.entries(policies)) {
    console.log(`  ${tool}: ${policy.policy} (${policy.riskLevel})`);
  }

  // Quick checks
  console.log('\nQuick checks:');

  const readCall: ToolCallInfo = { name: 'read_file', args: { path: '/etc/hosts' } };
  const readResult = manager.quickCheck(readCall);
  console.log(`\n  read_file /etc/hosts:`);
  console.log(`    Allowed: ${readResult.allowed}`);
  console.log(`    Reason: ${readResult.reason}`);

  const deleteCall: ToolCallInfo = { name: 'delete_file', args: { path: '/important.txt' } };
  const deleteResult = manager.quickCheck(deleteCall);
  console.log(`\n  delete_file /important.txt:`);
  console.log(`    Allowed: ${deleteResult.allowed}`);
  console.log(`    Reason: ${deleteResult.reason}`);

  // Permission grants
  console.log('\nPermission grants:');

  const grant = manager.grantFromUser('write_file', 'user123', {
    allowedArgs: { path: '/tmp/allowed.txt' },
    maxUses: 3,
    reason: 'User approved temporary file write',
  });
  console.log(`  Created grant: ${grant.id}`);

  const writeCall: ToolCallInfo = {
    name: 'write_file',
    args: { path: '/tmp/allowed.txt', content: 'hello' },
  };
  const writeResult = manager.quickCheck(writeCall);
  console.log(`\n  write_file /tmp/allowed.txt (with grant):`);
  console.log(`    Allowed: ${writeResult.allowed}`);
  console.log(`    Reason: ${writeResult.reason}`);
}

// =============================================================================
// DEMO 2: CONDITIONAL POLICIES
// =============================================================================

async function demoConditionalPolicies(): Promise<void> {
  printHeader('Demo 2: Conditional Policies');

  const manager = new PolicyManager({
    defaultPolicy: 'prompt',
    toolPolicies: {
      bash: {
        policy: 'prompt',
        riskLevel: 'high',
        conditions: [
          // Allow safe read-only commands
          { argMatch: { command: /^ls\s/ }, policy: 'allow', reason: 'Safe list command' },
          { argMatch: { command: /^cat\s/ }, policy: 'allow', reason: 'Safe read command' },
          { argMatch: { command: /^pwd$/ }, policy: 'allow', reason: 'Safe pwd command' },
          // Forbid dangerous commands
          { argMatch: { command: /^rm\s/ }, policy: 'forbidden', reason: 'Dangerous delete' },
          { argMatch: { command: /sudo/ }, policy: 'forbidden', reason: 'Sudo not allowed' },
          { argMatch: { command: />\s*\/dev\// }, policy: 'forbidden', reason: 'Device write' },
        ],
      },
      read_file: {
        policy: 'allow',
        riskLevel: 'low',
        conditions: [
          // Block sensitive files
          { argMatch: { path: { contains: '.env' } }, policy: 'forbidden', reason: 'Env file' },
          { argMatch: { path: { pattern: '\\.key$' } }, policy: 'forbidden', reason: 'Key file' },
          { argMatch: { path: { startsWith: '/etc/shadow' } }, policy: 'forbidden', reason: 'Shadow' },
        ],
      },
    },
  });

  console.log('\nEvaluating bash commands:');

  const commands = [
    'ls -la /home',
    'cat README.md',
    'pwd',
    'rm -rf /',
    'sudo apt install foo',
    'echo hello > /dev/null',
  ];

  for (const cmd of commands) {
    const call: ToolCallInfo = { name: 'bash', args: { command: cmd } };
    const result = manager.quickCheck(call);
    const status = result.allowed ? '\u2705' : '\u274c';
    console.log(`  ${status} "${cmd}" - ${result.reason}`);
  }

  console.log('\nEvaluating file reads:');

  const paths = [
    '/home/user/code/app.ts',
    '/home/user/.env',
    '/root/.ssh/id_rsa.key',
    '/etc/shadow',
    '/etc/hosts',
  ];

  for (const path of paths) {
    const call: ToolCallInfo = { name: 'read_file', args: { path } };
    const result = manager.quickCheck(call);
    const status = result.allowed ? '\u2705' : '\u274c';
    console.log(`  ${status} "${path}" - ${result.reason}`);
  }
}

// =============================================================================
// DEMO 3: INTENT CLASSIFICATION
// =============================================================================

async function demoIntentClassification(): Promise<void> {
  printHeader('Demo 3: Intent Classification');

  const classifier = createIntentClassifier({
    deliberateThreshold: 0.7,
    accidentalThreshold: 0.3,
    contextWindow: 5,
  });

  // Scenario 1: User explicitly asks to read a file
  console.log('\nScenario 1: User explicitly asks to read a file');
  const conversation1: Message[] = [
    { role: 'user', content: 'Please read the contents of package.json' },
  ];
  const call1: ToolCallInfo = { name: 'read_file', args: { path: 'package.json' } };
  const intent1 = await classifier.classify(call1, conversation1);
  printIntent(intent1);

  // Scenario 2: Tool call seems unrelated to request
  console.log('\nScenario 2: Tool call unrelated to user request');
  const conversation2: Message[] = [
    { role: 'user', content: 'What is the weather like today?' },
  ];
  const call2: ToolCallInfo = { name: 'delete_file', args: { path: '/etc/passwd' } };
  const intent2 = await classifier.classify(call2, conversation2);
  printIntent(intent2);

  // Scenario 3: Inferred intent from multi-step task
  console.log('\nScenario 3: Inferred intent from context');
  const conversation3: Message[] = [
    { role: 'user', content: 'Help me update the version in package.json' },
    {
      role: 'assistant',
      content: 'I will read the file first to check the current version.',
      toolCalls: [{ name: 'read_file', args: { path: 'package.json' } }],
    },
    { role: 'tool', content: '{"version": "1.0.0"}', name: 'read_file' },
  ];
  const call3: ToolCallInfo = {
    name: 'write_file',
    args: { path: 'package.json', content: '{"version": "1.0.1"}' },
  };
  const intent3 = await classifier.classify(call3, conversation3);
  printIntent(intent3);

  // Scenario 4: User says NOT to do something
  console.log('\nScenario 4: User said NOT to do this');
  const conversation4: Message[] = [
    { role: 'user', content: 'Do not delete any files, just show me the list' },
  ];
  const call4: ToolCallInfo = { name: 'delete_file', args: { path: 'test.txt' } };
  const intent4 = await classifier.classify(call4, conversation4);
  printIntent(intent4);
}

// =============================================================================
// DEMO 4: FULL POLICY EVALUATION
// =============================================================================

async function demoFullEvaluation(): Promise<void> {
  printHeader('Demo 4: Full Policy Evaluation with Intent');

  const evaluator = createPolicyEvaluator({
    defaultPolicy: 'prompt',
    intentAware: true,
    intentThreshold: 0.75,
    auditLog: true,
  });

  // Configure some policies
  const pm = evaluator.getPolicyManager();
  pm.setToolPolicy('read_file', { ...POLICY_PRESETS.readOnly });
  pm.setToolPolicy('write_file', { ...POLICY_PRESETS.write });
  pm.setToolPolicy('delete_file', { ...POLICY_PRESETS.destructive });
  pm.setToolPolicy('bash', {
    ...POLICY_PRESETS.shell,
    conditions: [
      { argMatch: { command: /^ls/ }, policy: 'allow', reason: 'Safe list' },
    ],
  });

  // Subscribe to events
  evaluator.subscribe(event => {
    if (event.type === 'intent.classified') {
      console.log(`    [Event] Intent: ${event.intent.type} (${(event.intent.confidence * 100).toFixed(0)}%)`);
    }
  });

  // Test cases
  const testCases = [
    {
      name: 'User asks to read file (allowed)',
      conversation: [{ role: 'user' as const, content: 'Show me the README file' }],
      toolCall: { name: 'read_file', args: { path: 'README.md' } },
    },
    {
      name: 'Deliberate write request',
      conversation: [
        { role: 'user' as const, content: 'Create a new file called notes.txt with "Hello"' },
      ],
      toolCall: { name: 'write_file', args: { path: 'notes.txt', content: 'Hello' } },
    },
    {
      name: 'Suspicious delete (no user request)',
      conversation: [{ role: 'user' as const, content: 'What files are in this directory?' }],
      toolCall: { name: 'delete_file', args: { path: 'important.db' } },
    },
    {
      name: 'Safe bash command',
      conversation: [{ role: 'user' as const, content: 'List files in the current directory' }],
      toolCall: { name: 'bash', args: { command: 'ls -la' } },
    },
    {
      name: 'Unknown tool (default policy)',
      conversation: [{ role: 'user' as const, content: 'Send an email to admin' }],
      toolCall: { name: 'send_email', args: { to: 'admin@example.com' } },
    },
  ];

  for (const test of testCases) {
    console.log(`\n${test.name}:`);
    console.log(`  Tool: ${test.toolCall.name}`);
    console.log(`  User: "${test.conversation[0].content}"`);

    const context = buildContext()
      .toolCall(test.toolCall)
      .conversation(test.conversation)
      .interactiveSession('demo-user')
      .build();

    const decision = await evaluator.evaluate(test.toolCall, context);
    printDecision(decision);
  }

  // Show audit log
  console.log('\nAudit log entries:');
  const auditLog = evaluator.getAuditLog();
  for (const entry of auditLog.slice(-3)) {
    console.log(`  [${entry.timestamp.toISOString()}] ${entry.event}: ${entry.tool}`);
  }
}

// =============================================================================
// DEMO 5: PERMISSION WORKFLOW
// =============================================================================

async function demoPermissionWorkflow(): Promise<void> {
  printHeader('Demo 5: Permission Grant Workflow');

  const evaluator = createPolicyEvaluator({
    defaultPolicy: 'prompt',
    intentAware: true,
  });

  const pm = evaluator.getPolicyManager();
  pm.setToolPolicy('deploy', { policy: 'prompt', riskLevel: 'high' });

  const deployCall: ToolCallInfo = {
    name: 'deploy',
    args: { environment: 'production', version: '2.0.0' },
  };

  // First attempt - requires approval
  console.log('\nFirst attempt (no grant):');
  const context1 = buildContext()
    .toolCall(deployCall)
    .addMessage('user', 'Deploy version 2.0.0 to production')
    .interactiveSession('admin')
    .build();

  const decision1 = await evaluator.evaluate(deployCall, context1);
  printDecision(decision1);

  // Simulate user approval
  console.log('\n... User approves the deployment ...');
  const grant = pm.grantFromUser('deploy', 'admin', {
    allowedArgs: { environment: 'production' },
    maxUses: 1,
    expiresIn: 60000, // 1 minute
    reason: 'Admin approved production deployment',
  });
  console.log(`  Grant created: ${grant.id}`);
  console.log(`  Expires: ${grant.expiresAt?.toISOString()}`);
  console.log(`  Max uses: ${grant.maxUses}`);

  // Second attempt - has grant
  console.log('\nSecond attempt (with grant):');
  const context2 = buildContext()
    .toolCall(deployCall)
    .addMessage('user', 'Deploy version 2.0.0 to production')
    .interactiveSession('admin')
    .grants([grant])
    .build();

  const decision2 = await evaluator.evaluate(deployCall, context2);
  printDecision(decision2);

  // Use the grant
  if (decision2.usedGrant) {
    pm.useGrant(decision2.usedGrant.id);
    console.log('  Grant used');
  }

  // Third attempt - grant exhausted
  console.log('\nThird attempt (grant exhausted):');
  const decision3 = await evaluator.evaluate(deployCall, context2);
  printDecision(decision3);

  // Show active grants
  console.log('\nActive grants:');
  const activeGrants = pm.getActiveGrants();
  console.log(`  Count: ${activeGrants.length}`);
}

// =============================================================================
// MAIN
// =============================================================================

async function main(): Promise<void> {
  console.log('Lesson 23: Execution Policies & Intent Classification');
  console.log('=====================================================');
  console.log('This lesson demonstrates granular control over tool execution');
  console.log('using policies, conditions, and intent classification.\n');

  try {
    await demoPolicyManager();
    await demoConditionalPolicies();
    await demoIntentClassification();
    await demoFullEvaluation();
    await demoPermissionWorkflow();

    printHeader('Summary');
    console.log(`
Key takeaways:
1. Three-tier policies (allow/prompt/forbidden) provide granular control
2. Conditions can override base policies based on arguments or context
3. Intent classification helps distinguish deliberate vs accidental calls
4. Permission grants create temporary allowances with audit trails
5. The policy evaluator combines all systems for comprehensive decisions

Next: Lesson 24 covers advanced patterns like thread management,
checkpoints, and configuration-driven agents.
`);
  } catch (error) {
    console.error('Demo error:', error);
    process.exit(1);
  }
}

main();
