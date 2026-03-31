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


def build_context_attachment(
    *,
    tool_listing: str | None = None,
    mcp_instructions: str | None = None,
    skill_listing: str | None = None,
    learning_context: str | None = None,
    extra_context: str | None = None,
) -> Message | None:
    """Build a context attachment message with dynamic content.

    Dynamic content (tool lists, MCP instructions, skills, learning context)
    is placed in a separate message rather than in the system prompt. This
    keeps the system prompt byte-stable across turns for LLM prompt cache hits.

    Returns None if no dynamic content was provided.
    """
    parts: list[str] = []

    if tool_listing:
        parts.append(f"<available-tools>\n{tool_listing}\n</available-tools>")

    if mcp_instructions:
        parts.append(f"<mcp-instructions>\n{mcp_instructions}\n</mcp-instructions>")

    if skill_listing:
        parts.append(f"<available-skills>\n{skill_listing}\n</available-skills>")

    if learning_context:
        parts.append(f"<learning-context>\n{learning_context}\n</learning-context>")

    if extra_context:
        parts.append(f"<extra-context>\n{extra_context}\n</extra-context>")

    if not parts:
        return None

    content = "<system-reminder>\n" + "\n\n".join(parts) + "\n</system-reminder>"
    return Message(role=Role.USER, content=content)


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


FORK_TAG = "[FORK_CHILD]"
FORK_PLACEHOLDER_RESULT = "[Fork context transferred]"


def build_forked_messages(
    parent_messages: list[Message | MessageWithStructuredContent],
    child_directive: str,
    *,
    fork_tag: str = FORK_TAG,
) -> list[Message | MessageWithStructuredContent]:
    """Build messages for a fork subagent that shares the parent's prompt cache.

    The child inherits the parent's system message byte-for-byte (cache hit),
    gets a placeholder fork-context message for continuity, and receives the
    child directive as a final user message.

    Args:
        parent_messages: The parent agent's current message list.
        child_directive: Task description for the child agent.
        fork_tag: Tag to detect recursive forking.

    Returns:
        Message list for the forked child agent.

    Raises:
        ValueError: If parent_messages is empty or recursive forking is detected.
    """
    if not parent_messages:
        raise ValueError("Cannot fork from empty parent messages")

    # Detect recursive forking — scan all messages for the fork tag
    for msg in parent_messages:
        if isinstance(msg.content, str):
            content_str = msg.content
        else:
            # MessageWithStructuredContent with list of content blocks
            parts: list[str] = []
            for block in msg.content:
                if isinstance(block, TextContentBlock):
                    parts.append(block.text)
            content_str = " ".join(parts)
        if fork_tag in content_str:
            raise ValueError("Recursive forking detected — fork children cannot spawn forks")

    # Copy parent's system message verbatim (byte-identical for cache hit)
    system_msg = parent_messages[0]

    # Build fork context message — marks this conversation as a fork
    fork_context = Message(
        role=Role.USER,
        content=f"{fork_tag}\n{FORK_PLACEHOLDER_RESULT}",
    )

    # Child directive as final user message
    directive_msg = Message(
        role=Role.USER,
        content=f"You are a fork subagent. Execute this task:\n\n{child_directive}",
    )

    return [system_msg, fork_context, directive_msg]


def build_initial_messages(
    prompt: str,
    *,
    images: list[str] | None = None,
    system_prompt: str | None = None,
    rules: list[str] | None = None,
    working_dir: str = "",
    skills: list[Any] | None = None,
    learning_context: str = "",
    context_attachment: Message | None = None,
) -> list[Message | MessageWithStructuredContent]:
    """Build the initial message list for an agent run.

    Returns [system_message, user_message] or
    [system_message, context_attachment, user_message] when a context
    attachment is provided.

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

    messages: list[Message | MessageWithStructuredContent] = [
        Message(role=Role.SYSTEM, content=sys_prompt),
    ]
    if context_attachment is not None:
        messages.append(context_attachment)
    messages.append(user_msg)
    return messages
