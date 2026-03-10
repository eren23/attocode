"""FastAPI application factory for Attocode Code Intelligence."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from attocode.code_intel.config import CodeIntelConfig

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


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
        graph,
        health,
        learning,
        lsp,
        projects,
        search,
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
            "All 27 MCP tools exposed as HTTP endpoints."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

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

    # Routes
    app.include_router(health.router)
    app.include_router(projects.router)
    app.include_router(analysis.router)
    app.include_router(search.router)
    app.include_router(graph.router)
    app.include_router(learning.router)
    app.include_router(lsp.router)

    logger.info("FastAPI app created for %s", config.project_dir or "(no project)")
    return app
