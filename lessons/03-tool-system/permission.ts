/**
 * Lesson 3: Permission System
 * 
 * Controls what operations the agent can perform.
 */

import * as readline from 'node:readline';
import type { 
  PermissionChecker, 
  PermissionRequest, 
  PermissionResponse,
  PermissionMode,
  DangerLevel,
  DangerPattern
} from './types.js';
import { DANGEROUS_PATTERNS } from './types.js';

// =============================================================================
// PERMISSION CHECKER IMPLEMENTATIONS
// =============================================================================

/**
 * Strict permission checker - blocks dangerous operations.
 */
class StrictPermissionChecker implements PermissionChecker {
  async check(request: PermissionRequest): Promise<PermissionResponse> {
    if (request.dangerLevel === 'safe') {
      return { granted: true };
    }
    if (request.dangerLevel === 'moderate') {
      return { granted: true };
    }
    return { 
      granted: false, 
      reason: `Operation blocked in strict mode: ${request.operation}` 
    };
  }
}

/**
 * Interactive permission checker - prompts user for dangerous operations.
 */
class InteractivePermissionChecker implements PermissionChecker {
  private rememberedDecisions: Map<string, boolean> = new Map();

  async check(request: PermissionRequest): Promise<PermissionResponse> {
    // Safe operations always allowed
    if (request.dangerLevel === 'safe') {
      return { granted: true };
    }

    // Check if we have a remembered decision
    const key = `${request.tool}:${request.dangerLevel}`;
    if (this.rememberedDecisions.has(key)) {
      return { granted: this.rememberedDecisions.get(key)! };
    }

    // Prompt user
    const emoji = request.dangerLevel === 'critical' ? '🚨' : 
                  request.dangerLevel === 'dangerous' ? '⚠️' : '⚡';
    
    console.log(`\n${emoji} Permission required (${request.dangerLevel}):`);
    console.log(`   Tool: ${request.tool}`);
    console.log(`   Operation: ${request.operation}`);
    console.log(`   Target: ${request.target}`);
    
    const answer = await this.prompt('Allow? (y/n/always/never): ');
    
    let granted = false;
    let remember = false;

    switch (answer.toLowerCase()) {
      case 'y':
      case 'yes':
        granted = true;
        break;
      case 'always':
        granted = true;
        remember = true;
        break;
      case 'never':
        granted = false;
        remember = true;
        break;
      default:
        granted = false;
    }

    if (remember) {
      this.rememberedDecisions.set(key, granted);
    }

    return { granted, remember };
  }

  private prompt(question: string): Promise<string> {
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout,
    });

    return new Promise(resolve => {
      rl.question(question, answer => {
        rl.close();
        resolve(answer);
      });
    });
  }
}

/**
 * Auto-safe permission checker - auto-approves safe and moderate.
 */
class AutoSafePermissionChecker implements PermissionChecker {
  private interactive = new InteractivePermissionChecker();

  async check(request: PermissionRequest): Promise<PermissionResponse> {
    if (request.dangerLevel === 'safe' || request.dangerLevel === 'moderate') {
      return { granted: true };
    }
    return this.interactive.check(request);
  }
}

/**
 * YOLO permission checker - approves everything (testing only).
 */
class YoloPermissionChecker implements PermissionChecker {
  async check(_request: PermissionRequest): Promise<PermissionResponse> {
    return { granted: true };
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create a permission checker for the given mode.
 */
export function createPermissionChecker(mode?: PermissionMode): PermissionChecker {
  switch (mode) {
    case 'strict':
      return new StrictPermissionChecker();
    case 'interactive':
      return new InteractivePermissionChecker();
    case 'auto-safe':
      return new AutoSafePermissionChecker();
    case 'yolo':
      console.warn('⚠️  YOLO mode enabled - all operations will be auto-approved');
      return new YoloPermissionChecker();
    default:
      return new InteractivePermissionChecker();
  }
}

// =============================================================================
// DANGER CLASSIFICATION
// =============================================================================

/**
 * Classify the danger level of a bash command.
 */
export function classifyCommand(command: string): { level: DangerLevel; reasons: string[] } {
  const reasons: string[] = [];
  let maxLevel: DangerLevel = 'safe';

  const levelPriority: Record<DangerLevel, number> = {
    safe: 0,
    moderate: 1,
    dangerous: 2,
    critical: 3,
  };

  for (const pattern of DANGEROUS_PATTERNS) {
    if (pattern.pattern.test(command)) {
      reasons.push(pattern.description);
      if (levelPriority[pattern.level] > levelPriority[maxLevel]) {
        maxLevel = pattern.level;
      }
    }
  }

  return { level: maxLevel, reasons };
}

/**
 * Add a custom danger pattern.
 */
export function addDangerPattern(pattern: DangerPattern): void {
  DANGEROUS_PATTERNS.push(pattern);
}

/**
 * Check if a command matches any danger patterns.
 */
export function isDangerous(command: string): boolean {
  const { level } = classifyCommand(command);
  return level === 'dangerous' || level === 'critical';
}
