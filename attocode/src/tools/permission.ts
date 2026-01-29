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
// READ-ONLY COMMAND PATTERNS
// =============================================================================

/**
 * Patterns for read-only bash commands that can be auto-approved.
 * These commands only read data and don't modify the filesystem or system state.
 */
const READ_ONLY_COMMAND_PATTERNS: RegExp[] = [
  // File reading commands
  /^cat\s/,
  /^head\s/,
  /^tail\s/,
  /^less\s/,
  /^more\s/,

  // File listing and info
  /^ls\b/,
  /^stat\s/,
  /^file\s/,
  /^tree\b/,
  /^du\s/,
  /^df\b/,
  /^wc\s/,

  // File searching
  /^find\s/,
  /^grep\s/,
  /^rg\s/,        // ripgrep
  /^ag\s/,        // silver searcher
  /^ack\s/,
  /^fd\s/,        // fd-find

  // Text processing (read-only)
  /^diff\s/,
  /^cmp\s/,
  /^sort\s.*\|/,  // sort piped (not writing)
  /^uniq\s/,
  /^cut\s/,
  /^awk\s.*\|/,   // awk piped (not writing)

  // System info
  /^which\s/,
  /^type\s/,
  /^whereis\s/,
  /^pwd$/,
  /^whoami$/,
  /^id$/,
  /^env$/,
  /^printenv\b/,
  /^hostname$/,
  /^uname\b/,
  /^uptime$/,
  /^date$/,
  /^echo\s/,

  // Git read-only commands
  /^git\s+(status|log|diff|show|branch|remote|rev-parse|describe|tag\s+-l|ls-files|ls-tree)\b/,
  /^git\s+config\s+--get/,
  /^git\s+config\s+-l/,
  /^git\s+config\s+--list/,
  /^git\s+blame\s/,
  /^git\s+shortlog\b/,
  /^git\s+stash\s+list/,

  // npm read-only commands
  /^npm\s+(ls|list|view|show|info|outdated|audit|search|whoami|version)\b/,
  /^npm\s+config\s+(list|get)/,

  // yarn read-only
  /^yarn\s+(list|info|outdated|why|workspaces)\b/,

  // pnpm read-only
  /^pnpm\s+(list|ls|outdated|why)\b/,

  // Python read-only
  /^python3?\s+-c\s+["']print/,
  /^pip\s+(list|show|freeze|search)\b/,
  /^pip3\s+(list|show|freeze|search)\b/,

  // Node read-only
  /^node\s+-e\s+["']console\.log/,
  /^node\s+--version$/,
  /^npm\s+--version$/,

  // Process inspection
  /^ps\b/,
  /^top\s+-l\s+1/,  // one-shot top
  /^pgrep\s/,

  // Network inspection (read-only)
  /^ping\s+-c\s+\d/,  // limited ping
  /^host\s/,
  /^dig\s/,
  /^nslookup\s/,

  // Testing commands (generally safe)
  /^npm\s+test\b/,
  /^npm\s+run\s+test\b/,
  /^yarn\s+test\b/,
  /^pnpm\s+test\b/,
  /^jest\b/,
  /^vitest\b/,
  /^mocha\b/,
  /^pytest\b/,
  /^go\s+test\b/,
  /^cargo\s+test\b/,

  // Type checking (read-only)
  /^tsc\s+--noEmit/,
  /^tsc\s+-p\s+.*--noEmit/,
  /^npm\s+run\s+(typecheck|type-check|check-types)\b/,
  /^npx\s+tsc\s+--noEmit/,

  // Linting (read-only)
  /^eslint\b/,
  /^prettier\s+--check/,
  /^npm\s+run\s+lint\b/,

  // Build inspection
  /^make\s+-n/,  // dry-run
  /^cargo\s+check\b/,
];

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

/**
 * Classify bash command danger level dynamically.
 *
 * This function provides smarter classification than static danger levels:
 * 1. First checks for dangerous/critical patterns (rm -rf, sudo, etc.)
 * 2. Then checks if command matches read-only patterns (cat, ls, grep, etc.)
 * 3. Falls back to 'moderate' for unknown commands
 *
 * This allows read-only commands to be auto-approved while still requiring
 * confirmation for write operations.
 */
export function classifyBashCommandDangerLevel(command: string): DangerLevel {
  // Normalize command - trim and handle common prefixes
  const normalizedCommand = command.trim();

  // First, check dangerous patterns using existing classifyCommand
  const { level: dangerousLevel, reasons } = classifyCommand(normalizedCommand);

  // If we found any dangerous patterns, use that classification
  if (reasons.length > 0) {
    return dangerousLevel;
  }

  // Check if command matches read-only patterns
  for (const pattern of READ_ONLY_COMMAND_PATTERNS) {
    if (pattern.test(normalizedCommand)) {
      return 'safe';
    }
  }

  // Default to moderate for unknown commands
  // This ensures new/unknown commands still get reviewed
  return 'moderate';
}

// =============================================================================
// TUI PERMISSION CHECKER
// =============================================================================

import type { TUIApprovalBridge } from '../adapters.js';

/**
 * TUI Permission Checker
 *
 * Routes permission requests through the TUI approval dialog.
 * This replaces the console-based InteractivePermissionChecker when in TUI mode.
 *
 * Key behaviors:
 * - Safe operations: auto-approve
 * - Moderate/dangerous/critical: route to TUI dialog
 * - Safety fallback: block if bridge not connected
 */
export class TUIPermissionChecker implements PermissionChecker {
  constructor(private bridge: TUIApprovalBridge) {}

  async check(request: PermissionRequest): Promise<PermissionResponse> {
    // Safety fallback: block non-safe operations if bridge not connected
    if (!this.bridge.isConnected() && request.dangerLevel !== 'safe') {
      return {
        granted: false,
        reason: 'Approval system not ready - TUI not connected'
      };
    }

    // Safe operations always auto-approve
    if (request.dangerLevel === 'safe') {
      return { granted: true };
    }

    // Map danger level to risk level for the approval dialog
    const riskMap: Record<DangerLevel, 'low' | 'moderate' | 'high' | 'critical'> = {
      safe: 'low',
      moderate: 'moderate',
      dangerous: 'high',
      critical: 'critical',
    };

    // Route to TUI approval dialog
    const approvalResponse = await this.bridge.handler({
      id: `perm-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      action: request.operation,
      tool: request.tool,
      args: { target: request.target },
      risk: riskMap[request.dangerLevel],
      context: request.context || `Tool: ${request.tool}`,
    });

    return {
      granted: approvalResponse.approved,
      reason: approvalResponse.reason,
    };
  }
}
