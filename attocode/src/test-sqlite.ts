/**
 * Quick test script to debug SQLite session persistence
 */
import { createSQLiteStore, SQLiteStore } from './integrations/sqlite-store.js';
import { createSessionStore, SessionStore } from './integrations/session-store.js';

async function testSQLitePersistence() {
  console.log('=== SQLite Persistence Test ===\n');

  try {
    // 1. Create SQLite store
    console.log('1. Creating SQLite store...');
    const store = await createSQLiteStore({ baseDir: '.agent/sessions' });
    console.log('   ✓ Store created');

    // 2. Check current state
    console.log('\n2. Current store stats:');
    const stats = store.getStats();
    console.log(`   Sessions: ${stats.sessionCount}`);
    console.log(`   Entries: ${stats.entryCount}`);
    console.log(`   Checkpoints: ${stats.checkpointCount}`);
    console.log(`   DB Size: ${stats.dbSizeBytes} bytes`);

    // 3. Create a new session
    console.log('\n3. Creating new session...');
    const sessionId = store.createSession('test-session');
    console.log(`   Session ID: ${sessionId}`);
    console.log(`   Current Session ID in store: ${store.getCurrentSessionId()}`);

    // 4. Check if currentSessionId is set correctly
    if (store.getCurrentSessionId() !== sessionId) {
      console.log('   ❌ ERROR: currentSessionId mismatch!');
    } else {
      console.log('   ✓ currentSessionId matches');
    }

    // 5. Try to save a checkpoint
    console.log('\n4. Saving checkpoint...');
    try {
      const checkpointData = {
        id: 'test-ckpt-1',
        label: 'test-checkpoint',
        messages: [{ role: 'user', content: 'test' }],
        iteration: 1,
      };
      const ckptId = store.saveCheckpoint(checkpointData, 'test-checkpoint');
      console.log(`   ✓ Checkpoint saved with ID: ${ckptId}`);
    } catch (err) {
      console.log(`   ❌ ERROR saving checkpoint: ${(err as Error).message}`);
      console.log(`   Stack: ${(err as Error).stack}`);
    }

    // 6. Verify checkpoint was saved
    console.log('\n5. Verifying checkpoint...');
    const statsAfter = store.getStats();
    console.log(`   Checkpoints before: ${stats.checkpointCount}`);
    console.log(`   Checkpoints after: ${statsAfter.checkpointCount}`);

    if (statsAfter.checkpointCount > stats.checkpointCount) {
      console.log('   ✓ Checkpoint count increased!');
    } else {
      console.log('   ❌ Checkpoint count did NOT increase!');
    }

    // 7. Try to load the checkpoint
    console.log('\n6. Loading checkpoint...');
    const loaded = store.loadLatestCheckpoint(sessionId);
    if (loaded) {
      console.log(`   ✓ Loaded checkpoint: ${loaded.id}`);
      console.log(`   State keys: ${Object.keys(loaded.state).join(', ')}`);
    } else {
      console.log('   ❌ No checkpoint found for session');
    }

    // 8. List all sessions
    console.log('\n7. Listing sessions...');
    const sessions = store.listSessions();
    console.log(`   Total sessions: ${sessions.length}`);
    if (sessions.length > 0) {
      console.log(`   Most recent: ${sessions[0].id}`);
    }

    // Cleanup
    store.close();
    console.log('\n=== Test Complete ===');

  } catch (err) {
    console.error('\n❌ Test failed:', (err as Error).message);
    console.error((err as Error).stack);
  }
}

async function testStoreTypeDetection() {
  console.log('\n=== Store Type Detection Test ===\n');

  const sqliteStore = await createSQLiteStore({ baseDir: '.agent/sessions' });
  const jsonlStore = await createSessionStore({ baseDir: '.agent/sessions' });

  console.log('SQLite store checks:');
  console.log('  "saveCheckpoint" in store:', 'saveCheckpoint' in sqliteStore);
  console.log('  typeof store.saveCheckpoint:', typeof sqliteStore.saveCheckpoint);
  console.log('  "appendEntry" in store:', 'appendEntry' in sqliteStore);

  console.log('\nJSONL store checks:');
  console.log('  "saveCheckpoint" in store:', 'saveCheckpoint' in jsonlStore);
  console.log('  typeof (store as any).saveCheckpoint:', typeof (jsonlStore as any).saveCheckpoint);
  console.log('  "appendEntry" in store:', 'appendEntry' in jsonlStore);

  // Test the actual condition used in saveCheckpointToStore
  console.log('\n=== saveCheckpointToStore detection ===');
  function detectStoreType(store: SQLiteStore | SessionStore): string {
    if ('saveCheckpoint' in store && typeof store.saveCheckpoint === 'function') {
      return 'SQLite (will use saveCheckpoint)';
    } else if ('appendEntry' in store && typeof store.appendEntry === 'function') {
      return 'JSONL (will use appendEntry)';
    }
    return 'Unknown';
  }

  console.log('SQLite store detected as:', detectStoreType(sqliteStore));
  console.log('JSONL store detected as:', detectStoreType(jsonlStore));

  sqliteStore.close();
  await jsonlStore.cleanup();
}

testSQLitePersistence().then(() => testStoreTypeDetection());
