# Exercise: Session Manager

## Objective
Implement a session manager for client-server agent communication.

## Time: ~12 minutes

## Your Task
Open `exercise-1.ts` and implement the `SessionManager` class.

## Requirements
1. **Create sessions** with unique IDs
2. **Track session state** (active, idle, terminated)
3. **Handle session timeout** and cleanup
4. **Store session context**

## Example Usage
```typescript
const manager = new SessionManager({ timeoutMs: 30000 });
const session = await manager.create({ userId: 'user1' });
await manager.update(session.id, { lastActivity: Date.now() });
await manager.terminate(session.id);
```

## Testing
```bash
npm run test:lesson:13:exercise
```
