"""Utility helpers for ARQ job implementations and enqueuing."""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_recent_enqueues: dict[str, float] = {}
_DEDUP_WINDOW_S = 60


async def enqueue_embedding_job(repo_id: str, branch_name: str = "main") -> bool:
    """Enqueue a generate_embeddings job via ARQ.

    Returns True if enqueued, False if skipped (dedup or no Redis).
    Silently returns False if Redis is not configured — graceful degradation.
    """
    from attocode.code_intel.config import CodeIntelConfig

    config = CodeIntelConfig.from_env()
    if not config.redis_url:
        logger.debug("Redis not configured, skipping embedding job enqueue")
        return False

    # Dedup: skip if same repo+branch was enqueued in last 60s
    key = f"{repo_id}:{branch_name}"
    now = time.monotonic()
    if key in _recent_enqueues and now - _recent_enqueues[key] < _DEDUP_WINDOW_S:
        logger.debug("Skipping duplicate embedding enqueue for %s", key)
        return False

    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(config.redis_url))
        await pool.enqueue_job("generate_embeddings", repo_id, branch_name)
        await pool.close()
        _recent_enqueues[key] = now
        logger.info("Enqueued embedding job for repo %s branch %s", repo_id, branch_name)
        return True
    except Exception:
        logger.warning("Failed to enqueue embedding job", exc_info=True)
        return False


async def get_repo_or_error(
    repo_id: str, session: AsyncSession,
):
    """Look up a Repository by ID or return an error dict.

    Returns (repo, None) on success, or (None, {"error": ...}) on failure.
    """
    from sqlalchemy import select

    from attocode.code_intel.db.models import Repository

    result = await session.execute(
        select(Repository).where(Repository.id == uuid.UUID(repo_id))
    )
    repo = result.scalar_one_or_none()
    if repo is None:
        return None, {"error": f"Repository {repo_id} not found"}
    return repo, None


async def get_branch_or_error(
    repo_id: uuid.UUID, branch_name: str, session: AsyncSession,
):
    """Look up a Branch by repo ID and name, or return an error dict.

    Returns (branch, None) on success, or (None, {"error": ...}) on failure.
    """
    from sqlalchemy import select

    from attocode.code_intel.db.models import Branch

    result = await session.execute(
        select(Branch).where(Branch.repo_id == repo_id, Branch.name == branch_name)
    )
    branch = result.scalar_one_or_none()
    if branch is None:
        return None, {"error": f"Branch {branch_name} not found"}
    return branch, None


async def resolve_repo_credential(repo_id, session: AsyncSession):
    """Fetch and decrypt RepoCredential for a repo.

    Returns a Credential instance or None if no credential is configured.
    """
    from sqlalchemy import select

    from attocode.code_intel.crypto import decrypt_credential
    from attocode.code_intel.db.models import RepoCredential
    from attocode.code_intel.git.credentials import Credential

    result = await session.execute(
        select(RepoCredential).where(RepoCredential.repo_id == repo_id).limit(1)
    )
    repo_cred = result.scalar_one_or_none()
    if repo_cred is None:
        return None
    return Credential(cred_type=repo_cred.cred_type, value=decrypt_credential(repo_cred.encrypted_value))
