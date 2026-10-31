"""Shared LLM client scaffolding for meta-harness proposers.

Both the search-scoring proposer (``proposer.py``) and the rule-bench
proposer (``rule_bench/proposer.py``) call into Claude via the same
underlying client. This module owns the keys, model selection, and the
``.env`` loader so we don't duplicate that logic in each proposer.

Public surface:
- :func:`call_llm` — re-exported from the shipped package
- :func:`load_env` — populate API keys from project ``.env`` files
- :func:`diff_from_defaults` — render a parameter diff string
"""

from __future__ import annotations

import os
from typing import Any

from attocode_intel.confidence.llm import call_llm

__all__ = ["call_llm", "diff_from_defaults", "load_env"]


def load_env() -> None:
    """Load API keys from project ``.env`` files if missing from environment."""
    needed = ["OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"]
    if any(os.environ.get(k) for k in needed):
        return

    project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    for env_file in [".env", ".env.dev"]:
        env_path = os.path.join(project_root, env_file)
        if not os.path.isfile(env_path):
            continue
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"")
                if key in needed and value:
                    os.environ[key] = value


def diff_from_defaults(
    config: dict[str, Any], defaults: dict[str, Any]
) -> str:
    """Render a comma-separated diff of *config* vs *defaults* (for prompts)."""
    diffs: list[str] = []
    for k, v in config.items():
        default_v = defaults.get(k)
        if default_v is not None and v != default_v:
            if isinstance(v, float):
                diffs.append(f"{k}={v:.3f}")
            else:
                diffs.append(f"{k}={v}")
    return ", ".join(diffs) if diffs else "(defaults)"
