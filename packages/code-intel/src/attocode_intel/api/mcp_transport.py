"""Native Streamable HTTP MCP, authenticated before protocol dispatch."""

from __future__ import annotations

import os

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.responses import JSONResponse

from attocode_intel.gateway import OperationGateway, create_mcp_server
from attocode_intel.remote import RemoteResolver, remote_identity, remote_profile, remote_workspace


class MCPTransport:
    def __init__(self, config):
        self.config = config
        self.gateway = OperationGateway(
            config.project_dir,
            os.environ.get("ATTOCODE_MCP_PROFILE", "full"),
            RemoteResolver(config) if config.is_service_mode else None,
            watch=os.environ.get("ATTOCODE_INTEL_WATCH", "1") != "0",
            watch_debounce=int(os.environ.get("ATTOCODE_INTEL_WATCH_DEBOUNCE", "500")),
        )
        self.manager = StreamableHTTPSessionManager(
            create_mcp_server(self.gateway), json_response=True, stateless=True
        )

    async def __call__(self, scope, receive, send):
        from fastapi import HTTPException

        from attocode_intel.api.auth import resolve_auth

        if scope["type"] != "http":
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        try:
            auth = await resolve_auth(headers.get("authorization"))
        except HTTPException as exc:
            await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(
                scope, receive, send
            )
            return
        token = remote_identity.set(auth)
        workspace_token = remote_workspace.set(headers.get("x-attocode-workspace", ""))
        profile_token = remote_profile.set(headers.get("x-attocode-profile", self.gateway.profile))
        try:
            await self.manager.handle_request(scope, receive, send)
        finally:
            remote_identity.reset(token)
            remote_workspace.reset(workspace_token)
            remote_profile.reset(profile_token)
