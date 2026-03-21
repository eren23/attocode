# Advanced Analysis

Three complementary tools for deep codebase analysis: dead code detection, code distillation, and graph DSL queries. Available as MCP tools and through the HTTP API.

## Dead Code Detection

The `dead_code` tool identifies unreferenced symbols, files, and modules using the cross-reference index. Results are ranked by a confidence score reflecting how likely the code is truly unused.

### Analysis Levels

| Level | What it finds | Use case |
|-------|--------------|----------|
| `symbol` | Functions, classes, methods with zero external references | Cleaning up unused internal code |
| `file` | Files with zero importers (not entry points) | Finding abandoned modules |
| `module` | Directories with no external imports from outside | Identifying dead packages |

### Entry Point Heuristics

Dead code detection automatically excludes known entry points to avoid false positives:

**Auto-detected entry-point files:**

- `main.py`, `__main__.py`, `__init__.py`, `setup.py`, `manage.py`, `conftest.py`
- Files starting with `test_` or ending with `_test.py`

**Auto-detected entry-point symbols:**

- Functions named `main`, `setup`, `teardown`
- Symbols with framework decorators containing: `route`, `endpoint`, `fixture`, `command`, `click`
- Symbols defined in `__init__.py` (treated as re-exports)

You can also specify additional entry points manually via the `entry_points` parameter.

### Confidence Scoring

Each result includes a confidence score from 0.0 to 1.0:

| Factor | Effect |
|--------|--------|
| Private name (leading `_`) | +0.1 (base 0.8 vs 0.7) |
| Defined in `__init__.py` | -0.3 |
| Public name (no `_` prefix) | -0.2 |
| File not modified in 180+ days | +0.1 |

Higher confidence = safer to remove. Use `min_confidence` to filter results.

### Examples

**MCP tool:**

```
dead_code(level="symbol", scope="src/api/", min_confidence=0.6, top_n=20)
```

**Sample output (symbol level):**

```
Dead symbols detected in src/api/ (5 results):

   1. [0.80] function _legacy_auth_check
      src/api/security.py:142
      Reason: function never called or imported; private symbol

   2. [0.70] class DeprecatedHandler
      src/api/handlers.py:88
      Reason: class never instantiated or referenced

   3. [0.70] method RequestParser._parse_legacy
      src/api/parsers.py:201
      Reason: method with no external callers
```

**Sample output (file level):**

```
Dead files detected (3 results):

   1. [0.80] src/utils/_old_helpers.py
      12 symbols, 0 dependencies
      Reason: no files import this module; also has no imports (orphan)

   2. [0.70] src/api/v1_compat.py
      5 symbols, 3 dependencies
      Reason: no files import this module
```

**Sample output (module level):**

```
Dead modules detected (2 results):

   1. [0.70] src/legacy_exporters/
      8 files, 34 symbols
      Reason: no external imports into this directory (8 files)

   2. [0.40] src/tools/deprecated/
      3 files, 12 symbols
      Reason: no external imports into this directory (3 files); contains entry-point files (lower confidence)
```

---

## Code Distillation

The `distill` tool compresses codebase information at varying fidelity levels, optimized for different context window budgets.

### Distillation Levels

| Level | Compression | What's included | Best for |
|-------|------------|-----------------|----------|
| `full` | ~0% | Complete repo map with symbols | Full understanding, large context |
| `signatures` | ~70% | Public API surface: function signatures, class definitions, type hints, first-line docstrings | API overview, code review |
| `structure` | ~90%+ | File tree + import graph adjacency list | Quick orientation, small context |

### File Selection

When `files` is specified, the tool includes those files plus neighbors up to `depth` hops via the dependency graph (max 3 hops). When `files` is omitted, auto-selects the most important files by PageRank score that fit within the token budget.

### Examples

**Signatures level** (public API surface):

```
distill(files=["src/auth/middleware.py"], level="signatures", depth=1, max_tokens=2000)
```

Output:

```python
# src/auth/middleware.py
class AuthMiddleware(BaseHTTPMiddleware):
    """JWT authentication middleware."""
    def __init__(self, app: ASGIApp, secret: str, algorithms: list[str] = ["HS256"]): ...
    async def dispatch(self, request: Request, call_next: Callable) -> Response: ...
        """Validate JWT token and inject user into request state."""

async def verify_token(token: str, secret: str) -> dict: ...
    """Verify and decode a JWT token."""

def extract_bearer(authorization: str) -> str | None: ...
    """Extract bearer token from Authorization header."""

# src/auth/tokens.py
def create_access_token(user_id: str, expires_delta: timedelta = ...) -> str: ...
    """Create a signed JWT access token."""

def create_refresh_token(user_id: str) -> str: ...
    """Create a signed JWT refresh token."""

(4 files, level=signatures, ~380 tokens)
```

**Structure level** (maximum compression):

```
distill(level="structure", max_tokens=1000)
```

Output:

```
# File tree
  src/api/__init__.py
  src/api/app.py
  src/api/routes/admin.py
  src/api/routes/auth.py
  src/api/routes/users.py
  src/auth/middleware.py
  src/auth/tokens.py
  src/config.py
  src/db/session.py
  src/models/user.py

# Import graph (file -> imports)
  src/api/app.py -> src/api/routes/admin.py, src/api/routes/auth.py, src/auth/middleware.py, src/config.py
  src/api/routes/auth.py -> src/auth/tokens.py, src/models/user.py, src/db/session.py
  src/auth/middleware.py -> src/auth/tokens.py, src/config.py, src/db/session.py

(10 files, level=structure, ~120 tokens)
```

**Full level** (delegates to `repo_map`):

```
distill(level="full", max_tokens=8000)
```

---

## Graph DSL

The `graph_dsl` tool provides a Cypher-inspired query language for traversing the dependency graph with depth constraints, filters, and multi-hop chains.

### Syntax Reference

```
MATCH <pattern> [WHERE <conditions>] RETURN <variables>
```

#### Nodes

- **Variable**: `target`, `caller`, `a`, `b` --- matches any file, binds to a variable name
- **Literal path**: `"src/api/app.py"` --- matches a specific file
- **Glob pattern**: `"src/api/*.py"` --- matches files by glob

#### Edges

- **Outbound**: `node -[EDGE_TYPE]-> node`
- **Inbound**: `node <-[EDGE_TYPE]- node`
- **Exact depth**: `-[IMPORTS*3]->`  (exactly 3 hops)
- **Depth range**: `-[IMPORTS*1..3]->` (1 to 3 hops)
- **Default depth**: `-[IMPORTS]->` (exactly 1 hop)

#### Edge Types

| Edge type | Meaning |
|-----------|---------|
| `IMPORTS` | File A imports file B |
| `IMPORTED_BY` | File A is imported by file B |

#### WHERE Clause

Filter results by file properties. Multiple conditions are AND-separated.

```
WHERE variable.field operator value
```

**Available fields:**

| Field | Type | Description |
|-------|------|-------------|
| `language` | string | File language (e.g. `"python"`, `"typescript"`) |
| `line_count` | int | Number of lines |
| `importance` | float | PageRank importance score |
| `path` | string | Relative file path |
| `fan_in` | int | Number of files that import this file |
| `fan_out` | int | Number of files this file imports |
| `is_test` | bool | Whether the file is a test file |
| `is_config` | bool | Whether the file is a config file |

**Available operators:** `=`, `!=`, `>`, `<`, `>=`, `<=`, `LIKE`

#### RETURN Clause

- `RETURN target` --- return file paths bound to `target`
- `RETURN target.language, target.line_count` --- return specific fields
- `RETURN COUNT` --- return count of matches

### Example Queries

**1. Find all files imported by a specific file (1 hop):**

```
MATCH "src/api/app.py" -[IMPORTS]-> target RETURN target
```

**2. Find transitive dependencies up to 3 hops:**

```
MATCH "src/api/app.py" -[IMPORTS*1..3]-> target RETURN target
```

**3. Find all callers of a module:**

```
MATCH "src/auth/middleware.py" <-[IMPORTED_BY]- caller RETURN caller
```

**4. Find Python files that import a module:**

```
MATCH "src/config.py" <-[IMPORTED_BY]- caller WHERE caller.language = "python" RETURN caller
```

**5. Find large files in the import chain:**

```
MATCH "src/core/loop.py" -[IMPORTS*1..2]-> dep WHERE dep.line_count > 500 RETURN dep, dep.line_count
```

**6. Multi-hop chain --- find files 2 hops downstream:**

```
MATCH a -[IMPORTS]-> b -[IMPORTS]-> c RETURN a, c
```

**7. Find high fan-in files (popular dependencies):**

```
MATCH source -[IMPORTS]-> target WHERE target.fan_in > 10 RETURN target, target.fan_in
```

**8. Find test files that depend on a module:**

```
MATCH "src/auth/middleware.py" <-[IMPORTED_BY]- test WHERE test.is_test = true RETURN test
```

**9. Count dependencies:**

```
MATCH "src/api/app.py" -[IMPORTS*1..3]-> dep RETURN COUNT
```

**10. Glob pattern matching:**

```
MATCH "src/api/*.py" -[IMPORTS]-> dep WHERE dep.path LIKE "src/db%" RETURN dep
```

**Sample output:**

```
Graph DSL results (6 matches):
    1. target=src/auth/tokens.py
    2. target=src/config.py
    3. target=src/db/session.py
    4. target=src/models/user.py
    5. target=src/api/routes/auth.py
    6. target=src/api/routes/admin.py
```
