# Implementation validation — 2026-09-05–06

Validated locally on macOS with Python 3.12.12:

- **2,066 existing regression tests passed**, with 5 skips and 1 expected failure, covering code intelligence, extracted context modules, and the MCP tool audit.
- **23 standalone product tests passed**, including workspace separation, file freshness, local/shared knowledge, repository authorization, real stdio/HTTP MCP, resource access, response budgets, idle workspace eviction, and remote installation validation.
- **All 20 schema migrations applied to a fresh PostgreSQL 16/pgvector container.** The 21 product tests present at that validation point passed against PostgreSQL; the subsequently added repository-source validation test passed with the full 22-test suite. The disposable container was stopped and removed.
- **The wheel installed into an isolated environment** without the `attocode` distribution. An import guard rejected agent, swarm, TUI, Anthropic, and OpenAI SDK imports; navigation and bundled rules still worked. The clean installation resolved MCP 1.29.1; the main regression environment used MCP 1.26.0.
- **Generated Codex, Claude Code, and Cursor configurations passed `doctor`**, each opening a real stdio MCP session and querying the selected workspace. The fixture path contained spaces. User-level client configurations were not changed.
- **Actual Codex CLI 0.153.4 and Claude Code 2.1.212 sessions called the standalone wheel's `symbols` tool**, returning a fixture function name that was absent from the prompt. Codex recovered from an initial invalid `search_symbols` call; Claude discovered the tool through `ToolSearch`. The sessions used temporary project configurations and existing account authentication. Cursor desktop 3.17.8 is installed, but its headless CLI is unavailable; an actual Cursor agent session remains unverified.
- **The dashboard production build passed.** The existing bundle-size warning remains.
- **The Docker image built on Linux ARM64 and passed its runtime smoke test:** health endpoint, dashboard HTML, MCP authentication, and real code navigation. Embedding dependencies are opt-in; the default image installs no CUDA packages. The disposable smoke-test container was removed.
- **The legacy agent CLI help command passed.** Original agent documentation and compatibility import paths remain available.
- New product modules pass the scoped Ruff check; all standalone Python files compile. The extracted legacy code still has existing style findings under a whole-package Ruff run.

The synthetic 10,000-source-file run discovered 10,001 files including project configuration and recovered all 9,999 expected dependency edges. Cold bootstrap took **7.32 s**, a focused lookup **246 ms**, and warm bootstrap **6.68 s**. Both bootstrap responses contained **1,052 tokens** under a 2,000-token budget. Raw results and workload caveats are in `packages/code-intel/evals/results/`.

The [first GitHub Intelligence run](https://github.com/eren23/attocode/actions/runs/34064068334) passed on Linux for commit `09aaeca`: Python 3.12 and 3.13 each applied all migrations, passed the complete 23-test product suite against PostgreSQL, passed the navigation and catalog gates, and verified an isolated wheel. The dashboard and Docker runtime jobs also passed.

The GitHub `pypi-intelligence` environment is configured to accept only `intel-v*` tags. Publishing requires a matching PyPI trusted publisher and passes through the complete reusable intelligence workflow. No package has been published or service deployed at this validation point. See the [release procedure](intelligence-release.md) for the account setup and verification steps.
