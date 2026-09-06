"""Apply repository authorization before legacy routes can consult cached services."""

from __future__ import annotations

import re

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class RepositoryAccessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        config = request.app.state.config
        if config.is_service_mode:
            match = re.match(r"/api/v[12]/(?:projects|repos)/([^/]+)", request.url.path)
            if match:
                from attocode_intel.api.auth import resolve_auth
                from attocode_intel.remote import authorized_repo

                try:
                    auth = await resolve_auth(request.headers.get("authorization"))
                    await authorized_repo(
                        match.group(1), auth, write=request.method not in {"GET", "HEAD", "OPTIONS"}
                    )
                except HTTPException as exc:
                    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
            elif request.url.path.rstrip("/") == "/api/v1/projects":
                return JSONResponse(
                    {"detail": "Use organization-scoped repository management"}, status_code=403
                )
        return await call_next(request)
