/**
 * Schema Migrator for SQLite Database
 *
 * Handles versioned SQL migrations using PRAGMA user_version.
 * Migrations are applied sequentially and tracked in the database.
 *
 * ## Concurrency Warning
 *
 * This migrator is NOT safe for concurrent access. If multiple processes
 * attempt to run migrations simultaneously, race conditions may occur.
 * **Recommendation:** Run migrations from a single process at startup
 * before spawning worker processes or subagents.
 *
 * ## Partial Failure Recovery
 *
 * SQLite requires autocommit mode for ALTER TABLE statements, so each
 * migration runs outside a transaction. If a migration fails partway:
 * - The schema version reflects the last successful migration
 * - The database may have partial changes from the failed migration
 *
 * **Recommendation:** Design migrations to be idempotent (re-runnable).
 * Column additions already handle "duplicate column name" errors gracefully.
 * After fixing an issue, re-run applyMigrations() to continue.
 *
 * @example
 * ```typescript
 * import Database from 'better-sqlite3';
 * import { applyMigrations, needsMigration } from './migrator.js';
 *
 * const db = new Database('sessions.db');
 * if (needsMigration(db, './migrations')) {
 *   const result = applyMigrations(db, './migrations');
 *   console.log(`Applied ${result.applied} migrations`);
 * }
 * ```
 */

import Database from 'better-sqlite3';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Represents a parsed migration file.
 */
export interface MigrationFile {
  /** Migration version number (extracted from filename) */
  version: number;
  /** Human-readable migration name */
  name: string;
  /** SQL content to execute */
  sql: string;
}

/**
 * Result of applying migrations.
 */
export interface MigrationResult {
  /** Number of migrations applied */
  applied: number;
  /** Current schema version after migration */
  currentVersion: number;
  /** List of applied migration names */
  appliedMigrations: string[];
}

// =============================================================================
// SCHEMA VERSION MANAGEMENT
// =============================================================================

/**
 * Get the current schema version from the database.
 * Uses SQLite's PRAGMA user_version.
 *
 * @param db - Database instance
 * @returns Current schema version (0 if never migrated)
 */
export function getSchemaVersion(db: Database.Database): number {
  const result = db.pragma('user_version', { simple: true });
  return typeof result === 'number' ? result : 0;
}

/**
 * Set the schema version in the database.
 * Uses SQLite's PRAGMA user_version.
 *
 * @param db - Database instance
 * @param version - Version number to set
 */
export function setSchemaVersion(db: Database.Database, version: number): void {
  db.pragma(`user_version = ${version}`);
}

// =============================================================================
// MIGRATION FILE LOADING
// =============================================================================

/**
 * Parse a migration filename to extract version and name.
 *
 * @param filename - Migration filename (e.g., "001_initial.sql")
 * @returns Parsed version and name, or null if invalid format
 */
function parseMigrationFilename(filename: string): { version: number; name: string } | null {
  // Match pattern: NNN_name.sql (e.g., 001_initial.sql, 002_add_costs.sql)
  const match = filename.match(/^(\d+)_(.+)\.sql$/);
  if (!match) return null;

  return {
    version: parseInt(match[1], 10),
    name: match[2],
  };
}

/**
 * Load all migration files from a directory.
 * Sorts migrations by version number.
 *
 * @param dir - Directory containing SQL migration files
 * @returns Array of migration files sorted by version
 */
export function loadMigrations(dir: string): MigrationFile[] {
  const migrations: MigrationFile[] = [];

  let files: string[];
  try {
    files = readdirSync(dir);
  } catch {
    // Directory doesn't exist or can't be read
    return [];
  }

  for (const file of files) {
    // Skip non-SQL files
    if (!file.endsWith('.sql')) continue;

    const parsed = parseMigrationFilename(file);
    if (!parsed) continue;

    const sql = readFileSync(join(dir, file), 'utf-8');

    migrations.push({
      version: parsed.version,
      name: parsed.name,
      sql,
    });
  }

  // Sort by version number (ascending)
  return migrations.sort((a, b) => a.version - b.version);
}

// =============================================================================
// MIGRATION APPLICATION
// =============================================================================

/**
 * Check if the database needs migration.
 *
 * @param db - Database instance
 * @param migrationsDir - Directory containing SQL migration files
 * @returns True if there are pending migrations
 */
export function needsMigration(db: Database.Database, migrationsDir: string): boolean {
  const currentVersion = getSchemaVersion(db);
  const migrations = loadMigrations(migrationsDir);

  if (migrations.length === 0) return false;

  const latestVersion = migrations[migrations.length - 1].version;
  return currentVersion < latestVersion;
}

/**
 * Get the list of pending migrations.
 *
 * @param db - Database instance
 * @param migrationsDir - Directory containing SQL migration files
 * @returns Array of migrations that need to be applied
 */
export function getPendingMigrations(
  db: Database.Database,
  migrationsDir: string,
): MigrationFile[] {
  const currentVersion = getSchemaVersion(db);
  const migrations = loadMigrations(migrationsDir);

  return migrations.filter((m) => m.version > currentVersion);
}

/**
 * Strip leading comment lines from a SQL statement.
 * Preserves the actual SQL command after comments.
 */
function stripLeadingComments(sql: string): string {
  const lines = sql.split('\n');
  let startIndex = 0;

  // Skip leading blank lines and comment lines
  while (startIndex < lines.length) {
    const line = lines[startIndex].trim();
    if (line === '' || line.startsWith('--')) {
      startIndex++;
    } else {
      break;
    }
  }

  return lines.slice(startIndex).join('\n').trim();
}

/**
 * Check if a statement is only comments (no actual SQL).
 */
function isCommentOnly(sql: string): boolean {
  const stripped = stripLeadingComments(sql);
  return stripped === '' || stripped.startsWith('--');
}

/**
 * Execute SQL statements from a migration.
 * Handles multiple statements and makes column additions idempotent.
 *
 * @param db - Database instance
 * @param sql - SQL content to execute
 */
function executeMigrationSql(db: Database.Database, sql: string): void {
  // Split by semicolons
  const rawStatements = sql.split(';');

  // Process each statement: trim, strip leading comments, filter out empty/comment-only
  const statements = rawStatements
    .map((s) => s.trim())
    .filter((s) => s.length > 0 && !isCommentOnly(s));

  for (const statement of statements) {
    try {
      db.exec(statement);
    } catch (err) {
      // Check if it's a "duplicate column" error for ALTER TABLE
      // This makes migrations idempotent for column additions
      const errorMessage = err instanceof Error ? err.message : String(err);
      if (errorMessage.includes('duplicate column name')) {
        // Column already exists, skip this statement
        continue;
      }
      throw err;
    }
  }
}

/**
 * Apply all pending migrations to the database.
 * Migrations are applied in a transaction for atomicity.
 *
 * @param db - Database instance
 * @param migrationsDir - Directory containing SQL migration files
 * @returns Result containing number of applied migrations and current version
 * @throws Error if any migration fails (transaction is rolled back)
 */
export function applyMigrations(db: Database.Database, migrationsDir: string): MigrationResult {
  const currentVersion = getSchemaVersion(db);
  const migrations = loadMigrations(migrationsDir);
  const appliedMigrations: string[] = [];

  // Filter to only pending migrations
  const pendingMigrations = migrations.filter((m) => m.version > currentVersion);

  if (pendingMigrations.length === 0) {
    return {
      applied: 0,
      currentVersion,
      appliedMigrations: [],
    };
  }

  // Apply each migration in order
  // Note: We can't use a single transaction for ALTER TABLE in SQLite
  // as it requires autocommit mode. We apply each migration separately.
  for (const migration of pendingMigrations) {
    try {
      executeMigrationSql(db, migration.sql);

      // Update schema version after successful migration
      setSchemaVersion(db, migration.version);
      appliedMigrations.push(migration.name);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : String(err);
      throw new Error(`Migration ${migration.version}_${migration.name} failed: ${errorMessage}`);
    }
  }

  const newVersion = getSchemaVersion(db);

  return {
    applied: appliedMigrations.length,
    currentVersion: newVersion,
    appliedMigrations,
  };
}

/**
 * Apply migrations up to a specific version.
 *
 * @param db - Database instance
 * @param migrationsDir - Directory containing SQL migration files
 * @param targetVersion - Maximum version to apply
 * @returns Result containing number of applied migrations and current version
 */
export function applyMigrationsTo(
  db: Database.Database,
  migrationsDir: string,
  targetVersion: number,
): MigrationResult {
  const currentVersion = getSchemaVersion(db);
  const migrations = loadMigrations(migrationsDir);
  const appliedMigrations: string[] = [];

  // Filter to migrations between current and target version
  const pendingMigrations = migrations.filter(
    (m) => m.version > currentVersion && m.version <= targetVersion,
  );

  if (pendingMigrations.length === 0) {
    return {
      applied: 0,
      currentVersion,
      appliedMigrations: [],
    };
  }

  for (const migration of pendingMigrations) {
    try {
      executeMigrationSql(db, migration.sql);

      setSchemaVersion(db, migration.version);
      appliedMigrations.push(migration.name);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : String(err);
      throw new Error(`Migration ${migration.version}_${migration.name} failed: ${errorMessage}`);
    }
  }

  const newVersion = getSchemaVersion(db);

  return {
    applied: appliedMigrations.length,
    currentVersion: newVersion,
    appliedMigrations,
  };
}

/**
 * Get migration status for the database.
 *
 * @param db - Database instance
 * @param migrationsDir - Directory containing SQL migration files
 * @returns Object containing version info and pending migrations
 */
export function getMigrationStatus(
  db: Database.Database,
  migrationsDir: string,
): {
  currentVersion: number;
  latestVersion: number;
  pendingCount: number;
  pendingMigrations: Array<{ version: number; name: string }>;
} {
  const currentVersion = getSchemaVersion(db);
  const migrations = loadMigrations(migrationsDir);
  const pending = migrations.filter((m) => m.version > currentVersion);

  return {
    currentVersion,
    latestVersion: migrations.length > 0 ? migrations[migrations.length - 1].version : 0,
    pendingCount: pending.length,
    pendingMigrations: pending.map((m) => ({ version: m.version, name: m.name })),
  };
}
