"""ARQ job implementations for background processing."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def index_repository(ctx: dict, repo_id: str, branch_name: str = "main") -> dict:
    """Full index of a repository branch.

    Timeout: 30min, Retries: 2, Priority: medium
    """
    from attocode.code_intel.db.engine import get_session
    from attocode.code_intel.db.models import Branch, IndexingJob, Repository
    from attocode.code_intel.pubsub import publish_event

    logger.info("Starting full index for repo %s branch %s", repo_id, branch_name)
    await publish_event(repo_id, "index.started", {"branch": branch_name})

    async for session in get_session():
        try:
            from sqlalchemy import select

            # Get repository
            result = await session.execute(
                select(Repository).where(Repository.id == uuid.UUID(repo_id))
            )
            repo = result.scalar_one_or_none()
            if repo is None:
                return {"error": f"Repository {repo_id} not found"}

            # Create/update job record
            job = IndexingJob(
                repo_id=repo.id,
                job_type="full_index",
                status="running",
                branch_name=branch_name,
                started_at=datetime.now(timezone.utc),
            )
            session.add(job)
            await session.flush()

            # Get or create branch
            branch_result = await session.execute(
                select(Branch).where(Branch.repo_id == repo.id, Branch.name == branch_name)
            )
            branch = branch_result.scalar_one_or_none()
            if branch is None:
                branch = Branch(
                    repo_id=repo.id,
                    name=branch_name,
                    is_default=(branch_name == repo.default_branch),
                )
                session.add(branch)
                await session.flush()

            # Progress callback
            async def on_progress(data: dict) -> None:
                await publish_event(repo_id, "index.progress", data)

            # Perform indexing
            from attocode.code_intel.api.deps import get_config
            from attocode.code_intel.git.manager import GitRepoManager
            from attocode.code_intel.indexing.full_indexer import FullIndexer

            config = get_config()
            git_mgr = GitRepoManager(config.git_clone_dir, config.git_ssh_key_path)
            indexer = FullIndexer(session, git_mgr, progress_callback=lambda d: None)

            stats = await indexer.index(repo_id, branch.id, ref=branch_name)

            # Update records
            branch.last_indexed_at = datetime.now(timezone.utc)
            repo.index_status = "indexed"
            repo.last_indexed_at = datetime.now(timezone.utc)
            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)
            job.result = stats

            await session.commit()
            await publish_event(repo_id, "index.completed", stats)
            return stats

        except Exception as e:
            logger.exception("Error indexing repo %s", repo_id)
            await publish_event(repo_id, "index.failed", {"error": str(e)})
            return {"error": str(e)}

    return {"error": "No session available"}


async def index_branch_delta(
    ctx: dict,
    repo_id: str,
    branch_name: str,
    from_ref: str,
    to_ref: str,
) -> dict:
    """Delta index of changed files between two refs.

    Timeout: 10min, Retries: 3, Priority: medium
    """
    from attocode.code_intel.db.engine import get_session
    from attocode.code_intel.db.models import Branch, IndexingJob, Repository
    from attocode.code_intel.pubsub import publish_event

    logger.info("Starting delta index for repo %s: %s..%s", repo_id, from_ref, to_ref)
    await publish_event(repo_id, "index.started", {"branch": branch_name, "type": "delta"})

    async for session in get_session():
        try:
            from sqlalchemy import select

            result = await session.execute(
                select(Repository).where(Repository.id == uuid.UUID(repo_id))
            )
            repo = result.scalar_one_or_none()
            if repo is None:
                return {"error": f"Repository {repo_id} not found"}

            branch_result = await session.execute(
                select(Branch).where(Branch.repo_id == repo.id, Branch.name == branch_name)
            )
            branch = branch_result.scalar_one_or_none()
            if branch is None:
                return {"error": f"Branch {branch_name} not found"}

            job = IndexingJob(
                repo_id=repo.id,
                job_type="delta_index",
                status="running",
                branch_name=branch_name,
                started_at=datetime.now(timezone.utc),
            )
            session.add(job)
            await session.flush()

            from attocode.code_intel.api.deps import get_config
            from attocode.code_intel.git.manager import GitRepoManager
            from attocode.code_intel.indexing.delta_indexer import DeltaIndexer

            config = get_config()
            git_mgr = GitRepoManager(config.git_clone_dir, config.git_ssh_key_path)
            indexer = DeltaIndexer(session, git_mgr)

            stats = await indexer.index(repo_id, branch.id, from_ref, to_ref)

            branch.head_commit = to_ref
            branch.last_indexed_at = datetime.now(timezone.utc)
            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)
            job.result = stats

            await session.commit()
            await publish_event(repo_id, "index.completed", stats)
            return stats

        except Exception as e:
            logger.exception("Error delta-indexing repo %s", repo_id)
            await publish_event(repo_id, "index.failed", {"error": str(e)})
            return {"error": str(e)}

    return {"error": "No session available"}


async def generate_embeddings(ctx: dict, repo_id: str, branch_name: str = "main") -> dict:
    """Generate embeddings for all files in a branch.

    Timeout: 20min, Retries: 2, Priority: low
    """
    logger.info("Starting embedding generation for repo %s branch %s", repo_id, branch_name)
    # Placeholder — will integrate with semantic search embedding pipeline
    return {"status": "not_implemented", "repo_id": repo_id, "branch": branch_name}


async def cleanup_stale_branches(ctx: dict) -> dict:
    """Cron job: remove branch overlays for branches that no longer exist in git.

    Runs every 6 hours.
    """
    logger.info("Running stale branch cleanup")
    # Placeholder — will compare DB branches with git branches
    return {"cleaned": 0}


async def gc_unreferenced_content(ctx: dict) -> dict:
    """Cron job: garbage collect unreferenced file_contents.

    Runs every 24 hours.
    """
    from attocode.code_intel.db.engine import get_session
    from attocode.code_intel.storage.content_store import ContentStore

    logger.info("Running content GC")
    async for session in get_session():
        store = ContentStore(session)
        count = await store.gc_unreferenced()
        await session.commit()
        return {"removed": count}
    return {"removed": 0}
