"""Git credential management — SSH keys, deploy tokens, PATs."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Credential:
    """Resolved credential for git remote operations."""

    cred_type: str  # ssh_key|deploy_token|pat
    value: str


class CredentialStore:
    """Resolves credentials for git remote operations.

    Supports SSH keys, deploy tokens, and personal access tokens.
    Returns pygit2-compatible RemoteCallbacks.
    """

    def __init__(self, ssh_key_path: str = "") -> None:
        self._ssh_key_path = ssh_key_path

    def resolve(self, credential: Credential | None = None):
        """Resolve a credential into pygit2 RemoteCallbacks.

        Returns None for public repos (no auth needed).
        """
        try:
            import pygit2
        except ImportError:
            logger.warning("pygit2 not installed — git operations unavailable")
            return None

        if credential is None:
            return None

        callbacks = pygit2.RemoteCallbacks()

        if credential.cred_type == "ssh_key":
            key_path = credential.value or self._ssh_key_path
            if key_path and os.path.exists(key_path):
                pub_path = f"{key_path}.pub"
                keypair = pygit2.Keypair(
                    "git",
                    pub_path if os.path.exists(pub_path) else key_path,
                    key_path,
                    "",
                )
                callbacks.credentials = lambda *_args: keypair
        elif credential.cred_type in ("deploy_token", "pat"):
            user_pass = pygit2.UserPass(credential.value, "x-oauth-basic")
            callbacks.credentials = lambda *_args: user_pass

        return callbacks

    def resolve_from_url(self, url: str) -> None:
        """Try to auto-detect credentials from URL format.

        Returns None — callers should use explicit credentials.
        """
        # Public repos don't need auth
        return None
