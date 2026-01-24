/**
 * Persistence Module
 *
 * Provides schema migration and database management utilities
 * for SQLite-based session storage.
 *
 * @example
 * ```typescript
 * import Database from 'better-sqlite3';
 * import { applyMigrations, needsMigration, getMigrationStatus } from './persistence/index.js';
 *
 * const db = new Database('sessions.db');
 *
 * // Check and apply pending migrations
 * if (needsMigration(db, './migrations')) {
 *   const result = applyMigrations(db, './migrations');
 *   console.log(`Applied ${result.applied} migrations, now at version ${result.currentVersion}`);
 * }
 *
 * // Get detailed status
 * const status = getMigrationStatus(db, './migrations');
 * console.log(`Current: v${status.currentVersion}, Latest: v${status.latestVersion}`);
 * ```
 */

// Migration utilities
export {
  // Types
  type MigrationFile,
  type MigrationResult,
  // Version management
  getSchemaVersion,
  setSchemaVersion,
  // Migration loading
  loadMigrations,
  // Migration execution
  needsMigration,
  getPendingMigrations,
  applyMigrations,
  applyMigrationsTo,
  getMigrationStatus,
} from './migrator.js';
