"""Validate remotely supplied repository locations before storing them."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from fastapi import HTTPException


def validate_remote_source(clone_url=None, local_path=None):
    from attocode_intel.api.deps import get_config

    if not get_config().is_service_mode:
        return
    if local_path:
        raise HTTPException(422, "Remote clients cannot select server filesystem paths. Connect a Git URL or use local MCP.")
    if clone_url:
        parsed = urlsplit(clone_url)
        scp_url = re.fullmatch(r"[\w.-]+@[\w.-]+:[^\s]+", clone_url)
        if not scp_url and not (parsed.scheme in {"https", "http", "ssh"} and parsed.hostname):
            raise HTTPException(422, "Repository URL must use HTTP(S) or SSH; local paths and file URLs are not accepted.")
