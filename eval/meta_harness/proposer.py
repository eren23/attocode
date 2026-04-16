"""LLM-based config proposer for meta-harness optimization.

Uses Claude to analyze evaluation results and propose targeted
parameter configurations based on failure analysis.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import yaml

from eval.meta_harness._llm_client import call_llm, diff_from_defaults, load_env
from eval.meta_harness.harness_config import HarnessConfig

logger = logging.getLogger(__name__)

_SKILL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".claude", "skills", "meta-harness-code-intel", "SKILL.md",
)


def _build_prompt(
    current_config: HarnessConfig,
    eval_result: dict[str, Any],
    history: list[dict[str, Any]],
    n_candidates: int = 3,
) -> str:
    """Build the proposer prompt with current state and failure analysis."""
    # Load skill for context
    skill_text = ""
    if os.path.isfile(_SKILL_PATH):
        with open(_SKILL_PATH) as f:
            skill_text = f.read()

    # Format current config
    config_yaml = yaml.dump(current_config.to_dict(), default_flow_style=False, sort_keys=True)

    # Extract failure analysis from search quality results
    failure_analysis = _build_failure_analysis(eval_result)

    # Format history (last 10 entries)
    history_text = ""
    if history:
        recent = history[-10:]
        lines = []
        defaults = HarnessConfig.default().to_dict()
        for h in recent:
            cfg_changes = diff_from_defaults(h.get("config", {}), defaults)
            lines.append(
                f"  - score={h.get('score', 0):.4f} status={h.get('status', '?')} "
                f"changes: {cfg_changes}"
            )
        history_text = "\n".join(lines)

    prompt = f"""You are optimizing code-intel search scoring parameters.

{skill_text}

## Current Best Config (score: {eval_result.get('composite', 0):.4f})

```yaml
{config_yaml}```

## Evaluation Breakdown

### Search Quality
{_format_search_quality(eval_result.get('search_quality', {}))}

### MCP Bench
{_format_mcp_bench(eval_result.get('mcp_bench', {}))}

## Failure Analysis
{failure_analysis}

## Recent History
{history_text or "No previous experiments."}

## Task

Propose {n_candidates} distinct candidate configs. For each:
1. State your hypothesis (what you're trying to improve and why)
2. Identify which failing queries this targets
3. Output a complete YAML config block with ALL 21 parameters

Output each candidate as a fenced YAML block with a hypothesis comment.
Use exactly this format for each candidate:

```yaml
# Hypothesis: <your hypothesis here>
bm25_k1: ...
bm25_b: ...
name_exact_boost: ...
name_substring_boost: ...
name_token_boost: ...
class_boost: ...
function_boost: ...
method_boost: ...
src_dir_boost: ...
multi_term_high_bonus: ...
multi_term_med_bonus: ...
multi_term_high_threshold: ...
multi_term_med_threshold: ...
non_code_penalty: ...
config_penalty: ...
test_penalty: ...
exact_phrase_bonus: ...
max_chunks_per_file: ...
wide_k_multiplier: ...
wide_k_min: ...
rrf_k: ...
```
"""
    return prompt


def _build_failure_analysis(eval_result: dict[str, Any]) -> str:
    """Extract per-query failures for the proposer to analyze."""
    lines: list[str] = []
    sq = eval_result.get("search_quality", {})
    per_repo = sq.get("per_repo", {})

    for repo, data in per_repo.items():
        query_details = data.get("query_details", [])
        if not query_details:
            continue

        # Sort by MRR ascending (worst first)
        sorted_queries = sorted(query_details, key=lambda q: q.get("mrr", 0))

        lines.append(f"\n### {repo} (avg MRR={data.get('mrr', 0):.3f})")
        for q in sorted_queries:
            mrr = q.get("mrr", 0)
            status = "GOOD" if mrr >= 0.5 else "WEAK" if mrr > 0 else "MISS"
            lines.append(f"\n**[{status}]** \"{q['query']}\" — MRR={mrr:.3f} recall={q.get('recall', 0):.3f}")
            if q.get("retrieved_top5"):
                lines.append(f"  Retrieved: {', '.join(q['retrieved_top5'][:3])}")
            if q.get("missed_files"):
                lines.append(f"  Missed: {', '.join(q['missed_files'][:3])}")

    return "\n".join(lines) if lines else "No query-level data available."


def _format_search_quality(sq: dict[str, Any]) -> str:
    if not sq or sq.get("error"):
        return f"Error: {sq.get('error', 'not available')}"
    return (
        f"Composite: {sq.get('composite', 0):.4f} | "
        f"MRR: {sq.get('avg_mrr', 0):.3f} | "
        f"NDCG: {sq.get('avg_ndcg', 0):.3f} | "
        f"P@10: {sq.get('avg_precision', 0):.3f} | "
        f"R@20: {sq.get('avg_recall', 0):.3f}"
    )


def _format_mcp_bench(mb: dict[str, Any]) -> str:
    if not mb or mb.get("error"):
        return f"Error: {mb.get('error', 'not available')}"
    lines = [f"Composite: {mb.get('composite', 0):.4f} ({mb.get('total_tasks', 0)} tasks)"]
    for cat, stats in mb.get("per_category", {}).items():
        lines.append(f"  {cat}: {stats.get('mean_score', 0):.2f}/5.0 ({stats.get('count', 0)} tasks)")
    return "\n".join(lines)


def _diff_from_defaults(config: dict[str, Any]) -> str:
    """Show which parameters differ from defaults."""
    defaults = HarnessConfig.default().to_dict()
    diffs = []
    for k, v in config.items():
        default_v = defaults.get(k)
        if default_v is not None and v != default_v:
            diffs.append(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}")
    return ", ".join(diffs) if diffs else "(defaults)"


def propose_configs_llm(
    current_config: HarnessConfig,
    eval_result: dict[str, Any],
    history: list[dict[str, Any]],
    n_candidates: int = 3,
    model: str = "",
) -> list[tuple[HarnessConfig, str]]:
    """Use an LLM to propose new configs based on failure analysis.

    Supports Anthropic direct or OpenRouter. Auto-detects based on
    available API keys.

    Args:
        current_config: Current best config.
        eval_result: Full evaluation result metadata.
        history: List of previous experiment entries.
        n_candidates: Number of configs to propose.
        model: Model identifier (auto-detected if empty).

    Returns:
        List of (HarnessConfig, hypothesis) tuples.
    """
    load_env()

    prompt = _build_prompt(current_config, eval_result, history, n_candidates)
    text = call_llm(prompt, model)
    return _parse_candidates(text)


def _diff_from_defaults(config: dict[str, Any]) -> str:
    """Backward-compat shim — see :func:`_llm_client.diff_from_defaults`."""
    return diff_from_defaults(config, HarnessConfig.default().to_dict())


def _parse_candidates(text: str) -> list[tuple[HarnessConfig, str]]:
    """Parse YAML config blocks from Claude's response.

    Returns list of (HarnessConfig, hypothesis) tuples.
    """
    candidates: list[tuple[HarnessConfig, str]] = []

    # Find all fenced YAML blocks
    pattern = r"```ya?ml\s*\n(.*?)```"
    blocks = re.findall(pattern, text, re.DOTALL)

    for block in blocks:
        try:
            # Extract hypothesis from comment
            hypothesis = ""
            for line in block.splitlines():
                line = line.strip()
                if line.startswith("# Hypothesis:") or line.startswith("#Hypothesis:"):
                    hypothesis = line.split(":", 1)[1].strip()
                    break
                elif line.startswith("# ") and not hypothesis:
                    hypothesis = line[2:].strip()

            # Parse YAML (strip comment lines for yaml.safe_load)
            yaml_lines = [l for l in block.splitlines() if not l.strip().startswith("#")]
            data = yaml.safe_load("\n".join(yaml_lines))

            if not isinstance(data, dict):
                continue

            # Must have at least some expected keys
            expected_keys = {"bm25_k1", "non_code_penalty", "rrf_k"}
            if not expected_keys.intersection(data.keys()):
                continue

            config = HarnessConfig.from_dict(data)
            errors = config.validate()
            if errors:
                logger.warning("LLM proposed invalid config: %s", errors)
                continue

            candidates.append((config, hypothesis))

        except Exception as exc:
            logger.warning("Failed to parse candidate block: %s", exc)
            continue

    return candidates
