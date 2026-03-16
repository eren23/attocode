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

## Attoswarm Audit Tests

The post-implementation audit (Phase 1-3) added targeted tests for bug fixes:

| Test File | Tests | Covers |
|-----------|-------|--------|
| `test_git_safety.py` | 13 | `GitSafetyNet`: setup, finalize, persist, stash, non-git no-ops |
| `test_control_messages.py::TestHandleAddTask` | 3 | C2: manifest sync after dynamic add_task |
| `test_control_messages.py::TestApprovalGateResumeSkip` | 3 | H1: skip approval gate on resume |
| `test_cli.py::test_build_start_cmd_*` | 1 | C3: `--no-git-safety` forwarded to subprocess |
| `test_cli.py::test_*_preview_no_monitor_*` | 2 | L2: `--preview --no-monitor` falls back to dry_run |

Run just the audit tests:

```bash
pytest tests/unit/attoswarm/test_git_safety.py \
       tests/unit/attoswarm/test_control_messages.py::TestHandleAddTask \
       tests/unit/attoswarm/test_control_messages.py::TestApprovalGateResumeSkip \
       tests/unit/attoswarm/test_cli.py::test_build_start_cmd_forwards_no_git_safety \
       tests/unit/attoswarm/test_cli.py::test_quick_preview_no_monitor_falls_back_to_dry_run \
       tests/unit/attoswarm/test_cli.py::test_start_preview_no_monitor_falls_back_to_dry_run \
       -v
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
