# Local Development Guide

This guide covers three ways to run the Code Intelligence service locally.

## Prerequisites

- **Python 3.12+** with [uv](https://docs.astral.sh/uv/) package manager
- **Node 20+** (for frontend development)
- **Docker** and **Docker Compose** (for service mode)
- **Git** (obviously)

## Mode 1: CLI (Zero Config)

The simplest way — no Postgres, no Redis, no auth. Uses SQLite for everything.

```bash
# Install with code-intel + semantic search extras
uv sync --extra code-intel --extra semantic

# Start the server
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

## Mode 2: Docker Compose (Full Stack)

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

## Mode 3: Local Service Mode (For Development)

Run Postgres and Redis in Docker, but the backend and frontend natively for hot reload.

### Terminal 1: Infrastructure

```bash
cd docker/code-intel
docker compose -f docker-compose.service.yml up postgres redis
```

### Terminal 2: Backend

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

### Terminal 3: Frontend (Dev Mode with HMR)

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173 (proxied to backend at :8080)
```

### Terminal 4: Worker (Background Jobs)

```bash
python -m attocode.code_intel.workers.run
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
