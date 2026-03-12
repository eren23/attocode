"""FastAPI application factory for Attocode Code Intelligence."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from attocode.code_intel.config import CodeIntelConfig

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastapi import FastAPI

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup/shutdown lifecycle — initialize DB engine in service mode."""
    config: CodeIntelConfig = app.state.config
    if config.is_service_mode:
        from attocode.code_intel.db.engine import dispose_engine, init_engine

        init_engine(config.database_url)
        logger.info("Service mode: database engine initialized")
    yield

    # Shutdown debouncer
    from attocode.code_intel.api.routes.notify import _debouncer
    if _debouncer is not None:
        await _debouncer.shutdown()

    if config.is_service_mode:
        from attocode.code_intel.db.engine import dispose_engine

        await dispose_engine()
        logger.info("Service mode: database engine disposed")


def create_app(config: CodeIntelConfig | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config: Service configuration. If None, reads from environment.
    """
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    from attocode.code_intel.api import deps
    from attocode.code_intel.api.middleware import RequestLoggingMiddleware
    from attocode.code_intel.api.routes import (
        analysis,
        analysis_v2,
        files,
        graph,
        graph_v2,
        health,
        learning,
        lsp,
        lsp_v2,
        notify,
        projects,
        search,
        search_v2,
    )

    if config is None:
        config = CodeIntelConfig.from_env()

    # Initialize DI
    deps.configure(config)

    app = FastAPI(
        title="Attocode Code Intelligence",
        description=(
            "Code intelligence service with AST parsing, dependency graphs, "
            "semantic search, impact analysis, and more. "
            "v1 endpoints return text (MCP-compatible), "
            "v2 endpoints return structured JSON (UI-ready)."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=_lifespan,
    )
    app.state.config = config

    # Middleware — credentials=True is invalid with origins=["*"] per CORS spec
    allow_creds = "*" not in config.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=allow_creds,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestLoggingMiddleware)

    # Rate limiting (service mode only)
    if config.is_service_mode:
        from attocode.code_intel.api.middleware import RateLimitMiddleware

        app.add_middleware(RateLimitMiddleware, requests_per_minute=60)

    # Legacy routes (local mode + backward compat)
    app.include_router(health.router)
    app.include_router(projects.router)
    app.include_router(analysis.router)
    app.include_router(search.router)
    app.include_router(graph.router)
    app.include_router(learning.router)
    app.include_router(lsp.router)
    app.include_router(notify.router)

    # v2 structured routes (return JSON, not text)
    app.include_router(analysis_v2.router)
    app.include_router(graph_v2.router)
    app.include_router(search_v2.router)
    app.include_router(lsp_v2.router)
    app.include_router(files.router)

    # Service mode routes
    if config.is_service_mode:
        from attocode.code_intel.api.routes import (
            activity,
            api_keys,
            auth,
            branches,
            embeddings,
            files_v2,
            git_v2,
            jobs,
            orgs,
            preferences,
            presence,
            webhooks,
            websocket,
        )

        app.include_router(auth.router)
        app.include_router(orgs.router)
        app.include_router(api_keys.router)
        app.include_router(branches.router)
        app.include_router(webhooks.router)
        app.include_router(websocket.router)
        app.include_router(jobs.router)
        # v2 service-mode routes
        app.include_router(files_v2.router)
        app.include_router(git_v2.router)
        app.include_router(embeddings.router)
        app.include_router(presence.router)
        app.include_router(activity.router)
        app.include_router(preferences.router)

    # SPA fallback — serve frontend static files (registered LAST so it
    # doesn't shadow /api/*, /docs, /redoc, /openapi.json).
    import os

    static_dir = os.environ.get("ATTOCODE_STATIC_DIR", "/app/static")
    if os.path.isdir(static_dir):
        from starlette.responses import FileResponse

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str) -> FileResponse:
            file_path = os.path.join(static_dir, full_path)
            if os.path.isfile(file_path):
                return FileResponse(file_path)
            return FileResponse(os.path.join(static_dir, "index.html"))

        logger.info("SPA fallback enabled from %s", static_dir)

    logger.info(
        "FastAPI app created for %s (service_mode=%s)",
        config.project_dir or "(no project)",
        config.is_service_mode,
    )
    return app
