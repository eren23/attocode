/**
 * Exercise 20: Sandbox Policy
 * Implement command validation with policies.
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

/**
 * TODO: Implement SandboxValidator
 */
export class SandboxValidator {
  constructor(private _policy: SandboxPolicy) {}

  validate(_command: string): ValidationResult {
    // TODO: Check against policy
    throw new Error('TODO: Implement validate');
  }

  isCommandAllowed(_command: string): boolean {
    throw new Error('TODO: Implement isCommandAllowed');
  }

  hasBlockedPattern(_command: string): string | null {
    throw new Error('TODO: Implement hasBlockedPattern');
  }
}

export const DEFAULT_POLICY: SandboxPolicy = {
  allowedCommands: ['node', 'npm', 'npx', 'git', 'ls', 'cat'],
  blockedPatterns: [/rm\s+-rf/, /sudo/, /curl.*\|.*sh/, /wget.*\|.*bash/],
  maxExecutionTime: 30000,
  allowNetwork: false,
};
