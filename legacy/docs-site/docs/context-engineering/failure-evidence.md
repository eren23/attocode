---
sidebar_position: 5
title: Failure Evidence (Trick S)
---

# Failure Evidence (Trick S)

## Problem

When tool errors are silently discarded or minimally logged, the model has no memory of what went wrong. Without structured evidence of past failures, the agent repeats the same mistakes -- reading a file that does not exist, calling a tool with wrong arguments, or hitting the same permission error over and over. This creates doom loops that waste tokens and time.

## Solution

Explicitly preserve failure evidence with structured metadata: what was attempted, what failed, why it failed, and what to try instead. This evidence is injected into the context so the model can learn and adapt within a single session.

## Failure Categories

Errors are auto-categorized based on their message content:

| Category | Matched Patterns |
|----------|-----------------|
| `permission` | "permission denied", "access denied", "EACCES", "unauthorized" |
| `not_found` | "not found", "no such file", "ENOENT", "does not exist", "404" |
| `syntax` | "syntax error", "unexpected token", "parse error", "invalid json" |
| `type` | "type error", "TypeError", "is not a function", "cannot read propert" |
| `runtime` | General runtime exceptions |
| `network` | "network", "connection", "ECONNREFUSED", "socket", "fetch failed" |
| `timeout` | "timeout", "timed out", "ETIMEDOUT" |
| `validation` | "validation", "invalid", "required", "must be" |
| `logic` | "assertion", "invariant", "expect" |
| `resource` | "out of memory", "disk full", "ENOMEM", "ENOSPC", "quota" |
| `unknown` | Anything that does not match the above |

## Failure Structure

```typescript
interface Failure {
  id: string;                           // Unique ID
  timestamp: string;                    // When it occurred
  action: string;                       // Tool/action attempted
  args?: Record<string, unknown>;       // Arguments passed
  error: string;                        // Error message
  stackTrace?: string;                  // Full stack trace (if available)
  category: FailureCategory;            // Auto-detected or manual
  iteration?: number;                   // Agent iteration when this occurred
  intent?: string;                      // What was the goal
  suggestion?: string;                  // Auto-generated fix suggestion
  resolved: boolean;                    // Whether this has been addressed
  repeatCount: number;                  // Times similar failure occurred
}
```

## FailureTracker

The main class for recording and querying failures:

```typescript
const tracker = createFailureTracker({
  maxFailures: 50,              // Keep at most 50 in memory
  preserveStackTraces: true,    // Store full stack traces
  categorizeErrors: true,       // Auto-categorize by message content
  detectRepeats: true,          // Count similar failures
  repeatWarningThreshold: 3,    // Warn after 3 repeats
});
```

### Recording Failures

```typescript
tracker.recordFailure({
  action: 'read_file',
  args: { path: '/etc/passwd' },
  error: 'Permission denied',
  iteration: 12,
  intent: 'Check system configuration',
});
```

The tracker automatically:
1. Categorizes the error (`permission`)
2. Counts similar failures (same action + error prefix)
3. Generates a suggestion based on category
4. Emits `failure.recorded` event
5. Emits `failure.repeated` event if `repeatCount >= threshold`
6. Evicts oldest failure if `maxFailures` is exceeded (with warning)

### Pattern Detection

The tracker detects four types of failure patterns:

| Pattern | Detection Rule | Confidence |
|---------|---------------|------------|
| `repeated_action` | Same action fails 3+ times (all unresolved) | 0.3 + count * 0.1 |
| `repeated_error` | Same error message prefix appears repeatedly | Based on count |
| `category_cluster` | 5+ of last 10 failures share same category | count / 10 |
| `escalating` | Failures increasing in severity over time | Based on trend |

When a pattern is detected, a `pattern.detected` event is emitted with a suggestion:

```typescript
tracker.on((event) => {
  if (event.type === 'pattern.detected') {
    console.log(event.pattern.suggestion);
    // "Consider an alternative approach. 'read_file' is consistently failing."
  }
});
```

### Getting Failure Context for LLM

The `getFailureContext()` method generates a formatted block suitable for injection into the agent's context:

```
[Previous Failures - Learn from these to avoid repeating mistakes]

**read_file** (permission): Permission denied
  Args: {"path":"/etc/passwd"}
  -> Check file/directory permissions. The action "read_file" may need
     elevated privileges or the path may be restricted.

**bash** (not_found): No such file or directory: /tmp/missing.sh
  Args: {"command":"bash /tmp/missing.sh"}
  -> Verify the resource exists before accessing. Use list_directory
     or check for typos in the path.
```

### Extracting Insights

The `extractInsights()` function analyzes failure patterns and returns actionable suggestions:

```typescript
const insights = extractInsights(tracker.getUnresolvedFailures());
// [
//   'Multiple permission errors - check if running with sufficient privileges',
//   '"read_file" failed 4 times - try an alternative tool/approach',
// ]
```

## Cross-Worker Sharing

In swarm mode, the `ContextEngineeringManager` replaces its local `FailureTracker` with the shared one from `SharedContextState`. This means all workers in a swarm learn from each other's failures in real time.

```typescript
// When a worker joins a swarm
contextEngineering.setSharedState(sharedState);
// Now all workers read/write to the same FailureTracker
```

## Injection Budget Integration

Failure context is assigned **priority 2** (Medium) in the `InjectionBudgetManager`. It ranks above goal recitation (priority 3) but below doom loop detection (priority 1) and budget warnings (priority 0).

## Key File

`src/tricks/failure-evidence.ts` (~817 lines)
