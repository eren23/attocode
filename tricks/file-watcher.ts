/**
 * Trick I: File Watcher Integration
 *
 * Watch for file changes and trigger callbacks.
 * Useful for hot-reloading and incremental updates.
 */

import { watch, type FSWatcher } from 'fs';
import { stat, readdir } from 'fs/promises';
import { join, relative, resolve } from 'path';

// =============================================================================
// TYPES
// =============================================================================

/**
 * File change event.
 */
export type FileEvent = 'add' | 'change' | 'delete';

/**
 * File change callback.
 */
export type FileChangeCallback = (path: string, event: FileEvent) => void;

/**
 * Disposable interface for cleanup.
 */
export interface Disposable {
  dispose(): void;
}

/**
 * Watcher options.
 */
export interface WatcherOptions {
  /** Debounce delay in ms (default: 100) */
  debounce?: number;
  /** Ignore patterns (glob-like) */
  ignore?: string[];
  /** Only watch these patterns */
  include?: string[];
  /** Watch subdirectories (default: true) */
  recursive?: boolean;
  /** Emit events for initial files (default: false) */
  emitInitial?: boolean;
}

// =============================================================================
// FILE WATCHER
// =============================================================================

/**
 * Watch files matching patterns for changes.
 */
export function watchProject(
  basePath: string,
  patterns: string[],
  onChange: FileChangeCallback,
  options: WatcherOptions = {}
): Disposable {
  const {
    debounce = 100,
    ignore = ['node_modules', '.git', 'dist', 'build'],
    recursive = true,
    emitInitial = false,
  } = options;

  const watchers: FSWatcher[] = [];
  const knownFiles = new Set<string>();
  const pendingEvents = new Map<string, { event: FileEvent; timeout: NodeJS.Timeout }>();
  const resolvedBase = resolve(basePath);

  /**
   * Check if path matches any pattern.
   */
  function matchesPattern(filePath: string): boolean {
    const relativePath = relative(resolvedBase, filePath);

    // Check ignore patterns
    for (const pattern of ignore) {
      if (matchGlob(relativePath, pattern)) {
        return false;
      }
    }

    // Check include patterns
    for (const pattern of patterns) {
      if (matchGlob(relativePath, pattern)) {
        return true;
      }
    }

    return false;
  }

  /**
   * Emit debounced event.
   */
  function emitEvent(path: string, event: FileEvent): void {
    // Clear existing timeout for this path
    const existing = pendingEvents.get(path);
    if (existing) {
      clearTimeout(existing.timeout);
    }

    // Set new timeout
    const timeout = setTimeout(() => {
      pendingEvents.delete(path);
      onChange(path, event);
    }, debounce);

    pendingEvents.set(path, { event, timeout });
  }

  /**
   * Handle file change event.
   */
  async function handleChange(eventType: string, filename: string | null, watchDir: string): Promise<void> {
    if (!filename) return;

    const fullPath = join(watchDir, filename);

    if (!matchesPattern(fullPath)) return;

    try {
      await stat(fullPath);
      // File exists
      if (knownFiles.has(fullPath)) {
        emitEvent(fullPath, 'change');
      } else {
        knownFiles.add(fullPath);
        emitEvent(fullPath, 'add');
      }
    } catch {
      // File doesn't exist - deleted
      if (knownFiles.has(fullPath)) {
        knownFiles.delete(fullPath);
        emitEvent(fullPath, 'delete');
      }
    }
  }

  /**
   * Scan directory for matching files.
   */
  async function scanDirectory(dir: string): Promise<string[]> {
    const files: string[] = [];

    try {
      const entries = await readdir(dir, { withFileTypes: true });

      for (const entry of entries) {
        const fullPath = join(dir, entry.name);
        const relativePath = relative(resolvedBase, fullPath);

        // Skip ignored directories
        let isIgnored = false;
        for (const pattern of ignore) {
          if (matchGlob(relativePath, pattern) || matchGlob(entry.name, pattern)) {
            isIgnored = true;
            break;
          }
        }
        if (isIgnored) continue;

        if (entry.isDirectory() && recursive) {
          files.push(...(await scanDirectory(fullPath)));
        } else if (entry.isFile() && matchesPattern(fullPath)) {
          files.push(fullPath);
        }
      }
    } catch {
      // Directory might not exist or be readable
    }

    return files;
  }

  /**
   * Setup watcher for a directory.
   */
  function setupWatcher(dir: string): void {
    try {
      const watcher = watch(dir, { recursive }, (eventType, filename) => {
        handleChange(eventType, filename, dir).catch(() => {
          // Ignore errors in change handler
        });
      });

      watcher.on('error', () => {
        // Ignore watcher errors (directory deleted, etc.)
      });

      watchers.push(watcher);
    } catch {
      // Directory might not exist
    }
  }

  // Initial setup
  (async () => {
    // Scan for existing files
    const initialFiles = await scanDirectory(resolvedBase);
    for (const file of initialFiles) {
      knownFiles.add(file);
      if (emitInitial) {
        onChange(file, 'add');
      }
    }

    // Setup watchers
    setupWatcher(resolvedBase);
  })();

  // Return disposable
  return {
    dispose() {
      // Close all watchers
      for (const watcher of watchers) {
        watcher.close();
      }

      // Clear pending events
      for (const { timeout } of pendingEvents.values()) {
        clearTimeout(timeout);
      }
      pendingEvents.clear();
    },
  };
}

// =============================================================================
// GLOB MATCHING
// =============================================================================

/**
 * Simple glob matching.
 * Supports: * (any chars), ** (any path), ? (single char)
 */
function matchGlob(path: string, pattern: string): boolean {
  // Normalize
  const normalizedPath = path.replace(/\\/g, '/');
  const normalizedPattern = pattern.replace(/\\/g, '/');

  // Convert glob to regex
  let regex = normalizedPattern
    .replace(/\./g, '\\.')
    .replace(/\*\*/g, '{{GLOBSTAR}}')
    .replace(/\*/g, '[^/]*')
    .replace(/\{\{GLOBSTAR\}\}/g, '.*')
    .replace(/\?/g, '.');

  // Handle leading **/ to match from root
  if (regex.startsWith('.*\\/')) {
    regex = '(.*\\/)?' + regex.slice(4);
  }

  return new RegExp(`^${regex}$`).test(normalizedPath);
}

// =============================================================================
// BATCHED WATCHER
// =============================================================================

/**
 * Watcher that batches multiple events.
 */
export class BatchedWatcher implements Disposable {
  private disposable: Disposable | null = null;
  private batch: Map<string, FileEvent> = new Map();
  private batchTimeout: NodeJS.Timeout | null = null;
  private batchDelay: number;
  private callback: (changes: Map<string, FileEvent>) => void;

  constructor(
    basePath: string,
    patterns: string[],
    callback: (changes: Map<string, FileEvent>) => void,
    options: WatcherOptions & { batchDelay?: number } = {}
  ) {
    this.batchDelay = options.batchDelay ?? 500;
    this.callback = callback;

    this.disposable = watchProject(basePath, patterns, (path, event) => {
      this.addToBatch(path, event);
    }, options);
  }

  private addToBatch(path: string, event: FileEvent): void {
    this.batch.set(path, event);

    // Reset batch timeout
    if (this.batchTimeout) {
      clearTimeout(this.batchTimeout);
    }

    this.batchTimeout = setTimeout(() => {
      this.flush();
    }, this.batchDelay);
  }

  private flush(): void {
    if (this.batch.size === 0) return;

    const changes = new Map(this.batch);
    this.batch.clear();
    this.batchTimeout = null;

    this.callback(changes);
  }

  dispose(): void {
    if (this.batchTimeout) {
      clearTimeout(this.batchTimeout);
    }
    this.flush(); // Emit any pending changes
    this.disposable?.dispose();
  }
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Create a batched watcher.
 */
export function watchProjectBatched(
  basePath: string,
  patterns: string[],
  callback: (changes: Map<string, FileEvent>) => void,
  options?: WatcherOptions & { batchDelay?: number }
): Disposable {
  return new BatchedWatcher(basePath, patterns, callback, options);
}

/**
 * Watch for specific file types.
 */
export function watchFileTypes(
  basePath: string,
  extensions: string[],
  onChange: FileChangeCallback,
  options?: WatcherOptions
): Disposable {
  const patterns = extensions.map((ext) => `**/*${ext.startsWith('.') ? ext : '.' + ext}`);
  return watchProject(basePath, patterns, onChange, options);
}

// Usage:
// const watcher = watchProject('.', ['**/*.ts', '**/*.tsx'], (path, event) => {
//   console.log(`File ${event}: ${path}`);
// }, {
//   ignore: ['node_modules', 'dist'],
//   debounce: 100,
// });
//
// // Later...
// watcher.dispose();
//
// // Or use batched version
// const batchedWatcher = watchProjectBatched('.', ['**/*.ts'], (changes) => {
//   console.log(`${changes.size} files changed`);
//   for (const [path, event] of changes) {
//     console.log(`  ${event}: ${path}`);
//   }
// });
