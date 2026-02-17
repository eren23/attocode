---
sidebar_position: 4
title: "Known Issues"
---

# Known Issues

Current limitations, technical debt, and areas for improvement in the Attocode codebase.

## Architecture

### God Object Pattern

`src/agent.ts` is approximately 3,100 lines with 30+ nullable manager references. Despite extractions into `src/agent/` modules (builder, feature-initializer, message-builder, session-api), the core `ProductionAgent` class still concentrates too many responsibilities.

**Impact:** Difficult to test individual features in isolation. High cognitive load when making changes.

### Embedded TUI

`src/main.ts` contains the `TUIApp` component alongside CLI parsing, totaling around 3,270 lines. The TUI should ideally be in a separate module.

**Impact:** Long initial load time, difficult to maintain.

### Circular Dependency Risk

The Phase 3 extraction pattern uses `this as unknown as DepsType` casts to break circular imports. While `import type` cycles are benign (erased at compile time), the runtime casts bypass TypeScript's type safety.

**Impact:** Refactoring can introduce subtle type errors that the compiler does not catch.

## Testing

### Pre-existing Test Failures

8 test files with 41 tests have known failures:

- `modernization.test.ts`
- `safety.test.ts`
- `retry.test.ts`
- `codebase-context-lsp.test.ts`
- `decision-traceability.test.ts`
- `resilience-all-paths.test.ts`
- `economics-incremental.test.ts`
- `bash-classification.test.ts`

These failures predate current development and should be fixed incrementally.

### Low Coverage

The coverage threshold is set at 20% with TUI components excluded. There are no integration tests for the full agent loop (prompt to result).

**Impact:** Regressions can be introduced without test failures catching them.

## Reliability

### Swarm Resume Fragility

When a swarm session crashes mid-execution, partial worker results may be lost. The swarm recovery system (`swarm-recovery.ts`) attempts to resume, but results from workers that completed between the last checkpoint and the crash are not guaranteed to be available.

### MCP Stdio Fragility

MCP server connections use stdio with no health checking or automatic reconnection. If an MCP server process crashes, its tools become unavailable until the agent is restarted.

**Workaround:** Restart the agent to reinitialize MCP connections.

### Trace File Growth

Trace files in `.traces/` grow without automatic rotation or compression. Long-running or frequent sessions can consume significant disk space.

**Workaround:** Manually delete old trace files: `find .traces -name "*.jsonl" -mtime +7 -delete`

## Platform Limitations

### No Windows Sandbox

Sandbox support exists only for macOS (Seatbelt) and Linux (Landlock). Windows has no sandbox implementation.

**Impact:** On Windows, the agent runs all bash commands without filesystem or network restrictions.

### Tree-sitter Loading Latency

Tree-sitter language bindings are loaded on first use per language. The initial parse of a new language incurs 1-2 seconds of latency.

**Impact:** Minor UX delay on first code analysis per language.

## Feature Gaps

### Semantic Cache Requires Embedding Model

The semantic cache (`src/integrations/context/semantic-cache.ts`) requires an embedding model to compute similarity. There is no fallback for environments where embeddings are unavailable.

**Impact:** The feature silently does nothing without an embedding provider.

### No Automatic Trace Rotation

The trace capture system writes JSONL files but has no built-in rotation, compression, or size limits.

### Stale Documentation

The `docs/` directory in the main source tree contains partially stale documentation from earlier development phases. The canonical documentation is in `docs-site/`.

## Performance

### Context Window Pressure

For long sessions, the context window can fill even with auto-compaction. The compaction system summarizes older messages but may lose fine-grained details needed for later reference.

**Mitigation:** The reversible compaction system stores references that can be retrieved, but retrieval adds latency.

### Agent Startup Time

Feature initialization creates up to 30+ manager instances. On slower machines, agent startup can take several seconds.

## Planned Improvements

- Further extraction of `agent.ts` to reduce class size
- Integration test suite for end-to-end agent flows
- MCP connection health monitoring and reconnection
- Trace file rotation with configurable retention
- Windows sandbox support (possibly via WSL integration)
- Increase test coverage threshold as tests are added
