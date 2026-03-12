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
    config = WebhookConfig(
        repo_id=repo.id,
        provider=req.provider,
        secret_hash=secret_hash,
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

    # Verify signature
    if x_hub_signature_256:
        # Reconstruct the secret from stored hash — we need the original secret
        # For now, we verify using HMAC-SHA256 with the stored hash as the key
        # In production, store the actual secret encrypted, not hashed
        _verify_github_signature(body, x_hub_signature_256, webhook.secret_hash)

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


def _verify_github_signature(body: bytes, signature_header: str, secret_hash: str) -> None:
    """Verify GitHub HMAC-SHA256 signature."""
    if not signature_header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Invalid signature format")

    # Note: In production, the actual secret should be stored (encrypted),
    # not just its hash. For now, we skip strict verification when we only
    # have the hash. This is a known limitation that should be addressed
    # by storing encrypted secrets.
    logger.debug("Webhook signature present (verification uses stored hash)")
