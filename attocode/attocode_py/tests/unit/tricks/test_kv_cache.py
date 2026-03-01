"""Tests for KV-cache aware context building (Trick P)."""

from __future__ import annotations

from attocode.tricks.kv_cache import (
    CacheAwareContext,
    CacheAwareConfig,
    DynamicContent,
    stable_stringify,
)


class TestBuildSystemPrompt:
    def test_constructs_prompt_with_all_sections(self):
        ctx = CacheAwareContext(CacheAwareConfig(static_prefix="You are a helpful agent."))
        prompt = ctx.build_system_prompt(
            rules="Follow coding standards.",
            tools="read_file, write_file",
            memory="User prefers Python.",
        )
        assert "You are a helpful agent." in prompt
        assert "## Rules" in prompt
        assert "Follow coding standards." in prompt
        assert "## Available Tools" in prompt
        assert "read_file, write_file" in prompt
        assert "## Relevant Context" in prompt
        assert "User prefers Python." in prompt

    def test_static_prefix_comes_first(self):
        ctx = CacheAwareContext(CacheAwareConfig(static_prefix="STATIC_PREFIX"))
        prompt = ctx.build_system_prompt(rules="rules", tools="tools")
        assert prompt.startswith("STATIC_PREFIX")

    def test_dynamic_content_comes_last(self):
        ctx = CacheAwareContext(CacheAwareConfig(static_prefix="PREFIX"))
        dynamic = DynamicContent(
            session_id="sess-123",
            timestamp="2026-02-28T12:00:00Z",
            mode="interactive",
        )
        prompt = ctx.build_system_prompt(rules="rules", dynamic=dynamic)
        # Dynamic content should be after the rules
        rules_idx = prompt.index("rules")
        session_idx = prompt.index("sess-123")
        assert session_idx > rules_idx

    def test_dynamic_extra_fields(self):
        ctx = CacheAwareContext()
        dynamic = DynamicContent(extra={"Branch": "feat/login", "Iteration": "5"})
        prompt = ctx.build_system_prompt(dynamic=dynamic)
        assert "Branch: feat/login" in prompt
        assert "Iteration: 5" in prompt

    def test_empty_sections_omitted(self):
        ctx = CacheAwareContext()
        prompt = ctx.build_system_prompt()
        assert "## Rules" not in prompt
        assert "## Available Tools" not in prompt
        assert "## Relevant Context" not in prompt

    def test_only_rules(self):
        ctx = CacheAwareContext()
        prompt = ctx.build_system_prompt(rules="Be concise.")
        assert "## Rules" in prompt
        assert "Be concise." in prompt
        assert "## Available Tools" not in prompt

    def test_tracks_breakpoint_positions(self):
        ctx = CacheAwareContext()
        ctx.build_system_prompt(
            rules="rules",
            tools="tools",
            memory="memory",
        )
        positions = ctx.get_breakpoint_positions()
        assert "system_end" in positions
        assert "tools_end" in positions
        assert "memory_end" in positions
        assert positions["tools_end"] < positions["memory_end"]
        assert positions["memory_end"] <= positions["system_end"]


class TestStableStringify:
    def test_deterministic_key_order(self):
        obj1 = {"b": 2, "a": 1, "c": 3}
        obj2 = {"c": 3, "a": 1, "b": 2}
        assert stable_stringify(obj1) == stable_stringify(obj2)

    def test_sorted_keys(self):
        result = stable_stringify({"z": 1, "a": 2, "m": 3})
        assert result == '{"a": 2, "m": 3, "z": 1}'

    def test_nested_objects_sorted(self):
        obj = {"b": {"d": 1, "c": 2}, "a": 0}
        result = stable_stringify(obj)
        # Outer keys sorted, inner keys sorted
        assert result.index('"a"') < result.index('"b"')
        assert result.index('"c"') < result.index('"d"')

    def test_with_indent(self):
        result = stable_stringify({"b": 1, "a": 2}, indent=2)
        assert "\n" in result
        assert '"a": 2' in result

    def test_unicode_preserved(self):
        result = stable_stringify({"key": "value"})
        assert "value" in result

    def test_simple_values(self):
        assert stable_stringify(42) == "42"
        assert stable_stringify("hello") == '"hello"'
        assert stable_stringify(True) == "true"
        assert stable_stringify(None) == "null"

    def test_array(self):
        result = stable_stringify([3, 1, 2])
        assert result == "[3, 1, 2]"  # arrays preserve order

    def test_empty_object(self):
        assert stable_stringify({}) == "{}"

    def test_empty_array(self):
        assert stable_stringify([]) == "[]"


class TestValidateAppendOnly:
    def test_no_violations_on_first_call(self):
        ctx = CacheAwareContext(CacheAwareConfig(enforce_append_only=True))
        messages = [
            {"id": "1", "role": "user", "content": "Hello"},
            {"id": "2", "role": "assistant", "content": "Hi there"},
        ]
        violations = ctx.validate_append_only(messages)
        assert violations == []

    def test_detects_mutation(self):
        ctx = CacheAwareContext(CacheAwareConfig(enforce_append_only=True))
        messages = [{"id": "msg1", "role": "user", "content": "Hello"}]
        ctx.validate_append_only(messages)
        # Mutate the message
        messages[0]["content"] = "Changed!"
        violations = ctx.validate_append_only(messages)
        assert len(violations) == 1
        assert "msg1" in violations[0]

    def test_no_violations_with_new_messages(self):
        ctx = CacheAwareContext(CacheAwareConfig(enforce_append_only=True))
        messages1 = [{"id": "1", "role": "user", "content": "Hello"}]
        ctx.validate_append_only(messages1)
        messages2 = [
            {"id": "1", "role": "user", "content": "Hello"},
            {"id": "2", "role": "assistant", "content": "Hi"},
        ]
        violations = ctx.validate_append_only(messages2)
        assert violations == []

    def test_disabled_enforcement(self):
        ctx = CacheAwareContext(CacheAwareConfig(enforce_append_only=False))
        messages = [{"id": "1", "role": "user", "content": "Hello"}]
        ctx.validate_append_only(messages)
        messages[0]["content"] = "Changed!"
        violations = ctx.validate_append_only(messages)
        assert violations == []

    def test_uses_index_when_no_id(self):
        ctx = CacheAwareContext(CacheAwareConfig(enforce_append_only=True))
        messages = [{"role": "user", "content": "Hello"}]
        ctx.validate_append_only(messages)
        messages[0]["content"] = "Changed!"
        violations = ctx.validate_append_only(messages)
        assert len(violations) == 1

    def test_emits_violation_event(self):
        events: list[tuple[str, dict]] = []
        ctx = CacheAwareContext(CacheAwareConfig(enforce_append_only=True))
        ctx.on(lambda event, data: events.append((event, data)))
        messages = [{"id": "1", "role": "user", "content": "Hello"}]
        ctx.validate_append_only(messages)
        messages[0]["content"] = "Mutated!"
        ctx.validate_append_only(messages)
        violation_events = [e for e in events if e[0] == "cache.violation"]
        assert len(violation_events) == 1


class TestCalculateCacheStats:
    def test_returns_cache_stats(self):
        ctx = CacheAwareContext()
        prompt = "A" * 350  # ~100 tokens
        stats = ctx.calculate_cache_stats(prompt)
        assert stats.cacheable_tokens > 0
        assert stats.cache_ratio > 0.0

    def test_dynamic_content_reduces_ratio(self):
        ctx = CacheAwareContext()
        prompt = "A" * 350
        stats_no_dynamic = ctx.calculate_cache_stats(prompt, dynamic_content_length=0)
        stats_with_dynamic = ctx.calculate_cache_stats(prompt, dynamic_content_length=100)
        assert stats_with_dynamic.cache_ratio < stats_no_dynamic.cache_ratio

    def test_messages_count_as_non_cacheable(self):
        ctx = CacheAwareContext()
        prompt = "Static prompt text here"
        messages = [
            {"role": "user", "content": "User message"},
            {"role": "assistant", "content": "Assistant response"},
        ]
        stats = ctx.calculate_cache_stats(prompt, messages=messages)
        assert stats.non_cacheable_tokens > 0

    def test_estimated_savings(self):
        ctx = CacheAwareContext()
        prompt = "A" * 700  # ~200 tokens
        stats = ctx.calculate_cache_stats(prompt)
        assert stats.estimated_savings >= 0.0
        assert stats.estimated_savings <= 1.0

    def test_emits_stats_event(self):
        events: list[tuple[str, dict]] = []
        ctx = CacheAwareContext()
        ctx.on(lambda event, data: events.append((event, data)))
        ctx.calculate_cache_stats("some prompt")
        stats_events = [e for e in events if e[0] == "cache.stats"]
        assert len(stats_events) == 1


class TestReset:
    def test_clears_message_hashes(self):
        ctx = CacheAwareContext(CacheAwareConfig(enforce_append_only=True))
        messages = [{"id": "1", "role": "user", "content": "Hello"}]
        ctx.validate_append_only(messages)
        ctx.reset()
        # After reset, same message with different content should not be a violation
        messages[0]["content"] = "Changed!"
        violations = ctx.validate_append_only(messages)
        assert violations == []

    def test_clears_breakpoint_positions(self):
        ctx = CacheAwareContext()
        ctx.build_system_prompt(rules="r", tools="t")
        assert len(ctx.get_breakpoint_positions()) > 0
        ctx.reset()
        assert len(ctx.get_breakpoint_positions()) == 0


class TestEventListener:
    def test_subscribe_and_unsubscribe(self):
        events: list[tuple[str, dict]] = []
        ctx = CacheAwareContext()
        unsub = ctx.on(lambda event, data: events.append((event, data)))
        ctx.calculate_cache_stats("prompt")
        assert len(events) > 0
        unsub()
        events.clear()
        ctx.calculate_cache_stats("prompt")
        assert len(events) == 0

    def test_listener_exception_does_not_crash(self):
        def bad_listener(event: str, data: dict) -> None:
            raise RuntimeError("boom")

        ctx = CacheAwareContext()
        ctx.on(bad_listener)
        # Should not raise
        ctx.calculate_cache_stats("prompt")


class TestSerializeMessage:
    def test_deterministic_json(self):
        ctx = CacheAwareContext(CacheAwareConfig(deterministic_json=True))
        msg1 = {"role": "user", "content": "hello", "id": "1"}
        msg2 = {"id": "1", "content": "hello", "role": "user"}
        assert ctx.serialize_message(msg1) == ctx.serialize_message(msg2)

    def test_non_deterministic_mode(self):
        ctx = CacheAwareContext(CacheAwareConfig(deterministic_json=False))
        msg = {"role": "user", "content": "hello"}
        result = ctx.serialize_message(msg)
        assert "hello" in result


class TestSerializeToolArgs:
    def test_deterministic_tool_args(self):
        ctx = CacheAwareContext(CacheAwareConfig(deterministic_json=True))
        args1 = {"path": "/src/main.py", "content": "code"}
        args2 = {"content": "code", "path": "/src/main.py"}
        assert ctx.serialize_tool_args(args1) == ctx.serialize_tool_args(args2)
