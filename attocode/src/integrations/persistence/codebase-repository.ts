/**
 * Codebase Repository
 *
 * Persistence layer for codebase analysis results.
 * Stores/loads chunk metadata and dependency graph to/from SQLite
 * for warm startup across sessions.
 */

import type { SQLiteStoreDeps } from './sqlite-store.js';
import { djb2Hash } from '../context/codebase-ast.js';

// =============================================================================
// TYPES
// =============================================================================

export interface SavedChunk {
  filePath: string;
  contentHash: string;
  symbolsJson: string;
  dependenciesJson: string;
  importance: number;
  chunkType: string;
  tokenCount: number;
  analyzedAt: number;
}

export interface SavedCodebaseAnalysis {
  chunks: Map<string, SavedChunk>;
  deps: Map<string, Set<string>>;
}

// =============================================================================
// SAVE
// =============================================================================

/**
 * Save codebase analysis to SQLite for persistence across sessions.
 */
export function saveCodebaseAnalysis(
  deps: SQLiteStoreDeps,
  root: string,
  chunks: Iterable<{
    filePath: string;
    content: string;
    symbolDetails: Array<{ name: string; kind: string; exported: boolean; line: number }>;
    dependencies: string[];
    importance: number;
    type: string;
    tokenCount: number;
  }>,
  dependencyGraph: Map<string, Set<string>>,
): void {
  if (!deps.features.codebaseAnalysis) return;

  const { db } = deps;
  const deleteChunks = db.prepare('DELETE FROM codebase_chunks WHERE workspace_root = ?');
  const deleteDeps = db.prepare('DELETE FROM codebase_deps WHERE workspace_root = ?');
  const insertChunk = db.prepare(`
    INSERT INTO codebase_chunks (file_path, workspace_root, content_hash, symbols_json,
      dependencies_json, importance, chunk_type, token_count, analyzed_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);
  const insertDep = db.prepare(`
    INSERT INTO codebase_deps (workspace_root, source_file, target_file) VALUES (?, ?, ?)
  `);

  const transaction = db.transaction(() => {
    deleteChunks.run(root);
    deleteDeps.run(root);
    for (const chunk of chunks) {
      const contentHash = djb2Hash(chunk.content).toString(36);
      insertChunk.run(
        chunk.filePath, root, contentHash,
        JSON.stringify(chunk.symbolDetails),
        JSON.stringify(chunk.dependencies),
        chunk.importance, chunk.type, chunk.tokenCount, Date.now(),
      );
    }
    for (const [source, targets] of dependencyGraph) {
      for (const target of targets) {
        insertDep.run(root, source, target);
      }
    }
  });
  transaction();
}

// =============================================================================
// LOAD
// =============================================================================

/**
 * Load persisted codebase analysis from SQLite.
 * Returns null if no analysis exists for the given workspace root.
 */
export function loadCodebaseAnalysis(
  deps: SQLiteStoreDeps,
  root: string,
): SavedCodebaseAnalysis | null {
  if (!deps.features.codebaseAnalysis) return null;

  const { db } = deps;
  const rows = db.prepare(
    'SELECT * FROM codebase_chunks WHERE workspace_root = ?',
  ).all(root) as Array<{
    file_path: string;
    content_hash: string;
    symbols_json: string;
    dependencies_json: string;
    importance: number;
    chunk_type: string;
    token_count: number;
    analyzed_at: number;
  }>;

  if (rows.length === 0) return null;

  const chunks = new Map<string, SavedChunk>();
  for (const row of rows) {
    chunks.set(row.file_path, {
      filePath: row.file_path,
      contentHash: row.content_hash,
      symbolsJson: row.symbols_json,
      dependenciesJson: row.dependencies_json,
      importance: row.importance,
      chunkType: row.chunk_type,
      tokenCount: row.token_count,
      analyzedAt: row.analyzed_at,
    });
  }

  const depRows = db.prepare(
    'SELECT source_file, target_file FROM codebase_deps WHERE workspace_root = ?',
  ).all(root) as Array<{ source_file: string; target_file: string }>;

  const depsMap = new Map<string, Set<string>>();
  for (const row of depRows) {
    if (!depsMap.has(row.source_file)) {
      depsMap.set(row.source_file, new Set());
    }
    depsMap.get(row.source_file)!.add(row.target_file);
  }

  return { chunks, deps: depsMap };
}

