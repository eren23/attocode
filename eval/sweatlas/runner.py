"""Task execution engine for SWE-Atlas QnA evaluation.

For each task: bootstraps CodeIntelService, runs category-appropriate tools,
generates an answer via LLM, and scores against the rubric.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Ensure src/ is importable
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if os.path.join(_PROJECT_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))


@dataclass
class TaskResult:
    """Result from running a single SWE-Atlas task."""

    task_id: str
    category: str
    repo: str
    mode: str  # "with_code_intel" or "baseline"
    answer: str = ""
    code_intel_context: str = ""
    tools_used: list[str] = field(default_factory=list)
    code_intel_time_ms: int = 0
    llm_time_ms: int = 0
    answer_length: int = 0
    error: str = ""

    # Scoring (filled after rubric evaluation)
    rubric_total: int = 0
    rubric_met: int = 0
    score: float = 0.0
    resolved: bool = False

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "category": self.category,
            "repo": self.repo,
            "mode": self.mode,
            "rubric_total": self.rubric_total,
            "rubric_met": self.rubric_met,
            "score": round(self.score, 3),
            "resolved": self.resolved,
            "tools_used": self.tools_used,
            "code_intel_time_ms": self.code_intel_time_ms,
            "llm_time_ms": self.llm_time_ms,
            "answer_length": self.answer_length,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Symbol/entity extraction from prompts
# ---------------------------------------------------------------------------

def extract_entities(prompt: str) -> dict:
    """Extract file paths, function names, and identifiers from task prompt."""
    entities: dict[str, list[str]] = {"files": [], "symbols": [], "keywords": []}

    # File paths (e.g., src/foo/bar.py, internal/cmd.go)
    file_pattern = r'[a-zA-Z_][\w/.-]*\.\w{1,5}'
    for match in re.findall(file_pattern, prompt):
        if "/" in match and not match.startswith("http"):
            entities["files"].append(match)

    # Backtick-quoted identifiers
    backtick_pattern = r'`([^`]+)`'
    for match in re.findall(backtick_pattern, prompt):
        if "/" in match:
            entities["files"].append(match)
        elif re.match(r'^[A-Za-z_]\w*', match):
            entities["symbols"].append(match)

    # CamelCase or snake_case identifiers that look like code
    ident_pattern = r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+|[a-z]+_[a-z_]+)\b'
    for match in re.findall(ident_pattern, prompt):
        if match not in entities["symbols"] and len(match) > 3:
            entities["symbols"].append(match)

    # Deduplicate
    entities["files"] = list(dict.fromkeys(entities["files"]))[:10]
    entities["symbols"] = list(dict.fromkeys(entities["symbols"]))[:10]

    return entities


# ---------------------------------------------------------------------------
# Code-intel context gathering
# ---------------------------------------------------------------------------

# Tools to run per category
CATEGORY_TOOLS: dict[str, list[str]] = {
    "architecture & system design": [
        "bootstrap", "community_detection", "hotspots", "repo_map_ranked",
    ],
    "root-cause analysis": [
        "bootstrap", "hotspots",
    ],
    "code onboarding": [
        "bootstrap", "conventions",
    ],
    "security": [
        "bootstrap", "security_scan",
    ],
    "api/library integration": [
        "bootstrap",
    ],
    "api & library usage / integration": [
        "bootstrap",
    ],
}

# Fallback for unknown categories
DEFAULT_TOOLS = ["bootstrap"]


def gather_code_intel_context(
    svc,  # CodeIntelService
    task: dict,
    entities: dict,
) -> tuple[str, list[str], int]:
    """Run code-intel tools and return (context_text, tools_used, time_ms)."""
    category = task.get("category", "").lower()
    tool_names = CATEGORY_TOOLS.get(category, DEFAULT_TOOLS)
    tools_used = []
    sections = []
    start = time.monotonic()

    for tool in tool_names:
        try:
            result = _run_tool(svc, tool, entities)
            if result:
                sections.append(f"## {tool}\n{result}")
                tools_used.append(tool)
        except Exception as e:
            logger.warning("Tool %s failed: %s", tool, e)

    # Entity-specific tools: cross-references for symbols, dependency_graph for files
    for sym in entities.get("symbols", [])[:3]:
        try:
            result = svc.cross_references(sym)
            if result and "No definitions" not in result:
                sections.append(f"## cross_references({sym})\n{result}")
                if "cross_references" not in tools_used:
                    tools_used.append("cross_references")
        except Exception as e:
            logger.debug("cross_references(%s) failed: %s", sym, e)

    for filepath in entities.get("files", [])[:3]:
        try:
            result = svc.file_analysis(filepath)
            if result and "not found" not in result.lower():
                sections.append(f"## file_analysis({filepath})\n{result}")
                if "file_analysis" not in tools_used:
                    tools_used.append("file_analysis")
        except Exception as e:
            logger.debug("file_analysis(%s) failed: %s", filepath, e)

        try:
            result = svc.dependency_graph(filepath, depth=2)
            if result and "(none)" not in result:
                sections.append(f"## dependency_graph({filepath})\n{result}")
                if "dependency_graph" not in tools_used:
                    tools_used.append("dependency_graph")
        except Exception as e:
            logger.debug("dependency_graph(%s) failed: %s", filepath, e)

    # Semantic search with keywords from the prompt
    prompt_text = task.get("prompt", "")
    search_query = _build_search_query(prompt_text)
    if search_query:
        try:
            result = svc.semantic_search(search_query, top_k=10)
            if result:
                sections.append(f"## semantic_search({search_query[:60]})\n{result}")
                tools_used.append("semantic_search")
        except Exception as e:
            logger.debug("semantic_search failed: %s", e)

    elapsed_ms = int((time.monotonic() - start) * 1000)
    context = "\n\n".join(sections)

    # Cap context to avoid token overflow
    if len(context) > 30000:
        context = context[:30000] + "\n\n[... truncated ...]"

    return context, tools_used, elapsed_ms


def _run_tool(svc, tool_name: str, entities: dict) -> str:
    """Run a single code-intel tool by name."""
    if tool_name == "bootstrap":
        return svc.bootstrap(max_tokens=6000)
    elif tool_name == "community_detection":
        return svc.community_detection()
    elif tool_name == "hotspots":
        return svc.hotspots(top_n=15)
    elif tool_name == "repo_map_ranked":
        return svc.repo_map(include_symbols=True, max_tokens=4000)
    elif tool_name == "conventions":
        return svc.conventions()
    elif tool_name == "security_scan":
        return svc.security_scan(mode="quick")
    elif tool_name == "project_summary":
        return svc.project_summary()
    else:
        return ""


def _build_search_query(prompt: str) -> str:
    """Extract a semantic search query from the task prompt."""
    # Take the first sentence or first 100 chars as search query
    sentences = re.split(r'[.?!]\s', prompt)
    if sentences:
        query = sentences[0].strip()
        # Remove common preamble
        for prefix in ["I'm trying to", "I want to", "How does", "When "]:
            if query.lower().startswith(prefix.lower()):
                query = query[len(prefix):]
        return query[:150].strip()
    return prompt[:100]


# ---------------------------------------------------------------------------
# Answer generation
# ---------------------------------------------------------------------------

async def generate_answer(
    prompt: str,
    code_intel_context: str,
    *,
    baseline: bool = False,
    model: str = "",
) -> tuple[str, int]:
    """Generate an answer to the task question.

    Returns (answer_text, time_ms).
    """
    try:
        import anthropic
    except ImportError:
        return "Error: anthropic SDK not installed", 0

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "Error: ANTHROPIC_API_KEY not set", 0

    model = model or os.environ.get("SWEATLAS_ANSWER_MODEL", "claude-sonnet-4-6")
    client = anthropic.AsyncAnthropic(api_key=api_key)

    if baseline or not code_intel_context:
        system = (
            "You are answering a deeply technical question about a codebase. "
            "You do not have access to the code — answer based on your general knowledge "
            "of the project and common software engineering patterns. "
            "Be specific and cite likely file paths and function names where possible."
        )
        user_msg = prompt
    else:
        system = (
            "You are answering a deeply technical question about a codebase. "
            "You have access to code intelligence analysis results below. "
            "Use these results to provide a thorough, accurate answer with specific "
            "file paths, function names, and line numbers where possible. "
            "Trace execution paths and explain architectural decisions concretely."
        )
        user_msg = (
            f"# Code Intelligence Context\n\n{code_intel_context}\n\n"
            f"---\n\n# Question\n\n{prompt}"
        )

    # Trim if too long
    if len(user_msg) > 50000:
        user_msg = user_msg[:50000] + "\n\n[... context truncated ...]"

    start = time.monotonic()
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=4000,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        answer = response.content[0].text
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return answer, elapsed_ms
    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return f"Error generating answer: {e}", elapsed_ms


# ---------------------------------------------------------------------------
# Full task execution
# ---------------------------------------------------------------------------

async def run_task(
    task: dict,
    repo_dir: str,
    *,
    baseline: bool = False,
    answer_model: str = "",
    judge_model: str = "",
) -> TaskResult:
    """Execute a single SWE-Atlas task end-to-end.

    1. Bootstrap CodeIntelService (unless baseline)
    2. Gather code-intel context
    3. Generate answer via LLM
    4. Score answer against rubric
    """
    from eval.sweatlas.scorer import (
        compute_task_score,
        parse_rubric,
        score_answer,
    )

    task_id = task.get("task_id", task.get("instance_id", "unknown"))
    category = task.get("category", "unknown")
    repo_url = task.get("repository_url", "unknown")
    repo_name = repo_url.split("/")[-1] if "/" in repo_url else repo_url
    prompt = task.get("prompt", "")
    reference_answer = task.get("reference_answer", "")
    rubric_raw = task.get("rubric", "")
    mode = "baseline" if baseline else "with_code_intel"

    result = TaskResult(
        task_id=task_id,
        category=category,
        repo=repo_name,
        mode=mode,
    )

    # Step 1-2: Gather code-intel context (skip for baseline)
    code_intel_context = ""
    if not baseline:
        try:
            from attocode.code_intel.service import CodeIntelService

            svc = CodeIntelService.get_instance(repo_dir)
            entities = extract_entities(prompt)
            code_intel_context, tools_used, ci_time = gather_code_intel_context(
                svc, task, entities
            )
            result.tools_used = tools_used
            result.code_intel_time_ms = ci_time
            result.code_intel_context = code_intel_context
        except Exception as e:
            logger.warning("Code-intel failed for %s: %s", task_id, e)
            result.error = f"Code-intel error: {e}"

    # Step 3: Generate answer
    answer, llm_time = await generate_answer(
        prompt,
        code_intel_context,
        baseline=baseline,
        model=answer_model,
    )
    result.answer = answer
    result.llm_time_ms = llm_time
    result.answer_length = len(answer)

    if answer.startswith("Error"):
        result.error = answer
        return result

    # Step 4: Score against rubric
    criteria = parse_rubric(rubric_raw)
    if criteria:
        criteria_results = await score_answer(
            answer=answer,
            reference_answer=reference_answer,
            prompt=prompt,
            criteria=criteria,
            model=judge_model,
        )
        task_score = compute_task_score(task_id, category, repo_name, criteria_results)
        result.rubric_total = task_score.rubric_total
        result.rubric_met = task_score.rubric_met
        result.score = task_score.score
        result.resolved = task_score.resolved
    else:
        result.error = result.error or "No rubric criteria parsed"

    return result


async def run_tasks(
    tasks: list[dict],
    repo_dirs: dict[str, str],
    *,
    baseline: bool = False,
    answer_model: str = "",
    judge_model: str = "",
) -> list[TaskResult]:
    """Run multiple SWE-Atlas tasks sequentially.

    Tasks run sequentially because CodeIntelService uses shared singleton
    state per repo (ASTService, index caches). The LLM calls within each
    task (answer generation + rubric scoring) are async-concurrent.
    """
    results: list[TaskResult] = []

    for idx, task in enumerate(tasks):
        task_id = task.get("task_id", f"task_{idx}")
        repo_url = task.get("repository_url", "")
        repo_name = repo_url.split("/")[-1] if "/" in repo_url else repo_url

        repo_dir = repo_dirs.get(repo_url, repo_dirs.get(repo_name, ""))
        if not repo_dir:
            results.append(TaskResult(
                task_id=task_id,
                category=task.get("category", "unknown"),
                repo=repo_name,
                mode="baseline" if baseline else "with_code_intel",
                error=f"Repo not found: {repo_url}",
            ))
            continue

        mode_label = "baseline" if baseline else "CI"
        print(
            f"  [{idx+1}/{len(tasks)}] {task_id} ({repo_name}/{task.get('category', '?')}) [{mode_label}]",
            flush=True,
        )

        result = await run_task(
            task,
            str(repo_dir),
            baseline=baseline,
            answer_model=answer_model,
            judge_model=judge_model,
        )

        status = f"score={result.score:.2f}" if not result.error else f"ERROR: {result.error[:50]}"
        print(f"    -> {status}", flush=True)

        results.append(result)

    return results
