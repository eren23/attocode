"""Jev scorer — a calibrated probability in place of a hardcoded constant.

Jev (TypeSafe System One) answers a yes/no question with a probability rather
than a sampled opinion. Measured against eval/rule_accuracy this is the
best-calibrated scorer available: ECE 0.07 against 0.21 for the constants.

It needs no client library. The backend is a public HTTP endpoint and one POST
is the whole protocol, so this module speaks it directly and needs only an
OPENROUTER_API_KEY.

If the standalone `jev` CLI happens to be importable, its decide() is used
instead. That is the same request, and it also appends a row to
~/.jev/decisions.jsonl, which is what `jev label` and `jev report` read.

An unkeyed or unreachable backend yields no estimate, and the caller keeps its
constant.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

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
    return bool(
        _HAS_JEV  # the CLI resolves its own key from ~/.jev/env
        or os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("TYPESAFE_API_KEY")
        or os.environ.get("ATTOCODE_LOCAL_ONLY")
    )


def _decide(site: str, state: dict[str, Any], questions: dict[str, Any],
            incumbent: str, chosen: str) -> dict[str, Any]:
    """One decision. Uses the jev CLI when present, else a direct POST."""
    if _HAS_JEV:
        result: dict[str, Any] = jev.decide(
            site, state, questions, incumbent=incumbent, backend=chosen,
        )
        return result

    url, model, keyvar = _BACKENDS[chosen]
    if url is None:
        # 127.0.0.1, not localhost: localhost resolves to ::1 first.
        base = os.environ.get("JEV_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
        url = base + "/v1/systemone"
    headers = {"Content-Type": "application/json"}
    key = os.environ.get(keyvar)
    if key:
        headers["Authorization"] = "Bearer " + key
    body = json.dumps(
        {"model": os.environ.get("JEV_MODEL", model), "state": state, "questions": questions}
    ).encode()
    request = urllib.request.Request(url, data=body, headers=headers)  # noqa: S310
    timeout = float(os.environ.get("JEV_TIMEOUT", "20"))
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        parsed: dict[str, Any] = json.loads(response.read())
    return {"answers": parsed.get("answers"), "error": None}


def backend() -> str:
    """Pick a Jev backend: local when offline or unkeyed, else the configured one."""
    if os.environ.get("ATTOCODE_LOCAL_ONLY"):
        return "local"
    _load_env()
    if not os.environ.get("OPENROUTER_API_KEY"):
        return "local"
    return os.environ.get("JEV_BACKEND", "openrouter")


def _state(finding: Any) -> dict[str, Any]:
    """The evidence Jev sees. Redacted: this leaves the machine."""
    code = "\n".join([
        *getattr(finding, "context_before", []),
        getattr(finding, "code_snippet", ""),
        *getattr(finding, "context_after", []),
    ])
    return {
        "file": finding.file,
        "line": finding.line,
        "rule": getattr(finding, "rule_id", ""),
        "message": getattr(finding, "description", ""),
        "code": redact(code[:3000]),
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
        if row.get("error"):
            logger.debug("jev: %s", row["error"])
            return None
        answer = (row.get("answers") or {}).get("p") or {}
        value = answer.get("noul")
        return float(value) if isinstance(value, int | float) else None

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return list(pool.map(ask, findings))
