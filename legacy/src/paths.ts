/**
 * XDG Base Directory compliant paths for attocode.
 *
 * This module follows the XDG Base Directory Specification for storing
 * application files in appropriate locations:
 *
 * - Config: ~/.config/attocode/ (or $XDG_CONFIG_HOME/attocode/)
 *   User-specific configuration files
 *
 * - Data: ~/.local/share/attocode/ (or $XDG_DATA_HOME/attocode/)
 *   User-specific data files (databases, persistent storage)
 *
 * - State: ~/.local/state/attocode/ (or $XDG_STATE_HOME/attocode/)
 *   User-specific state files (history, logs, runtime state)
 *
 * - Cache: ~/.cache/attocode/ (or $XDG_CACHE_HOME/attocode/)
 *   User-specific non-essential cached data
 *
 * - Project: .attocode/
 *   Project-specific files in the current working directory
 *
 * @see https://specifications.freedesktop.org/basedir-spec/basedir-spec-latest.html
 */

import { homedir } from 'os';
import { join } from 'path';

/**
 * Get the configuration directory path.
 * Uses $XDG_CONFIG_HOME if set, otherwise defaults to ~/.config/attocode/
 *
 * @returns Absolute path to the configuration directory
 */
export function getConfigDir(): string {
  const xdg = process.env.XDG_CONFIG_HOME;
  return xdg ? join(xdg, 'attocode') : join(homedir(), '.config', 'attocode');
}

/**
 * Get the data directory path.
 * Uses $XDG_DATA_HOME if set, otherwise defaults to ~/.local/share/attocode/
 *
 * @returns Absolute path to the data directory
 */
export function getDataDir(): string {
  const xdg = process.env.XDG_DATA_HOME;
  return xdg ? join(xdg, 'attocode') : join(homedir(), '.local', 'share', 'attocode');
}

/**
 * Get the state directory path.
 * Uses $XDG_STATE_HOME if set, otherwise defaults to ~/.local/state/attocode/
 *
 * @returns Absolute path to the state directory
 */
export function getStateDir(): string {
  const xdg = process.env.XDG_STATE_HOME;
  return xdg ? join(xdg, 'attocode') : join(homedir(), '.local', 'state', 'attocode');
}

/**
 * Get the cache directory path.
 * Uses $XDG_CACHE_HOME if set, otherwise defaults to ~/.cache/attocode/
 *
 * @returns Absolute path to the cache directory
 */
export function getCacheDir(): string {
  const xdg = process.env.XDG_CACHE_HOME;
  return xdg ? join(xdg, 'attocode') : join(homedir(), '.cache', 'attocode');
}

/**
 * Get the project-specific directory path.
 * This is always .attocode/ within the specified working directory.
 *
 * @param cwd - The working directory (defaults to process.cwd())
 * @returns Absolute path to the project directory
 */
export function getProjectDir(cwd: string = process.cwd()): string {
  return join(cwd, '.attocode');
}

// ============================================================================
// Specific file paths
// ============================================================================

/**
 * Get the path to the main configuration file.
 *
 * @returns Absolute path to config.json
 */
export function getConfigPath(): string {
  return join(getConfigDir(), 'config.json');
}

/**
 * Get the path to the sessions database.
 *
 * @returns Absolute path to sessions.db
 */
export function getSessionsDbPath(): string {
  return join(getDataDir(), 'sessions.db');
}

/**
 * Get the path to the command history file.
 *
 * @returns Absolute path to history file
 */
export function getHistoryPath(): string {
  return join(getStateDir(), 'history');
}

/**
 * Get the path to the global rules file.
 *
 * @returns Absolute path to rules.md
 */
export function getGlobalRulesPath(): string {
  return join(getConfigDir(), 'rules.md');
}

/**
 * Get the hierarchical MCP config paths.
 * Returns paths in order of precedence (later overrides earlier):
 * 1. Global user config: ~/.config/attocode/mcp.json
 * 2. Workspace config: ./.mcp.json
 *
 * @param cwd - The working directory (defaults to process.cwd())
 * @returns Array of config paths to check (in order of precedence)
 */
export function getMCPConfigPaths(cwd: string = process.cwd()): string[] {
  return [
    join(getConfigDir(), 'mcp.json'), // Global user config
    join(cwd, '.mcp.json'), // Workspace-specific
  ];
}

// ============================================================================
// Directory management
// ============================================================================

/**
 * Ensure all XDG directories exist.
 * Creates config, data, state, and cache directories if they don't exist.
 *
 * @returns Promise that resolves when all directories are created
 */
export async function ensureDirectories(): Promise<void> {
  const { mkdir } = await import('fs/promises');
  await Promise.all([
    mkdir(getConfigDir(), { recursive: true }),
    mkdir(getDataDir(), { recursive: true }),
    mkdir(getStateDir(), { recursive: true }),
    mkdir(getCacheDir(), { recursive: true }),
  ]);
}
