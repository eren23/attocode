/**
 * Example Plugin: Security
 *
 * A plugin that blocks dangerous operations.
 * Demonstrates intercepting hooks that can prevent actions.
 *
 * USER CONTRIBUTION OPPORTUNITY:
 * The security patterns below are basic examples. You could implement
 * more sophisticated patterns like:
 * - Path traversal detection
 * - Command injection detection
 * - Rate limiting
 * - Permission-based access control
 */

import type { Plugin, PluginContext } from '../types.js';
import type { ToolBeforeEvent } from '../../10-hook-system/types.js';

/**
 * Dangerous command patterns to block.
 */
const DANGEROUS_PATTERNS = [
  { pattern: /\brm\s+-rf\s+\//, description: 'Recursive delete from root' },
  { pattern: /\bsudo\b/, description: 'Superuser command' },
  { pattern: /\bchmod\s+777\b/, description: 'World-writable permission' },
  { pattern: />\s*\/dev\//, description: 'Write to device' },
  { pattern: /\bdd\b.*of=\/dev\//, description: 'Direct disk write' },
  { pattern: /\bcurl\b.*\|\s*(ba)?sh/, description: 'Pipe URL to shell' },
  { pattern: /\bwget\b.*\|\s*(ba)?sh/, description: 'Pipe URL to shell' },
  { pattern: /\beval\b/, description: 'Eval command' },
  { pattern: /`.*`/, description: 'Command substitution' },
  { pattern: /\$\(.*\)/, description: 'Command substitution' },
];

/**
 * Sensitive file paths to protect.
 */
const PROTECTED_PATHS = [
  '/etc/passwd',
  '/etc/shadow',
  '/etc/sudoers',
  '~/.ssh/',
  '~/.aws/',
  '~/.config/',
  '.env',
  '.git/config',
];

export const securityPlugin: Plugin = {
  metadata: {
    name: 'security',
    version: '1.0.0',
    description: 'Blocks dangerous operations and protects sensitive files',
    author: 'First Principles Agent',
    tags: ['security', 'safety'],
  },

  async initialize(context: PluginContext) {
    context.log('info', 'Security plugin initializing...');

    // Track blocked operations
    let blockedCount = 0;

    // Get configuration
    const strictMode = context.getConfig<boolean>('strictMode', true);
    const customPatterns = context.getConfig<RegExp[]>('customPatterns', []);

    // All patterns to check
    const allPatterns = [
      ...DANGEROUS_PATTERNS,
      ...customPatterns.map((p) => ({ pattern: p, description: 'Custom pattern' })),
    ];

    // Register security hook with high priority (runs early)
    context.registerHook(
      'tool.before',
      (event: ToolBeforeEvent) => {
        // Check bash/shell commands
        if (['bash', 'shell', 'execute', 'run'].includes(event.tool.toLowerCase())) {
          const command = extractCommand(event.args);

          if (command) {
            // Check against dangerous patterns
            for (const { pattern, description } of allPatterns) {
              if (pattern.test(command)) {
                blockedCount++;
                context.log('warn', `BLOCKED: ${description}`);
                context.log('debug', `Command: ${command.slice(0, 100)}...`);

                // Prevent execution
                event.preventDefault = true;

                // Emit security event for other plugins
                context.emit('security.blocked', {
                  tool: event.tool,
                  reason: description,
                  command: command.slice(0, 100),
                });

                return;
              }
            }
          }
        }

        // Check file operations for protected paths
        if (['read_file', 'write_file', 'edit_file', 'delete_file'].includes(event.tool)) {
          const path = extractPath(event.args);

          if (path && isProtectedPath(path)) {
            blockedCount++;
            context.log('warn', `BLOCKED: Access to protected path: ${path}`);

            event.preventDefault = true;

            context.emit('security.blocked', {
              tool: event.tool,
              reason: 'Protected path',
              path,
            });

            return;
          }
        }

        // In strict mode, log all tool calls
        if (strictMode) {
          context.log('debug', `Allowed: ${event.tool}`);
        }
      },
      {
        priority: 5, // High priority - run early
        canModify: true, // Can prevent events
        description: 'Security check for dangerous operations',
      }
    );

    // Listen for other security-related events
    context.subscribe('security.alert', (data) => {
      context.log('error', `Security alert: ${JSON.stringify(data)}`);
    });

    // Store blocked count
    await context.store('blockedCount', blockedCount);

    context.log('info', `Security plugin initialized (strict mode: ${strictMode})`);
  },

  async cleanup() {
    console.log('[security] Cleanup complete');
  },
};

/**
 * Extract command from tool arguments.
 */
function extractCommand(args: unknown): string | null {
  if (typeof args === 'string') {
    return args;
  }

  if (args && typeof args === 'object') {
    const obj = args as Record<string, unknown>;
    return (
      (typeof obj.command === 'string' ? obj.command : null) ??
      (typeof obj.cmd === 'string' ? obj.cmd : null) ??
      (typeof obj.script === 'string' ? obj.script : null)
    );
  }

  return null;
}

/**
 * Extract path from tool arguments.
 */
function extractPath(args: unknown): string | null {
  if (typeof args === 'string') {
    return args;
  }

  if (args && typeof args === 'object') {
    const obj = args as Record<string, unknown>;
    return (
      (typeof obj.path === 'string' ? obj.path : null) ??
      (typeof obj.file === 'string' ? obj.file : null) ??
      (typeof obj.filename === 'string' ? obj.filename : null)
    );
  }

  return null;
}

/**
 * Check if a path is protected.
 */
function isProtectedPath(path: string): boolean {
  const normalizedPath = path.toLowerCase();

  for (const protected_ of PROTECTED_PATHS) {
    // Handle home directory expansion
    const normalizedProtected = protected_
      .replace(/^~/, process.env.HOME ?? '/home/user')
      .toLowerCase();

    if (
      normalizedPath === normalizedProtected ||
      normalizedPath.startsWith(normalizedProtected)
    ) {
      return true;
    }
  }

  return false;
}

export default securityPlugin;
