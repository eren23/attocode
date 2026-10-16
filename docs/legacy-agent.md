# Archived agent and migration

The agent is retired from active development in this repository. Its complete
Python agent, swarm, older TypeScript implementation, lessons, tests and original
development instructions are preserved at
[agent-archive-2026-10-16](https://github.com/eren23/attocode/tree/agent-archive-2026-10-16),
commit `9518a3d7724e2d9fe3f169a0d4a9b2d9ee492500`.

Use a separate checkout of that tag for historical agent work. The tag is an
archive, not a new package release or a promise of continued agent maintenance.
The existing `attocode` distribution and its commands have not been renamed or
repurposed into intelligence. Existing global installations are not modified by
this repository migration.

For intelligence, install `attocode-code-intel` and use its CLI directly. Python
integrations should import `attocode_intel`; the retired `attocode.code_intel`
and agent-internal compatibility imports belong to the archive. Run `init` and
`doctor` for your chosen MCP client, and restart that client after changing its
server executable. Existing `.attocode` indexes, client settings, credentials,
shared caches and frozen study environments are not deleted by this migration.

The active repository retains the intelligence engine, MCP/CLI/API, database
migrations, dashboard, Docker deployment, rule packs, benchmarks and their useful
unit/integration fixtures. Tests that previously reached this engine through
agent aliases now import the standalone package directly. Agent-specific
orchestration, TUI and provider tests remain in the archive.

This is a product and maintenance decision. The intelligence studies do not
establish that the archived agent was useless. Historical evaluation results and
failed trials remain available with their original limitations.
