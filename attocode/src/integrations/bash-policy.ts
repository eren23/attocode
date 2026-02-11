/**
 * Unified bash policy classifier.
 *
 * Centralizes shell command safety decisions so sandbox/safety/mode checks
 * all use the same logic.
 */

export type BashMode = 'disabled' | 'read_only' | 'task_scoped' | 'full';
export type BashWriteProtection = 'off' | 'block_file_mutation';

export interface BashPolicyDecision {
  allowed: boolean;
  reason?: string;
  isWrite: boolean;
  category: 'disabled' | 'read' | 'write' | 'blocked';
}

const READ_ONLY_PATTERNS: RegExp[] = [
  /^\s*ls\b/,
  /^\s*cat\b/,
  /^\s*head\b/,
  /^\s*tail\b/,
  /^\s*wc\b/,
  /^\s*find\b/,
  /^\s*grep\b/,
  /^\s*rg\b/,
  /^\s*fd\b/,
  /^\s*tree\b/,
  /^\s*pwd\b/,
  /^\s*which\b/,
  /^\s*whoami\b/,
  /^\s*env\b/,
  /^\s*echo\b/,
  /^\s*git\s+(status|log|diff|show|branch|remote|rev-parse|describe|tag)\b/,
  /^\s*node\s+(--version|-v)\b/,
  /^\s*npm\s+(list|ls|view|info|show|outdated|audit|test|run\s+test)\b/,
  /^\s*python3?\s+(--version|-V)\b/,
  /^\s*du\b/,
  /^\s*df\b/,
  /^\s*file\b/,
  /^\s*stat\b/,
  /^\s*uname\b/,
  /^\s*date\b/,
  /^\s*uptime\b/,
  /^\s*type\b/,
  /^\s*less\b/,
  /^\s*more\b/,
  /^\s*diff\b/,
  /^\s*jq\b/,
  /^\s*sort\b/,
  /^\s*uniq\b/,
  /^\s*cut\b/,
  /^\s*tr\b/,
  /^\s*tsc\s+--noEmit\b/,
  /^\s*npx\s+tsc\s+--noEmit\b/,
  /^\s*vitest\b/,
  /^\s*jest\b/,
  /^\s*pytest\b/,
];

const WRITE_COMMAND_PATTERNS: RegExp[] = [
  /\brm\b/,
  /\bmv\b/,
  /\bcp\b/,
  /\bmkdir\b/,
  /\btouch\b/,
  /\bchmod\b/,
  /\bchown\b/,
  /\bsed\b.*\s-i\b/,
  /\bawk\b.*\s-i(\s|$)/,
  /\bperl\b.*\s-i\b/,
  /\bgit\s+(add|commit|push|pull|merge|rebase|reset|checkout)\b/,
  /\b(npm|yarn|pnpm)\s+(install|add|remove|uninstall)\b/i,
];

const FILE_MUTATION_PATTERNS: Array<{ pattern: RegExp; reason: string }> = [
  { pattern: /<<-?\s*['"]?[A-Za-z_][\w-]*/m, reason: 'heredoc (<<)' },
  { pattern: /(^|[^<])>>\s*(?!\/dev\/null)\S/m, reason: 'append redirect (>>)' },
  { pattern: /(^|[^>])>\s*(?!\/dev\/null)\S/m, reason: 'output redirect (>)' },
  { pattern: /\|\s*tee\b(?![^|;]*\/dev\/null)/m, reason: 'pipe to tee' },
  { pattern: /\bsed\b[^|;]*\s-i(\b|['"])/m, reason: 'in-place sed edit' },
  { pattern: /\bperl\b[^|;]*\s-i(\b|['"])/m, reason: 'in-place perl edit' },
  { pattern: /\bawk\b[^|;]*-i\s*(inplace|in_place)?/mi, reason: 'in-place awk edit' },
  { pattern: /-exec\b.*\b(rm|mv|cp|chmod|chown)\b/m, reason: 'find -exec mutation' },
  { pattern: /-delete\b/m, reason: 'find -delete' },
  { pattern: /\bxargs\b.*\b(rm|mv|cp|chmod|chown)\b/m, reason: 'xargs mutation' },
];

export function detectFileMutationViaBash(command: string): { detected: boolean; reason?: string } {
  for (const { pattern, reason } of FILE_MUTATION_PATTERNS) {
    if (pattern.test(command)) {
      return { detected: true, reason };
    }
  }
  return { detected: false };
}

export function isReadOnlyBashCommand(command: string): boolean {
  const trimmed = command.trim();
  if (!READ_ONLY_PATTERNS.some(p => p.test(trimmed))) {
    return false;
  }
  if (WRITE_COMMAND_PATTERNS.some(p => p.test(trimmed))) {
    return false;
  }
  return !detectFileMutationViaBash(trimmed).detected;
}

export function isWriteLikeBashCommand(command: string): boolean {
  const trimmed = command.trim();
  if (detectFileMutationViaBash(trimmed).detected) {
    return true;
  }
  return WRITE_COMMAND_PATTERNS.some(p => p.test(trimmed));
}

export function evaluateBashPolicy(
  command: string,
  mode: BashMode = 'full',
  writeProtection: BashWriteProtection = 'off',
): BashPolicyDecision {
  const mutation = detectFileMutationViaBash(command);
  const isWrite = isWriteLikeBashCommand(command);

  if (mode === 'disabled') {
    return {
      allowed: false,
      isWrite,
      category: 'disabled',
      reason: 'Bash is disabled by policy profile.',
    };
  }

  if (mode === 'read_only' && !isReadOnlyBashCommand(command)) {
    return {
      allowed: false,
      isWrite: true,
      category: 'blocked',
      reason: 'Only read-only bash commands are allowed by policy profile.',
    };
  }

  if (writeProtection === 'block_file_mutation' && mutation.detected) {
    return {
      allowed: false,
      isWrite: true,
      category: 'blocked',
      reason:
        `File creation/modification via bash is blocked (${mutation.reason}). ` +
        'Use write_file to create files and edit_file to modify them.',
    };
  }

  return {
    allowed: true,
    isWrite,
    category: isWrite ? 'write' : 'read',
  };
}
