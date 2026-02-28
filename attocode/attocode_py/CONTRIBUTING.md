# Contributing to Attocode

## Getting Started

```bash
git clone https://github.com/eren23/attocode.git
cd attocode/attocode_py

uv sync --all-extras          # creates .venv, installs everything
# or: python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

## Development Workflow

1. Create a feature branch from `main`
2. Make changes, add tests
3. Run `pytest tests/unit/ -x -q` for fast feedback
4. Run `ruff check src/ tests/` for linting
5. Open a pull request

## Running Tests

```bash
# All tests
pytest tests/

# Unit tests only (fast, no I/O)
pytest tests/unit/ -x -q

# Specific module
pytest tests/unit/integrations/test_agents.py -v

# With coverage
pytest tests/ --cov=src/attocode --cov-report=term-missing

# Skip known pre-existing failures
pytest tests/unit/ --ignore=tests/unit/attoswarm -x
```

## Code Style

- **Formatter/Linter:** [Ruff](https://docs.astral.sh/ruff/)
- **Type checker:** [mypy](https://mypy-lang.org/) (strict mode)
- **Test framework:** [pytest](https://docs.pytest.org/) with `pytest-asyncio`
- Use `@dataclass` for data containers
- Use `AsyncMock` for async dependencies in tests
- Group related tests in classes: `class TestFeatureName:`

## Project Structure

```
src/
  attocode/          Main agent package
  attoswarm/         Standalone swarm orchestration
  attocode_core/     Shared AST indexing
tests/
  unit/              Fast tests, no I/O
  integration/       Slower tests requiring I/O
```

See [Architecture](ARCHITECTURE.md) for detailed module documentation.

## Adding a New Tool

1. Create `src/attocode/tools/my_tool.py` implementing `BaseTool`
2. Register in `src/attocode/tools/registry.py`
3. Add tests in `tests/unit/tools/test_my_tool.py`
4. Update the policy table in `src/attocode/integrations/safety/policy_engine.py` if the tool needs special permissions

## Adding a New Provider

1. Create adapter in `src/attocode/providers/adapters/`
2. Implement `LLMProvider` base class from `providers/base.py`
3. Register in `providers/registry.py`
4. Add model defaults in `config.py`
5. See [Providers](PROVIDERS.md)

## Adding a New Integration

1. Pick the appropriate subdirectory under `src/attocode/integrations/` (or create one)
2. Add your module
3. Export from the subdirectory's `__init__.py`
4. Write tests in `tests/unit/integrations/`

## Commit Messages

Use conventional commit style:

```
feat(budget): add dynamic budget reallocation
fix(sandbox): handle missing Landlock kernel support
test(recording): add playback engine unit tests
docs(providers): add OpenAI adapter reference
```

## Known Pre-existing Test Failures

These tests fail in CI due to environment assumptions and are safe to ignore:

| Test | Reason |
|------|--------|
| `test_mcp.py::test_empty_when_no_files` | Global MCP defaults now include context7 |
| `test_attoswarm_smoke.py::test_two_claude_smoke_fake_worker` | Swarm integration timing |
| `test_cli.py::test_init_interactive_minimal_existing_repo` | Attoswarm CLI change |
