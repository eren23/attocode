# Exercise: Rules Merger

## Objective
Implement a rules merger that combines configuration from multiple sources with priority.

## Time: ~12 minutes

## Your Task
Open `exercise-1.ts` and implement the `RulesMerger` class.

## Requirements
1. **Load rules** from multiple sources
2. **Merge with priority** (higher priority wins conflicts)
3. **Support nested objects** and arrays
4. **Validate merged output**

## Example Usage
```typescript
const merger = new RulesMerger();
merger.addSource('global', globalRules, 1);
merger.addSource('project', projectRules, 2);
const merged = merger.merge();
```

## Testing
```bash
npm run test:lesson:12:exercise
```
