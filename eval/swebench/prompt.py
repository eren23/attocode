"""Build swarm goal + custom_instructions from SWE-bench instance.

Constructs a structured goal that guides the swarm through:
1. Understanding the issue
2. Identifying affected code
3. Implementing the fix
4. Verifying via tests
"""

from __future__ import annotations

from eval.harness import BenchInstance


def build_swarm_goal(instance: BenchInstance) -> str:
    """Build the top-level goal for SwarmOrchestrator."""
    repo_short = instance.repo.split("/")[-1] if "/" in instance.repo else instance.repo

    goal = (
        f"Fix the following issue in {repo_short}.\n\n"
        f"## Issue\n\n"
        f"{instance.problem_statement}\n\n"
        f"## Instructions\n\n"
        f"1. Understand the issue thoroughly — read the relevant source files\n"
        f"2. Identify the root cause\n"
        f"3. Implement a minimal, correct fix\n"
        f"4. Run the existing tests to verify your fix doesn't break anything\n"
    )

    if instance.hints:
        goal += f"\n## Hints\n\n{instance.hints}\n"

    return goal


def build_custom_instructions(instance: BenchInstance) -> str:
    """Build custom_instructions for the swarm orchestration config."""
    repo_short = instance.repo.split("/")[-1] if "/" in instance.repo else instance.repo

    instructions = (
        f"You are working on the {repo_short} repository.\n\n"
        f"## Decomposition Strategy\n\n"
        f"Break this task into 4 phases:\n\n"
        f"### Phase 1: Understand\n"
        f"- Read the issue description carefully\n"
        f"- Identify the key symptoms and expected behavior\n"
        f"- Search for relevant files, classes, and functions\n\n"
        f"### Phase 2: Identify\n"
        f"- Trace the code path from the reported symptom to root cause\n"
        f"- Read the specific file(s) that need modification\n"
        f"- Understand the surrounding code context\n\n"
        f"### Phase 3: Fix\n"
        f"- Implement the minimal change needed to fix the issue\n"
        f"- Do not refactor unrelated code\n"
        f"- Ensure backward compatibility\n\n"
        f"### Phase 4: Verify\n"
        f"- Run existing tests to check for regressions\n"
        f"- If a test file is mentioned in the issue, run it specifically\n"
        f"- Confirm the fix resolves the described symptoms\n\n"
        f"## Constraints\n\n"
        f"- Only modify files directly related to the fix\n"
        f"- Do not add new dependencies\n"
        f"- Prefer the simplest correct fix\n"
        f"- Do not modify test files unless the tests themselves are buggy\n"
    )

    return instructions


def build_agent_prompt(
    instance: BenchInstance,
    *,
    phase: str = "",
    context: str = "",
) -> str:
    """Build a prompt for a single swarm agent.

    This is used when the decomposer assigns specific sub-tasks.
    """
    repo_short = instance.repo.split("/")[-1] if "/" in instance.repo else instance.repo

    prompt = f"Working on {repo_short} issue: {instance.instance_id}\n\n"

    if phase:
        prompt += f"Your role: {phase}\n\n"

    prompt += f"Issue:\n{instance.problem_statement[:3000]}\n"

    if context:
        prompt += f"\nAdditional context:\n{context}\n"

    return prompt
