# Project Rules

This repository contains multiple generations of the project. Unless the user
explicitly asks otherwise, the source of truth is the Python implementation.

Focus on these paths by default:
- `src/attocode/**`
- `src/attoswarm/**`
- `tests/unit/**`
- `.attocode/**` when project configuration or persistent rules matter

Treat these paths as out of scope unless the user explicitly asks for them:
- `legacy/**`
- `frontend/**`
- `lessons/**`
- old docs that describe the JS/TS implementation

For TUI work, default to the Python Textual implementation:
- `src/attocode/tui/**`
- `src/attoswarm/tui/**`

Do not explain behavior in terms of the JS/TS version when the user is asking
about the Python TUI or Python swarm stack.

If multiple implementations appear relevant, prefer the Python paths above and
only bring in legacy references when needed for migration or historical context.
