"""Shared LLM client scaffolding for meta-harness proposers.

Both the search-scoring proposer (``proposer.py``) and the rule-bench
proposer (``rule_bench/proposer.py``) call into Claude via the same
underlying client. This module owns the keys, model selection, and the
``.env`` loader so we don't duplicate that logic in each proposer.

Public surface:
- :func:`call_llm` — send a single-prompt completion request
- :func:`load_env` — populate API keys from project ``.env`` files
- :func:`diff_from_defaults` — render a parameter diff string
"""

from __future__ import annotations

import os
from typing import Any


def call_llm(prompt: str, model: str = "", max_tokens: int = 4096) -> str:
    """Call the LLM via OpenRouter or Anthropic direct.

    Routes to OpenRouter when ``OPENROUTER_API_KEY`` is set (preferred),
    falling back to ``ANTHROPIC_API_KEY``. Raises ``RuntimeError`` if
    neither key is present.
    """
    or_key = os.environ.get("OPENROUTER_API_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if or_key:
        import openai

        if not model:
            model = "anthropic/claude-sonnet-4"
        client = openai.OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=or_key,
        )
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content or ""

    if anthropic_key:
        import anthropic

        if not model:
            model = "claude-sonnet-4-20250514"
        client = anthropic.Anthropic(api_key=anthropic_key)
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    raise RuntimeError(
        "No API key found. Set OPENROUTER_API_KEY or ANTHROPIC_API_KEY "
        "in environment or .env file."
    )


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
