# Sandbox System

## Overview

The sandbox system provides platform-aware isolation for command execution. Located in `src/attocode/integrations/safety/sandbox/`.

## Implementations

| Implementation | Platform | Mechanism | Status |
|---------------|----------|-----------|--------|
| BasicSandbox | All | Allowlist/blocklist | Production |
| SeatbeltSandbox | macOS | `sandbox-exec` profiles | Production |
| LandlockSandbox | Linux 5.13+ | Landlock LSM syscalls | Production |
| DockerSandbox | All (Docker) | Container isolation | Production |

## Platform Detection

With `mode: "auto"` (default):
1. macOS → SeatbeltSandbox
2. Linux 5.13+ → LandlockSandbox
3. Docker available → DockerSandbox
4. Fallback → BasicSandbox

## Configuration

### Via Config

```json
{
  "sandboxMode": "auto"
}
```

### Via Builder

```python
agent = (
    AgentBuilder()
    .with_sandbox(True)
    .build()
)
```

## BasicSandbox

Validates commands against allowlists and blocklists before execution:

- Default allowed: `node`, `npm`, `git`, `python`, `pip`, `ls`, `cat`, `grep`, etc.
- Default blocked: `rm -rf /`, `sudo`, `chmod 777`, etc.

## SeatbeltSandbox (macOS)

Uses `sandbox-exec` with dynamically generated profiles:

- Restricts filesystem access to writable/readable paths
- Blocks network access by default
- Uses Apple's Seatbelt framework

## LandlockSandbox (Linux)

Uses Linux Landlock LSM via ctypes syscall wrappers:

- `landlock_create_ruleset` - Creates a new ruleset
- `landlock_add_rule` - Adds path-based rules
- `landlock_restrict_self` - Applies restrictions to the process

Requires:
- Linux kernel 5.13+
- `PR_SET_NO_NEW_PRIVS` capability
- No root required

## DockerSandbox

Full container isolation with:

- Configurable memory and CPU limits
- Mount-based filesystem access
- Network isolation
- Timeout enforcement

## Policy Engine

The `PolicyEngine` determines permission levels:

| Tool | Default Policy | Danger Level |
|------|---------------|-------------|
| `read_file`, `glob`, `grep` | ALLOW | Safe |
| `write_file`, `edit_file` | ALLOW | Low |
| `bash` | PROMPT | Medium |
| `spawn_agent` | ALLOW | Low |
| Unknown tools | PROMPT | Medium |

Permissions can be persisted via the `remembered_permissions` table in SQLite.
