/**
 * Command Handler Types
 *
 * Defines the interfaces for the unified command system that works
 * across both REPL and TUI modes.
 */

import type { ProductionAgent } from '../agent.js';
import type { MCPClient, Compactor, SQLiteStore, SessionStore } from '../integrations/index.js';
import type * as readline from 'node:readline/promises';

/**
 * Session store type that works with both SQLite and JSONL.
 */
export type AnySessionStore = SQLiteStore | SessionStore;

/**
 * Output abstraction for command handlers.
 * Allows the same command logic to work in both REPL (console) and TUI (React state) modes.
 */
export interface CommandOutput {
  /** Log a message (replaces console.log) */
  log(message: string): void;
  /** Log an error (replaces console.error) */
  error(message: string): void;
  /** Clear the screen/output */
  clear(): void;
}

/**
 * Context provided to command handlers.
 */
export interface CommandContext {
  /** The agent instance */
  agent: ProductionAgent;
  /** Current session ID */
  sessionId: string;
  /** Output abstraction (log, error, clear) */
  output: CommandOutput;
  /** Integration services */
  integrations: {
    sessionStore: AnySessionStore;
    mcpClient: MCPClient;
    compactor: Compactor;
  };
  /** Readline interface (only available in REPL mode, used for prompts) */
  rl?: readline.Interface;
  /** Request user confirmation (returns true if confirmed) */
  confirm?: (message: string) => Promise<boolean>;
}

/**
 * Command handler result.
 */
export type CommandResult = 'quit' | void;

/**
 * Command definition metadata.
 */
export interface CommandDefinition {
  /** Command name (with leading slash) */
  name: string;
  /** Command aliases */
  aliases?: string[];
  /** Brief description */
  description: string;
  /** Usage example */
  usage?: string;
  /** Category for help grouping */
  category: CommandCategory;
}

/**
 * Command categories for help organization.
 */
export type CommandCategory =
  | 'general'
  | 'modes'
  | 'plan'
  | 'sessions'
  | 'context'
  | 'checkpoints'
  | 'reasoning'
  | 'subagents'
  | 'mcp'
  | 'budget'
  | 'security'
  | 'debugging';
