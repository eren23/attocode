"""Opt-in hosted query rewrite: likely code identifiers for a plain question.

Trial candidate (evals/results/2026-11-query-rewrite.md). The request carries
only the redacted question; no source text, file path or repository name leaves
the machine. Any failure gives no extra words, so search falls back to the
question's own terms.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time

import httpx

from attocode_intel._internal.integrations.context.systemone_ranker import (
    _REMOTE_BLOCKED,
    check_endpoint,
    post_json,
)
from attocode_intel.confidence.redact import redact

OPENROUTER_REWRITE = {
    "endpoint": "https://openrouter.ai/api/v1/chat/completions",
    "model": "anthropic/claude-haiku-5.5",
    "auth_env": "OPENROUTER_API_KEY",
    "timeout_ms": 1500,
}
INSTRUCTION = (
    "Answer only a JSON array of at most 12 identifiers (function, class, method, "
    "file or config names) that code answering this question likely contains."
)
_FENCE = re.compile(r"\A```(?:json)?\s*(.*?)\s*```\Z", re.DOTALL)
_MAX_WORDS = 12
_MAX_WORD_CHARS = 80


class QueryRewriter:
    """One bounded chat-completions call per question.

    The timeout is a whole-call deadline. A timed-out worker keeps the one
    in-flight slot until it exits, so a stalled endpoint cannot queue calls.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        model: str,
        auth_env: str = "",
        allow_remote: bool = False,
        service_mode: bool = False,
        timeout_seconds: float = 1.5,
        max_query_chars: int = 512,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.remote = check_endpoint(
            endpoint, allow_remote=allow_remote, service_mode=service_mode, auth_env=auth_env
        )
        if not model or not 0 < timeout_seconds <= 30 or max_query_chars < 1:
            raise ValueError("invalid rewrite settings")
        self.endpoint = endpoint
        self.model = model
        self.auth_env = auth_env
        self.timeout_seconds = timeout_seconds
        self.max_query_chars = max_query_chars
        self._transport = transport
        self._inflight = threading.Lock()

    def _post(self, body: dict, headers: dict[str, str]) -> object:
        return post_json(self.endpoint, body, headers, self.timeout_seconds, self._transport)

    def _words(self, response: object) -> list[str]:
        if not isinstance(response, dict):
            raise ValueError("invalid rewrite response")
        returned = response.get("model")
        # Hosted routers can answer with a dated snapshot of the pinned model.
        if not (isinstance(returned, str)
                and re.fullmatch(re.escape(self.model) + r"(?:-\d{8})?", returned)):
            raise ValueError("unexpected rewrite model")
        choices = response.get("choices")
        message = choices[0].get("message") if isinstance(choices, list) and choices \
            and isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ValueError("invalid rewrite response")
        content = content.strip()
        fenced = _FENCE.match(content)
        words = json.loads(fenced.group(1) if fenced else content)
        if (not isinstance(words, list) or len(words) > _MAX_WORDS
                or not all(isinstance(word, str) and 0 < len(word) <= _MAX_WORD_CHARS
                           for word in words)):
            raise ValueError("invalid rewrite words")
        return words

    def rewrite(self, query: str) -> tuple[str, list[str], float]:
        """Return ``(status, identifiers, elapsed_ms)``; status ``ok`` on success."""
        started = time.monotonic()

        def outcome(status: str, words: list[str] | None = None) -> tuple[str, list[str], float]:
            return status, words or [], round((time.monotonic() - started) * 1000, 3)

        if not query.strip():
            return outcome("empty_query")
        if self.remote and os.environ.get("ATTOCODE_LOCAL_ONLY", "").lower() in _REMOTE_BLOCKED:
            return outcome("remote_disabled")
        token = os.environ.get(self.auth_env) if self.auth_env else None
        if self.auth_env and not token:
            return outcome("missing_credential")
        question = query[: self.max_query_chars]
        body = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 120,
            "messages": [
                {"role": "system", "content": INSTRUCTION},
                {"role": "user", "content": redact(question) if self.remote else question},
            ],
        }
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if not self._inflight.acquire(blocking=False):
            return outcome("busy")
        done = threading.Event()
        output: list[tuple[str, list[str] | None]] = []

        def call() -> None:
            try:
                output.append(("ok", self._words(self._post(body, headers))))
            except (ValueError, json.JSONDecodeError):
                output.append(("invalid_response", None))
            except (httpx.HTTPError, OSError):
                output.append(("transport_error", None))
            except Exception:
                output.append(("provider_error", None))
            finally:
                self._inflight.release()
                done.set()

        try:
            threading.Thread(target=call, name="query-rewriter", daemon=True).start()
        except RuntimeError:
            self._inflight.release()
            return outcome("provider_error")
        if not done.wait(self.timeout_seconds):
            return outcome("timeout")
        return outcome(*output[0])
