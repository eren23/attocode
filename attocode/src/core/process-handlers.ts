/**
 * Process Error Handlers and Cleanup Management
 *
 * Provides graceful cleanup on process exit, signal handling,
 * and resource registration for the application.
 */

// =============================================================================
// CLEANUP RESOURCES
// =============================================================================

/**
 * Global cleanup resources - populated during initialization.
 * Used by process error handlers to gracefully clean up before exit.
 */
export interface CleanupResources {
  agent?: { cleanup: () => Promise<void> };
  mcpClient?: { cleanup: () => Promise<void> };
  tui?: { cleanup: () => void };
  rl?: { close: () => void };
}

let cleanupResources: CleanupResources = {};
let isCleaningUp = false;

/**
 * Gracefully clean up all resources before exit.
 * Times out after 5 seconds to prevent hanging.
 */
export async function gracefulCleanup(reason: string): Promise<void> {
  // Prevent recursive cleanup
  if (isCleaningUp) {
    return;
  }
  isCleaningUp = true;

  console.error(`\n[CLEANUP] Starting graceful cleanup (reason: ${reason})...`);

  // Set a hard timeout to prevent hanging
  const forceExitTimeout = setTimeout(() => {
    console.error('[CLEANUP] Timeout reached, forcing exit');
    process.exit(1);
  }, 5000);

  try {
    // Clean up in reverse initialization order
    // 1. TUI (synchronous)
    if (cleanupResources.tui) {
      try {
        cleanupResources.tui.cleanup();
      } catch (e) {
        console.error('[CLEANUP] TUI cleanup error:', e);
      }
    }

    // 2. Readline (synchronous)
    if (cleanupResources.rl) {
      try {
        cleanupResources.rl.close();
      } catch (e) {
        console.error('[CLEANUP] Readline cleanup error:', e);
      }
    }

    // 3. Agent (async)
    if (cleanupResources.agent) {
      try {
        await cleanupResources.agent.cleanup();
      } catch (e) {
        console.error('[CLEANUP] Agent cleanup error:', e);
      }
    }

    // 4. MCP Client (async)
    if (cleanupResources.mcpClient) {
      try {
        await cleanupResources.mcpClient.cleanup();
      } catch (e) {
        console.error('[CLEANUP] MCP cleanup error:', e);
      }
    }

    console.error('[CLEANUP] Cleanup completed');
  } finally {
    clearTimeout(forceExitTimeout);
  }
}

/**
 * Register a resource for cleanup on process exit.
 */
export function registerCleanupResource<K extends keyof CleanupResources>(
  key: K,
  resource: CleanupResources[K]
): void {
  cleanupResources[key] = resource;
}

/**
 * Reset cleanup state - useful for testing or re-initialization.
 */
export function resetCleanupState(): void {
  cleanupResources = {};
  isCleaningUp = false;
}

// =============================================================================
// PROCESS SIGNAL HANDLERS
// =============================================================================

/**
 * Install process-level error handlers.
 * Should be called once at application startup.
 */
export function installProcessHandlers(): void {
  // Handle unhandled promise rejections
  process.on('unhandledRejection', async (reason, _promise) => {
    console.error('\n[FATAL] Unhandled Promise Rejection:');
    console.error('  Reason:', reason);
    if (reason instanceof Error && reason.stack) {
      console.error('  Stack:', reason.stack.split('\n').slice(0, 5).join('\n'));
    }
    await gracefulCleanup('unhandled rejection');
    process.exit(1);
  });

  // Handle uncaught exceptions
  process.on('uncaughtException', async (error, origin) => {
    console.error(`\n[FATAL] Uncaught Exception (${origin}):`);
    console.error('  Error:', error.message);
    if (error.stack) {
      console.error('  Stack:', error.stack.split('\n').slice(0, 5).join('\n'));
    }
    await gracefulCleanup('uncaught exception');
    process.exit(1);
  });

  // Handle SIGTERM for graceful shutdown (e.g., container orchestration)
  process.on('SIGTERM', async () => {
    console.error('\n[INFO] Received SIGTERM signal');
    await gracefulCleanup('SIGTERM');
    process.exit(0);
  });
}
