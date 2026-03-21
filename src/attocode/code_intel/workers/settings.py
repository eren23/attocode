"""ARQ worker settings and configuration."""

from __future__ import annotations

import os

from arq.connections import RedisSettings
from arq.cron import cron

from attocode.code_intel.workers.jobs import (
    cleanup_stale_branches,
    gc_orphaned_embeddings,
    gc_unreferenced_content,
    generate_embeddings,
    index_branch_delta,
    index_repository,
    prune_expired_revocations,
)


def get_redis_settings() -> RedisSettings:
    """Build Redis settings from environment."""
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    # Parse redis:// URL
    if redis_url.startswith("redis://"):
        parts = redis_url[len("redis://"):]
        host_port = parts.split("/")[0]
        host = host_port.split(":")[0] if ":" in host_port else host_port
        port = int(host_port.split(":")[1]) if ":" in host_port else 6379
        database = int(parts.split("/")[1]) if "/" in parts else 0
        return RedisSettings(host=host, port=port, database=database)
    return RedisSettings()


class WorkerSettings:
    """ARQ worker settings."""

    functions = [
        index_repository,
        index_branch_delta,
        generate_embeddings,
        gc_orphaned_embeddings,
    ]

    cron_jobs = [
        # Every 6 hours: clean up stale branch overlays
        cron(cleanup_stale_branches, hour={0, 6, 12, 18}, minute=0),
        # Every 24 hours: GC unreferenced content
        cron(gc_unreferenced_content, hour=3, minute=0),
        # Daily at 3:30am: GC orphaned embeddings
        cron(gc_orphaned_embeddings, hour=3, minute=30),
        # Every 24 hours: prune expired token revocations
        cron(prune_expired_revocations, hour=4, minute=0),
    ]

    redis_settings = get_redis_settings()

    # Configurable via environment
    max_jobs = int(os.environ.get("WORKER_MAX_JOBS", "10"))
    job_timeout = 1800  # 30 minutes default
    health_check_interval = 30
