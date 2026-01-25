/**
 * Session Resume Picker
 *
 * Displays recent sessions and allows user to select one to resume.
 * Works with both SQLite and JSONL session stores.
 */

import type { SessionMetadata } from './integrations/session-store.js';

// =============================================================================
// RAW INPUT HELPER
// =============================================================================

/**
 * Read a line from stdin without using readline.
 * Uses raw mode and removes ALL existing stdin listeners to prevent
 * double-echo issues from other parts of the application.
 */
async function readLineRaw(prompt: string, debug = false): Promise<string> {
  const stdin = process.stdin;
  const stdout = process.stdout;

  // Save and remove ALL existing stdin listeners
  const savedListeners = {
    data: stdin.rawListeners('data') as Function[],
    readable: stdin.rawListeners('readable') as Function[],
    keypress: stdin.rawListeners('keypress') as Function[],
  };

  if (debug) {
    console.error(`[DEBUG] stdin listeners before: data=${savedListeners.data.length}, readable=${savedListeners.readable.length}, keypress=${savedListeners.keypress.length}`);
  }

  stdin.removeAllListeners('data');
  stdin.removeAllListeners('readable');
  stdin.removeAllListeners('keypress');

  // Save current state
  const wasRaw = stdin.isRaw ?? false;
  const wasPaused = stdin.isPaused?.() ?? true;

  if (debug) {
    console.error(`[DEBUG] stdin state before: isRaw=${wasRaw}, isPaused=${wasPaused}, isTTY=${stdin.isTTY}`);
  }

  // Configure stdin for raw character input
  if (stdin.isTTY && typeof stdin.setRawMode === 'function') {
    stdin.setRawMode(true);
    if (debug) {
      console.error(`[DEBUG] setRawMode(true) called, isRaw now=${stdin.isRaw}`);
    }
  }
  stdin.resume();
  stdin.setEncoding('utf8');

  // Write prompt
  stdout.write(prompt);

  return new Promise((resolve) => {
    let buffer = '';

    const onData = (chunk: string | Buffer) => {
      const chars = typeof chunk === 'string' ? chunk : chunk.toString('utf8');

      for (const c of chars) {
        if (c === '\r' || c === '\n') {
          // Enter pressed - done
          stdout.write('\n');
          cleanup();
          resolve(buffer);
          return;
        } else if (c === '\x03') {
          // Ctrl+C
          cleanup();
          process.exit(0);
        } else if (c === '\x7f' || c === '\b') {
          // Backspace
          if (buffer.length > 0) {
            buffer = buffer.slice(0, -1);
            stdout.write('\b \b'); // Erase character
          }
        } else if (c >= ' ' && c <= '~') {
          // Printable ASCII character
          buffer += c;
          stdout.write(c); // Echo the character
        }
      }
    };

    const cleanup = () => {
      stdin.removeListener('data', onData);

      // Restore raw mode state
      if (stdin.isTTY && typeof stdin.setRawMode === 'function') {
        stdin.setRawMode(wasRaw);
      }

      // Restore paused state
      if (wasPaused) {
        stdin.pause();
      }

      // Restore all saved listeners
      savedListeners.data.forEach(l => stdin.on('data', l as any));
      savedListeners.readable.forEach(l => stdin.on('readable', l as any));
      savedListeners.keypress.forEach(l => stdin.on('keypress', l as any));
    };

    stdin.on('data', onData);
  });
}

// =============================================================================
// FORMATTING HELPERS
// =============================================================================

/**
 * Format a date as relative time (e.g., "2 hours ago", "yesterday").
 * Handles invalid/missing dates gracefully.
 */
function formatRelativeTime(dateStr: string | null | undefined): string {
  if (!dateStr) return 'unknown';

  const date = new Date(dateStr);

  // Check for invalid date
  if (isNaN(date.getTime())) {
    return 'unknown';
  }

  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays === 1) return 'yesterday';
  if (diffDays < 7) return `${diffDays}d ago`;

  // Format as date for older sessions
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

/**
 * Truncate string with ellipsis.
 */
function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen - 3) + '...';
}

/**
 * Format session ID for display (shorter form).
 */
function formatSessionId(id: string): string {
  // session-abc123def456 -> abc123de
  const match = id.match(/session-([a-z0-9]+)/);
  if (match) {
    return match[1].slice(0, 8);
  }
  return id.slice(0, 12);
}

/**
 * Get display name for session (summary > name > short ID).
 */
function getSessionDisplayName(session: SessionMetadata): string {
  // Prefer summary if available (first user message)
  if (session.summary) {
    return session.summary;
  }
  // Fall back to name
  if (session.name) {
    return session.name;
  }
  // Last resort: formatted ID
  return formatSessionId(session.id);
}

// =============================================================================
// SESSION PICKER
// =============================================================================

export interface SessionPickerOptions {
  maxSessions?: number;
  showCost?: boolean;
}

export interface SessionPickerResult {
  action: 'resume' | 'new' | 'cancel';
  sessionId?: string;
}

/**
 * Display sessions and let user pick one.
 */
export async function showSessionPicker(
  sessions: SessionMetadata[],
  options: SessionPickerOptions = {}
): Promise<SessionPickerResult> {
  const { maxSessions = 10 } = options;

  const recentSessions = sessions.slice(0, maxSessions);

  if (recentSessions.length === 0) {
    return { action: 'new' };
  }

  console.log('\n┌────────────────────────────────────────────────────────────────────┐');
  console.log('│                       Resume Session?                              │');
  console.log('├────────────────────────────────────────────────────────────────────┤');

  // Display sessions
  recentSessions.forEach((session, idx) => {
    const num = (idx + 1).toString().padStart(2, ' ');
    const name = truncate(getSessionDisplayName(session), 30).padEnd(30);
    const msgs = `${session.messageCount} msgs`.padEnd(10);
    const time = formatRelativeTime(session.lastActiveAt).padEnd(12);

    console.log(`│  ${num}) ${name} ${msgs} ${time} │`);
  });

  console.log('├────────────────────────────────────────────────────────────────────┤');
  console.log('│  n)  Start new session                                             │');
  console.log('│  q)  Quit                                                          │');
  console.log('└────────────────────────────────────────────────────────────────────┘');

  // Use raw input to avoid conflicts with other readline instances
  const answer = await readLineRaw('\nChoice: ');
  const trimmed = answer.trim().toLowerCase();

  if (trimmed === 'n' || trimmed === 'new') {
    return { action: 'new' };
  }

  if (trimmed === 'q' || trimmed === 'quit' || trimmed === 'exit') {
    return { action: 'cancel' };
  }

  const num = parseInt(trimmed, 10);
  if (num >= 1 && num <= recentSessions.length) {
    return {
      action: 'resume',
      sessionId: recentSessions[num - 1].id
    };
  }

  // Default to new session on invalid input
  console.log('Starting new session...');
  return { action: 'new' };
}

/**
 * Simple inline session picker (single line prompt).
 */
export async function showQuickPicker(
  sessions: SessionMetadata[]
): Promise<SessionPickerResult> {
  if (sessions.length === 0) {
    return { action: 'new' };
  }

  const mostRecent = sessions[0];
  const name = truncate(getSessionDisplayName(mostRecent), 40);
  const time = formatRelativeTime(mostRecent.lastActiveAt);

  console.log(`\nMost recent: "${name}" (${mostRecent.messageCount} msgs, ${time})`);

  // Use raw input to avoid conflicts with other readline instances
  // Enable debug logging to diagnose double character issue
  const answer = await readLineRaw('Resume? [Y/n/list]: ', true);
  const trimmed = answer.trim().toLowerCase();

  if (trimmed === '' || trimmed === 'y' || trimmed === 'yes') {
    return { action: 'resume', sessionId: mostRecent.id };
  }

  if (trimmed === 'n' || trimmed === 'no') {
    return { action: 'new' };
  }

  // For 'list', caller should show full picker
  return { action: 'cancel' }; // Signal to show full picker
}

/**
 * Format sessions for display (used by /sessions command).
 */
export function formatSessionsTable(
  sessions: SessionMetadata[],
  maxRows: number = 10
): string {
  if (sessions.length === 0) {
    return 'No saved sessions.';
  }

  const rows = sessions.slice(0, maxRows);
  const lines: string[] = [];

  lines.push('┌────┬────────────────────────────────┬──────────┬────────────┐');
  lines.push('│ #  │ Session                        │ Messages │ Last Active│');
  lines.push('├────┼────────────────────────────────┼──────────┼────────────┤');

  rows.forEach((session, idx) => {
    const num = (idx + 1).toString().padStart(2, ' ');
    const name = truncate(getSessionDisplayName(session), 30).padEnd(30);
    const msgs = session.messageCount.toString().padStart(6) + '   ';
    const time = formatRelativeTime(session.lastActiveAt).padEnd(10);

    lines.push(`│ ${num} │ ${name} │ ${msgs} │ ${time} │`);
  });

  lines.push('└────┴────────────────────────────────┴──────────┴────────────┘');

  if (sessions.length > maxRows) {
    lines.push(`  ... and ${sessions.length - maxRows} more (use /load <id> to load specific session)`);
  }

  return lines.join('\n');
}
