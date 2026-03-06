"""Message builder - assembles system prompt and initial messages."""

from __future__ import annotations

from typing import Any

from attocode.types.messages import (
    ImageContentBlock,
    Message,
    MessageWithStructuredContent,
    Role,
    TextContentBlock,
)

DEFAULT_SYSTEM_PROMPT = """\
You are an AI coding assistant. You help users with software engineering tasks \
by reading files, writing code, running commands, and analyzing problems.

Guidelines:
- Read files before modifying them
- Make changes incrementally
- Run tests after changes
- Explain what you're doing
- Ask for clarification when needed

Context awareness:
- This is a multi-turn conversation. Your previous messages are part of the shared context.
- When the user refers to "these", "those", "the above", "your findings", etc., \
they mean content from your most recent substantive response.
- When asked to write or save something without specifying content, use your \
recent output as the content source.
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


def build_user_message(
    prompt: str,
    *,
    images: list[str] | None = None,
    working_dir: str = "",
) -> Message | MessageWithStructuredContent:
    """Build a user message, optionally with inline images.

    When images are provided, returns a MessageWithStructuredContent
    containing text + image content blocks. Otherwise returns a plain Message.

    Note: working_dir is NOT enforced for user-provided images. The user
    explicitly chose to share these files (drag-drop / paste), unlike
    agent-initiated vision_analyze calls where the restriction applies.
    """
    if not images:
        text = prompt or "Describe this image."
        return Message(role=Role.USER, content=text)

    from attocode.tools.image_utils import load_image_to_source

    content_blocks: list[TextContentBlock | ImageContentBlock] = []
    text = prompt or "Describe this image."
    content_blocks.append(TextContentBlock(text=text))

    for img_path in images:
        # No working_dir restriction — user explicitly shared these files
        source = load_image_to_source(img_path)
        if source is not None:
            content_blocks.append(ImageContentBlock(source=source))

    # If no images actually loaded, fall back to plain message
    if len(content_blocks) == 1:
        return Message(role=Role.USER, content=text)

    return MessageWithStructuredContent(role=Role.USER, content=content_blocks)


def build_initial_messages(
    prompt: str,
    *,
    images: list[str] | None = None,
    system_prompt: str | None = None,
    rules: list[str] | None = None,
    working_dir: str = "",
    skills: list[Any] | None = None,
    learning_context: str = "",
) -> list[Message | MessageWithStructuredContent]:
    """Build the initial message list for an agent run.

    Returns [system_message, user_message].
    When images are provided, the user message will be a
    MessageWithStructuredContent with inline image blocks.
    """
    sys_prompt = system_prompt or build_system_prompt(
        rules=rules,
        working_dir=working_dir,
        skills=skills,
        extra_context=learning_context or None,
    )

    user_msg = build_user_message(prompt, images=images, working_dir=working_dir)

    return [
        Message(role=Role.SYSTEM, content=sys_prompt),
        user_msg,
    ]
