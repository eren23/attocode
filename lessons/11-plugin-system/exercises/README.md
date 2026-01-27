# Exercise: Plugin Loader

## Objective
Implement a plugin loader that manages plugin lifecycle and isolated contexts.

## Time: ~12 minutes

## Your Task
Open `exercise-1.ts` and implement the `PluginLoader` class.

## Requirements
1. **Load plugins** from configuration
2. **Initialize plugins** with isolated context
3. **Track plugin state** (loaded, active, error)
4. **Support plugin dependencies**

## Example Usage
```typescript
const loader = new PluginLoader();
await loader.load({ name: 'security', version: '1.0' });
await loader.initialize('security');
const plugin = loader.get('security');
```

## Testing
```bash
npm run test:lesson:11:exercise
```
