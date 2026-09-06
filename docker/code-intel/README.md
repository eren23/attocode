# Self-hosted Attocode Intelligence

See the [product operations guide](../../docs/intelligence.md#self-host-the-team-service) for installation, configuration, authentication, upgrades, and knowledge migration.

The Docker image installs the standalone `attocode-code-intel` package and the dashboard. It does not install the legacy agent. Use `docker-compose.service.yml` for PostgreSQL, Redis, API, and workers; set a persistent `SECRET_KEY` before startup. `docker-compose.dev.yml` supplies only development databases. The local `docker-compose.yml` serves a mounted working tree.

For the local compose file, create the mountpoints before mounting source read-only:

```sh
export PROJECT_DIR=/absolute/path/to/repo
mkdir -p "$PROJECT_DIR/.attocode/cache" "$PROJECT_DIR/.attocode/index"
docker compose -f docker/code-intel/docker-compose.yml up --build -d
```

The existing cache volume retains knowledge across upgrades; a separate writable volume holds the AST index. The default image uses keyword search. Optional embedding dependencies can be enabled with Docker build argument `ATTOCODE_INTEL_EXTRAS=service,semantic`.
