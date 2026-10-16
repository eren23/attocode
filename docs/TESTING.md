# Testing intelligence

The [contribution guide](contributing.md) gives the exact local commands. The
active suites are all under `packages/code-intel/tests`:

- Product contract tests at the package test root cover MCP, retrieval, output,
  persistence, SQL/HTTP and incremental workflows.
- `unit/` retains intelligence tests migrated from the agent tree, including
  parsers, lexical/vector stores, rules, API, CLI and evaluation contracts.
- `integration/` exercises real in-process HTTP/MCP and disposable project indexes.
- `fixtures/` contains source-only sample projects and intentionally bad rule inputs.

CI separates these suites to avoid running every migrated test twice. Engine and
integration jobs reject imports from `attocode`, `attoswarm` and `attocode_core`.
PostgreSQL, clean wheels, Docker, optional grammars, real language servers and the
frozen ranking gate remain required. Local environment skips are recorded and
must not be reported as database coverage. Use the bounded quality controller for
resource-sensitive corpus runs; see [quality](intelligence-quality.md).

Historical agent/TUI/provider tests remain with the [archive](legacy-agent.md).
Frozen studies and their original grading environments are preserved.
