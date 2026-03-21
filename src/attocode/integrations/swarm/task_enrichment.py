"""Post-decomposition task enrichment pipeline.

Enriches thin subtask descriptions with acceptance criteria, code context,
technical constraints, and modification instructions. Ensures that workers
receive enough information to produce correct output on the first attempt.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from attocode.integrations.swarm.orchestrator import OrchestratorInternals
    from attocode.integrations.swarm.types import SmartSubtask

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class EnrichmentConfig:
    """Configuration for the task enrichment pipeline."""

    min_description_chars: int = 80
    require_acceptance_criteria: bool = True
    require_code_context: bool = True
    max_code_snippet_chars: int = 2000
    skip_enrichment_for_types: list[str] = field(
        default_factory=lambda: ["research", "design"]
    )


# =============================================================================
# Result
# =============================================================================


@dataclass
class EnrichmentResult:
    """Result of the enrichment pipeline."""

    enriched_subtasks: list[SmartSubtask] = field(default_factory=list)
    rejected_ids: list[str] = field(default_factory=list)
    re_decompose_requested: bool = False


# =============================================================================
# Actionable Verb Detection
# =============================================================================

_ACTIONABLE_VERBS = frozenset({
    "add", "create", "implement", "write", "build", "define", "update",
    "modify", "refactor", "extract", "fix", "delete", "remove", "replace",
    "configure", "set up", "test", "validate", "verify", "integrate",
    "migrate", "convert", "extend", "enhance", "optimize", "document",
    "move", "rename", "split", "merge", "wrap", "deploy", "install",
    "scaffold", "generate", "parse", "serialize", "deserialize",
})


def _has_actionable_verb(description: str) -> bool:
    """Check whether a description starts with or contains an actionable verb."""
    lower = description.lower().strip()
    for verb in _ACTIONABLE_VERBS:
        if lower.startswith(verb):
            return True
        # Also check after common prefixes like "- " or "* "
        if re.search(rf'\b{re.escape(verb)}\b', lower[:80]):
            return True
    return False


# =============================================================================
# Description Quality Check
# =============================================================================


def _check_description_quality(
    subtask: SmartSubtask,
    config: EnrichmentConfig,
) -> list[str]:
    """Return issues with subtask description. Empty list = good quality.

    Checks:
    - Description length >= min_description_chars
    - Contains an actionable verb
    - Has at least one target or relevant file
    """
    issues: list[str] = []

    if len(subtask.description) < config.min_description_chars:
        issues.append(
            f"Description too short ({len(subtask.description)} chars, "
            f"minimum {config.min_description_chars})"
        )

    if not _has_actionable_verb(subtask.description):
        issues.append("Description lacks an actionable verb")

    has_files = bool(
        subtask.target_files
        or subtask.relevant_files
        or subtask.read_files
    )
    if not has_files:
        issues.append("No target or relevant files specified")

    return issues


# =============================================================================
# Code Context Gathering
# =============================================================================


def _gather_code_context(
    ctx: OrchestratorInternals,
    subtask: SmartSubtask,
    config: EnrichmentConfig,
) -> list[str]:
    """Pull relevant code snippets from AST service or file reads.

    For each target/relevant file, attempts to read the first N chars and
    extract key structures (classes, functions) to give the worker context.
    """
    snippets: list[str] = []
    max_snippet_chars = config.max_code_snippet_chars

    # Collect seed files
    seed_files: list[str] = []
    if subtask.target_files:
        seed_files.extend(subtask.target_files[:3])
    if subtask.relevant_files:
        seed_files.extend(subtask.relevant_files[:3])
    if subtask.read_files:
        seed_files.extend(subtask.read_files[:2])

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_files: list[str] = []
    for f in seed_files:
        if f not in seen:
            seen.add(f)
            unique_files.append(f)

    working_dir = getattr(ctx, "working_dir", None) or "."

    for fpath in unique_files[:5]:
        full_path = (
            os.path.join(working_dir, fpath)
            if not os.path.isabs(fpath)
            else fpath
        )
        if not os.path.isfile(full_path):
            continue

        try:
            with open(full_path, encoding="utf-8", errors="replace") as f:
                content = f.read(max_snippet_chars + 500)

            # Truncate to max_snippet_chars
            if len(content) > max_snippet_chars:
                content = content[:max_snippet_chars] + "\n... (truncated)"

            if content.strip():
                snippets.append(f"### {fpath}\n```\n{content}\n```")

            if len(snippets) >= 3:
                break
        except Exception:
            continue

    # Also try AST service for structural info
    ast_svc = None
    if ctx.codebase_context and hasattr(ctx.codebase_context, "_ast_service"):
        ast_svc = ctx.codebase_context._ast_service

    if ast_svc is not None and hasattr(ast_svc, "get_file_symbols"):
        for fpath in unique_files[:3]:
            try:
                symbols = ast_svc.get_file_symbols(fpath)
                if symbols:
                    symbol_info = f"### Symbols in {fpath}\n{symbols[:500]}"
                    if symbol_info not in snippets:
                        snippets.append(symbol_info)
            except Exception:
                continue

    return snippets


# =============================================================================
# Rule-Based Acceptance Criteria Generation
# =============================================================================


def _generate_acceptance_criteria(
    subtask: SmartSubtask,
    task_type: str,
) -> list[str]:
    """Generate rule-based acceptance criteria by task type.

    Returns a list of criteria strings appropriate for the given task type.
    """
    criteria: list[str] = []

    if task_type in ("implement", "integrate"):
        if subtask.target_files:
            for tf in subtask.target_files[:3]:
                criteria.append(f"File '{tf}' exists and is non-empty")
        criteria.append("Contains described functions/classes")
        criteria.append("Imports resolve without errors")
        criteria.append("No syntax errors in modified files")

    elif task_type == "test":
        criteria.append("Test file exists and is non-empty")
        criteria.append("Tests pass when run")
        criteria.append("Edge cases are covered")
        criteria.append("Test names are descriptive")

    elif task_type == "refactor":
        criteria.append("All existing tests still pass")
        criteria.append("No new type errors introduced")
        criteria.append("API surface unchanged (same exports/signatures)")
        criteria.append("No syntax errors in modified files")

    elif task_type == "document":
        criteria.append("Documentation file exists and is non-empty")
        criteria.append("All public API items are documented")
        criteria.append("Examples are runnable")

    elif task_type == "deploy":
        criteria.append("Deployment configuration is valid")
        criteria.append("Required environment variables documented")
        criteria.append("Health check endpoint responds")

    else:
        # Generic criteria
        criteria.append("Task output matches description")
        criteria.append("No syntax errors in modified files")

    return criteria


# =============================================================================
# LLM Enrichment for Thin Tasks
# =============================================================================


async def _enrich_single_task(
    ctx: OrchestratorInternals,
    subtask: SmartSubtask,
    original_task: str,
    sibling_context: str,
    config: EnrichmentConfig,
) -> SmartSubtask:
    """Use LLM to flesh out a thin task description.

    Called for tasks whose description quality check reveals issues.
    Returns the subtask with enriched fields.
    """
    target_files = ", ".join(subtask.target_files[:5]) if subtask.target_files else "none"
    relevant_files = ", ".join(subtask.relevant_files[:5]) if subtask.relevant_files else "none"

    prompt = f"""Enrich this thin subtask description for a swarm worker agent.

## Original Task
{original_task}

## Subtask to Enrich
- ID: {subtask.id}
- Type: {subtask.type}
- Description: {subtask.description}
- Target files: {target_files}
- Relevant files: {relevant_files}

## Sibling Tasks
{sibling_context}

Return ONLY JSON:
{{
  "enriched_description": "Detailed description of what the worker should do...",
  "acceptance_criteria": ["criterion 1", "criterion 2", ...],
  "technical_constraints": ["constraint 1", ...],
  "modification_instructions": "Step-by-step instructions...",
  "test_expectations": ["test 1 should pass", ...]
}}"""

    try:
        response = await ctx.provider.chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.2,
        )
        if ctx.track_orchestrator_usage:
            ctx.track_orchestrator_usage(response, "task-enrichment")

        from attocode.integrations.swarm.lifecycle import parse_json
        parsed = parse_json(response.content)
        if parsed:
            enriched_desc = parsed.get("enriched_description", "")
            if enriched_desc and len(enriched_desc) > len(subtask.description):
                subtask.description = enriched_desc

            new_criteria = parsed.get("acceptance_criteria")
            if isinstance(new_criteria, list) and new_criteria:
                if subtask.acceptance_criteria:
                    # Merge, avoiding duplicates
                    existing = set(subtask.acceptance_criteria)
                    subtask.acceptance_criteria.extend(
                        c for c in new_criteria if c not in existing
                    )
                else:
                    subtask.acceptance_criteria = new_criteria

            new_constraints = parsed.get("technical_constraints")
            if isinstance(new_constraints, list) and new_constraints:
                subtask.technical_constraints = new_constraints

            new_instructions = parsed.get("modification_instructions")
            if isinstance(new_instructions, str) and new_instructions:
                subtask.modification_instructions = new_instructions

            new_tests = parsed.get("test_expectations")
            if isinstance(new_tests, list) and new_tests:
                subtask.test_expectations = new_tests

    except Exception as exc:
        logger.warning("LLM enrichment failed for subtask %s: %s", subtask.id, exc)

    return subtask


# =============================================================================
# Main Enrichment Pipeline
# =============================================================================


async def enrich_subtasks(
    ctx: OrchestratorInternals,
    subtasks: list[SmartSubtask],
    original_task: str,
    config: EnrichmentConfig | None = None,
) -> EnrichmentResult:
    """Post-decomposition enrichment pipeline.

    For each subtask:
    1. Check description quality
    2. Gather code context from target/relevant files
    3. Generate rule-based acceptance criteria
    4. For thin tasks, use LLM to enrich descriptions

    Args:
        ctx: Orchestrator internals for provider access and codebase context.
        subtasks: The subtasks to enrich (modified in-place).
        original_task: The original user task description.
        config: Optional enrichment configuration.

    Returns:
        An :class:`EnrichmentResult` with the enriched subtasks and metadata.
    """
    if config is None:
        config = EnrichmentConfig(
            min_description_chars=ctx.config.enrichment_min_description_chars,
        )

    enriched: list[SmartSubtask] = []
    rejected_ids: list[str] = []
    thin_tasks: list[SmartSubtask] = []

    # Build sibling context for LLM enrichment
    sibling_lines = []
    for st in subtasks:
        sibling_lines.append(f"- {st.id} ({st.type}): {st.description[:100]}")
    sibling_context = "\n".join(sibling_lines)

    for subtask in subtasks:
        # Skip enrichment for excluded types
        if subtask.type in config.skip_enrichment_for_types:
            enriched.append(subtask)
            continue

        # Step 1: Check description quality
        issues = _check_description_quality(subtask, config)

        # Step 2: Gather code context
        if config.require_code_context:
            snippets = _gather_code_context(ctx, subtask, config)
            if snippets and not subtask.code_context_snippets:
                subtask.code_context_snippets = snippets

        # Step 3: Generate rule-based acceptance criteria
        if config.require_acceptance_criteria and not subtask.acceptance_criteria:
            subtask.acceptance_criteria = _generate_acceptance_criteria(
                subtask, subtask.type
            )

        # Step 4: Mark thin tasks for LLM enrichment
        if issues:
            thin_tasks.append(subtask)
            logger.info(
                "Task %s flagged for enrichment: %s",
                subtask.id, "; ".join(issues),
            )

        enriched.append(subtask)

    # LLM enrichment for thin tasks (one call per task)
    for thin_task in thin_tasks:
        try:
            await _enrich_single_task(
                ctx, thin_task, original_task, sibling_context, config,
            )
        except Exception as exc:
            logger.warning("Failed to enrich task %s: %s", thin_task.id, exc)

    # Check rejection ratio
    # If description quality is still too low after enrichment, reject
    still_thin = 0
    for subtask in enriched:
        if subtask.type in config.skip_enrichment_for_types:
            continue
        issues = _check_description_quality(subtask, config)
        if issues:
            still_thin += 1

    enrichable_count = sum(
        1 for st in enriched
        if st.type not in config.skip_enrichment_for_types
    )
    re_decompose = False
    if enrichable_count > 0 and still_thin / enrichable_count > 0.5:
        re_decompose = True
        rejected_ids = [
            st.id for st in enriched
            if st.type not in config.skip_enrichment_for_types
            and _check_description_quality(st, config)
        ]

    return EnrichmentResult(
        enriched_subtasks=enriched,
        rejected_ids=rejected_ids,
        re_decompose_requested=re_decompose,
    )
