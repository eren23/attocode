# Code Intelligence Docker Setup

Docker packaging for the Attocode Code Intelligence HTTP API server.

## Quick Start

```bash
# Analyze the current directory
docker-compose up --build

# Analyze a specific project
PROJECT_DIR=/path/to/repo docker-compose up --build

# With authentication
PROJECT_DIR=/path/to/repo ATTOCODE_API_KEY=my-secret docker-compose up --build
```

The server starts at `http://localhost:8080`. Open `http://localhost:8080/docs` for Swagger UI.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PROJECT_DIR` | `.` (host-side) | Path to the project to analyze |
| `ATTOCODE_API_KEY` | (empty) | API key for bearer token auth (empty = no auth) |
| `ATTOCODE_PORT` | `8080` | Port to expose on the host |

Inside the container, `ATTOCODE_HOST` is set to `0.0.0.0` and `ATTOCODE_PROJECT_DIR` is `/project`.

## Volume Mounts

- **`$PROJECT_DIR:/project:ro`** --- Your source code, mounted read-only. The server cannot modify your files.
- **`code-intel-cache:/project/.attocode/cache`** --- Named volume for persistent SQLite databases (AST graph, embeddings, memory). Survives container restarts.

## Building Manually

```bash
# From the repository root
docker build -f docker/code-intel/Dockerfile -t attocode-code-intel .

# Run
docker run -p 8080:8080 \
  -v /path/to/repo:/project:ro \
  -e ATTOCODE_API_KEY=optional-key \
  attocode-code-intel
```

## What's Included

- Python 3.12 slim base image
- Git (for future repo cloning support)
- Attocode with `[code-intel]` extras (FastAPI, uvicorn, etc.)
- Runs `attocode-code-intel serve --transport http` as the entrypoint

For full API documentation, see [Code Intel HTTP API](../../docs/code-intel-http-api.md).
