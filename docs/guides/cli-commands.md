# CLI Commands Reference

The `attocode code-intel` CLI exposes code intelligence features directly from the terminal. All commands work in both local mode (direct filesystem analysis) and remote mode (connected to a running code-intel server).

## Quick Reference

| Command | Description |
|---------|-------------|
| `query <text>` | Semantic search across the codebase |
| `symbols <file>` | List symbols in a file or search by name |
| `impact <file> ...` | Show blast radius of file changes |
| `hotspots` | Show risk/complexity hotspots |
| `deps <file>` | Show file dependencies and dependents |
| `gc` | Run garbage collection on orphaned data |
| `verify` | Run integrity checks on the index |
| `reindex` | Force a full reindex of the project |

All commands accept `--project <path>` to specify the project directory (defaults to current directory).

---

## Query Commands

### `query` --- Semantic Search

Search across the codebase using natural language. Uses vector similarity + BM25 keyword matching with Reciprocal Rank Fusion.

```bash
attocode code-intel query "authentication middleware"
attocode code-intel query "error handling" --top 20
attocode code-intel query "database connection" --filter "*.py"
attocode code-intel query "React hooks" --project /path/to/repo
```

**Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--top N` | `10` | Number of results to return |
| `--filter GLOB` | (none) | File pattern filter (e.g. `"*.py"`, `"src/**/*.ts"`) |
| `--project PATH` | `.` | Project directory |

**Sample output:**

```
Semantic search: "authentication middleware" (10 results)

  1. [0.92] src/auth/middleware.py
     JWT token validation and session management

  2. [0.87] src/api/security.py
     Request authentication and authorization checks

  3. [0.81] src/auth/oauth.py
     OAuth2 provider integration
```

---

### `symbols` --- Symbol Listing

List all symbols (functions, classes, methods, variables) in a file, or search for symbols by name across the project.

```bash
# List symbols in a file
attocode code-intel symbols src/auth/middleware.py

# Search for a symbol by name
attocode code-intel symbols --search "authenticate"

# Combine with project flag
attocode code-intel symbols src/app.py --project /path/to/repo
```

**Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--search NAME` | (none) | Fuzzy search for symbols by name instead of listing a file |
| `--project PATH` | `.` | Project directory |

**Sample output (file listing):**

```
Symbols in src/auth/middleware.py

  Kind       Name                          Line
  --------   ---------------------------   ----
  class      AuthMiddleware                  12
  method     AuthMiddleware.__init__         15
  method     AuthMiddleware.dispatch         28
  function   verify_token                    65
  function   extract_bearer                  82
  variable   DEFAULT_REALM                    9
```

**Sample output (search):**

```
Search results for 'authenticate' (5 matches)

  Kind       Name                          File                         Line
  --------   ---------------------------   --------------------------   ----
  function   authenticate_user             src/auth/service.py            34
  method     AuthProvider.authenticate     src/auth/providers/base.py     22
  function   authenticate_request          src/api/security.py            51
```

---

### `impact` --- Impact Analysis

Show the blast radius of changes to one or more files. Computes transitive dependents to reveal what might break.

```bash
attocode code-intel impact src/auth.py
attocode code-intel impact src/auth.py src/config.py
attocode code-intel impact src/core/loop.py --project /path/to/repo
```

**Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--project PATH` | `.` | Project directory |

**Sample output:**

```
Impact analysis for 2 file(s):

Changed files:
  src/auth.py
  src/config.py

Direct dependents (depth 1):
  src/api/middleware.py
  src/api/routes/login.py
  src/services/user_service.py

2nd-order dependents (depth 2):
  src/api/app.py
  src/main.py

Total blast radius: 5 files affected
```

---

### `hotspots` --- Risk Hotspots

Identify files with the highest risk/complexity scores. Scores combine cyclomatic complexity, fan-in/fan-out, file size, and change frequency.

```bash
attocode code-intel hotspots
attocode code-intel hotspots --top 20
attocode code-intel hotspots --project /path/to/repo
```

**Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--top N` | `15` | Number of top hotspots to show |
| `--project PATH` | `.` | Project directory |

**Sample output:**

```
Code hotspots (top 15 by risk score):

   #  Score  Lines  Fan-in  Fan-out  File
  ---  -----  -----  ------  -------  ----------------------------------------
    1  0.94    3100      28       45  src/agent/agent.py
    2  0.88    1866      15       32  src/core/execution_loop.py
    3  0.82    1233      12       22  src/swarm/swarm_execution.py
    4  0.79    1100       9       18  src/swarm/swarm_orchestrator.py
    5  0.75     990       8       15  src/decomposer/smart_decomposer.py
```

---

### `deps` --- Dependencies

Show what a file imports and what imports it. Useful for understanding coupling and planning refactors.

```bash
attocode code-intel deps src/auth/middleware.py
attocode code-intel deps src/api/app.py --project /path/to/repo
```

**Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--project PATH` | `.` | Project directory |

**Sample output:**

```
Dependencies for src/auth/middleware.py

  Imports (this file depends on):
    src/auth/tokens.py
    src/config.py
    src/db/session.py

  Imported by (files that depend on this):
    src/api/app.py
    src/api/routes/admin.py
    src/api/routes/login.py

  Fan-out: 3 | Fan-in: 3
```

---

## Maintenance Commands

### `gc` --- Garbage Collection

Clean up orphaned embeddings, unreferenced content, and stale cache files. Behavior adapts to the deployment mode:

- **Local mode**: Clears the `.attocode/cache` directory
- **Remote mode**: Enqueues `gc_orphaned_embeddings` and `gc_unreferenced_content` jobs on the server
- **Service mode (with database)**: Runs GC operations directly against the database

```bash
attocode code-intel gc
attocode code-intel gc --project /path/to/repo
```

**Sample output (local):**

```
Local mode: clearing AST cache...
  Removed 47 cached file(s).
GC complete.
```

**Sample output (remote):**

```
Triggering GC on remote server https://code-intel.example.com...
  Enqueued gc_orphaned_embeddings job
  Enqueued gc_unreferenced_content job
GC jobs enqueued on remote server.
```

---

### `verify` --- Integrity Checks

Run integrity checks on the code-intel index. In local mode, verifies cache and index files exist. In service mode, checks for:

- Orphaned `branch_files` referencing missing `file_contents`
- Orphaned embeddings not referenced by any branch manifest
- Missing embeddings for content in branch manifests
- Broken `parent_branch_id` references
- Orphaned symbols referencing missing `file_contents`

```bash
attocode code-intel verify
attocode code-intel verify --project /path/to/repo
```

**Sample output (service mode, clean):**

```
Running integrity checks...

Integrity check results:
  Orphaned branch_files:      0
  Orphaned embeddings:        0
  Missing embeddings:         0
  Broken parent_branch refs:  0
  Orphaned symbols:           0

All checks passed.
```

**Sample output (with issues):**

```
Running integrity checks...

Integrity check results:
  Orphaned branch_files:      0
  Orphaned embeddings:        12
  Missing embeddings:         3
  Broken parent_branch refs:  0
  Orphaned symbols:           0

Found 2 issue(s):
  [!] 12 embeddings reference content not in any branch manifest
  [!] 3 content SHAs in branch manifests have no embeddings

Run 'attocode code-intel gc' to clean up orphaned data.
Run 'attocode code-intel reindex' to rebuild missing embeddings.
```

---

### `reindex` --- Full Reindex

Force a complete reindex of the project. Clears all cached data and rebuilds the AST index and embedding vectors from scratch.

- **Local mode**: Clears cache, removes stale index file, runs full embedding index
- **Remote mode**: Triggers an `index_repository` job on the server

```bash
attocode code-intel reindex
attocode code-intel reindex --project /path/to/repo
```

**Sample output (local):**

```
Reindexing /path/to/repo...
  Cleared 47 cached file(s).
  Removed stale index file.
  Indexed 1,234 chunks.
```

!!! note "Reindex duration"
    Full reindexing can take several minutes for large projects, depending on file count and embedding model. Use `attocode code-intel index --background` for non-blocking indexing.
