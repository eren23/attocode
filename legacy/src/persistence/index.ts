/**
 * Persistence Module
 *
 * Provides schema migration and database management utilities
 * for SQLite-based session storage.
 *
 * ## New Embedded Migration System
 *
 * Migrations are now embedded directly in TypeScript code, eliminating
 * the need for external SQL files and file path resolution issues.
 *
 * @example
 * ```typescript
 * import Database from 'better-sqlite3';
 * import { applyMigrations, needsMigration, getMigrationStatus } from './persistence/index.js';
 *
 * const db = new Database('sessions.db');
 *
 * // Check and apply pending migrations (no path needed!)
 * if (needsMigration(db)) {
 *   const result = applyMigrations(db);
 *   console.log(`Applied ${result.applied} migrations, now at version ${result.currentVersion}`);
 * }
 *
 * // Get detailed status
 * const status = getMigrationStatus(db);
 * console.log(`Current: v${status.currentVersion}, Latest: v${status.latestVersion}`);
 *
 * // Check which features are available
 * const features = detectFeatures(db);
 * if (features.goals) {
 *   console.log('Goal tracking is available!');
 * }
 * ```
 */

// New embedded migration system
export {
  // Types
  type Migration,
  type MigrationResult,
  type SchemaFeatures,
  // Embedded migrations
  MIGRATIONS,
  // Version management
  getSchemaVersion,
  setSchemaVersion,
  // Migration execution
  needsMigration,
  applyMigrations,
  getMigrationStatus,
  // Feature detection
  detectFeatures,
} from './schema.js';

// Legacy file-based migrator (for backwards compatibility with external migrations)
export {
  type MigrationFile,
  loadMigrations,
  getPendingMigrations,
  applyMigrationsTo,
  applyMigrations as applyFileMigrations,
  getMigrationStatus as getFileMigrationStatus,
  needsMigration as fileNeedsMigration,
} from './migrator.js';
