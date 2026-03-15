"""Webhook endpoints for GitHub/GitLab/Bitbucket push events (service mode only)."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from attocode.code_intel.api.deps import get_db_session
from attocode.code_intel.db.models import Repository, WebhookConfig

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)


def _get_fernet():
    """Get Fernet instance using SECRET_KEY from config."""
    from attocode.code_intel.crypto import _get_fernet as _shared_get_fernet

    return _shared_get_fernet()


def _encrypt_secret(secret: str) -> str:
    """Encrypt a webhook secret for storage."""
    return _get_fernet().encrypt(secret.encode()).decode()


def _decrypt_secret(encrypted: str) -> str:
    """Decrypt a stored webhook secret."""
    return _get_fernet().decrypt(encrypted.encode()).decode()


class WebhookConfigRequest(BaseModel):
    repo_id: str
    provider: str  # github|gitlab|bitbucket
    secret: str
    events: list[str] = ["push"]


class WebhookConfigResponse(BaseModel):
    id: str
    repo_id: str
    provider: str
    events: list[str]
    active: bool


@router.post("/config", response_model=WebhookConfigResponse)
async def create_webhook_config(
    req: WebhookConfigRequest,
    session: AsyncSession = Depends(get_db_session),
) -> WebhookConfigResponse:
    """Create a webhook configuration for a repository."""
    repo_result = await session.execute(
        select(Repository).where(Repository.id == uuid.UUID(req.repo_id))
    )
    repo = repo_result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    secret_hash = hashlib.sha256(req.secret.encode()).hexdigest()
    secret_encrypted = _encrypt_secret(req.secret)
    config = WebhookConfig(
        repo_id=repo.id,
        provider=req.provider,
        secret_hash=secret_hash,
        secret_encrypted=secret_encrypted,
        events=req.events,
    )
    session.add(config)
    await session.commit()
    await session.refresh(config)

    return WebhookConfigResponse(
        id=str(config.id),
        repo_id=str(config.repo_id),
        provider=config.provider,
        events=list(config.events),
        active=config.active,
    )


@router.post("/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None),
    x_github_event: str | None = Header(None),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Handle GitHub webhook events."""
    body = await request.body()

    # Parse payload
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Identify repository
    repo_url = payload.get("repository", {}).get("clone_url", "")
    if not repo_url:
        repo_url = payload.get("repository", {}).get("html_url", "")

    if not repo_url:
        raise HTTPException(status_code=400, detail="Cannot identify repository from payload")

    # Find matching webhook config
    result = await session.execute(
        select(WebhookConfig).where(
            WebhookConfig.provider == "github",
            WebhookConfig.active == True,  # noqa: E712
        )
    )
    webhook = None
    for wh in result.scalars():
        # Verify the repo matches
        repo_result = await session.execute(
            select(Repository).where(Repository.id == wh.repo_id)
        )
        repo = repo_result.scalar_one_or_none()
        if repo and repo.clone_url and repo_url in (repo.clone_url, repo.clone_url.rstrip(".git")):
            webhook = wh
            break

    if webhook is None:
        raise HTTPException(status_code=404, detail="No matching webhook config found")

    # Verify signature using decrypted secret
    if x_hub_signature_256:
        if webhook.secret_encrypted:
            secret = _decrypt_secret(webhook.secret_encrypted)
            _verify_github_signature(body, x_hub_signature_256, secret)
        else:
            # Legacy fallback: no encrypted secret stored yet (pre-migration data)
            logger.warning("Webhook %s has no encrypted secret; signature verification skipped", webhook.id)

    # Log webhook received
    from attocode.code_intel.audit import log_event

    repo_result2 = await session.execute(
        select(Repository).where(Repository.id == webhook.repo_id)
    )
    wh_repo = repo_result2.scalar_one_or_none()
    if wh_repo:
        await log_event(session, wh_repo.org_id, "webhook.received", repo_id=webhook.repo_id, detail={"provider": "github", "event": x_github_event or "push"})
        await session.commit()

    # Handle events
    event = x_github_event or "push"
    if event == "push":
        ref = payload.get("ref", "")
        branch = ref.removeprefix("refs/heads/")
        before = payload.get("before", "")
        after = payload.get("after", "")

        logger.info("GitHub push: %s %s → %s", branch, before[:8], after[:8])

        # Enqueue delta index job
        try:
            from arq import create_pool

            from attocode.code_intel.workers.settings import get_redis_settings

            pool = await create_pool(get_redis_settings())
            await pool.enqueue_job(
                "index_branch_delta",
                str(webhook.repo_id),
                branch,
                before,
                after,
            )
            await pool.aclose()
            return {"status": "queued", "branch": branch, "job": "index_branch_delta"}
        except Exception as e:
            logger.warning("Failed to enqueue job: %s", e)
            return {"status": "received", "branch": branch, "note": "Job queuing unavailable"}

    elif event == "pull_request":
        action = payload.get("action", "")
        pr = payload.get("pull_request", {})
        merged = pr.get("merged", False)

        if action == "closed" and merged:
            # Auto-trigger merge + delete source branch in DB
            base_branch = pr.get("base", {}).get("ref", "")
            head_branch = pr.get("head", {}).get("ref", "")

            if base_branch and head_branch:
                logger.info("GitHub PR merged: %s → %s", head_branch, base_branch)
                try:
                    from attocode.code_intel.db.models import Branch
                    from attocode.code_intel.storage.branch_overlay import BranchOverlay

                    repo_result3 = await session.execute(
                        select(Repository).where(Repository.id == webhook.repo_id)
                    )
                    merge_repo = repo_result3.scalar_one_or_none()
                    if merge_repo:
                        src_result = await session.execute(
                            select(Branch).where(
                                Branch.repo_id == merge_repo.id, Branch.name == head_branch
                            )
                        )
                        tgt_result = await session.execute(
                            select(Branch).where(
                                Branch.repo_id == merge_repo.id, Branch.name == base_branch
                            )
                        )
                        src_branch = src_result.scalar_one_or_none()
                        tgt_branch = tgt_result.scalar_one_or_none()

                        if src_branch and tgt_branch:
                            overlay = BranchOverlay(session)
                            await overlay.merge_branch(
                                src_branch.id, tgt_branch.id, delete_source=True,
                            )
                            await session.commit()
                            return {
                                "status": "merged",
                                "source": head_branch,
                                "target": base_branch,
                            }
                except Exception as e:
                    logger.warning("Auto-merge failed for PR: %s", e)

        return {"status": "received", "event": "pull_request", "action": action}

    return {"status": "ignored", "event": event}


@router.post("/gitlab")
async def gitlab_webhook(
    request: Request,
    x_gitlab_token: str | None = Header(None),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Handle GitLab webhook events."""
    body = await request.body()
    payload = json.loads(body)

    # GitLab uses a shared secret token
    if not x_gitlab_token:
        raise HTTPException(status_code=401, detail="X-Gitlab-Token header required")

    token_hash = hashlib.sha256(x_gitlab_token.encode()).hexdigest()
    result = await session.execute(
        select(WebhookConfig).where(
            WebhookConfig.provider == "gitlab",
            WebhookConfig.secret_hash == token_hash,
            WebhookConfig.active == True,  # noqa: E712
        )
    )
    webhook = result.scalar_one_or_none()
    if webhook is None:
        raise HTTPException(status_code=401, detail="Invalid token")

    event_type = payload.get("object_kind", "push")
    if event_type == "push":
        ref = payload.get("ref", "")
        branch = ref.removeprefix("refs/heads/")
        before = payload.get("before", "")
        after = payload.get("after", "")

        logger.info("GitLab push: %s %s → %s", branch, before[:8], after[:8])
        return {"status": "received", "branch": branch}

    return {"status": "ignored", "event": event_type}


@router.post("/bitbucket")
async def bitbucket_webhook(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Handle Bitbucket webhook events (Cloud)."""
    body = await request.body()
    payload = json.loads(body)

    # Bitbucket Cloud uses a shared UUID key in the URL or body
    event = request.headers.get("x-event-key", "repo:push")

    if event == "repo:push":
        changes = payload.get("push", {}).get("changes", [])
        for change in changes:
            new = change.get("new", {})
            branch = new.get("name", "")
            commit = new.get("target", {}).get("hash", "")
            logger.info("Bitbucket push: %s → %s", branch, commit[:8])

        return {"status": "received", "changes": len(changes)}

    return {"status": "ignored", "event": event}


def _verify_github_signature(body: bytes, signature_header: str, secret: str) -> None:
    """Verify GitHub webhook HMAC-SHA256 signature."""
    if not signature_header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Invalid signature format")

    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(f"sha256={expected}", signature_header):
        raise HTTPException(status_code=401, detail="Invalid signature")
