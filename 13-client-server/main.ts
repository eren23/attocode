/**
 * Lesson 13: Client/Server Separation - Demonstration
 *
 * Shows how to separate agent logic from UI using a client/server architecture.
 * This enables multiple clients (CLI, web, mobile) to connect to a single agent server.
 */

import { createAgentClient } from './client.js';
import { createAgentServer } from './server.js';
import type { AgentEvent, StreamChunk } from './types.js';

// =============================================================================
// DEMONSTRATION
// =============================================================================

async function main() {
  console.log('='.repeat(70));
  console.log('Lesson 13: Client/Server Separation');
  console.log('='.repeat(70));

  // =========================================================================
  // Part 1: Basic Client Connection
  // =========================================================================
  console.log('\n📡 Part 1: Basic Client Connection\n');

  const client = createAgentClient({
    serverUrl: 'http://localhost:3000',
    timeout: 30000,
    autoReconnect: true,
  });

  console.log('Initial state:', client.getState());

  // Connect to server
  await client.connect();
  console.log('After connect:', client.getState());

  // =========================================================================
  // Part 2: Health Check
  // =========================================================================
  console.log('\n❤️ Part 2: Health Check\n');

  const health = await client.health();
  console.log('Server health:', {
    status: health.status,
    version: health.version,
    uptime: `${Math.round(health.uptime / 1000)}s`,
    activeSessions: health.activeSessions,
    load: `${(health.load * 100).toFixed(1)}%`,
  });

  // =========================================================================
  // Part 3: Session Management
  // =========================================================================
  console.log('\n🗂️ Part 3: Session Management\n');

  // Create a session
  const session = await client.createSession({
    model: 'gpt-4',
    maxTokens: 1000,
    temperature: 0.7,
    metadata: { purpose: 'demo' },
  });

  console.log('Created session:', {
    id: session.id,
    status: session.status,
    model: session.config.model,
    createdAt: session.createdAt,
  });

  // Get the session back
  const retrieved = await client.getSession(session.id);
  console.log('Retrieved session:', retrieved?.id === session.id ? 'Match!' : 'Mismatch');

  // List all sessions
  const sessions = await client.listSessions();
  console.log('Active sessions:', sessions.length);

  // =========================================================================
  // Part 4: Sending Messages
  // =========================================================================
  console.log('\n💬 Part 4: Sending Messages\n');

  // Send a message
  const response = await client.sendMessage(session.id, 'Hello, agent!');
  console.log('User message sent');
  console.log('Assistant response:', {
    id: response.id,
    role: response.role,
    content: response.content.substring(0, 50) + '...',
  });

  // Send another message
  const response2 = await client.sendMessage(session.id, 'What can you help me with?');
  console.log('Second response:', response2.content.substring(0, 50) + '...');

  // =========================================================================
  // Part 5: Message History
  // =========================================================================
  console.log('\n📜 Part 5: Message History\n');

  const messages = await client.getMessages(session.id);
  console.log(`Session has ${messages.length} messages:`);
  for (const msg of messages) {
    console.log(`  [${msg.role}] ${msg.content.substring(0, 40)}...`);
  }

  // Get limited messages
  const recentMessages = await client.getMessages(session.id, { limit: 2 });
  console.log(`\nLast 2 messages: ${recentMessages.length}`);

  // =========================================================================
  // Part 6: Streaming Responses
  // =========================================================================
  console.log('\n🌊 Part 6: Streaming Responses\n');

  console.log('Streaming response:');
  process.stdout.write('  ');

  for await (const chunk of client.streamMessage(session.id, 'Tell me a story')) {
    if (chunk.type === 'text') {
      process.stdout.write(chunk.content || '');
    } else if (chunk.type === 'done') {
      console.log(`\n  [Done: ${chunk.messageId}]`);
    }
  }

  // =========================================================================
  // Part 7: Event Subscription
  // =========================================================================
  console.log('\n📢 Part 7: Event Subscription\n');

  // Global event subscription
  const unsubscribe = client.subscribe((event: AgentEvent) => {
    console.log('  Event:', event.type);
  });

  console.log('Subscribed to global events');

  // Session-specific events
  console.log('\nSession events:');
  let eventCount = 0;
  for await (const event of client.subscribeToSession(session.id)) {
    console.log(`  Session event: ${event.type}`);
    eventCount++;
    if (eventCount >= 2) break;
  }

  unsubscribe();
  console.log('Unsubscribed from events');

  // =========================================================================
  // Part 8: Multiple Sessions
  // =========================================================================
  console.log('\n🔀 Part 8: Multiple Sessions\n');

  // Create additional sessions
  const session2 = await client.createSession({ metadata: { purpose: 'coding' } });
  const session3 = await client.createSession({ metadata: { purpose: 'research' } });

  console.log('Created sessions:', [session.id, session2.id, session3.id].map((id) => id.slice(0, 15) + '...'));

  const allSessions = await client.listSessions();
  console.log('Total active sessions:', allSessions.length);

  // Send messages to different sessions
  await client.sendMessage(session2.id, 'Help me write code');
  await client.sendMessage(session3.id, 'Research quantum computing');

  // Check stats
  const stats = await client.stats();
  console.log('Server stats:', {
    total: stats.totalSessions,
    active: stats.activeSessions,
    messages: stats.totalMessages,
  });

  // =========================================================================
  // Part 9: Session Closure
  // =========================================================================
  console.log('\n🚪 Part 9: Session Closure\n');

  // Close one session
  await client.closeSession(session2.id);
  console.log('Closed session:', session2.id.slice(0, 15) + '...');

  // Verify it's gone
  const closedSession = await client.getSession(session2.id);
  console.log('Closed session retrievable:', closedSession !== null);

  const remainingSessions = await client.listSessions();
  console.log('Remaining sessions:', remainingSessions.length);

  // =========================================================================
  // Part 10: Cancel Operation
  // =========================================================================
  console.log('\n🛑 Part 10: Cancel Operation\n');

  // Request cancellation (simulated)
  await client.cancel(session.id);
  console.log('Cancellation requested');

  // =========================================================================
  // Part 11: Error Handling
  // =========================================================================
  console.log('\n⚠️ Part 11: Error Handling\n');

  // Try to get non-existent session
  const nonExistent = await client.getSession('session-does-not-exist');
  console.log('Non-existent session:', nonExistent);

  // Try to send to closed session
  try {
    await client.sendMessage(session2.id, 'This should fail');
  } catch (err) {
    console.log('Expected error:', err instanceof Error ? err.message : String(err));
  }

  // =========================================================================
  // Part 12: Client Disconnect
  // =========================================================================
  console.log('\n🔌 Part 12: Client Disconnect\n');

  console.log('State before disconnect:', client.getState());

  await client.disconnect();
  console.log('State after disconnect:', client.getState());

  // Try to use after disconnect
  try {
    await client.health();
  } catch (err) {
    console.log('Expected error after disconnect:', err instanceof Error ? err.message : String(err));
  }

  // =========================================================================
  // Summary
  // =========================================================================
  console.log('\n' + '='.repeat(70));
  console.log('Client/Server Separation Summary');
  console.log('='.repeat(70));
  console.log(`
Key Concepts Demonstrated:

1. Connection Management
   - Connect/disconnect lifecycle
   - Auto-reconnect capability
   - Connection state tracking

2. Session Management
   - Create sessions with configuration
   - Retrieve and list sessions
   - Close sessions cleanly

3. Messaging
   - Send messages and receive responses
   - Get message history with pagination
   - Stream responses in real-time

4. Event System
   - Subscribe to global events
   - Subscribe to session-specific events
   - Clean unsubscription

5. Server Features
   - Health checks
   - Statistics gathering
   - Rate limiting (configured on server)

Architecture Benefits:
- UI independence: CLI, web, mobile can all connect
- Scalability: Server can handle multiple clients
- State persistence: Sessions survive client disconnects
- Real-time updates: Event streaming for live feedback

This pattern is used by:
- OpenAI's API (REST + streaming)
- Claude's API (similar pattern)
- GitHub Copilot (client/server separation)
- VS Code's LSP (Language Server Protocol)
`);
}

// Run the demonstration
main().catch(console.error);
