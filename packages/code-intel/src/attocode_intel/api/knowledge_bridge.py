"""Keep historical HTTP knowledge endpoints on the team's canonical store."""

from __future__ import annotations

from attocode_intel.api.auth import resolve_auth
from attocode_intel.api.routes.operations import execute_operation


async def shared_operation(request, workspace, name, arguments):
    if not request.app.state.config.is_service_mode:
        return None
    auth = await resolve_auth(request.headers.get("authorization"))
    return await execute_operation(name, {"workspace": workspace, **arguments}, request, auth)
