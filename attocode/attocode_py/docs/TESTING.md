# Testing Guide

## Running Tests

```bash
# All tests
pytest tests/

# Unit tests only (fast)
pytest tests/unit/ -x -q

# Specific module
pytest tests/unit/integrations/test_agents.py -v

# With coverage
pytest tests/ --cov=src/attocode --cov-report=term-missing

# Skip known failures
pytest tests/unit/ --ignore=tests/unit/attoswarm -x
```

## Test Structure

```
tests/
├── unit/                          # Fast, no I/O
│   ├── core/                      # Execution loop, agent state machine
│   ├── integrations/              # Budget, context, safety, persistence
│   ├── providers/                 # LLM provider adapters
│   ├── tools/                     # Tool implementations
│   ├── tui/                       # TUI widgets and screens
│   ├── types/                     # Type definitions
│   └── attoswarm/                 # Standalone swarm package
└── integration/                   # Slower, requires I/O
    ├── test_session_persistence.py
    └── test_attoswarm_smoke.py
```

## Writing Tests

### Conventions

- Use `pytest` (not unittest)
- Use `@dataclass` for test fixtures where possible
- Use `tmp_path` fixture for filesystem tests
- Use `AsyncMock` for async dependencies
- Group related tests in classes: `class TestFeatureName:`
- Test file naming: `test_<module_name>.py`

### Example

```python
import pytest
from unittest.mock import AsyncMock

class TestMyFeature:
    @pytest.fixture
    def my_fixture(self, tmp_path):
        # Setup
        return MyClass(path=tmp_path)

    def test_basic_behavior(self, my_fixture):
        result = my_fixture.do_thing()
        assert result.success

    @pytest.mark.asyncio
    async def test_async_behavior(self, my_fixture):
        result = await my_fixture.do_async_thing()
        assert result is not None
```

## Known Pre-existing Failures

| Test | Reason |
|------|--------|
| `test_mcp.py::test_empty_when_no_files` | Global MCP defaults now include context7 |
| `test_attoswarm_smoke.py::test_two_claude_smoke_fake_worker` | Swarm integration timing |
| `test_cli.py::test_init_interactive_minimal_existing_repo` | Attoswarm CLI change |

## Coverage Targets

| Module | Current | Target |
|--------|---------|--------|
| `agent/` | ~70% | 85% |
| `core/` | ~50% | 80% |
| `tools/` | ~60% | 80% |
| `integrations/` | ~40% | 70% |
| `tui/` | ~30% | 50% |
