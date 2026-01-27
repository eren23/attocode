/**
 * Lesson 5: Error Recovery Demo
 * 
 * Demonstrates retry strategies and circuit breakers.
 */

import chalk from 'chalk';
import { RetryManager, withRetry } from './retry.js';
import { CircuitBreaker, CircuitOpenError, getCircuitBreaker } from './circuit-breaker.js';
import { classifyError } from './classifier.js';
import type { RecoveryEvent, RetryConfig } from './types.js';

// =============================================================================
// SIMULATED FAILURES
// =============================================================================

/**
 * Simulate a flaky API that fails sometimes.
 */
function createFlakyAPI(failureRate: number, errorType: 'network' | 'rate_limit' | 'auth' = 'network') {
  let callCount = 0;

  return async function flakyAPI(): Promise<string> {
    callCount++;
    
    // Simulate network delay
    await sleep(100 + Math.random() * 200);

    if (Math.random() < failureRate) {
      switch (errorType) {
        case 'network':
          throw new Error('ECONNRESET: Connection reset');
        case 'rate_limit':
          throw new Error('429 Too Many Requests');
        case 'auth':
          throw new Error('401 Unauthorized: Invalid API key');
      }
    }

    return `Success on call #${callCount}`;
  };
}

/**
 * Event handler for logging.
 */
function createEventLogger(): (event: RecoveryEvent) => void {
  return (event: RecoveryEvent) => {
    switch (event.type) {
      case 'retry_start':
        console.log(chalk.yellow(`   ↻ Retry #${event.attempt} in ${event.delay}ms`));
        break;
      case 'retry_success':
        console.log(chalk.green(`   ✓ Success on attempt #${event.attempt}`));
        break;
      case 'retry_failed':
        console.log(chalk.red(`   ✗ Attempt #${event.attempt} failed: ${event.error.category}`));
        break;
      case 'retry_exhausted':
        console.log(chalk.red(`   ✗ All ${event.totalAttempts} attempts exhausted`));
        break;
      case 'circuit_opened':
        console.log(chalk.red(`   🔴 Circuit OPENED after ${event.failures} failures`));
        break;
      case 'circuit_half_opened':
        console.log(chalk.yellow(`   🟡 Circuit HALF-OPEN, testing...`));
        break;
      case 'circuit_closed':
        console.log(chalk.green(`   🟢 Circuit CLOSED, service recovered`));
        break;
      case 'circuit_rejected':
        console.log(chalk.red(`   🚫 Request rejected by circuit breaker`));
        break;
    }
  };
}

// =============================================================================
// DEMOS
// =============================================================================

async function demoRetryStrategies() {
  console.log(chalk.bold('\n📊 Demo: Retry Strategies\n'));
  
  const strategies: Array<{ name: string; config: Partial<RetryConfig> }> = [
    { name: 'Fixed delay (1s)', config: { strategy: 'fixed', baseDelay: 1000, jitter: false } },
    { name: 'Linear backoff', config: { strategy: 'linear', baseDelay: 500, jitter: false } },
    { name: 'Exponential backoff', config: { strategy: 'exponential', baseDelay: 500, jitter: false } },
    { name: 'Exponential with jitter', config: { strategy: 'exponential', baseDelay: 500, jitter: true } },
  ];

  for (const { name, config } of strategies) {
    console.log(chalk.cyan(`\n${name}:`));
    
    const manager = new RetryManager({ ...config, maxRetries: 4 });
    
    // Show calculated delays
    const delays: number[] = [];
    for (let i = 1; i <= 4; i++) {
      const delay = (manager as any).calculateDelay(i, { ...manager['config'], ...config });
      delays.push(Math.round(delay));
    }
    console.log(`   Delays: ${delays.map(d => `${d}ms`).join(' → ')}`);
  }
}

async function demoErrorClassification() {
  console.log(chalk.bold('\n🏷️  Demo: Error Classification\n'));

  const errors = [
    new Error('ECONNREFUSED: Connection refused'),
    new Error('429 Too Many Requests'),
    new Error('500 Internal Server Error'),
    new Error('401 Unauthorized'),
    new Error('Context length exceeded: maximum is 100000 tokens'),
    new Error('Something went wrong'),
  ];

  for (const error of errors) {
    const classified = classifyError(error);
    const icon = classified.recoverable ? '🔄' : '❌';
    console.log(
      `   ${icon} ${error.message.slice(0, 40).padEnd(42)} → ` +
      chalk.cyan(classified.category.padEnd(15)) +
      (classified.recoverable ? chalk.green('recoverable') : chalk.red('not recoverable'))
    );
  }
}

async function demoRetryManager() {
  console.log(chalk.bold('\n🔄 Demo: Retry Manager\n'));

  const manager = new RetryManager({
    maxRetries: 3,
    strategy: 'exponential',
    baseDelay: 500,
  });

  // Test 1: Eventual success
  console.log(chalk.cyan('Test 1: Flaky API (50% failure rate)'));
  const flakyAPI = createFlakyAPI(0.5);
  
  const result1 = await manager.execute(flakyAPI, {
    operation: 'flaky_test',
    onEvent: createEventLogger(),
  });
  
  console.log(`   Result: ${result1.success ? chalk.green('SUCCESS') : chalk.red('FAILED')}`);
  console.log(`   Attempts: ${result1.attempts.length}, Time: ${result1.totalTime}ms`);

  // Test 2: Unrecoverable error
  console.log(chalk.cyan('\nTest 2: Auth error (should not retry)'));
  const authAPI = createFlakyAPI(1.0, 'auth');
  
  const result2 = await manager.execute(authAPI, {
    operation: 'auth_test',
    onEvent: createEventLogger(),
  });
  
  console.log(`   Result: ${result2.success ? chalk.green('SUCCESS') : chalk.red('FAILED')}`);
  console.log(`   Attempts: ${result2.attempts.length} (stopped immediately - non-recoverable)`);
}

async function demoCircuitBreaker() {
  console.log(chalk.bold('\n⚡ Demo: Circuit Breaker\n'));

  const breaker = new CircuitBreaker({
    failureThreshold: 3,
    resetTimeout: 2000,
    successThreshold: 2,
  });

  breaker.onEvent(createEventLogger());

  // Simulate a failing service
  let shouldFail = true;
  const unreliableService = async () => {
    await sleep(50);
    if (shouldFail) {
      throw new Error('Service unavailable');
    }
    return 'OK';
  };

  console.log(chalk.cyan('Phase 1: Triggering failures to open circuit'));
  for (let i = 1; i <= 5; i++) {
    try {
      await breaker.execute(unreliableService);
      console.log(`   Request ${i}: Success`);
    } catch (error) {
      if (error instanceof CircuitOpenError) {
        console.log(`   Request ${i}: ${chalk.red('Circuit open, request rejected')}`);
      } else {
        console.log(`   Request ${i}: ${chalk.yellow('Failed')}`);
      }
    }
    await sleep(100);
  }

  console.log(chalk.cyan('\nPhase 2: Waiting for half-open state (2s)'));
  await sleep(2100);
  
  // Service recovers
  shouldFail = false;

  console.log(chalk.cyan('\nPhase 3: Testing recovery'));
  for (let i = 1; i <= 3; i++) {
    try {
      const result = await breaker.execute(unreliableService);
      console.log(`   Request ${i}: ${chalk.green(result)}`);
    } catch (error) {
      console.log(`   Request ${i}: ${chalk.red('Failed')}`);
    }
    await sleep(100);
  }

  // Show final state
  const state = breaker.getState();
  console.log(chalk.cyan('\nFinal state:'), state.state);
}

async function demoWithRetryDecorator() {
  console.log(chalk.bold('\n🎀 Demo: withRetry Decorator\n'));

  // Original function
  let callCount = 0;
  const fetchData = async (url: string): Promise<string> => {
    callCount++;
    if (callCount < 3) {
      throw new Error('ETIMEDOUT: Request timed out');
    }
    return `Data from ${url}`;
  };

  // Wrap with retry
  const reliableFetch = withRetry(fetchData, {
    maxRetries: 5,
    strategy: 'exponential',
    baseDelay: 100,
  });

  console.log(chalk.cyan('Calling wrapped function:'));
  try {
    const result = await reliableFetch('https://api.example.com/data');
    console.log(`   Result: ${chalk.green(result)}`);
    console.log(`   Total calls made: ${callCount}`);
  } catch (error) {
    console.log(`   Error: ${chalk.red((error as Error).message)}`);
  }
}

// =============================================================================
// MAIN
// =============================================================================

async function main() {
  console.log('╔════════════════════════════════════════════════════════════════╗');
  console.log('║  Lesson 5: Error Recovery                                      ║');
  console.log('╚════════════════════════════════════════════════════════════════╝');

  const demo = process.argv[2] || 'all';

  switch (demo) {
    case 'strategies':
      await demoRetryStrategies();
      break;
    case 'classify':
      await demoErrorClassification();
      break;
    case 'retry':
      await demoRetryManager();
      break;
    case 'circuit':
      await demoCircuitBreaker();
      break;
    case 'decorator':
      await demoWithRetryDecorator();
      break;
    case 'all':
    default:
      await demoErrorClassification();
      await demoRetryStrategies();
      await demoRetryManager();
      await demoCircuitBreaker();
      await demoWithRetryDecorator();
  }

  console.log('\n════════════════════════════════════════════════════════════════');
  console.log('\n📝 Key Concepts Demonstrated:');
  console.log('   1. Error classification by type and recoverability');
  console.log('   2. Multiple retry strategies (fixed, linear, exponential)');
  console.log('   3. Circuit breaker for cascading failure prevention');
  console.log('   4. Decorator pattern for easy retry wrapping');
  console.log('\nTry individual demos:');
  console.log('   npx tsx 05-error-recovery/main.ts classify');
  console.log('   npx tsx 05-error-recovery/main.ts strategies');
  console.log('   npx tsx 05-error-recovery/main.ts retry');
  console.log('   npx tsx 05-error-recovery/main.ts circuit');
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

main().catch(console.error);
