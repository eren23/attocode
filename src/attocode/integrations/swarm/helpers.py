"""Swarm helper utilities.

Detection of hollow completions, future-intent language,
and repository scaffolding state.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from attocode.integrations.swarm.types import SpawnResult, SwarmConfig

# =============================================================================
# Constants
# =============================================================================

FAILURE_INDICATORS: list[str] = [
    "I was unable to",
    "I couldn't",
    "I could not",
    "I wasn't able to",
    "failed to",
    "unable to complete",
    "error occurred",
    "ran into an issue",
    "encountered a problem",
    "hit a roadblock",
    "blocked by",
    "permission denied",
    "does not exist",
    "not found",
    "no such file",
]

BOILERPLATE_INDICATORS: list[str] = [
    "I'll help you",
    "I'd be happy to",
    "Let me help",
    "Sure, I can",
    "Of course!",
    "Absolutely!",
    "Here's what I",
    "I understand you",
    "I'll start by",
    "Let me start",
    "First, let me",
    "I need to",
    "I should",
    "I want to",
    "I plan to",
    "My approach",
]

_FUTURE_INTENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bI will (create|write|implement|build|add|fix|update|modify)\b", re.IGNORECASE),
    re.compile(r"\bI need to (create|write|implement|build|add|fix|update)\b", re.IGNORECASE),
    re.compile(r"\bnext step[s]?\b", re.IGNORECASE),
    re.compile(r"\bI('ll| shall| am going to)\b", re.IGNORECASE),
    re.compile(r"\blet me (create|write|implement|build|add|fix)\b", re.IGNORECASE),
    re.compile(r"\bI('m| am) going to\b", re.IGNORECASE),
    re.compile(r"\bwill need to\b", re.IGNORECASE),
    re.compile(r"\bshould (create|write|implement|build|fix)\b", re.IGNORECASE),
]

_COMPLETION_SIGNALS: list[re.Pattern[str]] = [
    re.compile(r"\bdone\b", re.IGNORECASE),
    re.compile(r"\bcompleted?\b", re.IGNORECASE),
    re.compile(r"\bcreated\b", re.IGNORECASE),
    re.compile(r"\bfinished\b", re.IGNORECASE),
    re.compile(r"\bimplemented\b", re.IGNORECASE),
    re.compile(r"\bwrote\b", re.IGNORECASE),
    re.compile(r"\bwritten\b", re.IGNORECASE),
    re.compile(r"\bupdated\b", re.IGNORECASE),
    re.compile(r"\bfixed\b", re.IGNORECASE),
    re.compile(r"\bmodified\b", re.IGNORECASE),
    re.compile(r"\bsuccessfully\b", re.IGNORECASE),
]


# =============================================================================
# Detection Functions
# =============================================================================


def is_hollow_completion(
    spawn_result: SpawnResult,
    task_type: str | None = None,
    swarm_config: SwarmConfig | None = None,
) -> bool:
    """Detect hollow completions — tasks that produced no meaningful work.

    Returns True if any of:
    1. Zero tool calls AND output shorter than threshold
    2. Zero tool calls AND short output contains boilerplate
    3. Success=True but output contains failure indicators
    4. Task type requires tool calls but got zero
    """
    from attocode.integrations.swarm.types import BUILTIN_TASK_TYPE_CONFIGS

    output = spawn_result.output.strip()
    tool_calls = spawn_result.tool_calls
    threshold = 120
    if swarm_config is not None:
        threshold = swarm_config.hollow_output_threshold

    # Timeout (tool_calls == -1) is never hollow
    if tool_calls == -1:
        return False

    # Check 1: No tool calls + short output
    if tool_calls == 0 and len(output) < threshold:
        return True

    # Check 2: No tool calls + short output with boilerplate
    if tool_calls == 0 and len(output) < 300:
        for indicator in BOILERPLATE_INDICATORS:
            if indicator.lower() in output.lower():
                return True

    # Check 3: "Success" but output contains failure indicators
    if spawn_result.success:
        for indicator in FAILURE_INDICATORS:
            if indicator.lower() in output.lower():
                return True

    # Check 4: Task type requires tool calls but got zero
    if task_type and tool_calls == 0:
        config = BUILTIN_TASK_TYPE_CONFIGS.get(task_type)
        if config and config.requires_tool_calls:
            return True

    return False


def has_future_intent_language(content: str) -> bool:
    """Detect output that describes future work rather than completed work.

    Returns True if content has future-intent patterns but
    no completion signals.
    """
    has_future = any(p.search(content) for p in _FUTURE_INTENT_PATTERNS)
    if not has_future:
        return False

    has_completion = any(p.search(content) for p in _COMPLETION_SIGNALS)
    return not has_completion


def repo_looks_unscaffolded(base_dir: str) -> bool:
    """Check if repository lacks basic scaffolding.

    Returns True if neither package.json nor src/ directory exists.
    """
    has_package = os.path.isfile(os.path.join(base_dir, "package.json"))
    has_src = os.path.isdir(os.path.join(base_dir, "src"))
    return not has_package and not has_src
