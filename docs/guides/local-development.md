# Local Development Guide

This guide covers the two main ways to use Code Intelligence, plus instructions for running your own server.

## Prerequisites

- **Python 3.12+** with [uv](https://docs.astral.sh/uv/) package manager
- **Node 20+** (for frontend development)
- **Docker** and **Docker Compose** (for running your own server)
- **Git** (obviously)

## Mode 1: CLI (Zero Config)

The simplest way — no server needed. Uses SQLite for everything.

```bash
# Install with code-intel + semantic search extras
uv sync --extra code-intel --extra semantic

# Install MCP server into your coding assistant
attocode code-intel install claude     # or cursor, vscode, codex, ...

# Or start the HTTP API directly
attocode code-intel serve --transport http --project .
# → http://localhost:8080/docs (Swagger UI)
```

This gives you:

- Single-project analysis (the directory you point it at)
- SQLite-backed graph, embeddings, and learnings
- API key auth (or open access if `ATTOCODE_API_KEY` is empty)
- All v1 and v2 analysis/search/graph/LSP endpoints

!!! note "No service-mode features"
    OAuth, multi-user, organizations, repositories, branches, webhooks, and the
    frontend dashboard require service mode (Postgres + Redis).

## Mode 2: Connect to a Server

Connect your project to an already-running code-intel server (local Docker, cloud, hosted).

```bash
# Interactive — prompts for email/password, selects org/repo
attocode code-intel connect --server https://code.example.com

# Non-interactive — provide token directly (CI, scripts)
attocode code-intel connect --server https://code.example.com --token $TOKEN --repo $REPO_ID

# CI/CD: non-interactive, skip sync
attocode code-intel connect --server https://code.example.com --token $TOKEN --repo $REPO_ID --ci --skip-sync

# Scripted with credentials
attocode code-intel connect --server https://code.example.com \
  --email user@example.com --password secret --org my-org
```

The `connect` command:

1. Health-checks the server
2. Registers or logs in (interactive or via `--token`/`--email`/`--password`)
3. Auto-detects or prompts for organization
4. Adds the current project as a repo (or matches an existing one)
5. Writes `.attocode/config.toml` for subsequent `notify`/`watch` commands
6. Verifies the connection

After connecting:

```bash
# Auto-notify the server on every file save
attocode code-intel watch

# Install MCP server (uses the remote server)
attocode code-intel install claude
```

---

## Running Your Own Server

### Docker Compose (Full Stack)

Runs everything in containers: API, worker, Postgres (with pgvector), Redis.

```bash
cd docker/code-intel

# Copy env template and edit
cp ../../.env.example .env
# Edit .env — at minimum set SECRET_KEY to something random

# Start the full stack
docker compose -f docker-compose.service.yml up --build
```

What you get:

| Service | URL / Port |
|---------|------------|
| API | `http://localhost:8080` |
| Frontend | `http://localhost:8080` (static files served by FastAPI) |
| Swagger UI | `http://localhost:8080/docs` |
| Postgres | `localhost:5432` (user: `codeintel`, db: `codeintel`) |
| Redis | `localhost:6379` |

The API container runs Alembic migrations on startup and serves the frontend as static files.

Then connect your project:

```bash
attocode code-intel connect --server http://localhost:8080
```

### Local Service Mode (For Development)

Run Postgres and Redis in Docker, but the backend and frontend natively for hot reload.

#### Terminal 1: Infrastructure

```bash
cd docker/code-intel
docker compose -f docker-compose.service.yml up postgres redis
```

#### Terminal 2: Backend

```bash
uv sync --extra service --extra semantic

# Load environment
cp .env.example .env
# Edit .env (DATABASE_URL, SECRET_KEY, etc.)
source .env  # or use direnv / dotenv

# Run migrations
alembic -c src/attocode/code_intel/migrations/alembic.ini upgrade head

# Start the API server with hot reload
uvicorn attocode.code_intel.api.app:create_app --factory --reload --port 8080
```

#### Terminal 3: Frontend (Dev Mode with HMR)

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173 (proxied to backend at :8080)
```

#### Terminal 4: Worker (Background Jobs)

```bash
python -m attocode.code_intel.workers.run
```

### Quick Bootstrap (Contributors)

For contributors to this project, `setup` automates the infrastructure and registration:

#### Step 1: Infrastructure + migrations

```bash
attocode code-intel setup
```

This starts Postgres + Redis in Docker, installs Python dependencies, loads `.env.dev`, and runs Alembic migrations. If the API server isn't running yet, Phase 1 completes and prints instructions.

#### Step 2: Start the API server (separate terminal)

```bash
source .env.dev && uvicorn attocode.code_intel.api.app:create_app --factory --reload --port 8080
```

#### Step 3: Complete registration

```bash
attocode code-intel setup    # re-run — detects API, registers user/org/repo
```

The command is idempotent — re-running won't create duplicates. State is saved to `.attocode/dev-state.json`.

#### Step 4: Worker + Frontend

```bash
# Worker (processes indexing jobs)
source .env.dev && python -m attocode.code_intel.workers.run

# Frontend (optional)
cd frontend && npm run dev
```

#### Managing the environment

```bash
attocode code-intel setup --reset      # Wipe DB + state, re-bootstrap
attocode code-intel setup --skip-deps  # Skip uv sync
```

## Environment Variables

See [`.env.example`](../../.env.example) for the full list. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `ATTOCODE_PROJECT_DIR` | `.` | Project directory to index (CLI mode) |
| `ATTOCODE_HOST` | `127.0.0.1` | Bind address |
| `ATTOCODE_PORT` | `8080` | Bind port |
| `ATTOCODE_API_KEY` | (empty) | API key for auth (empty = open access) |
| `DATABASE_URL` | (empty) | PostgreSQL URL — enables service mode |
| `SECRET_KEY` | (empty) | JWT signing key (required for service mode) |
| `REDIS_URL` | (empty) | Redis URL for job queue and pub/sub |
| `ATTOCODE_EMBEDDING_MODEL` | (auto) | Embedding model: `all-MiniLM-L6-v2`, `nomic-embed-text`, `openai` |
| `GITHUB_CLIENT_ID` | (empty) | GitHub OAuth app client ID |
| `GOOGLE_CLIENT_ID` | (empty) | Google OAuth client ID |
| `ATTOCODE_RATE_LIMIT_RPM` | `300` | Base rate limit per minute |
| `WORKER_MAX_JOBS` | `10` | Max concurrent ARQ worker jobs |

---

## Managing Repos

```bash
# Read token/org from saved state
export TOKEN=$(python3 -c "import json; print(json.load(open('.attocode/dev-state.json'))['token'])")
export ORG_ID=$(python3 -c "import json; print(json.load(open('.attocode/dev-state.json'))['org_id'])")

# Add a local repo
curl -X POST "http://localhost:8080/api/v1/orgs/$ORG_ID/repos" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "another-project", "local_path": "/path/to/another-project", "default_branch": "main"}'

# Add a GitHub repo (server will clone it)
curl -X POST "http://localhost:8080/api/v1/orgs/$ORG_ID/repos" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-repo", "clone_url": "https://github.com/user/repo.git", "default_branch": "main"}'
```

---

## Branch Workflow Walkthrough

Once the service is running and your repo is indexed, here's how branch workflows work end-to-end.

### 1. Verify main branch is indexed

```bash
export TOKEN=$(python3 -c "import json; print(json.load(open('.attocode/dev-state.json'))['token'])")
export ORG_ID=$(python3 -c "import json; print(json.load(open('.attocode/dev-state.json'))['org_id'])")
export REPO_ID=$(python3 -c "import json; print(json.load(open('.attocode/dev-state.json'))['repo_id'])")

curl -s "http://localhost:8080/api/v2/repos/$REPO_ID/branches" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### 2. Create a feature branch and make changes

```bash
git checkout -b feature/new-auth
echo 'def authenticate(user): pass' > src/new_module.py
```

### 3. Notify the server about changes

```bash
# Single file
attocode code-intel notify --file src/new_module.py

# Or use watch for auto-notify on every save
attocode code-intel watch
```

The server auto-creates a branch record and runs the incremental indexing pipeline.

### 4. Query branch-specific data

```bash
# List branches — your new branch should appear
curl -s "http://localhost:8080/api/v2/repos/$REPO_ID/branches" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Compare branches
curl -s -X POST "http://localhost:8080/api/v2/repos/$REPO_ID/branches/compare" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"base_branch": "main", "compare_branch": "feature/new-auth"}' | python3 -m json.tool
```

### 5. Switch branches, observe independent overlays

```bash
git checkout main
echo 'def logging_setup(): pass' > src/logging_util.py
attocode code-intel notify --file src/logging_util.py

# Each branch has its own overlay — changes don't leak across branches
```

### 6. Diff between branches (line-level hunks)

```bash
curl -s "http://localhost:8080/api/v2/projects/$REPO_ID/diff?from=main&to=feature/new-auth" \
  -H "Authorization: Bearer $TOKEN"
```

### 7. Merge branch

```bash
curl -X POST "http://localhost:8080/api/v1/repos/$REPO_ID/branches/merge" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source_branch": "feature/new-auth", "target_branch": "main", "delete_source": true}'
```

---

## CLI Bridge (connect + watch)

For local development, the CLI can auto-notify the server on every file save — no manual `notify` calls needed.

### Connect to the server

```bash
# Interactive (register/login, org/repo selection)
attocode code-intel connect --server http://localhost:8080

# Or with explicit token
attocode code-intel connect \
  --server http://localhost:8080 \
  --token $TOKEN \
  --repo $REPO_ID

# Verify the connection
attocode code-intel test-connection
```

### Watch for changes

```bash
# Auto-notifies on every file save
attocode code-intel watch
```

How watch works:
- Uses `watchfiles` (Rust-based) for efficient filesystem monitoring
- Filters to code files only (skips `.git/`, `node_modules/`, binaries)
- Auto-detects the current git branch
- Batches rapid changes with configurable debounce (default: 500ms)
- Sends incremental updates to the server per-file

---

## local_path vs clone_url

Both modes are interchangeable. A repo can even have both — `clone_url` for the canonical source, `local_path` as an override when running locally.

| Scenario | Mode | How changes arrive | Best for |
|----------|------|--------------------|----------|
| Dev on same machine | `local_path` | CLI `notify` / `watch` | Local development |
| Remote server | `clone_url` | Git push → webhook | Production, CI |
| Local + GitHub | Both | `local_path` for dev, webhook for team | Hybrid |

**`local_path`**: The server reads files directly from disk. Changes are detected via CLI `notify` or `watch` commands. No git push required.

**`clone_url`**: The server clones the repo into `GIT_CLONE_DIR`. Changes arrive via git push + webhook (or manual `reindex`). Used when the server runs on a different machine.

**Hybrid**: Set both on the same repo. When running locally, the server prefers `local_path` for file reads. The `clone_url` serves as the canonical source for webhook-driven indexing when deployed remotely.

```bash
# Add a repo with both
curl -X POST "http://localhost:8080/api/v1/orgs/$ORG_ID/repos" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-project",
    "local_path": "/home/user/my-project",
    "clone_url": "https://github.com/user/my-project.git",
    "default_branch": "main"
  }'
```

---

## Team Onboarding

When multiple developers share a single code-intel server, the **team hybrid workflow** looks like this:

### 1st developer: create the repo

```bash
# Alice creates her account and connects
cd /home/alice/my-project
attocode code-intel connect --server https://ci.myteam.dev

# The CLI auto-detects the git remote origin, creates the repo on the server,
# and syncs all tracked files.
```

### 2nd developer: connect to the same repo

```bash
# Bob clones the same GitHub repo to a different path
cd /home/bob/my-project
attocode code-intel connect --server https://ci.myteam.dev
```

The CLI automatically matches Bob's local checkout to Alice's repo using the **clone URL matching** algorithm:

1. **`local_path`** — exact path match (same machine only)
2. **`clone_url`** — normalized git remote URL match (works across machines)
3. **Name fallback** — directory name matches repo name on server

URL normalization strips protocol, `.git` suffix, and `git@` SSH syntax, so these all match:
- `https://github.com/org/repo.git`
- `git@github.com:org/repo`
- `https://github.com/org/repo`

### Private repositories

If the repo is private, an admin sets a credential on the server so it can clone/fetch:

```bash
# Set a PAT (Personal Access Token) for the repo
curl -X POST "https://ci.myteam.dev/api/v1/orgs/$ORG_ID/repos/$REPO_ID/credentials" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"cred_type": "pat", "value": "ghp_xxxxxxxxxxxx"}'

# Trigger a reindex — the server will clone using the PAT
curl -X POST "https://ci.myteam.dev/api/v1/orgs/$ORG_ID/repos/$REPO_ID/reindex" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

After this, `watch` keeps changes in sync — each developer's local edits are pushed to the server in real-time.

---

## End-to-End Walkthrough

Once the service is running in service mode, here's the full flow using curl:

### 1. Register a User

```bash
curl -X POST http://localhost:8080/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "dev@example.com", "password": "secure-password", "name": "Dev User"}'
```

Save the `access_token` from the response:

```bash
export TOKEN="eyJhbG..."
```

### 2. Create an Organization

```bash
curl -X POST http://localhost:8080/api/v1/orgs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "My Org", "slug": "my-org"}'
```

### 3. Add a GitHub Repository

```bash
curl -X POST http://localhost:8080/api/v1/orgs/{org_id}/repos \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-repo", "clone_url": "https://github.com/user/repo.git", "default_branch": "main"}'
```

### 4. Trigger Indexing

```bash
curl -X POST http://localhost:8080/api/v1/orgs/{org_id}/repos/{repo_id}/reindex \
  -H "Authorization: Bearer $TOKEN"
```

### 5. Check Indexing Status

```bash
curl http://localhost:8080/api/v2/repos/{repo_id}/indexing/status \
  -H "Authorization: Bearer $TOKEN"
```

### 6. Browse Files

```bash
curl "http://localhost:8080/api/v2/repos/{repo_id}/files?branch=main" \
  -H "Authorization: Bearer $TOKEN"
```

### 7. Search Code

```bash
curl -X POST http://localhost:8080/api/v2/projects/{project_id}/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "authentication middleware", "top_k": 10}'
```

### 8. List Branches

```bash
curl http://localhost:8080/api/v2/repos/{repo_id}/branches \
  -H "Authorization: Bearer $TOKEN"
```

### 9. Compare Branches

```bash
curl -X POST http://localhost:8080/api/v2/repos/{repo_id}/branches/compare \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"base_branch": "main", "compare_branch": "feature/auth"}'
```

### 10. Set Up Webhook for Auto-Indexing

```bash
curl -X POST http://localhost:8080/api/v1/webhooks/config \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"repo_id": "...", "provider": "github", "secret": "your-webhook-secret"}'
```

Then in GitHub repo settings: Webhooks → Add webhook → URL: `https://your-server.com/api/v1/webhooks/github`, Secret: `your-webhook-secret`, Events: Push.

### 11. Security Scan

```bash
curl -X POST "http://localhost:8080/api/v2/projects/$REPO_ID/security-scan" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"mode": "full"}'
```

## Testing OAuth Locally

### GitHub OAuth

1. Go to [GitHub Developer Settings](https://github.com/settings/developers) → New OAuth App
2. Set **Homepage URL** to `http://localhost:8080`
3. Set **Authorization callback URL** to `http://localhost:8080/api/v1/auth/github/callback`
4. Copy Client ID and Client Secret to your `.env`

### Google OAuth

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials) → Create OAuth Client ID
2. Application type: **Web application**
3. Add **Authorized redirect URI**: `http://localhost:8080/api/v1/auth/google/callback`
4. Copy Client ID and Client Secret to your `.env`

## Testing Semantic Search

```bash
# 1. Trigger embedding generation for a repo branch
curl -X POST http://localhost:8080/api/v2/repos/{repo_id}/embeddings/generate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"branch": "main"}'

# 2. Check embedding coverage
curl http://localhost:8080/api/v2/repos/{repo_id}/embeddings/status \
  -H "Authorization: Bearer $TOKEN"

# 3. Run a semantic search
curl -X POST http://localhost:8080/api/v2/projects/{project_id}/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "how does authentication work", "top_k": 5}'
```

## Troubleshooting

### Port Conflicts

```bash
# Check what's using port 8080
lsof -i :8080

# Use a different port
ATTOCODE_PORT=9090 uvicorn ...
```

### Migration Errors

```bash
# Check current migration state
alembic -c src/attocode/code_intel/migrations/alembic.ini current

# Re-run migrations
alembic -c src/attocode/code_intel/migrations/alembic.ini upgrade head

# Reset database (destructive!)
alembic -c src/attocode/code_intel/migrations/alembic.ini downgrade base
alembic -c src/attocode/code_intel/migrations/alembic.ini upgrade head
```

### Embedding Model Download

The first time you run with `--extra semantic`, sentence-transformers downloads the model (~22MB). If you're behind a proxy:

```bash
export HF_HUB_OFFLINE=0
export TRANSFORMERS_CACHE=/path/to/cache
```

### Postgres Connection Refused

If Postgres isn't ready when the API starts:

```bash
# Check Postgres health
docker compose -f docker-compose.service.yml ps

# Wait for it explicitly
docker compose -f docker-compose.service.yml up -d postgres
docker compose -f docker-compose.service.yml exec postgres pg_isready -U codeintel
```
