# Exercise: Hook Registration

## Objective
Implement an event hook system that allows registering and executing hooks with priority ordering.

## Time: ~12 minutes

## Your Task
Open `exercise-1.ts` and implement the `HookRegistry` class.

## Requirements
1. **Register hooks** with name, handler, and priority
2. **Execute hooks** in priority order (lower number = higher priority)
3. **Support async hooks** that can modify or block events
4. **Allow hook removal** by name

## Example Usage
```typescript
const registry = new HookRegistry();
registry.register('log', async (event) => console.log(event), 10);
registry.register('validate', async (event) => event.valid, 5);
await registry.execute('tool.before', { tool: 'read_file' });
```

## Testing
```bash
npm run test:lesson:10:exercise
```
