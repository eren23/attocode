"""KV-cache aware context building (Trick P).

Structures system prompts to maximize KV-cache hit rates
by keeping static content at the start and dynamic content at the end.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from attocode.integrations.utilities.token_estimate import estimate_tokens


@dataclass
class CacheableContentBlock:
    """A content block with optional cache control."""

    type: str = "text"
    text: str = ""
    cache_control: dict[str, str] | None = None


@dataclass
class CacheStats:
    """Statistics about cache efficiency."""

    cacheable_tokens: int = 0
    non_cacheable_tokens: int = 0
    cache_ratio: float = 0.0
    estimated_savings: float = 0.0


@dataclass
class CacheAwareConfig:
    """Configuration for cache-aware context."""

    static_prefix: str = ""
    cache_breakpoints: list[str] = field(default_factory=lambda: ["system_end"])
    deterministic_json: bool = True
    enforce_append_only: bool = True


@dataclass
class DynamicContent:
    """Dynamic content that changes between calls."""

    session_id: str | None = None
    timestamp: str | None = None
    mode: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


CacheEventListener = Callable[[str, dict[str, Any]], None]


class CacheAwareContext:
    """Builds system prompts optimized for KV-cache efficiency.

    Static content goes first (cacheable), dynamic content at
    the end to maximize cache prefix hits.
    """

    def __init__(self, config: CacheAwareConfig | None = None) -> None:
        self._config = config or CacheAwareConfig()
        self._listeners: list[CacheEventListener] = []
        self._message_hashes: dict[str, int] = {}
        self._breakpoint_positions: dict[str, int] = {}

    def build_system_prompt(
        self,
        rules: str = "",
        tools: str = "",
        memory: str = "",
        dynamic: DynamicContent | None = None,
    ) -> str:
        """Build a flat system prompt with static prefix first."""
        sections: list[str] = []
        pos = 0

        # Static prefix first (most cacheable)
        if self._config.static_prefix:
            sections.append(self._config.static_prefix)
            pos += len(self._config.static_prefix)

        if rules:
            sections.append(f"\n---\n## Rules\n{rules}")
            pos += len(sections[-1])

        if tools:
            sections.append(f"\n---\n## Available Tools\n{tools}")
            pos += len(sections[-1])
            self._breakpoint_positions["tools_end"] = pos

        if memory:
            sections.append(f"\n---\n## Relevant Context\n{memory}")
            pos += len(sections[-1])
            self._breakpoint_positions["memory_end"] = pos

        self._breakpoint_positions["system_end"] = pos

        # Dynamic content at the end (not cacheable)
        if dynamic:
            dynamic_parts = []
            if dynamic.session_id:
                dynamic_parts.append(f"Session: {dynamic.session_id}")
            if dynamic.timestamp:
                dynamic_parts.append(f"Time: {dynamic.timestamp}")
            if dynamic.mode:
                dynamic_parts.append(f"Mode: {dynamic.mode}")
            for k, v in dynamic.extra.items():
                dynamic_parts.append(f"{k}: {v}")
            if dynamic_parts:
                sections.append(f"\n---\n{' | '.join(dynamic_parts)}")

        return "".join(sections)

    def build_cacheable_system_prompt(
        self,
        rules: str = "",
        tools: str = "",
        memory: str = "",
        dynamic: DynamicContent | None = None,
    ) -> list[CacheableContentBlock]:
        """Build structured content blocks with cache control markers."""
        blocks: list[CacheableContentBlock] = []

        # Static sections are cacheable
        static_parts: list[str] = []

        if self._config.static_prefix:
            static_parts.append(self._config.static_prefix)
        if rules:
            static_parts.append(f"\n---\n## Rules\n{rules}")
        if tools:
            static_parts.append(f"\n---\n## Available Tools\n{tools}")
        if memory:
            static_parts.append(f"\n---\n## Relevant Context\n{memory}")

        if static_parts:
            blocks.append(CacheableContentBlock(
                type="text",
                text="".join(static_parts),
                cache_control={"type": "ephemeral"},
            ))

        # Dynamic content without cache control
        if dynamic:
            dynamic_parts = []
            if dynamic.session_id:
                dynamic_parts.append(f"Session: {dynamic.session_id}")
            if dynamic.timestamp:
                dynamic_parts.append(f"Time: {dynamic.timestamp}")
            if dynamic.mode:
                dynamic_parts.append(f"Mode: {dynamic.mode}")
            for k, v in dynamic.extra.items():
                dynamic_parts.append(f"{k}: {v}")
            if dynamic_parts:
                blocks.append(CacheableContentBlock(
                    type="text",
                    text=f"\n---\n{' | '.join(dynamic_parts)}",
                ))

        return blocks

    def validate_append_only(self, messages: list[dict[str, Any]]) -> list[str]:
        """Validate that messages are append-only (no mutations).

        Returns list of violation descriptions.
        """
        if not self._config.enforce_append_only:
            return []

        violations: list[str] = []
        for i, msg in enumerate(messages):
            msg_id = msg.get("id", str(i))
            content = msg.get("content", "")
            msg_hash = _djb2_hash(str(content))

            if msg_id in self._message_hashes:
                if self._message_hashes[msg_id] != msg_hash:
                    violations.append(f"Message {msg_id} was mutated")
            else:
                self._message_hashes[msg_id] = msg_hash

        if violations:
            self._emit("cache.violation", {"violations": violations})

        return violations

    def serialize_message(self, message: dict[str, Any]) -> str:
        """Serialize a message deterministically."""
        if self._config.deterministic_json:
            return stable_stringify(message)
        return json.dumps(message)

    def serialize_tool_args(self, args: dict[str, Any]) -> str:
        """Serialize tool arguments deterministically."""
        if self._config.deterministic_json:
            return stable_stringify(args)
        return json.dumps(args)

    def calculate_cache_stats(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]] | None = None,
        dynamic_content_length: int = 0,
    ) -> CacheStats:
        """Calculate cache efficiency statistics."""
        total_tokens = estimate_tokens(system_prompt)
        dynamic_tokens = max(1, int(dynamic_content_length / 3.5)) if dynamic_content_length else 0
        cacheable_tokens = total_tokens - dynamic_tokens
        non_cacheable_tokens = dynamic_tokens

        if messages:
            for msg in messages:
                content = msg.get("content", "")
                non_cacheable_tokens += estimate_tokens(str(content))

        cache_ratio = cacheable_tokens / max(1, cacheable_tokens + non_cacheable_tokens)
        estimated_savings = cache_ratio * 0.9

        stats = CacheStats(
            cacheable_tokens=cacheable_tokens,
            non_cacheable_tokens=non_cacheable_tokens,
            cache_ratio=cache_ratio,
            estimated_savings=estimated_savings,
        )

        self._emit("cache.stats", {"stats": stats})
        return stats

    def get_breakpoint_positions(self) -> dict[str, int]:
        """Get positions of cache breakpoints."""
        return dict(self._breakpoint_positions)

    def on(self, listener: CacheEventListener) -> Callable[[], None]:
        """Subscribe to cache events. Returns unsubscribe function."""
        self._listeners.append(listener)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

        return unsubscribe

    def reset(self) -> None:
        """Reset all tracked state."""
        self._message_hashes.clear()
        self._breakpoint_positions.clear()

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        for listener in self._listeners:
            try:
                listener(event, data)
            except Exception:
                pass


def stable_stringify(obj: Any, indent: int | None = None) -> str:
    """JSON serialize with sorted keys for deterministic output."""
    return json.dumps(obj, sort_keys=True, indent=indent, ensure_ascii=False)


def normalize_json(json_string: str) -> str:
    """Parse and re-serialize JSON deterministically."""
    try:
        parsed = json.loads(json_string)
        return stable_stringify(parsed)
    except (json.JSONDecodeError, TypeError):
        return json_string


def analyze_cache_efficiency(system_prompt: str) -> dict[str, list[str]]:
    """Analyze a system prompt for cache efficiency issues."""
    warnings: list[str] = []
    suggestions: list[str] = []

    # Check for timestamps near the start
    first_200 = system_prompt[:200].lower()
    if any(w in first_200 for w in ["timestamp", "session", "generated at", "current time"]):
        warnings.append("Dynamic content detected near prompt start - reduces cache hits")
        suggestions.append("Move timestamps and session IDs to the end of the prompt")

    if len(system_prompt) < 100:
        suggestions.append("Very short system prompt - cache benefits are minimal")

    return {"warnings": warnings, "suggestions": suggestions}


def build_multi_breakpoint_prompt(
    sections: list[tuple[str, str, bool]],
) -> list[CacheableContentBlock]:
    """Build a prompt with multiple cache breakpoints.

    Args:
        sections: List of (label, content, cacheable) tuples.
            Cacheable sections get cache_control markers.

    Returns:
        List of CacheableContentBlock with appropriate cache control.
    """
    blocks: list[CacheableContentBlock] = []
    for label, content, cacheable in sections:
        text = f"\n---\n## {label}\n{content}" if label else content
        block = CacheableContentBlock(
            type="text",
            text=text,
            cache_control={"type": "ephemeral"} if cacheable else None,
        )
        blocks.append(block)
    return blocks


def estimate_cache_savings(
    system_prompt_tokens: int,
    avg_messages_per_turn: int = 3,
    turns: int = 10,
    cache_hit_rate: float = 0.85,
) -> dict[str, float]:
    """Estimate token savings from KV-cache over a session."""
    total_without_cache = system_prompt_tokens * turns
    total_with_cache = system_prompt_tokens + (system_prompt_tokens * (1 - cache_hit_rate) * (turns - 1))
    savings = total_without_cache - total_with_cache
    savings_pct = savings / max(1, total_without_cache) * 100

    return {
        "total_without_cache": total_without_cache,
        "total_with_cache": total_with_cache,
        "token_savings": savings,
        "savings_percentage": savings_pct,
        "estimated_cost_savings_usd": savings / 1_000_000 * 3.0,  # sonnet input rate
    }


def optimize_message_order(
    messages: list[dict[str, Any]],
    system_prompt: str,
) -> list[dict[str, Any]]:
    """Reorder messages to maximize cache prefix length.

    Ensures system message is first and static content precedes
    dynamic content. Does not modify the original list.
    """
    result: list[dict[str, Any]] = []
    system_msgs: list[dict[str, Any]] = []
    other_msgs: list[dict[str, Any]] = []

    for msg in messages:
        if msg.get("role") == "system":
            system_msgs.append(msg)
        else:
            other_msgs.append(msg)

    # System messages first
    result.extend(system_msgs)
    result.extend(other_msgs)
    return result


def _djb2_hash(s: str) -> int:
    """Simple DJB2 hash for change detection."""
    h = 5381
    for c in s:
        h = ((h << 5) + h + ord(c)) & 0x7FFFFFFF
    return h
