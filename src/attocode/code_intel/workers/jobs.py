"""ARQ job implementations for background processing."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def index_repository(ctx: dict, repo_id: str, branch_name: str = "main") -> dict:
    """Full index of a repository branch.

    Timeout: 30min, Retries: 2, Priority: medium
    """
    from attocode.code_intel.db.engine import get_session
    from attocode.code_intel.db.models import Branch, IndexingJob
    from attocode.code_intel.pubsub import publish_event

    logger.info("Starting full index for repo %s branch %s", repo_id, branch_name)
    await publish_event(repo_id, "index.started", {"branch": branch_name})

    async for session in get_session():
        try:
            from sqlalchemy import select

            from attocode.code_intel.workers.job_utils import get_repo_or_error

            repo, err = await get_repo_or_error(repo_id, session)
            if err:
                return err

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

            # Clone if needed, then index
            from attocode.code_intel.api.deps import get_config
            from attocode.code_intel.git.manager import GitRepoManager
            from attocode.code_intel.indexing.full_indexer import FullIndexer

            config = get_config()
            git_mgr = GitRepoManager(config.git_clone_dir, config.git_ssh_key_path)

            # Clone the repo if it has a clone_url and hasn't been cloned yet
            if repo.clone_url and not repo.clone_path:
                import asyncio

                from attocode.code_intel.workers.job_utils import resolve_repo_credential

                credential = await resolve_repo_credential(repo.id, session)
                loop = asyncio.get_running_loop()
                clone_path = await loop.run_in_executor(
                    None, git_mgr.clone, repo.clone_url, repo_id, credential,
                )
                repo.clone_path = clone_path
                await session.flush()
                logger.info("Cloned %s to %s", repo.clone_url, clone_path)

                # Detect default branch from cloned repo
                branches = git_mgr.list_branches(repo_id)
                default = next((b for b in branches if b.is_default), None)
                if default and default.name != repo.default_branch:
                    repo.default_branch = default.name
                    if branch_name == "main" and default.name != "main":
                        branch_name = default.name
                        branch.name = default.name
                        branch.is_default = True
                    await session.flush()

            # Determine the working path for indexing
            work_path = repo.clone_path or repo.local_path
            if not work_path:
                return {"error": "No clone_path or local_path for repo"}

            # Guard: if the path doesn't exist on this machine, skip
            # (local_path is a client-side path that the server can't access)
            import os

            if not os.path.exists(work_path):
                logger.warning(
                    "Skipping full index for repo %s: path %s not accessible (remote client path?)",
                    repo_id, work_path,
                )
                repo.index_status = "pending_client"
                await session.commit()
                return {"skipped": True, "reason": f"Path {work_path} not accessible from server"}

            # Register path override so git operations use the correct directory
            git_mgr.register_path(repo_id, work_path)

            # Advisory lock: prevent concurrent indexing of the same branch
            from attocode.code_intel.indexing.incremental import IncrementalPipeline

            await IncrementalPipeline.acquire_branch_lock(session, branch.id)

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

            # Auto-trigger embedding generation after successful index
            from attocode.code_intel.workers.job_utils import enqueue_embedding_job
            await enqueue_embedding_job(repo_id, branch_name)

            return stats

        except Exception as e:
            logger.exception("Error indexing repo %s", repo_id)
            try:
                repo.index_status = "failed"
                job.status = "failed"
                job.completed_at = datetime.now(timezone.utc)
                job.error = str(e)
                job.result = {"error": str(e)}
                await session.commit()
            except Exception:
                logger.warning("Failed to persist error state for repo %s", repo_id)
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
    from attocode.code_intel.db.models import IndexingJob
    from attocode.code_intel.pubsub import publish_event

    logger.info("Starting delta index for repo %s: %s..%s", repo_id, from_ref, to_ref)
    await publish_event(repo_id, "index.started", {"branch": branch_name, "type": "delta"})

    async for session in get_session():
        try:
            from attocode.code_intel.workers.job_utils import get_branch_or_error, get_repo_or_error

            repo, err = await get_repo_or_error(repo_id, session)
            if err:
                return err

            branch, err = await get_branch_or_error(repo.id, branch_name, session)
            if err:
                return err

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

            # Fetch latest commits for bare clones
            if repo.clone_url and repo.clone_path:
                import asyncio

                from attocode.code_intel.workers.job_utils import resolve_repo_credential

                credential = await resolve_repo_credential(repo.id, session)
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, git_mgr.fetch, str(repo.id), credential)

            # Advisory lock: prevent concurrent indexing of the same branch
            from attocode.code_intel.indexing.incremental import IncrementalPipeline

            await IncrementalPipeline.acquire_branch_lock(session, branch.id)

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
            try:
                job.status = "failed"
                job.completed_at = datetime.now(timezone.utc)
                job.error = str(e)
                job.result = {"error": str(e)}
                await session.commit()
            except Exception:
                logger.warning("Failed to persist error state for delta-index repo %s", repo_id)
            await publish_event(repo_id, "index.failed", {"error": str(e)})
            return {"error": str(e)}

    return {"error": "No session available"}


async def generate_embeddings(ctx: dict, repo_id: str, branch_name: str = "main") -> dict:
    """Generate embeddings for all files in a branch.

    Timeout: 20min, Retries: 2, Priority: low

    Pipeline:
    1. Resolve branch manifest (all content_shas)
    2. Check which shas already have embeddings
    3. For each missing sha: read content, embed, store with vector
    4. Batch 32 files at a time for memory efficiency
    """
    from attocode.code_intel.db.engine import get_session
    from attocode.code_intel.db.models import FileContent
    from attocode.code_intel.pubsub import publish_event

    logger.info("Starting embedding generation for repo %s branch %s", repo_id, branch_name)
    await publish_event(repo_id, "embeddings.started", {"branch": branch_name})

    async for session in get_session():
        try:
            from sqlalchemy import select

            from attocode.code_intel.workers.job_utils import get_branch_or_error, get_repo_or_error

            # 1. Get repo + branch
            repo, err = await get_repo_or_error(repo_id, session)
            if err:
                return err

            branch, err = await get_branch_or_error(repo.id, branch_name, session)
            if err:
                return err

            # 2. Create embedding provider
            from attocode.code_intel.api.deps import get_config
            from attocode.integrations.context.embeddings import create_embedding_provider

            config = get_config()
            try:
                provider = create_embedding_provider(config.embedding_model)
            except (ImportError, RuntimeError) as exc:
                return {"error": str(exc)}
            if provider.name == "none":
                return {"error": "No embedding provider available", "hint": "Install sentence-transformers or set OPENAI_API_KEY"}

            dim = provider.dimension()

            # 3. Ensure vector column exists with the right dimension
            from attocode.code_intel.storage.embedding_store import (
                EmbeddingStore,
                ensure_vector_columns,
            )

            await ensure_vector_columns(session, primary_dim=dim)

            # 4. Resolve branch manifest
            from attocode.code_intel.storage.branch_overlay import BranchOverlay

            overlay = BranchOverlay(session)
            manifest = await overlay.resolve_manifest(branch.id)
            all_shas = set(manifest.values())

            if not all_shas:
                return {"embedded": 0, "skipped": 0, "total": 0, "model": provider.name, "dimension": dim}

            # 5. Find which SHAs need embedding
            store = EmbeddingStore(session)
            existing_shas = await store.batch_has_embeddings(all_shas, provider.name)
            missing_shas = all_shas - existing_shas

            embedded_count = 0
            skipped_count = len(existing_shas)
            batch_size = 32

            # 6. Process in batches
            sha_list = list(missing_shas)
            for i in range(0, len(sha_list), batch_size):
                batch_shas = sha_list[i:i + batch_size]

                # Read content for this batch
                content_result = await session.execute(
                    select(FileContent).where(FileContent.sha256.in_(batch_shas))
                )
                contents = {fc.sha256: fc for fc in content_result.scalars()}

                texts = []
                shas_in_batch = []
                for sha in batch_shas:
                    fc = contents.get(sha)
                    if fc is None:
                        continue
                    try:
                        text_content = fc.content.decode("utf-8", errors="replace")
                        text_content = text_content.replace('\x00', '')
                    except Exception:
                        continue
                    # Truncate very large files to avoid OOM in embedding model
                    if len(text_content) > 100_000:
                        text_content = text_content[:100_000]
                    texts.append(text_content)
                    shas_in_batch.append(sha)

                if not texts:
                    continue

                # Embed the batch (CPU-bound, run in executor to avoid blocking event loop)
                try:
                    import asyncio
                    loop = asyncio.get_running_loop()
                    vectors = await loop.run_in_executor(None, provider.embed, texts)
                except Exception:
                    logger.exception("Embedding failed for batch starting at index %d", i)
                    continue

                # Store embeddings with vectors
                for sha, text_content, vector in zip(shas_in_batch, texts, vectors):
                    await store.upsert_embeddings(sha, [{
                        "embedding_model": provider.name,
                        "chunk_text": text_content[:500],  # Store truncated preview
                        "chunk_type": "file",
                        "vector": vector,
                    }])
                    embedded_count += 1

                # Publish progress
                await publish_event(repo_id, "embeddings.progress", {
                    "branch": branch_name,
                    "embedded": embedded_count,
                    "total": len(missing_shas),
                })

            await session.commit()

            stats = {
                "embedded": embedded_count,
                "skipped": skipped_count,
                "total": len(all_shas),
                "model": provider.name,
                "dimension": dim,
            }
            await publish_event(repo_id, "embeddings.completed", stats)
            logger.info("Embedding generation complete for repo %s: %s", repo_id, stats)
            return stats

        except Exception as e:
            logger.exception("Error generating embeddings for repo %s", repo_id)
            await publish_event(repo_id, "embeddings.failed", {"error": str(e)})
            return {"error": str(e)}

    return {"error": "No session available"}


async def cleanup_stale_branches(ctx: dict) -> dict:
    """Cron job: remove branch overlays for branches that no longer exist.

    Runs every 6 hours. For local repos: compares DB branches against git.
    For remote repos: cleans up merged branches (merged_at > 7 days ago)
    and inactive branches (no overlay changes and no commits in 30 days).
    """
    from datetime import timedelta

    from sqlalchemy import func as sa_func
    from sqlalchemy import select

    from attocode.code_intel.api.deps import get_config
    from attocode.code_intel.db.engine import get_session
    from attocode.code_intel.db.models import Branch, BranchFile, Commit, Repository
    from attocode.code_intel.git.manager import GitRepoManager

    logger.info("Running stale branch cleanup")
    cleaned = 0

    async for session in get_session():
        config = get_config()
        git_mgr = GitRepoManager(config.git_clone_dir, config.git_ssh_key_path)
        now = datetime.now(timezone.utc)

        result = await session.execute(select(Repository))
        repos = result.scalars().all()

        for repo in repos:
            if repo.clone_path:
                # Local/cloned repos: compare against git branches
                try:
                    git_branches = {b.name for b in git_mgr.list_branches(str(repo.id))}
                except (FileNotFoundError, ValueError):
                    continue

                branch_result = await session.execute(
                    select(Branch).where(Branch.repo_id == repo.id)
                )
                for db_branch in branch_result.scalars():
                    if db_branch.name not in git_branches and not db_branch.is_default:
                        logger.info(
                            "Removing stale branch %s from repo %s",
                            db_branch.name, repo.id,
                        )
                        await session.delete(db_branch)
                        cleaned += 1
            else:
                # Remote repos: clean up merged + inactive branches
                branch_result = await session.execute(
                    select(Branch).where(Branch.repo_id == repo.id)
                )
                for db_branch in branch_result.scalars():
                    if db_branch.is_default:
                        continue

                    # Clean up merged branches older than retention threshold
                    if db_branch.merged_at and (now - db_branch.merged_at) > timedelta(days=config.gc_merged_branch_retention_days):
                        logger.info(
                            "Removing merged branch %s from repo %s (merged %s)",
                            db_branch.name, repo.id, db_branch.merged_at,
                        )
                        await session.delete(db_branch)
                        cleaned += 1
                        continue

                    # Clean up inactive branches: no overlay changes AND no commits in retention period
                    if not db_branch.merged_at:
                        overlay_count_result = await session.execute(
                            select(sa_func.count()).select_from(
                                select(BranchFile.path)
                                .where(BranchFile.branch_id == db_branch.id)
                                .subquery()
                            )
                        )
                        overlay_count = overlay_count_result.scalar() or 0

                        if overlay_count == 0:
                            cutoff = now - timedelta(days=config.gc_inactive_branch_retention_days)
                            recent_commit_result = await session.execute(
                                select(sa_func.count()).select_from(
                                    select(Commit.id)
                                    .where(
                                        Commit.repo_id == repo.id,
                                        Commit.branch_name == db_branch.name,
                                        Commit.created_at > cutoff,
                                    )
                                    .subquery()
                                )
                            )
                            recent_commits = recent_commit_result.scalar() or 0
                            if recent_commits == 0:
                                logger.info(
                                    "Removing inactive branch %s from repo %s",
                                    db_branch.name, repo.id,
                                )
                                await session.delete(db_branch)
                                cleaned += 1

        await session.commit()

    logger.info("Stale branch cleanup complete: removed %d branches", cleaned)
    return {"cleaned": cleaned}


async def prune_expired_revocations(ctx: dict) -> dict:
    """Cron job: prune expired token revocations.

    Runs every 24 hours. Removes entries whose expires_at has passed
    (tokens that are already expired don't need blocklist entries).
    """
    from sqlalchemy import delete

    from attocode.code_intel.db.engine import get_session
    from attocode.code_intel.db.models import RevokedToken

    logger.info("Running token revocation cleanup")

    async for session in get_session():
        result = await session.execute(
            delete(RevokedToken).where(
                RevokedToken.expires_at < datetime.now(timezone.utc)
            )
        )
        pruned = result.rowcount
        await session.commit()
        logger.info("Pruned %d expired token revocations", pruned)
        return {"pruned": pruned}

    return {"pruned": 0}


async def gc_unreferenced_content(ctx: dict) -> dict:
    """Cron job: garbage collect unreferenced file_contents.

    Runs every 24 hours.
    """
    from attocode.code_intel.api.deps import get_config
    from attocode.code_intel.db.engine import get_session
    from attocode.code_intel.storage.content_store import ContentStore

    logger.info("Running content GC")
    config = get_config()
    async for session in get_session():
        store = ContentStore(session)
        count = await store.gc_unreferenced(min_age_minutes=config.gc_content_min_age_minutes)
        await session.commit()
        return {"removed": count}
    return {"removed": 0}


async def gc_orphaned_embeddings(ctx: dict) -> dict:
    """Cron job: garbage collect orphaned embeddings.

    Deletes embeddings whose content_sha is not referenced by any branch manifest.
    Runs daily at 3:30am.
    """
    from attocode.code_intel.api.deps import get_config
    from attocode.code_intel.db.engine import get_session
    from attocode.code_intel.storage.embedding_store import EmbeddingStore

    logger.info("Running orphaned embeddings GC")
    config = get_config()
    async for session in get_session():
        store = EmbeddingStore(session)
        count = await store.gc_orphaned(min_age_minutes=config.gc_content_min_age_minutes)
        await session.commit()
        logger.info("Orphaned embeddings GC complete: removed %d embeddings", count)
        return {"removed": count}
    return {"removed": 0}
