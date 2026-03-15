# Code Intelligence Docker Setup

Docker packaging for the Attocode Code Intelligence HTTP API server.

## Docker Compose Files

| File | Use case |
|------|----------|
| `docker-compose.yml` | **CLI mode** — single project, no Postgres/Redis |
| `docker-compose.service.yml` | **Service mode** — full stack with Postgres (pgvector), Redis, background worker |

## Quick Start (CLI Mode)

```bash
# Analyze the current directory
docker-compose up --build

# Analyze a specific project
PROJECT_DIR=/path/to/repo docker-compose up --build

# With authentication
PROJECT_DIR=/path/to/repo ATTOCODE_API_KEY=my-secret docker-compose up --build
```

The server starts at `http://localhost:8080`. Open `http://localhost:8080/docs` for Swagger UI.

## Quick Start (Service Mode)

```bash
cd docker/code-intel

# Copy and edit environment config
cp ../../.env.example .env
# Edit .env — at minimum set SECRET_KEY

# Start the full stack
docker compose -f docker-compose.service.yml up --build
```

This starts:

| Service | URL / Port | Description |
|---------|------------|-------------|
| **api** | `http://localhost:8080` | FastAPI server + frontend static files |
| **worker** | (background) | ARQ job processor (indexing, embeddings) |
| **postgres** | `localhost:5432` | PostgreSQL 16 with pgvector extension |
| **redis** | `localhost:6379` | Job queue and pub/sub |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ATTOCODE_PROJECT_DIR` | `.` (host-side) | Path to the project to analyze (CLI mode) |
| `ATTOCODE_API_KEY` | (empty) | API key for bearer token auth (empty = no auth) |
| `ATTOCODE_PORT` | `8080` | Port to expose on the host |
| `SECRET_KEY` | `change-me-in-production` | JWT signing key (service mode) |
| `GITHUB_CLIENT_ID` | (empty) | GitHub OAuth app client ID |
| `GITHUB_CLIENT_SECRET` | (empty) | GitHub OAuth app client secret |
| `GOOGLE_CLIENT_ID` | (empty) | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | (empty) | Google OAuth client secret |
| `GIT_CLONE_MAX_GB` | `50` | Max disk for cloned repos (GB) |
| `POSTGRES_PORT` | `5432` | Host port for Postgres |
| `REDIS_PORT` | `6379` | Host port for Redis |
| `ATTOCODE_EMBEDDING_MODEL` | (auto) | Embedding model: `all-MiniLM-L6-v2`, `nomic-embed-text`, `openai` |

Inside the container, `ATTOCODE_HOST` is set to `0.0.0.0` and `DATABASE_URL`/`REDIS_URL` point to the compose network.

See [`.env.example`](../../.env.example) for the complete list with descriptions.

### Adding Google OAuth

Add to the `api` service in `docker-compose.service.yml`:

```yaml
environment:
  # ... existing vars ...
  - GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID:-}
  - GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET:-}
  - ATTOCODE_BASE_URL=${ATTOCODE_BASE_URL:-http://localhost:8080}
```

## Volume Mounts

**CLI mode:**

- `$PROJECT_DIR:/project:ro` — Your source code, mounted read-only
- `code-intel-cache:/project/.attocode/cache` — Persistent SQLite databases

**Service mode:**

- `pgdata` — PostgreSQL data directory
- `redisdata` — Redis persistence
- `repo-clones` — Cloned git repositories (`/var/lib/code-intel/repos`)

## Running Migrations

Migrations run automatically when the API container starts. To run them manually:

```bash
# Inside the running container
docker compose -f docker-compose.service.yml exec api \
  alembic -c src/attocode/code_intel/migrations/alembic.ini upgrade head

# Check current migration
docker compose -f docker-compose.service.yml exec api \
  alembic -c src/attocode/code_intel/migrations/alembic.ini current
```

## Accessing the Frontend

The frontend is served as static files by the API container at `http://localhost:8080`. In service mode, it provides:

- Repository browser
- Branch comparison
- Embedding coverage dashboard
- Real-time indexing status (WebSocket)

## Viewing Logs

```bash
# All services
docker compose -f docker-compose.service.yml logs -f

# Specific service
docker compose -f docker-compose.service.yml logs -f api
docker compose -f docker-compose.service.yml logs -f worker
docker compose -f docker-compose.service.yml logs -f postgres
```

## Building Manually

```bash
# From the repository root
docker build -f docker/code-intel/Dockerfile -t attocode-code-intel .

# Run (CLI mode)
docker run -p 8080:8080 \
  -v /path/to/repo:/project:ro \
  -e ATTOCODE_API_KEY=optional-key \
  attocode-code-intel
```

## What's Included

- Python 3.12 slim base image
- Git (for repo cloning)
- Attocode with `[service]` extras (FastAPI, uvicorn, SQLAlchemy, asyncpg, etc.)
- pgvector support (via `pgvector/pgvector:pg16` Postgres image)
- Runs `attocode-code-intel serve --transport http` as the entrypoint

For full API documentation, see [Code Intel HTTP API](../../docs/code-intel-http-api.md).
For local development setup, see [Local Development Guide](../../docs/guides/local-development.md).
