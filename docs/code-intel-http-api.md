# Code Intelligence HTTP API

The HTTP API exposes all 36 code intelligence tools as REST endpoints, backed by the same analysis engine as the MCP server. It supports multi-project management, bearer token auth, and interactive API docs.

## Quick Start

### Option 1: CLI

```bash
# Install attocode
uv tool install attocode
# or: pip install 'attocode[code-intel]'

# Start the HTTP server for a project
attocode code-intel serve --transport http --project /path/to/repo
```

The server starts at `http://127.0.0.1:8080`. Open `http://127.0.0.1:8080/docs` for interactive Swagger UI.

### Option 2: Docker

```bash
cd docker/code-intel

# Point PROJECT_DIR to the repo you want to analyze
PROJECT_DIR=/path/to/repo docker-compose up
```

See [Docker Deployment](#docker-deployment) for details.

### Option 3: Programmatic

```python
from attocode.code_intel.api.app import create_app
from attocode.code_intel.config import CodeIntelConfig

config = CodeIntelConfig(project_dir="/path/to/repo", host="0.0.0.0", port=8080)
app = create_app(config)

# Run with uvicorn
import uvicorn
uvicorn.run(app, host=config.host, port=config.port)
```

---

## Authentication

Authentication is controlled by the `ATTOCODE_API_KEY` environment variable.

| `ATTOCODE_API_KEY` | Behavior |
|---------------------|----------|
| Not set (empty) | **Open mode** --- all requests are allowed without auth |
| Set to a value | **Auth required** --- every request must include `Authorization: Bearer <key>` |

The auth middleware accepts both `Bearer <key>` and the raw key in the `Authorization` header.

```bash
# Start with auth
ATTOCODE_API_KEY=my-secret-key attocode code-intel serve --transport http

# Authenticated request
curl -H "Authorization: Bearer my-secret-key" http://localhost:8080/api/v1/projects
```

---

## Configuration

All configuration is via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `ATTOCODE_PROJECT_DIR` | `""` | Default project directory to index on startup |
| `ATTOCODE_HOST` | `127.0.0.1` | Server bind address |
| `ATTOCODE_PORT` | `8080` | Server port |
| `ATTOCODE_API_KEY` | `""` | API key for bearer auth (empty = open mode) |
| `ATTOCODE_CORS_ORIGINS` | `*` | Comma-separated allowed CORS origins |
| `ATTOCODE_LOG_LEVEL` | `info` | Log level (`debug`, `info`, `warning`, `error`) |
| `ATTOCODE_RATE_LIMIT_RPM` | `300` | Base rate limit (RPM). Notify gets 10x, auth gets 0.1x |
| `WORKER_MAX_JOBS` | `10` | Max concurrent worker jobs |

---

## Rate Limiting

Rate limits are tiered by endpoint category. The base rate is controlled by `ATTOCODE_RATE_LIMIT_RPM` (default: 300 RPM):

| Category | Multiplier | Effective Default |
|----------|-----------|-------------------|
| Standard endpoints | 1x | 300 RPM |
| Notify endpoints (`/notify/*`) | 10x | 3,000 RPM |
| Auth endpoints (`/auth/*`) | 0.1x | 30 RPM |

Rate limit headers (`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`) are included in every response. When exceeded, the server returns `429 Too Many Requests`.

---

## Org Isolation

In service mode, all repositories are scoped to the authenticated user's organization. API requests only return data belonging to the user's org — there is no cross-org data leakage. Org membership is established during the `connect` or registration flow.

---

## Endpoint Reference

All project-scoped endpoints use the pattern `/api/v1/projects/{project_id}/...`. Register a project first to obtain a `project_id`.

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Basic health check |
| `GET` | `/ready` | Readiness probe (checks for registered projects) |

```bash
curl http://localhost:8080/health
# {"status": "ok"}
```

### Projects

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/projects` | Register a project |
| `GET` | `/api/v1/projects` | List all registered projects |
| `GET` | `/api/v1/projects/{id}` | Get project details |
| `POST` | `/api/v1/projects/{id}/reindex` | Trigger full reindex |

```bash
# Register a project
curl -X POST http://localhost:8080/api/v1/projects \
  -H "Content-Type: application/json" \
  -d '{"path": "/path/to/repo", "name": "my-project"}'
# {"id": "a1b2c3d4", "name": "my-project", "path": "/path/to/repo", "status": "ready", ...}

# List projects
curl http://localhost:8080/api/v1/projects
```

### Analysis

| Method | Path | Parameters | Description |
|--------|------|-----------|-------------|
| `GET` | `/{id}/map` | `include_symbols`, `max_tokens` | Token-budgeted repository map |
| `GET` | `/{id}/summary` | `max_tokens` | High-level project overview |
| `POST` | `/{id}/bootstrap` | `task_hint`, `max_tokens` | All-in-one codebase orientation |
| `GET` | `/{id}/symbols` | `path` (required) | List symbols in a file |
| `GET` | `/{id}/search-symbols` | `name` (required) | Fuzzy symbol search |
| `GET` | `/{id}/dependencies` | `path` (required) | File dependencies (forward/reverse) |
| `GET` | `/{id}/impact` | `files` (required, repeatable) | Transitive impact analysis |
| `GET` | `/{id}/cross-refs` | `symbol` (required) | Symbol cross-references |
| `GET` | `/{id}/file-analysis` | `path` (required) | Detailed single-file analysis |
| `POST` | `/{id}/dependency-graph` | `start_file`, `depth` | Dependency graph from a starting file |
| `GET` | `/{id}/hotspots` | `top_n` | Risk/complexity hotspots |
| `GET` | `/{id}/conventions` | `sample_size`, `path` | Coding conventions detection |
| `POST` | `/{id}/explore` | `path`, `max_items`, `importance_threshold` | Hierarchical directory drill-down |
| `POST` | `/{id}/security-scan` | `mode`, `path` | Security analysis |
| `POST` | `/{id}/notify` | `files` | Notify about changed files |

> All paths above are relative to `/api/v1/projects`. For example, `/{id}/map` means `/api/v1/projects/{project_id}/map`.

```bash
# Get repo map
curl "http://localhost:8080/api/v1/projects/a1b2c3d4/map?max_tokens=6000"

# Bootstrap orientation
curl -X POST http://localhost:8080/api/v1/projects/a1b2c3d4/bootstrap \
  -H "Content-Type: application/json" \
  -d '{"task_hint": "fix auth bug", "max_tokens": 8000}'

# Impact analysis
curl "http://localhost:8080/api/v1/projects/a1b2c3d4/impact?files=src/auth.py&files=src/config.py"
```

### Notify (File Changes)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/notify/file-changed` | Notify about changed files (202 async) |
| `POST` | `/api/v1/notify/flush` | Force-flush pending debounced notifications |
| `POST` | `/api/v1/notify/bulk-sync` | Bulk sync up to 500 files (bypasses debouncer) |
| `POST` | `/api/v1/notify/blame` | Push blame data for DB-backed blame |
| `POST` | `/api/v1/notify/commits` | Push commit metadata |

#### Idempotency

The notify endpoint supports an optional `idempotency_key` field to prevent duplicate processing:

```bash
curl -X POST http://localhost:8080/api/v1/notify/file-changed \
  -H "Content-Type: application/json" \
  -d '{"paths": ["src/app.py"], "idempotency_key": "hook-abc123"}'
```

- Keys are cached for 5 minutes (TTL). Duplicate requests within the window return `{"accepted": 0, "message": "Duplicate ..."}`.
- Empty or omitted `idempotency_key` skips deduplication.

#### Optimistic Concurrency (If-Match)

The `if_match` field enables optimistic concurrency control against the branch version counter:

```bash
curl -X POST http://localhost:8080/api/v1/notify/file-changed \
  -H "Content-Type: application/json" \
  -d '{"paths": ["src/app.py"], "branch": "main", "if_match": 42}'
```

If the branch version doesn't match, the write is rejected with a version mismatch error.

#### WebSocket Replay

WebSocket clients can pass `last_event_id` as a query parameter to replay missed events on reconnect:

```
ws://localhost:8080/ws/repos/{repo_id}/events?token=...&last_event_id=1234567890-0
```

- `last_event_id=$` (default) — receive only new events
- `last_event_id=0` — replay all available events from the stream
- `last_event_id=<specific-id>` — resume from a specific stream position

Each event includes a `_stream_id` field that clients should track for reconnection.

---

### Search

| Method | Path | Parameters | Description |
|--------|------|-----------|-------------|
| `POST` | `/{id}/search` | `query`, `top_k`, `file_filter` | Semantic search (vector + keyword RRF) |

```bash
curl -X POST http://localhost:8080/api/v1/projects/a1b2c3d4/search \
  -H "Content-Type: application/json" \
  -d '{"query": "authentication middleware", "top_k": 10}'
```

### Graph

| Method | Path | Parameters | Description |
|--------|------|-----------|-------------|
| `POST` | `/{id}/graph/query` | `file`, `edge_type`, `direction`, `depth` | BFS traversal over dependency edges |
| `POST` | `/{id}/graph/related` | `file`, `top_k` | Find structurally related files |
| `GET` | `/{id}/graph/communities` | `min_community_size`, `max_communities` | Detect file communities |
| `POST` | `/{id}/graph/context` | `files`, `depth`, `max_tokens`, `include_symbols` | Subgraph capsule with neighbors |

```bash
# BFS traversal
curl -X POST http://localhost:8080/api/v1/projects/a1b2c3d4/graph/query \
  -H "Content-Type: application/json" \
  -d '{"file": "src/core/loop.py", "edge_type": "IMPORTS", "direction": "outbound", "depth": 2}'

# Relevant context for a set of files
curl -X POST http://localhost:8080/api/v1/projects/a1b2c3d4/graph/context \
  -H "Content-Type: application/json" \
  -d '{"files": ["src/auth.py"], "depth": 1, "max_tokens": 4000}'
```

### Learning

| Method | Path | Parameters | Description |
|--------|------|-----------|-------------|
| `POST` | `/{id}/learnings` | `type`, `description`, `details`, `scope`, `confidence` | Record a learning |
| `GET` | `/{id}/learnings/recall` | `query` (required), `scope`, `max_results` | Recall relevant learnings |
| `POST` | `/{id}/learnings/{learning_id}/feedback` | `helpful` | Mark learning as helpful/unhelpful |
| `GET` | `/{id}/learnings` | `status`, `type`, `scope` | List all learnings |

> All paths above are relative to `/api/v1/projects`.

```bash
# Record a learning
curl -X POST http://localhost:8080/api/v1/projects/a1b2c3d4/learnings \
  -H "Content-Type: application/json" \
  -d '{"type": "gotcha", "description": "Config module is lazy-loaded", "scope": "src/config/"}'

# Recall learnings
curl "http://localhost:8080/api/v1/projects/a1b2c3d4/learnings/recall?query=config+loading"
```

### LSP

| Method | Path | Parameters | Description |
|--------|------|-----------|-------------|
| `POST` | `/{id}/lsp/definition` | `file`, `line`, `col` | Go-to-definition |
| `POST` | `/{id}/lsp/references` | `file`, `line`, `col`, `include_declaration` | Find all references |
| `POST` | `/{id}/lsp/hover` | `file`, `line`, `col` | Hover info (type + docs) |
| `GET` | `/{id}/lsp/diagnostics` | `file` (required) | Errors and warnings |

> All paths above are relative to `/api/v1/projects`.

```bash
# Go-to-definition
curl -X POST http://localhost:8080/api/v1/projects/a1b2c3d4/lsp/definition \
  -H "Content-Type: application/json" \
  -d '{"file": "src/auth.py", "line": 42, "col": 10}'

# Get diagnostics
curl "http://localhost:8080/api/v1/projects/a1b2c3d4/lsp/diagnostics?file=src/auth.py"
```

### History

| Method | Path | Parameters | Description |
|--------|------|-----------|-------------|
| `GET` | `/api/v2/projects/{id}/evolution` | `path` (required), `symbol`, `since`, `max_results` | Change history for a file or symbol |
| `GET` | `/api/v2/projects/{id}/recent-changes` | `days`, `path`, `top_n` | Recently modified files and change frequency |

```bash
# File evolution
curl "http://localhost:8080/api/v2/projects/$PROJECT_ID/evolution?path=src/auth.py&since=2026-01-01" \
  -H "Authorization: Bearer $TOKEN"

# Recent changes (last 14 days)
curl "http://localhost:8080/api/v2/projects/$PROJECT_ID/recent-changes?days=14&top_n=10" \
  -H "Authorization: Bearer $TOKEN"
```

### Cross-Repository Search

| Method | Path | Parameters | Description |
|--------|------|-----------|-------------|
| `POST` | `/api/v2/orgs/{org_id}/search` | `query`, `repo_ids`, `top_k`, `file_filter` | Semantic search across all repos in an org |

Requires service mode (Postgres + pgvector). Searches all repositories in the user's org, or a subset specified by `repo_ids`. Results are sorted globally by cosine similarity.

```bash
# Search across all repos in an org
curl -X POST "http://localhost:8080/api/v2/orgs/$ORG_ID/search" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "authentication middleware", "top_k": 20}'

# Search specific repos only
curl -X POST "http://localhost:8080/api/v2/orgs/$ORG_ID/search" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "database migration", "repo_ids": ["repo-uuid-1", "repo-uuid-2"], "file_filter": "*.py"}'
```

### Graph Visualization

| Method | Path | Parameters | Description |
|--------|------|-----------|-------------|
| `GET` | `/api/v2/projects/{id}/graph-viz` | `root`, `depth`, `max_nodes` | D3-compatible graph data (nodes + links + communities) |

Returns graph data in D3 force-directed format. If `root` is provided, performs BFS from that file up to `depth` hops. Otherwise returns the top files ranked by importance. Community detection data is included.

```bash
# Get full graph (top 100 files by importance)
curl "http://localhost:8080/api/v2/projects/$PROJECT_ID/graph-viz" \
  -H "Authorization: Bearer $TOKEN"

# BFS from a root file
curl "http://localhost:8080/api/v2/projects/$PROJECT_ID/graph-viz?root=src/api/app.py&depth=3&max_nodes=50" \
  -H "Authorization: Bearer $TOKEN"
```

### Metrics

| Method | Path | Parameters | Description |
|--------|------|-----------|-------------|
| `GET` | `/api/v1/metrics` | `format` (`json` or `prometheus`) | Aggregated query and performance metrics |

Unauthenticated endpoint for monitoring infrastructure. See the [Observability guide](guides/observability.md) for details.

```bash
# JSON format
curl http://localhost:8080/api/v1/metrics

# Prometheus text exposition format
curl "http://localhost:8080/api/v1/metrics?format=prometheus"
```

### Service Mode Endpoints

These endpoints provide DB-backed capabilities for remote repos (no local git clone required). Available only in service mode (Postgres + Redis).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v2/projects/{id}/diff?from=X&to=Y` | Branch diff with line-level hunks (DB-backed) |
| `GET` | `/api/v2/projects/{id}/blame/{path}` | Blame data (DB-backed for remote repos) |
| `POST` | `/api/v2/projects/{id}/security-scan` | Security scan (DB-backed for remote repos) |
| `POST` | `/api/v1/repos/{repo_id}/branches/merge` | Merge branch overlay |
| `GET` | `/api/v2/projects/{id}/commits` | Commit log (DB-backed) |
| `GET` | `/api/v2/projects/{id}/commits/{sha}` | Commit detail with changed files |

```bash
# Branch diff with line-level hunks
curl "http://localhost:8080/api/v2/projects/$PROJECT_ID/diff?from=main&to=feature/auth" \
  -H "Authorization: Bearer $TOKEN"

# Blame for a file
curl "http://localhost:8080/api/v2/projects/$PROJECT_ID/blame/src/app.py" \
  -H "Authorization: Bearer $TOKEN"

# Merge a branch
curl -X POST "http://localhost:8080/api/v1/repos/$REPO_ID/branches/merge" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source_branch": "feature/auth", "target_branch": "main", "delete_source": true}'

# Commit log
curl "http://localhost:8080/api/v2/projects/$PROJECT_ID/commits" \
  -H "Authorization: Bearer $TOKEN"

# Commit detail with changed files
curl "http://localhost:8080/api/v2/projects/$PROJECT_ID/commits/abc123def" \
  -H "Authorization: Bearer $TOKEN"
```

---

## Docker Deployment

The `docker/code-intel/` directory contains a ready-to-use Docker setup.

### Build and Run

```bash
cd docker/code-intel

# Analyze the current directory
docker-compose up --build

# Analyze a specific project
PROJECT_DIR=/path/to/repo docker-compose up --build

# With authentication
PROJECT_DIR=/path/to/repo ATTOCODE_API_KEY=secret docker-compose up --build
```

### Volume Mounts

| Mount | Container Path | Mode | Purpose |
|-------|---------------|------|---------|
| `$PROJECT_DIR` (or `.`) | `/project` | Read-only | Source code to analyze |
| `code-intel-cache` named volume | `/project/.attocode/cache` | Read-write | SQLite databases (graph.db, embeddings.db, memory.db) |

The read-only mount ensures the server cannot modify your source code. The named volume persists cache data across container restarts.

### Customizing the Port

```bash
ATTOCODE_PORT=9090 docker-compose up
```

---

## OpenAPI Docs

When the HTTP server is running, interactive API docs are available at:

- **Swagger UI**: `http://localhost:8080/docs`
- **ReDoc**: `http://localhost:8080/redoc`

These are auto-generated from the route definitions and Pydantic models.

---

## Client Examples

### Python (httpx)

```python
import httpx

BASE = "http://localhost:8080/api/v1"
HEADERS = {"Authorization": "Bearer my-key"}  # omit if no auth

# Register project
r = httpx.post(f"{BASE}/projects", json={"path": "/my/repo"}, headers=HEADERS)
project_id = r.json()["id"]

# Get repo map
r = httpx.get(f"{BASE}/projects/{project_id}/map?max_tokens=6000", headers=HEADERS)
print(r.json()["result"])

# Semantic search
r = httpx.post(
    f"{BASE}/projects/{project_id}/search",
    json={"query": "error handling", "top_k": 5},
    headers=HEADERS,
)
print(r.json()["result"])
```

### JavaScript (fetch)

```javascript
const BASE = "http://localhost:8080/api/v1";
const headers = {
  "Content-Type": "application/json",
  Authorization: "Bearer my-key", // omit if no auth
};

// Register project
const res = await fetch(`${BASE}/projects`, {
  method: "POST",
  headers,
  body: JSON.stringify({ path: "/my/repo" }),
});
const { id: projectId } = await res.json();

// Get repo map
const mapRes = await fetch(
  `${BASE}/projects/${projectId}/map?max_tokens=6000`,
  { headers }
);
const { result } = await mapRes.json();
console.log(result);
```

### curl

```bash
# Full workflow: register + analyze
PROJECT_ID=$(curl -s -X POST http://localhost:8080/api/v1/projects \
  -H "Content-Type: application/json" \
  -d '{"path": "/my/repo"}' | jq -r '.id')

curl "http://localhost:8080/api/v1/projects/$PROJECT_ID/summary"
curl "http://localhost:8080/api/v1/projects/$PROJECT_ID/hotspots?top_n=10"
```

---

## Differences from MCP

| Aspect | MCP (stdio/SSE) | HTTP API |
|--------|-----------------|----------|
| Project selection | `ATTOCODE_PROJECT_DIR` env var at server start | Project IDs in URL path (`/projects/{id}/...`) |
| Multi-project | One project per server instance | Multiple projects via `/projects` endpoint |
| Authentication | None (local transport) | `Authorization: Bearer <key>` header |
| Transport | stdio or SSE | HTTP REST (JSON) |
| Auto-discovery | Registered in MCP client config | Swagger UI at `/docs`, ReDoc at `/redoc` |
| Tool invocation | MCP `tools/call` protocol | Standard HTTP methods (GET/POST) |
| Client compatibility | MCP-compatible clients only | Any HTTP client |

The same 36 analysis tools are available through both transports. Choose MCP for AI coding assistants with built-in MCP support; choose HTTP for custom integrations, CI pipelines, or multi-project scenarios.

---

## MCP Tools Reference

The 36 MCP tools exposed by the code-intel server:

**Navigation & Search:**
`repo_map`, `project_summary`, `bootstrap`, `symbols`, `search_symbols`, `semantic_search`, `semantic_search_status`, `explore_codebase`

**Analysis:**
`dependencies`, `impact_analysis`, `cross_references`, `file_analysis`, `dependency_graph`, `hotspots`, `conventions`, `security_scan`, `dead_code`, `distill`

**Graph:**
`graph_query`, `graph_dsl`, `find_related`, `community_detection`, `relevant_context`

**History:**
`code_evolution`, `recent_changes`

**Learning:**
`record_learning`, `recall`, `learning_feedback`, `list_learnings`

**ADR (Architecture Decisions):**
`record_adr`, `list_adrs`, `get_adr`, `update_adr_status`

**LSP:**
`lsp_definition`, `lsp_references`, `lsp_hover`, `lsp_diagnostics`

**Events:**
`notify_file_changed`
