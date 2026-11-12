"""Native Streamable HTTP MCP, authenticated before protocol dispatch."""

from __future__ import annotations

import os

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.responses import JSONResponse

from attocode_intel.api.mcp_cancellation import (
    CancellationRegistry,
    CancellationServer,
    current_owner,
    owner_for,
)
from attocode_intel.gateway import OperationGateway, create_mcp_server
from attocode_intel.remote import RemoteResolver, remote_identity, remote_profile, remote_workspace


class MCPTransport:
    def __init__(self, config):
        self.config = config
        self.cancellation_enabled = os.environ.get("ATTOCODE_MCP_HTTP_CANCEL", "0") == "1"
        if self.cancellation_enabled and not (config.is_service_mode or config.api_key):
            raise ValueError("HTTP cancellation requires configured authentication")
        self.gateway = OperationGateway(
            config.project_dir,
            os.environ.get("ATTOCODE_MCP_PROFILE", "full"),
            RemoteResolver(config) if config.is_service_mode else None,
            watch=os.environ.get("ATTOCODE_INTEL_WATCH", "1") != "0",
            watch_debounce=int(os.environ.get("ATTOCODE_INTEL_WATCH_DEBOUNCE", "500")),
        )
        if self.cancellation_enabled:
            registry = CancellationRegistry()
            server = create_mcp_server(
                self.gateway,
                on_tool_start=lambda identity: registry.activate(current_owner.get(), identity),
            )
            server = CancellationServer(server, registry)
        else:
            server = create_mcp_server(self.gateway)
        self.manager = StreamableHTTPSessionManager(server, json_response=True, stateless=True)

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
        workspace = headers.get("x-attocode-workspace", "")
        profile = headers.get("x-attocode-profile", self.gateway.profile)
        owner = None
        if self.cancellation_enabled and "x-attocode-cancellation-id" in headers:
            try:
                owner = owner_for(auth, headers.get("authorization", ""), workspace, profile,
                                  headers["x-attocode-cancellation-id"])
            except ValueError as exc:
                await JSONResponse({"detail": str(exc)}, status_code=400)(scope, receive, send)
                return
        owner_token = current_owner.set(owner)
        token = remote_identity.set(auth)
        workspace_token = remote_workspace.set(workspace)
        profile_token = remote_profile.set(profile)
        try:
            await self.manager.handle_request(scope, receive, send)
        finally:
            current_owner.reset(owner_token)
            remote_identity.reset(token)
            remote_workspace.reset(workspace_token)
            remote_profile.reset(profile_token)
