"""Message builder - assembles system prompt and initial messages."""

from __future__ import annotations

from typing import Any

from attocode.types.messages import Message, Role


DEFAULT_SYSTEM_PROMPT = """\
You are an AI coding assistant. You help users with software engineering tasks \
by reading files, writing code, running commands, and analyzing problems.

Guidelines:
- Read files before modifying them
- Make changes incrementally
- Run tests after changes
- Explain what you're doing
- Ask for clarification when needed
"""


def build_system_prompt(
    *,
    base_prompt: str | None = None,
    rules: list[str] | None = None,
    working_dir: str = "",
    extra_context: str | None = None,
    skills: list[Any] | None = None,
) -> str:
    """Build the full system prompt from components."""
    parts: list[str] = []

    # Base prompt
    parts.append(base_prompt or DEFAULT_SYSTEM_PROMPT)

    # Working directory context
    if working_dir:
        parts.append(f"\nWorking directory: {working_dir}")

    # Rules
    if rules:
        parts.append("\n# Rules")
        for rule in rules:
            parts.append(rule)

    # Skills
    if skills:
        skill_lines: list[str] = []
        for skill in skills:
            name = getattr(skill, "name", str(skill))
            desc = getattr(skill, "description", "")
            content = getattr(skill, "content", "")
            if content:
                skill_lines.append(f"## Skill: {name}")
                if desc:
                    skill_lines.append(desc)
                skill_lines.append(content)
                skill_lines.append("")
        if skill_lines:
            parts.append("\n# Available Skills")
            parts.extend(skill_lines)

    # Extra context
    if extra_context:
        parts.append(f"\n{extra_context}")

    return "\n".join(parts)


def build_initial_messages(
    prompt: str,
    *,
    system_prompt: str | None = None,
    rules: list[str] | None = None,
    working_dir: str = "",
    skills: list[Any] | None = None,
    learning_context: str = "",
) -> list[Message]:
    """Build the initial message list for an agent run.

    Returns [system_message, user_message].
    """
    sys_prompt = system_prompt or build_system_prompt(
        rules=rules,
        working_dir=working_dir,
        skills=skills,
        extra_context=learning_context or None,
    )

    return [
        Message(role=Role.SYSTEM, content=sys_prompt),
        Message(role=Role.USER, content=prompt),
    ]
