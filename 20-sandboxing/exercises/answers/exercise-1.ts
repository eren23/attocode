/**
 * Exercise 20: Sandbox Policy - REFERENCE SOLUTION
 */

export interface SandboxPolicy {
  allowedCommands: string[];
  blockedPatterns: RegExp[];
  maxExecutionTime: number;
  allowNetwork: boolean;
}

export interface ValidationResult {
  allowed: boolean;
  reason?: string;
}

export class SandboxValidator {
  constructor(private policy: SandboxPolicy) {}

  validate(command: string): ValidationResult {
    // Check blocked patterns first
    const blockedPattern = this.hasBlockedPattern(command);
    if (blockedPattern) {
      return { allowed: false, reason: `Blocked pattern: ${blockedPattern}` };
    }

    // Check if command is allowed
    if (!this.isCommandAllowed(command)) {
      return { allowed: false, reason: 'Command not in allowed list' };
    }

    return { allowed: true };
  }

  isCommandAllowed(command: string): boolean {
    const baseCommand = command.trim().split(/\s+/)[0];
    return this.policy.allowedCommands.some(allowed =>
      baseCommand === allowed || baseCommand.endsWith(`/${allowed}`)
    );
  }

  hasBlockedPattern(command: string): string | null {
    for (const pattern of this.policy.blockedPatterns) {
      if (pattern.test(command)) {
        return pattern.source;
      }
    }
    return null;
  }
}

export const DEFAULT_POLICY: SandboxPolicy = {
  allowedCommands: ['node', 'npm', 'npx', 'git', 'ls', 'cat'],
  blockedPatterns: [/rm\s+-rf/, /sudo/, /curl.*\|.*sh/, /wget.*\|.*bash/],
  maxExecutionTime: 30000,
  allowNetwork: false,
};
