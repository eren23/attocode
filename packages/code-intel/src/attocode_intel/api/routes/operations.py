"""Structured operations used by both the dashboard and MCP."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from jsonschema import ValidationError

from attocode_intel.api.auth import resolve_auth
from attocode_intel.remote import remote_identity

router = APIRouter(prefix="/api/v2/operations", tags=["intelligence"])


@router.post("/{name}")
async def execute_operation(
    name: str, arguments: dict, request: Request, auth: Annotated[object, Depends(resolve_auth)]
):
    token = remote_identity.set(auth)
    try:
        result = await request.app.state.mcp_transport.gateway.execute(name, arguments)
        return result.structuredContent
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        remote_identity.reset(token)
