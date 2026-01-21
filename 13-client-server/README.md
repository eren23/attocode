# Lesson 13: Client/Server Separation

## Overview

This lesson implements a client/server architecture for AI agents, separating the agent logic (server) from the user interface (client). This pattern enables:

- **Multiple UIs**: CLI, web, mobile, IDE plugins can all connect
- **Scalability**: Server handles multiple concurrent clients
- **State Persistence**: Sessions survive client disconnects
- **Real-time Updates**: Event streaming for live feedback

## Why Client/Server Architecture?

### The Problem

Early AI agents often tightly couple the UI with the agent logic:

```typescript
// Tightly coupled - UI and agent mixed together
async function runAgent() {
  const input = await readline.question('> ');  // UI concern
  const response = await llm.chat(input);       // Agent concern
  console.log(response);                         // UI concern
}
```

This makes it impossible to:
- Use the same agent from different interfaces
- Scale to multiple users
- Maintain state across connections
- Add features like streaming without rewriting everything

### The Solution

Separate concerns with a clear API boundary:

```
┌─────────────┐     ┌─────────────────────────────────────┐
│   CLI UI    │────▶│                                     │
└─────────────┘     │                                     │
                    │           Agent Server              │
┌─────────────┐     │  ┌─────────┐  ┌────────────────┐  │
│   Web UI    │────▶│  │ Session │  │   LLM/Tools    │  │
└─────────────┘     │  │ Manager │  │   Integration  │  │
                    │  └─────────┘  └────────────────┘  │
┌─────────────┐     │                                     │
│  Mobile UI  │────▶│                                     │
└─────────────┘     └─────────────────────────────────────┘
```

## Core Components

### 1. Types (`types.ts`)

Defines the contract between client and server:

```typescript
// Session represents an ongoing conversation
interface Session {
  id: string;
  config: SessionConfig;
  status: SessionStatus;
  createdAt: Date;
  lastActivityAt: Date;
  messageCount: number;
  tokenUsage: TokenUsage;
}

// Message represents a single exchange
interface Message {
  id: string;
  sessionId: string;
  role: MessageRole;
  content: string;
  timestamp: Date;
}

// Server API defines available operations
interface AgentServerAPI {
  createSession(config?: SessionConfig): Promise<Session>;
  sendMessage(sessionId: string, content: string): Promise<Message>;
  getMessages(sessionId: string, options?: GetMessagesOptions): Promise<Message[]>;
  streamMessage(sessionId: string, content: string): AsyncIterable<StreamChunk>;
  subscribe(sessionId: string): AsyncIterable<AgentEvent>;
  health(): Promise<HealthStatus>;
}
```

### 2. Protocol (`protocol.ts`)

Handles message serialization and request/response correlation:

```typescript
// Message format for wire protocol
interface ProtocolMessage {
  version: string;
  type: 'request' | 'response' | 'event' | 'ping' | 'pong';
  payload: unknown;
}

// Build typed requests
const message = buildRequest('session.create', { model: 'gpt-4' });

// Parse responses
const response = extractResponse<Session>(parsed);
if (response?.success) {
  console.log('Created session:', response.data);
}

// Protocol handler routes methods to implementations
const handler = createProtocolHandler();
handler.register('session.create', async (params) => {
  return sessionManager.createSession(params);
});
```

### 3. Session Manager (`session-manager.ts`)

Manages multiple concurrent sessions:

```typescript
class SessionManager {
  // Lifecycle
  createSession(config: SessionConfig): Session;
  getSession(sessionId: string): Session | null;
  closeSession(sessionId: string): boolean;

  // Messaging
  addMessage(sessionId: string, role: MessageRole, content: string): Message;
  getMessages(sessionId: string, options?: GetMessagesOptions): Message[];

  // Events
  subscribeToSession(sessionId: string, listener: AgentEventListener): () => void;
  emitToSession(sessionId: string, event: AgentEvent): void;

  // Maintenance
  updateStatus(sessionId: string, status: SessionStatus): void;
  getStats(): SessionStats;
}
```

Key features:
- **Automatic cleanup**: Expired sessions are removed
- **Event distribution**: Subscribers receive real-time updates
- **Token tracking**: Usage is tracked per session

### 4. Server (`server.ts`)

Exposes the agent via HTTP/WebSocket API:

```typescript
class AgentServer {
  // Lifecycle
  async start(): Promise<void>;
  async stop(): Promise<void>;

  // Connection handling
  async handleConnection(connectionId: string): Promise<void>;
  async handleMessage(connectionId: string, rawMessage: string): Promise<string | null>;
  async closeConnection(connectionId: string): Promise<void>;
}

// Create and start server
const server = createAgentServer({
  port: 3000,
  maxSessions: 100,
  sessionTimeout: 30 * 60 * 1000,
  rateLimit: { maxRequests: 100, windowMs: 60000 },
});
await server.start();
```

### 5. Client (`client.ts`)

Provides a clean SDK for connecting to servers:

```typescript
class AgentClient {
  // Connection
  async connect(): Promise<void>;
  async disconnect(): Promise<void>;
  getState(): ConnectionState;

  // Sessions
  async createSession(config?: SessionConfig): Promise<Session>;
  async getSession(sessionId: string): Promise<Session | null>;
  async closeSession(sessionId: string): Promise<void>;

  // Messaging
  async sendMessage(sessionId: string, content: string): Promise<Message>;
  async *streamMessage(sessionId: string, content: string): AsyncIterable<StreamChunk>;

  // Events
  subscribe(listener: AgentEventListener): () => void;
}

// Use the client
const client = createAgentClient({ serverUrl: 'http://localhost:3000' });
await client.connect();

const session = await client.createSession({ model: 'gpt-4' });
const response = await client.sendMessage(session.id, 'Hello!');
```

## Key Patterns

### Request/Response with Correlation IDs

Every request has a unique ID that the response references:

```typescript
// Client sends request with ID
{
  "type": "request",
  "payload": {
    "id": "req-123",
    "method": "session.create",
    "params": { "model": "gpt-4" }
  }
}

// Server responds with same ID
{
  "type": "response",
  "payload": {
    "id": "req-123",
    "success": true,
    "data": { "id": "session-456", ... }
  }
}
```

### Request Queue with Timeouts

The client tracks pending requests and handles timeouts:

```typescript
class RequestQueue {
  add<T>(requestId: string, timeout?: number): Promise<T>;
  resolve(requestId: string, result: unknown): boolean;
  reject(requestId: string, error: Error): boolean;
  cancelAll(reason: string): void;
}

// Usage
const responsePromise = queue.add<Session>('req-123', 30000);

// Later, when response arrives
queue.resolve('req-123', sessionData);
```

### Event Streaming

Real-time updates via async iterables:

```typescript
// Server emits events
sessionManager.emitToSession(sessionId, {
  type: 'message.delta',
  messageId: 'msg-123',
  delta: 'Hello',
});

// Client receives events
for await (const event of client.subscribeToSession(sessionId)) {
  if (event.type === 'message.delta') {
    process.stdout.write(event.delta);
  }
}
```

### Connection State Machine

Client tracks connection state:

```
disconnected ─── connect() ──▶ connecting ──▶ connected
     ▲                              │              │
     │                              ▼              │
     └──────────────────── reconnecting ◀─────────┘
                              (on error)
```

### Rate Limiting

Server protects against abuse:

```typescript
interface RateLimitConfig {
  maxRequests: number;
  windowMs: number;
}

// Check before processing
if (!checkRateLimit(connectionId)) {
  return buildErrorResponse(requestId, 'RATE_LIMITED', 'Too many requests');
}
```

## Streaming Responses

### Server-Side Streaming

```typescript
// Server streams response chunks
async *generateResponse(sessionId: string, content: string): AsyncIterable<StreamChunk> {
  const chunks = await llm.streamChat(content);

  for await (const chunk of chunks) {
    yield { type: 'text', content: chunk };

    // Also emit as event for subscribers
    this.emitToSession(sessionId, {
      type: 'message.delta',
      delta: chunk,
    });
  }

  yield { type: 'done', messageId: 'msg-123' };
}
```

### Client-Side Consumption

```typescript
// Client consumes stream
const fullResponse: string[] = [];

for await (const chunk of client.streamMessage(sessionId, 'Tell me a story')) {
  switch (chunk.type) {
    case 'text':
      process.stdout.write(chunk.content);
      fullResponse.push(chunk.content);
      break;
    case 'done':
      console.log('\nCompleted:', chunk.messageId);
      break;
    case 'error':
      console.error('Error:', chunk.error);
      break;
  }
}
```

## Error Handling

### Error Codes

```typescript
type ErrorCode =
  | 'INVALID_REQUEST'    // Malformed request
  | 'SESSION_NOT_FOUND'  // Session doesn't exist
  | 'SESSION_EXPIRED'    // Session timed out
  | 'RATE_LIMITED'       // Too many requests
  | 'SERVER_ERROR'       // Internal error
  | 'TIMEOUT'            // Request timed out
  | 'CANCELLED'          // Operation cancelled
  | 'UNAUTHORIZED';      // Auth failed
```

### Custom Error Types

```typescript
class SessionNotFoundError extends Error {
  constructor(sessionId: string) {
    super(`Session not found: ${sessionId}`);
    this.name = 'SessionNotFoundError';
  }
}

// Handler maps errors to codes
if (err instanceof SessionNotFoundError) {
  return buildErrorResponse(requestId, 'SESSION_NOT_FOUND', err.message);
}
```

### Client Error Handling

```typescript
try {
  const session = await client.getSession('invalid-id');
} catch (err) {
  if (err.message.includes('SESSION_NOT_FOUND')) {
    console.log('Session does not exist');
  }
}
```

## Real-World Implementations

### OpenAI API

```typescript
// Similar pattern: client SDK connecting to server
const openai = new OpenAI({ apiKey: 'sk-...' });

const response = await openai.chat.completions.create({
  model: 'gpt-4',
  messages: [{ role: 'user', content: 'Hello!' }],
  stream: true,
});

for await (const chunk of response) {
  process.stdout.write(chunk.choices[0]?.delta?.content || '');
}
```

### Language Server Protocol (LSP)

```typescript
// VS Code uses similar client/server separation
const client = new LanguageClient('typescript', 'TypeScript', serverOptions, clientOptions);

client.onNotification('textDocument/publishDiagnostics', (params) => {
  // Handle diagnostics from server
});

await client.start();
```

## Running the Demo

```bash
npx ts-node --esm 13-client-server/main.ts
```

Expected output:
```
======================================================================
Lesson 13: Client/Server Separation
======================================================================

📡 Part 1: Basic Client Connection

Initial state: disconnected
After connect: connected

❤️ Part 2: Health Check

Server health: { status: 'healthy', version: '1.0.0', uptime: '0s', activeSessions: 0, load: '0.0%' }

🗂️ Part 3: Session Management

Created session: { id: 'session-...', status: 'active', model: 'gpt-4' }
...
```

## Key Takeaways

1. **Separation of Concerns**: UI and agent logic can evolve independently

2. **Protocol Design**: Clear message formats with correlation IDs enable reliable communication

3. **Session Management**: Server maintains state, clients are stateless

4. **Event Streaming**: Async iterables provide clean streaming APIs

5. **Error Handling**: Typed error codes enable proper client-side handling

6. **Rate Limiting**: Protect server resources from abuse

7. **Connection Management**: Handle disconnects and reconnects gracefully

## Extension Ideas

- **Authentication**: Add API key validation or OAuth
- **WebSocket**: Replace HTTP polling with WebSocket for real-time events
- **Load Balancing**: Add session affinity for multi-server deployments
- **Persistence**: Store sessions in Redis/database for durability
- **Metrics**: Add Prometheus metrics for monitoring

## Advanced: Session Persistence (JSONL)

The production agent implements session persistence using JSONL (JSON Lines) format for crash-safe, append-only storage.

### Why JSONL?

```
JSON (entire file must be valid):
┌─────────────────────────────────────────────────────────────────┐
│ {"messages":[{"role":"user",...},{"role":"assistant",...}]}   │
│ → Crash during write = corrupted file, entire history lost     │
└─────────────────────────────────────────────────────────────────┘

JSONL (each line is independent):
┌─────────────────────────────────────────────────────────────────┐
│ {"type":"message","data":{...}}                                 │
│ {"type":"message","data":{...}}                                 │
│ {"type":"tool_call","data":{...}}                               │
│ → Crash during write = only last line corrupted, history safe  │
└─────────────────────────────────────────────────────────────────┘
```

### Session Entry Types

```typescript
type SessionEntryType =
  | 'message'     // User or assistant message
  | 'tool_call'   // Tool invocation
  | 'tool_result' // Tool response
  | 'checkpoint'  // Manual save point
  | 'compaction'  // Summary of compacted messages
  | 'metadata';   // Session metadata updates

interface SessionEntry {
  timestamp: string;
  type: SessionEntryType;
  data: unknown;
}
```

### Session Store

```typescript
class SessionStore {
  // Create new session
  async createSession(name?: string): Promise<string> {
    const id = `session-${Date.now().toString(36)}-${randomId()}`;

    const metadata: SessionMetadata = {
      id,
      name,
      createdAt: new Date().toISOString(),
      lastActiveAt: new Date().toISOString(),
      messageCount: 0,
      tokenCount: 0,
    };

    this.index.sessions.unshift(metadata);
    await this.saveIndex();
    return id;
  }

  // Append entry (crash-safe)
  async appendEntry(entry: Omit<SessionEntry, 'timestamp'>): Promise<void> {
    const fullEntry = {
      ...entry,
      timestamp: new Date().toISOString(),
    };

    // Append single line to file
    const sessionPath = join(this.baseDir, `${sessionId}.jsonl`);
    await writeFile(sessionPath, JSON.stringify(fullEntry) + '\n', { flag: 'a' });

    // Update index
    await this.saveIndex();
  }

  // Load session entries
  async loadSession(sessionId: string): Promise<SessionEntry[]> {
    const content = await readFile(`${sessionId}.jsonl`, 'utf-8');
    const entries: SessionEntry[] = [];

    for (const line of content.split('\n')) {
      if (line.trim()) {
        try {
          entries.push(JSON.parse(line));
        } catch {
          // Skip corrupted lines (crash recovery)
        }
      }
    }

    return entries;
  }

  // Reconstruct messages for LLM
  async loadSessionMessages(sessionId: string): Promise<Message[]> {
    const entries = await this.loadSession(sessionId);
    const messages: Message[] = [];

    for (const entry of entries) {
      if (entry.type === 'message') {
        messages.push(entry.data as Message);
      } else if (entry.type === 'compaction') {
        // Insert compaction summary as context
        const compaction = entry.data as { summary: string };
        messages.push({
          role: 'system',
          content: `[Previous conversation summary]\n${compaction.summary}`,
        });
      }
    }

    return messages;
  }
}
```

### Session Index

Metadata stored separately for fast listing:

```typescript
interface SessionIndex {
  version: number;
  sessions: SessionMetadata[];
}

interface SessionMetadata {
  id: string;
  name?: string;
  createdAt: string;
  lastActiveAt: string;
  messageCount: number;
  tokenCount: number;
  summary?: string;  // AI-generated summary
}
```

### Compaction Integration

When context is compacted (see Lesson 9), store the summary:

```typescript
// After compaction
await sessionStore.appendEntry({
  type: 'compaction',
  data: {
    summary: 'User was working on implementing OAuth. Key decisions...',
    compactedCount: 50,  // Messages summarized
    compactedAt: new Date().toISOString(),
  },
});
```

### Convenience Methods

```typescript
// Quick message append
await store.appendMessage({ role: 'user', content: 'Hello' });
await store.appendMessage({ role: 'assistant', content: 'Hi there!' });

// Tool tracking
await store.appendToolCall({ id: 'call_123', name: 'read_file', args: {...} });
await store.appendToolResult('call_123', { content: '...' });
```

### Events

```typescript
store.on((event) => {
  switch (event.type) {
    case 'session.created':
      console.log(`Created session: ${event.sessionId}`);
      break;
    case 'session.loaded':
      console.log(`Loaded ${event.entryCount} entries`);
      break;
    case 'entry.appended':
      console.log(`Appended ${event.entryType} to ${event.sessionId}`);
      break;
  }
});
```

### Auto-Pruning

Old sessions are automatically removed:

```typescript
const store = new SessionStore({
  baseDir: '.agent/sessions',
  maxSessions: 50,  // Keep last 50 sessions
  autoSave: true,   // Save index on each entry
});

// Old sessions pruned when limit exceeded
await store.createSession('new-session');
```

### Directory Structure

```
.agent/sessions/
├── index.json                    # Session metadata index
├── session-abc123.jsonl          # Session entries
├── session-def456.jsonl
└── session-ghi789.jsonl
```
