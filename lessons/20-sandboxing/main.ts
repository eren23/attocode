/**
 * Lesson 20: Sandboxing & Isolation
 *
 * This lesson demonstrates how to safely execute untrusted
 * code using sandboxes with resource limits and isolation.
 *
 * Run: npm run lesson:20
 */

import chalk from 'chalk';
import type { ExecutionCommand, SandboxConfig } from './types.js';
import {
  DEFAULT_SANDBOX_CONFIG,
  STRICT_SANDBOX_CONFIG,
  DEFAULT_RESOURCE_LIMITS,
  mergeConfig,
} from './types.js';
import { ProcessSandbox, createProcessSandbox } from './process-sandbox.js';
import { DockerSandbox, createDockerSandbox, SandboxImageBuilder } from './docker-sandbox.js';
import {
  ResourceMonitor,
  LimitEnforcer,
  OutputLimiter,
  ResourceEstimator,
  withTimeout,
  TimeoutError,
} from './resource-limits.js';

// =============================================================================
// DEMO SETUP
// =============================================================================

console.log(chalk.bold.cyan('╔════════════════════════════════════════════════════════════╗'));
console.log(chalk.bold.cyan('║        Lesson 20: Sandboxing & Isolation                   ║'));
console.log(chalk.bold.cyan('╚════════════════════════════════════════════════════════════╝'));
console.log();

// =============================================================================
// PART 1: WHY SANDBOXING?
// =============================================================================

console.log(chalk.bold.yellow('Part 1: Why Sandboxing?'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nAgents executing code need protection:'));
console.log(chalk.gray(`
  ┌─────────────────────────────────────────────────────────┐
  │  Without Sandboxing:                                    │
  │                                                         │
  │  Agent: "Running user's code..."                        │
  │  Code: while(true) { fork(); }  // Fork bomb            │
  │  Result: 💥 System crash, all resources consumed        │
  │                                                         │
  │  With Sandboxing:                                       │
  │                                                         │
  │  Agent: "Running user's code in sandbox..."             │
  │  Code: while(true) { fork(); }                          │
  │  Sandbox: Process limit reached (10), killed            │
  │  Result: ✓ System safe, agent continues                 │
  └─────────────────────────────────────────────────────────┘
`));

// =============================================================================
// PART 2: ISOLATION LEVELS
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 2: Isolation Levels'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nIsolation levels from weakest to strongest:'));
console.log(chalk.gray(`
  Level      │ Protection │ Overhead │ Use Case
  ───────────┼────────────┼──────────┼────────────────────────
  none       │    ❌      │   None   │ Trusted code only
  process    │    ⚠️      │   Low    │ Basic scripts
  container  │    ✓       │   Medium │ Untrusted code
  vm         │    ✓✓      │   High   │ Maximum security
  wasm       │    ✓✓      │   Low    │ Browser/portable
`));

// =============================================================================
// PART 3: RESOURCE LIMITS
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 3: Resource Limits'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.green('\nDefault resource limits:'));
console.log(chalk.gray('─'.repeat(50)));

const limits = DEFAULT_RESOURCE_LIMITS;
console.log(chalk.gray(`  CPU Time:        ${limits.maxCpuSeconds} seconds`));
console.log(chalk.gray(`  Memory:          ${limits.maxMemoryMB} MB`));
console.log(chalk.gray(`  Disk:            ${limits.maxDiskMB} MB`));
console.log(chalk.gray(`  Timeout:         ${limits.timeoutMs / 1000} seconds`));
console.log(chalk.gray(`  Processes:       ${limits.maxProcesses}`));
console.log(chalk.gray(`  File Descriptors: ${limits.maxFileDescriptors}`));
console.log(chalk.gray(`  Output:          ${limits.maxOutputBytes / 1024} KB`));

// Show limit enforcer usage
const enforcer = new LimitEnforcer(limits);

console.log(chalk.green('\nUlimit flags for shell:'));
console.log(chalk.gray(`  ${enforcer.getUlimitFlags().join(' ')}`));

console.log(chalk.green('\nDocker resource flags:'));
console.log(chalk.gray(`  ${enforcer.getDockerFlags().join(' ')}`));

// =============================================================================
// PART 4: PROCESS SANDBOX
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 4: Process Sandbox'));
console.log(chalk.gray('─'.repeat(60)));

const processSandbox = createProcessSandbox({
  allowedReadPaths: ['/tmp', '/usr'],
  allowedWritePaths: ['/tmp'],
  workingDirectory: '/tmp',
  resourceLimits: {
    ...DEFAULT_RESOURCE_LIMITS,
    timeoutMs: 5000,
    maxOutputBytes: 4096,
  },
});

// Listen for events
processSandbox.on((event) => {
  switch (event.type) {
    case 'execution.started':
      console.log(chalk.blue(`    ▶ Started: ${event.command.command}`));
      break;
    case 'execution.completed':
      const icon = event.result.exitCode === 0 ? chalk.green('✓') : chalk.red('✗');
      console.log(`    ${icon} Completed (exit: ${event.result.exitCode}, ${event.result.durationMs}ms)`);
      break;
    case 'execution.killed':
      console.log(chalk.red(`    ⚠ Killed: ${event.reason}`));
      break;
    case 'security.violation':
      console.log(chalk.red(`    🚫 Security: ${event.violation}`));
      break;
  }
});

console.log(chalk.green('\nExecuting commands in process sandbox:'));

// Safe commands
const safeCommands: ExecutionCommand[] = [
  { command: 'echo', args: ['Hello from sandbox!'], stdin: '' },
  { command: 'date', args: [], stdin: '' },
  { command: 'ls', args: ['/tmp'], stdin: '' },
];

for (const cmd of safeCommands) {
  console.log(chalk.white(`\n  Command: ${cmd.command} ${cmd.args.join(' ')}`));
  const result = await processSandbox.execute(cmd);

  if (result.stdout) {
    console.log(chalk.gray(`    stdout: ${result.stdout.slice(0, 50)}...`));
  }
}

// Dangerous command (should be blocked or restricted)
console.log(chalk.white('\n  Attempting dangerous command:'));
const dangerousResult = await processSandbox.execute({
  command: 'rm',
  args: ['-rf', '/'],
  stdin: '',
});
console.log(chalk.gray(`    stderr: ${dangerousResult.stderr || '(command validated/blocked)'}`));

// Clean up
await processSandbox.cleanup();

// =============================================================================
// PART 5: DOCKER SANDBOX
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 5: Docker Sandbox'));
console.log(chalk.gray('─'.repeat(60)));

const dockerSandbox = createDockerSandbox({
  allowNetwork: false,
  resourceLimits: {
    ...DEFAULT_RESOURCE_LIMITS,
    maxMemoryMB: 64,
    maxCpuSeconds: 5,
  },
});

console.log(chalk.green('\nDocker sandbox provides stronger isolation:'));
console.log(chalk.gray(`  • Network: ${dockerSandbox.config.allowNetwork ? 'Enabled' : 'Disabled'}`));
console.log(chalk.gray(`  • Memory: ${dockerSandbox.config.resourceLimits.maxMemoryMB}MB`));
console.log(chalk.gray(`  • User: ${dockerSandbox.config.security.userId} (non-root)`));
console.log(chalk.gray(`  • Capabilities: ${dockerSandbox.config.security.dropCapabilities ? 'Dropped' : 'Kept'}`));

console.log(chalk.green('\nSimulating Docker execution:'));

const dockerResult = await dockerSandbox.execute({
  command: 'ls',
  args: ['-la'],
  stdin: '',
});

console.log(chalk.gray(`  Exit code: ${dockerResult.exitCode}`));
console.log(chalk.gray(`  Duration: ${dockerResult.durationMs}ms`));
console.log(chalk.gray(`  Memory: ${dockerResult.resourceUsage.peakMemoryMB}MB`));

// Clean up
await dockerSandbox.cleanup();

// =============================================================================
// PART 6: DOCKERFILE GENERATION
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 6: Sandbox Image Building'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.green('\nGenerating minimal Dockerfile:'));

const dockerfile = SandboxImageBuilder.generateDockerfile({
  baseImage: 'alpine:latest',
  packages: ['bash', 'python3'],
  user: 65534,
});

console.log(chalk.gray(dockerfile.split('\n').map((l) => '  ' + l).join('\n')));

// =============================================================================
// PART 7: OUTPUT LIMITING
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 7: Output Limiting'));
console.log(chalk.gray('─'.repeat(60)));

const outputLimiter = new OutputLimiter(100); // 100 bytes max

console.log(chalk.green('\nLimiting output to 100 bytes:'));

const testOutput = 'A'.repeat(150);
outputLimiter.append(testOutput);

console.log(chalk.gray(`  Input length: ${testOutput.length} bytes`));
console.log(chalk.gray(`  Output length: ${outputLimiter.getCurrentSize()} bytes`));
console.log(chalk.gray(`  Truncated: ${outputLimiter.wasTruncated()}`));

const limitedOutput = outputLimiter.getOutput();
console.log(chalk.gray(`  Result: "${limitedOutput.slice(0, 50)}..."`));

// =============================================================================
// PART 8: RESOURCE ESTIMATION
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 8: Resource Estimation'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.green('\nEstimating resources for different commands:'));

const commands = [
  'node index.js',
  'python train.py',
  'cargo build',
  'ls -la',
];

for (const cmd of commands) {
  const estimated = ResourceEstimator.getRecommendedLimits(cmd);
  console.log(chalk.white(`\n  ${cmd}`));
  console.log(chalk.gray(`    Memory: ${estimated.maxMemoryMB}MB`));
  console.log(chalk.gray(`    CPU: ${estimated.maxCpuSeconds}s`));
  console.log(chalk.gray(`    Timeout: ${estimated.timeoutMs! / 1000}s`));
}

// =============================================================================
// PART 9: TIMEOUT HANDLING
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 9: Timeout Handling'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.green('\nDemonstrating timeout wrapper:'));

try {
  // This will timeout
  await withTimeout(
    new Promise((resolve) => setTimeout(resolve, 5000)),
    100,
    () => console.log(chalk.yellow('  ⏱ Timeout callback triggered'))
  );
} catch (err) {
  if (err instanceof TimeoutError) {
    console.log(chalk.red(`  ✗ ${err.message}`));
  }
}

// This will succeed
const fastResult = await withTimeout(
  Promise.resolve('fast result'),
  1000
);
console.log(chalk.green(`  ✓ Fast operation completed: "${fastResult}"`));

// =============================================================================
// PART 10: CONFIGURATION COMPARISON
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 10: Configuration Comparison'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\n  Default vs Strict Configuration:'));
console.log(chalk.gray('─'.repeat(50)));

const configs: [string, SandboxConfig][] = [
  ['Default', DEFAULT_SANDBOX_CONFIG],
  ['Strict', STRICT_SANDBOX_CONFIG],
];

const attrs = [
  ['Isolation', (c: SandboxConfig) => c.isolationLevel],
  ['Network', (c: SandboxConfig) => c.allowNetwork ? 'Yes' : 'No'],
  ['Memory', (c: SandboxConfig) => `${c.resourceLimits.maxMemoryMB}MB`],
  ['CPU', (c: SandboxConfig) => `${c.resourceLimits.maxCpuSeconds}s`],
  ['Timeout', (c: SandboxConfig) => `${c.resourceLimits.timeoutMs / 1000}s`],
  ['Processes', (c: SandboxConfig) => String(c.resourceLimits.maxProcesses)],
  ['Read-only FS', (c: SandboxConfig) => c.security.readOnlyRootFilesystem ? 'Yes' : 'No'],
];

console.log(chalk.gray(`  ${'Attribute'.padEnd(15)} ${'Default'.padEnd(12)} ${'Strict'.padEnd(12)}`));
console.log(chalk.gray('  ' + '─'.repeat(39)));

for (const [name, getter] of attrs) {
  const defaultVal = getter(DEFAULT_SANDBOX_CONFIG);
  const strictVal = getter(STRICT_SANDBOX_CONFIG);
  console.log(chalk.gray(`  ${name.padEnd(15)} ${String(defaultVal).padEnd(12)} ${String(strictVal).padEnd(12)}`));
}

// =============================================================================
// SUMMARY
// =============================================================================

console.log();
console.log(chalk.bold.cyan('═'.repeat(60)));
console.log(chalk.bold.cyan('Summary'));
console.log(chalk.bold.cyan('═'.repeat(60)));
console.log();
console.log(chalk.white('What we learned:'));
console.log(chalk.gray('  1. Sandboxing protects against malicious/buggy code'));
console.log(chalk.gray('  2. Different isolation levels offer different trade-offs'));
console.log(chalk.gray('  3. Resource limits prevent resource exhaustion'));
console.log(chalk.gray('  4. Process sandboxing uses OS-level restrictions'));
console.log(chalk.gray('  5. Docker provides stronger container isolation'));
console.log(chalk.gray('  6. Output limiting prevents memory exhaustion'));
console.log(chalk.gray('  7. Timeouts prevent infinite loops'));
console.log();
console.log(chalk.white('Key components:'));
console.log(chalk.gray('  • ProcessSandbox - OS-level process isolation'));
console.log(chalk.gray('  • DockerSandbox - Container-based isolation'));
console.log(chalk.gray('  • ResourceMonitor - Tracks resource usage'));
console.log(chalk.gray('  • LimitEnforcer - Generates limit configurations'));
console.log(chalk.gray('  • OutputLimiter - Prevents output overflow'));
console.log();
console.log(chalk.bold.green('Next: Lesson 21 - Human-in-the-Loop Patterns'));
console.log(chalk.gray('Approval workflows and human oversight!'));
console.log();
