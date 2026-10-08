"""Bounded, opt-in SystemOne shortlist ranking over an explicit HTTP endpoint.

This is a wire-protocol adapter, not a model recommendation. In particular,
being compatible with ``POST /v1/systemone`` says nothing about code-search
quality. No request is made during construction or for a disabled provider.
"""

from __future__ import annotations

import ipaddress
import json
import math
import os
import re
import threading
from urllib.parse import urlsplit

import httpx

from attocode_intel._internal.integrations.context.reranker import RankingOutcome
from attocode_intel.confidence.redact import redact

_MAX_RESPONSE_BYTES = 64 * 1024
_REMOTE_BLOCKED = {"1", "true", "yes", "on"}


class SystemOneChoiceReranker:
    """One ``choice`` request for a bounded page of distinct files.

    The timeout is a whole-call deadline. A timed-out worker retains the one
    in-flight slot until it exits, so a stalled endpoint cannot create an
    unbounded queue. Responses must contain a complete probability distribution.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        model: str = "",
        auth_env: str = "",
        allow_remote: bool = False,
        service_mode: bool = False,
        max_candidates: int = 24,
        timeout_seconds: float | None = None,
        max_query_chars: int = 512,
        max_excerpt_chars: int = 1350,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        parsed = urlsplit(endpoint)
        try:
            host = parsed.hostname
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("invalid ranking endpoint") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or not parsed.path
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "ranking endpoint must be an absolute HTTP(S) URL without credentials or query"
            )
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            # A hostname can resolve differently between validation and use.
            # Local source access requires an explicit loopback IP literal.
            loopback = False
        if not loopback and parsed.scheme != "https":
            raise ValueError("non-loopback ranking endpoints require HTTPS")
        if not loopback and (
            not allow_remote
            or service_mode
            or os.environ.get("ATTOCODE_LOCAL_ONLY", "").lower() in _REMOTE_BLOCKED
        ):
            raise ValueError("remote source ranking is not permitted")
        if auth_env and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", auth_env) is None:
            raise ValueError("ranking credential must be an environment-variable name")
        if timeout_seconds is None:
            timeout_seconds = 5.0 if loopback else 0.8
        if not 1 <= max_candidates <= 64 or not 0 < timeout_seconds <= 30:
            raise ValueError("invalid ranking limits")
        if min(max_query_chars, max_excerpt_chars) < 1:
            raise ValueError("ranking text limits must be positive")
        self.endpoint = endpoint
        self.model = model
        self.auth_env = auth_env
        self.remote = not loopback
        self.max_candidates = max_candidates
        self.timeout_seconds = timeout_seconds
        self.max_query_chars = max_query_chars
        self.max_excerpt_chars = max_excerpt_chars
        self._transport = transport
        self._inflight = threading.Lock()

    @property
    def status(self) -> str:
        return "configured"

    @property
    def is_available(self) -> bool:
        return True

    def _post(self, body: dict, headers: dict[str, str]) -> dict:
        # Do not inherit proxy settings or follow a redirect to a different
        # origin; both could silently send source to an unapproved host.
        with (
            httpx.Client(
                timeout=self.timeout_seconds,
                trust_env=False,
                follow_redirects=False,
                transport=self._transport,
            ) as client,
            client.stream("POST", self.endpoint, json=body, headers=headers) as response,
        ):
            response.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > _MAX_RESPONSE_BYTES:
                    raise ValueError("ranking response too large")
                chunks.append(chunk)
        result = json.loads(b"".join(chunks))
        if not isinstance(result, dict):
            raise ValueError("invalid ranking response")
        # Workers AI wraps every answer as {"result": {...}, "success": true, "errors": []}.
        inner = result.get("result")
        if "answers" not in result and isinstance(inner, dict):
            if result.get("success") is not True or result.get("errors"):
                raise ValueError("ranking provider reported a failure")
            result = {"model": result["model"], **inner} if "model" in result else inner
        return result

    @staticmethod
    def _scores(response: dict, count: int) -> list[float]:
        answers = response.get("answers")
        answer = answers.get("best") if isinstance(answers, dict) else None
        probabilities = answer.get("probabilities") if isinstance(answer, dict) else None
        choice = answer.get("choice") if isinstance(answer, dict) else None
        expected = {str(index) for index in range(count)}
        if (
            not isinstance(probabilities, dict)
            or set(probabilities) != expected
            or not isinstance(choice, str)
            or choice not in expected
        ):
            raise ValueError("incomplete ranking probabilities")
        scores = [probabilities[str(index)] for index in range(count)]
        if any(
            isinstance(score, bool)
            or not isinstance(score, int | float)
            or not math.isfinite(score)
            or not 0 <= score <= 1
            for score in scores
        ):
            raise ValueError("invalid ranking probability")
        numeric = [float(score) for score in scores]
        if not 0.95 <= sum(numeric) <= 1.05:
            raise ValueError("ranking probabilities do not sum to one")
        if numeric[int(choice)] < max(numeric) - 1e-6:
            raise ValueError("choice disagrees with ranking probabilities")
        return numeric

    def rerank_result(
        self,
        query: str,
        candidates: list[tuple[str, str, float]],
        top_k: int = 10,
    ) -> RankingOutcome:
        fallback = candidates[: max(0, top_k)]
        if top_k <= 0 or not candidates:
            return RankingOutcome(fallback, False, "empty")
        if not query.strip():
            return RankingOutcome(fallback, False, "empty_query")
        if self.remote and os.environ.get("ATTOCODE_LOCAL_ONLY", "").lower() in _REMOTE_BLOCKED:
            return RankingOutcome(fallback, False, "remote_disabled")
        token = os.environ.get(self.auth_env) if self.auth_env else None
        if self.auth_env and not token:
            return RankingOutcome(fallback, False, "missing_credential")
        bounded = candidates[: self.max_candidates]
        question = {
            "best": {
                "type": "choice",
                "instructions": "Which source file most directly implements the behavior in the query?",
                "criteria": {
                    str(index): excerpt[: self.max_excerpt_chars]
                    for index, (_id, excerpt, _score) in enumerate(bounded)
                },
            },
        }
        state = {
            "query": query[: self.max_query_chars],
            "task": "Find the primary implementation file, not an incidental match.",
        }
        if self.remote:
            state["query"] = redact(state["query"])
            question["best"]["criteria"] = {
                key: redact(value) for key, value in question["best"]["criteria"].items()
            }
        body = {"state": state, "questions": question}
        if self.model:
            body["model"] = self.model
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if not self._inflight.acquire(blocking=False):
            return RankingOutcome(fallback, False, "busy")
        done = threading.Event()
        output: list[tuple[str, list[float] | None]] = []

        def predict() -> None:
            try:
                response = self._post(body, headers)
                if self.model and response.get("model") not in {None, self.model}:
                    raise ValueError("unexpected ranking model")
                output.append(("ok", self._scores(response, len(bounded))))
            except ValueError:
                output.append(("invalid_response", None))
            except (httpx.HTTPError, json.JSONDecodeError, OSError):
                output.append(("transport_error", None))
            except Exception:
                output.append(("provider_error", None))
            finally:
                self._inflight.release()
                done.set()

        try:
            threading.Thread(target=predict, name="systemone-ranker", daemon=True).start()
        except RuntimeError:
            self._inflight.release()
            return RankingOutcome(fallback, False, "provider_error")
        if not done.wait(self.timeout_seconds):
            return RankingOutcome(fallback, False, "timeout")
        status, scores = output[0]
        if scores is None:
            return RankingOutcome(fallback, False, status)
        scored = [
            (candidate_id, excerpt, score)
            for (candidate_id, excerpt, _original), score in zip(bounded, scores, strict=True)
        ]
        scored.sort(key=lambda item: item[2], reverse=True)
        return RankingOutcome((scored + candidates[self.max_candidates :])[:top_k], True)
