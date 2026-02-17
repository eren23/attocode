/**
 * Unified Configuration Loader
 *
 * Single entry point for loading, merging, and validating configuration
 * from user-level (~/.config/attocode/config.json) and project-level
 * (.attocode/config.json) sources.
 */

import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { getConfigPath, getProjectDir } from '../paths.js';
import { UserConfigSchema, type ValidatedUserConfig } from './schema.js';

// =============================================================================
// TYPES
// =============================================================================

export interface ConfigLoadOptions {
  /** Working directory for locating project config (defaults to process.cwd()) */
  cwd?: string;
  /** Skip project-level config loading */
  skipProject?: boolean;
}

export interface ConfigLoadResult {
  /** Merged and validated config */
  config: ValidatedUserConfig;
  /** Sources that were checked */
  sources: Array<{ path: string; level: 'user' | 'project'; loaded: boolean }>;
  /** Non-fatal validation warnings */
  warnings: string[];
}

// =============================================================================
// DEEP MERGE
// =============================================================================

/**
 * Deep merge two config objects.
 * Same algorithm as defaults.ts:mergeConfig() — shallow spread with 1-level
 * nested object merge, arrays replace (not concat).
 */
function deepMergeConfigs(
  base: Record<string, unknown>,
  override: Record<string, unknown>,
): Record<string, unknown> {
  const result = { ...base };

  for (const [key, value] of Object.entries(override)) {
    const baseValue = result[key];

    if (
      typeof value === 'object' &&
      value !== null &&
      !Array.isArray(value) &&
      typeof baseValue === 'object' &&
      baseValue !== null &&
      !Array.isArray(baseValue)
    ) {
      // 1-level nested object merge
      result[key] = {
        ...(baseValue as Record<string, unknown>),
        ...(value as Record<string, unknown>),
      };
    } else {
      result[key] = value;
    }
  }

  return result;
}

// =============================================================================
// LOADER
// =============================================================================

/**
 * Load a JSON config file, returning the parsed object or null.
 * Collects parse errors as warnings.
 */
function loadJsonFile(filePath: string, warnings: string[]): Record<string, unknown> | null {
  if (!existsSync(filePath)) {
    return null;
  }

  try {
    const content = readFileSync(filePath, 'utf-8');
    const parsed = JSON.parse(content);

    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      warnings.push(
        `${filePath}: expected a JSON object, got ${Array.isArray(parsed) ? 'array' : typeof parsed}`,
      );
      return null;
    }

    return parsed as Record<string, unknown>;
  } catch (err) {
    warnings.push(`${filePath}: failed to parse JSON — ${(err as Error).message}`);
    return null;
  }
}

/**
 * Load configuration from user-level and project-level sources.
 *
 * Priority: user ← project (project overrides user).
 * Validates the merged result with Zod. Validation errors are collected
 * as warnings — the best-effort config is always returned.
 */
export function loadConfig(options: ConfigLoadOptions = {}): ConfigLoadResult {
  const { cwd, skipProject = false } = options;
  const warnings: string[] = [];
  const sources: ConfigLoadResult['sources'] = [];

  // 1. Load user-level config
  const userConfigPath = getConfigPath();
  const userRaw = loadJsonFile(userConfigPath, warnings);
  sources.push({ path: userConfigPath, level: 'user', loaded: userRaw !== null });

  // 2. Load project-level config
  let projectRaw: Record<string, unknown> | null = null;
  if (!skipProject) {
    const projectConfigPath = join(getProjectDir(cwd), 'config.json');
    projectRaw = loadJsonFile(projectConfigPath, warnings);
    sources.push({ path: projectConfigPath, level: 'project', loaded: projectRaw !== null });
  }

  // 3. Deep merge: user ← project
  let merged: Record<string, unknown> = {};
  if (userRaw) {
    merged = { ...userRaw };
  }
  if (projectRaw) {
    merged = deepMergeConfigs(merged, projectRaw);
  }

  // 4. Validate with Zod
  const result = UserConfigSchema.safeParse(merged);

  if (result.success) {
    return { config: result.data, sources, warnings };
  }

  // Collect validation issues as warnings but return best-effort config
  for (const issue of result.error.issues) {
    const path = issue.path.length > 0 ? issue.path.join('.') : '(root)';
    warnings.push(`config validation: ${path} — ${issue.message}`);
  }

  // Return the raw merged object cast through passthrough parsing
  // Since top-level uses passthrough(), most fields survive even on error
  return { config: merged as ValidatedUserConfig, sources, warnings };
}
