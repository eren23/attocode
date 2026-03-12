"""GitHub OAuth 2.0 authorization code flow."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"


async def get_github_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    """Build the GitHub OAuth authorization URL."""
    import urllib.parse

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "user:email",
        "state": state,
    }
    return f"{GITHUB_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


async def exchange_github_code(
    code: str,
    client_id: str,
    client_secret: str,
) -> dict:
    """Exchange authorization code for access token and fetch user info.

    Returns dict with keys: github_id, email, name, avatar_url.
    """
    import httpx

    async with httpx.AsyncClient() as client:
        # Exchange code for token
        token_resp = await client.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()
        access_token = token_data["access_token"]

        # Fetch user profile
        user_resp = await client.get(
            GITHUB_USER_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_resp.raise_for_status()
        user_data = user_resp.json()

        # Fetch email if not public
        email = user_data.get("email")
        if not email:
            email_resp = await client.get(
                "https://api.github.com/user/emails",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            email_resp.raise_for_status()
            emails = email_resp.json()
            primary = next((e for e in emails if e.get("primary")), None)
            email = primary["email"] if primary else emails[0]["email"]

        return {
            "github_id": user_data["id"],
            "email": email,
            "name": user_data.get("name") or user_data.get("login", ""),
            "avatar_url": user_data.get("avatar_url", ""),
        }
