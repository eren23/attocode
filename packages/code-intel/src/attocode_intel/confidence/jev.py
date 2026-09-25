"""Jev scorer — a calibrated probability in place of a hardcoded constant.

Jev (TypeSafe System One) answers a yes/no question with a probability.
Historical comparisons and their limitations live in eval/rule_accuracy/demo.

It needs no client library. The backend is a public HTTP endpoint and one POST
is the whole protocol. Supported backends are OpenRouter, TypeSafe, and a
local server, with credentials selected for the configured backend.

If the standalone `jev` CLI happens to be importable, its decide() is used
outside workspace-scoped requests. It also appends a row to
~/.jev/decisions.jsonl, which is what `jev label` and `jev report` read.

An unkeyed or unreachable backend yields no estimate, and the caller keeps its
constant.
"""

from __future__ import annotations

import json
import logging
import math
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from attocode_intel.confidence import settings
from attocode_intel.confidence.redact import redact

if TYPE_CHECKING:
    from collections.abc import Sequence

try:  # optional: only for the decisions.jsonl log the jev CLI reads
    import jev

    _HAS_JEV = True
except ImportError:
    jev = None
    _HAS_JEV = False

logger = logging.getLogger(__name__)

_env_loaded = False


def _load_env() -> None:
    """Populate keys once, from wherever this machine keeps them.

    The jev CLI keeps its key in ~/.jev/env; the project keeps one in .env.
    Neither is on a hook's or a subprocess's environment by default.
    """
    global _env_loaded
    if settings.project_dir():
        return  # Scoped requests read .env without mutating process credentials.
    if _env_loaded:
        return
    _env_loaded = True
    if _HAS_JEV:
        jev.load_env()
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - declared dependency
        return
    load_dotenv()


# backend -> (url, model, key env var). Mirrors the jev CLI so a row logged by
# either route is directly comparable.
_BACKENDS = {
    "openrouter": (
        "https://openrouter.ai/api/alpha/decisions",
        "typesafe/jev-1.13",
        "OPENROUTER_API_KEY",
    ),
    "typesafe": ("https://api.typesafe.ai/v1/systemone", "jev-1.13.0", "TYPESAFE_API_KEY"),
    "local": (None, "jev-latest", "OPENJEV_API_KEY"),
}

# Measured on the rule corpus: near-linear to 16 workers (9.8x), flat after.
WORKERS = 16

QUESTION = "Is this rule match a true positive at this location?"
CRITERIA = {
    "true": "The problem the rule describes is really present in this code.",
    "false": "Test code, a comment, a string literal, a dead branch, or the case "
             "is already handled nearby.",
}


def available() -> bool:
    """True when a backend can be reached: a key, or a local server."""
    _load_env()
    chosen = backend()
    return bool(chosen == "local" and (
        settings.environment().get("JEV_BASE_URL")
        or settings.environment().get("JEV_BACKEND") == "local"
        or settings.local_settings().get("backend") == "local"
        or settings.environment().get("ATTOCODE_LOCAL_ONLY", "").lower() in {"1", "true", "yes", "on"}
    ) or settings.environment().get(_BACKENDS[chosen][2])
        or (_HAS_JEV and not settings.project_dir()))


def _decide(site: str, state: dict[str, Any], questions: dict[str, Any],
            incumbent: str, chosen: str) -> dict[str, Any]:
    """One decision. Uses the jev CLI when present, else a direct POST."""
    if _HAS_JEV and not settings.project_dir():
        result: dict[str, Any] = jev.decide(
            site, state, questions, incumbent=incumbent, backend=chosen,
        )
        return result

    env = settings.environment()
    url, model, keyvar = _BACKENDS[chosen]
    if url is None:
        # 127.0.0.1, not localhost: localhost resolves to ::1 first.
        base = env.get("JEV_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
        url = base + "/v1/systemone"
    headers = {"Content-Type": "application/json"}
    key = env.get(keyvar)
    if key:
        headers["Authorization"] = "Bearer " + key
    body = json.dumps(
        {"model": env.get("JEV_MODEL", model), "state": state, "questions": questions}
    ).encode()
    request = urllib.request.Request(url, data=body, headers=headers)  # noqa: S310
    timeout = float(env.get("JEV_TIMEOUT", "20"))
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        parsed: dict[str, Any] = json.loads(response.read())
    return {"answers": parsed.get("answers"), "error": None}


def backend() -> str:
    """Pick a Jev backend: local when offline or unkeyed, else the configured one."""
    _load_env()
    env = settings.environment()
    if env.get("ATTOCODE_LOCAL_ONLY", "").lower() in {"1", "true", "yes", "on"}:
        return "local"
    explicit = env.get("JEV_BACKEND") or settings.local_settings().get("backend")
    if explicit:
        if explicit not in _BACKENDS:
            raise ValueError("Unsupported Jev backend")
        return explicit
    if env.get("OPENROUTER_API_KEY"):
        return "openrouter"
    if env.get("TYPESAFE_API_KEY"):
        return "typesafe"
    return "local"


def _state(finding: Any) -> dict[str, Any]:
    """The evidence Jev sees. Redacted: this leaves the machine."""
    code = "\n".join([
        *getattr(finding, "context_before", []),
        getattr(finding, "code_snippet", ""),
        *getattr(finding, "context_after", []),
    ])
    return {
        "file": redact(finding.file),
        "line": finding.line,
        "rule": redact(getattr(finding, "rule_id", "")),
        "message": redact(getattr(finding, "description", ""))[:1000],
        "code": redact(code)[:3000],
    }


def estimate(findings: Sequence[Any], *, min_confidence: float) -> list[float | None]:
    """Return p(true positive) per finding, or None where Jev gave no answer.

    The incumbent recorded with each row is the constant's own verdict at
    ``min_confidence``, which makes every logged row a paired comparison.
    """
    if not findings:
        return []

    _load_env()
    questions = {"p": {"type": "noul", "instructions": QUESTION, "criteria": CRITERIA}}
    chosen = backend()

    def ask(finding: Any) -> float | None:
        try:
            row = _decide(
                "attocode_rule_fp",
                _state(finding),
                questions,
                "yes" if finding.confidence >= min_confidence else "no",
                chosen,
            )
        except Exception:  # thread plus network; a finding is not worth an outage
            logger.debug("jev: decide failed for %s:%s", finding.file, finding.line)
            return None
        try:
            if row.get("error"):
                return None
            value = ((row.get("answers") or {}).get("p") or {}).get("noul")
            if isinstance(value, bool) or not isinstance(value, int | float):
                return None
            return float(value) if math.isfinite(value) and 0 <= value <= 1 else None
        except (AttributeError, TypeError, ValueError, OverflowError):
            return None

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        from contextvars import copy_context
        futures = [pool.submit(copy_context().run, ask, finding) for finding in findings]
        return [future.result() for future in futures]
