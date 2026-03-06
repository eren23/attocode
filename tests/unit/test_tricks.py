"""Comprehensive tests for the tricks module.

Tests for:
- CacheAwareContext (kv_cache)
- RecitationManager (recitation)
- ReversibleCompactor (reversible_compaction)
- FailureTracker (failure_evidence)
- DiverseSerializer (serialization_diversity)
"""

from __future__ import annotations

import json
import time

import pytest

from attocode.tricks.kv_cache import (
    CacheAwareConfig,
    CacheAwareContext,
    CacheableContentBlock,
    DynamicContent,
    analyze_cache_efficiency,
    normalize_json,
    stable_stringify,
)
from attocode.tricks.recitation import (
    PlanState,
    PlanTask,
    RecitationConfig,
    RecitationEntry,
    RecitationManager,
    RecitationState,
    TodoItem,
    build_quick_recitation,
    calculate_optimal_frequency,
)
from attocode.tricks.reversible_compaction import (
    CompactionResult,
    Reference,
    ReferenceType,
    ReversibleCompactionConfig,
    ReversibleCompactor,
    calculate_relevance,
    extract_command_references,
    extract_error_references,
    extract_file_references,
    extract_function_references,
    extract_url_references,
)
from attocode.tricks.failure_evidence import (
    FailureCategory,
    FailureInput,
    FailureTracker,
    FailureTrackerConfig,
    categorize_error,
    create_repeat_warning,
    format_failure_context,
    generate_suggestion,
    Failure,
)
from attocode.tricks.serialization_diversity import (
    DiverseSerializer,
    DiverseSerializerConfig,
    SerializationStyle,
    are_semantic_equivalent,
    generate_variations,
)


# =============================================================================
# CacheAwareContext Tests
# =============================================================================


class TestCacheAwareContext:
    """Tests for CacheAwareContext."""

    def test_build_system_prompt_static_prefix_plus_rules_tools_memory(self) -> None:
        config = CacheAwareConfig(static_prefix="You are a helpful assistant.")
        ctx = CacheAwareContext(config)
        prompt = ctx.build_system_prompt(
            rules="Be concise.",
            tools="search, edit",
            memory="User prefers Python.",
        )
        assert prompt.startswith("You are a helpful assistant.")
        assert "## Rules" in prompt
        assert "Be concise." in prompt
        assert "## Available Tools" in prompt
        assert "search, edit" in prompt
        assert "## Relevant Context" in prompt
        assert "User prefers Python." in prompt

    def test_build_system_prompt_dynamic_content_at_end(self) -> None:
        config = CacheAwareConfig(static_prefix="Static part.")
        ctx = CacheAwareContext(config)
        dynamic = DynamicContent(
            session_id="abc-123",
            timestamp="2026-02-19T10:00:00",
            mode="interactive",
            extra={"project": "attocode"},
        )
        prompt = ctx.build_system_prompt(
            rules="Rule 1",
            dynamic=dynamic,
        )
        assert prompt.startswith("Static part.")
        assert prompt.endswith(
            "Session: abc-123 | Time: 2026-02-19T10:00:00 | Mode: interactive | project: attocode"
        )

    def test_build_cacheable_system_prompt_returns_blocks_with_cache_control(self) -> None:
        config = CacheAwareConfig(static_prefix="Prefix.")
        ctx = CacheAwareContext(config)
        blocks = ctx.build_cacheable_system_prompt(
            rules="No swearing.",
            dynamic=DynamicContent(session_id="s1"),
        )
        assert len(blocks) == 2
        assert isinstance(blocks[0], CacheableContentBlock)
        assert blocks[0].cache_control == {"type": "ephemeral"}
        assert "Prefix." in blocks[0].text
        assert "No swearing." in blocks[0].text
        assert blocks[1].cache_control is None
        assert "Session: s1" in blocks[1].text

    def test_build_cacheable_system_prompt_no_dynamic(self) -> None:
        ctx = CacheAwareContext(CacheAwareConfig(static_prefix="Only static."))
        blocks = ctx.build_cacheable_system_prompt(rules="R1")
        assert len(blocks) == 1
        assert blocks[0].cache_control is not None

    def test_validate_append_only_detects_mutations(self) -> None:
        ctx = CacheAwareContext(CacheAwareConfig(enforce_append_only=True))
        messages = [
            {"id": "m1", "content": "Hello"},
            {"id": "m2", "content": "World"},
        ]
        violations = ctx.validate_append_only(messages)
        assert violations == []
        messages_mutated = [
            {"id": "m1", "content": "Changed!"},
            {"id": "m2", "content": "World"},
        ]
        violations = ctx.validate_append_only(messages_mutated)
        assert len(violations) == 1
        assert "m1" in violations[0]

    def test_validate_append_only_disabled(self) -> None:
        ctx = CacheAwareContext(CacheAwareConfig(enforce_append_only=False))
        messages = [{"id": "m1", "content": "Hello"}]
        ctx.validate_append_only(messages)
        violations = ctx.validate_append_only([{"id": "m1", "content": "Changed"}])
        assert violations == []

    def test_validate_append_only_emits_event(self) -> None:
        ctx = CacheAwareContext(CacheAwareConfig(enforce_append_only=True))
        events: list[tuple[str, dict]] = []
        ctx.on(lambda e, d: events.append((e, d)))
        messages = [{"id": "m1", "content": "Hello"}]
        ctx.validate_append_only(messages)
        ctx.validate_append_only([{"id": "m1", "content": "Changed"}])
        assert any(e == "cache.violation" for e, _ in events)

    def test_serialize_message_with_deterministic_json(self) -> None:
        ctx = CacheAwareContext(CacheAwareConfig(deterministic_json=True))
        msg = {"b": 2, "a": 1, "c": {"z": 26, "y": 25}}
        result = ctx.serialize_message(msg)
        parsed = json.loads(result)
        keys = list(parsed.keys())
        assert keys == ["a", "b", "c"]
        inner_keys = list(parsed["c"].keys())
        assert inner_keys == ["y", "z"]

    def test_serialize_message_non_deterministic(self) -> None:
        ctx = CacheAwareContext(CacheAwareConfig(deterministic_json=False))
        msg = {"b": 2, "a": 1}
        result = ctx.serialize_message(msg)
        parsed = json.loads(result)
        assert parsed == {"a": 1, "b": 2}

    def test_calculate_cache_stats(self) -> None:
        ctx = CacheAwareContext()
        prompt = "A" * 350
        stats = ctx.calculate_cache_stats(prompt, dynamic_content_length=35)
        assert stats.cacheable_tokens > 0
        assert stats.non_cacheable_tokens > 0
        assert 0 < stats.cache_ratio <= 1.0
        assert 0 < stats.estimated_savings <= 1.0

    def test_calculate_cache_stats_with_messages(self) -> None:
        ctx = CacheAwareContext()
        prompt = "System prompt content here."
        msgs = [{"content": "User message."}]
        stats = ctx.calculate_cache_stats(prompt, messages=msgs)
        assert stats.non_cacheable_tokens > 0

    def test_get_breakpoint_positions(self) -> None:
        config = CacheAwareConfig(static_prefix="Static.")
        ctx = CacheAwareContext(config)
        ctx.build_system_prompt(rules="R", tools="T", memory="M")
        positions = ctx.get_breakpoint_positions()
        assert "tools_end" in positions
        assert "memory_end" in positions
        assert "system_end" in positions
        assert positions["tools_end"] < positions["memory_end"]
        assert positions["memory_end"] <= positions["system_end"]

    def test_reset_clears_state(self) -> None:
        ctx = CacheAwareContext(CacheAwareConfig(enforce_append_only=True))
        messages = [{"id": "m1", "content": "Hello"}]
        ctx.validate_append_only(messages)
        ctx.build_system_prompt(tools="T")
        ctx.reset()
        assert ctx.get_breakpoint_positions() == {}
        violations = ctx.validate_append_only([{"id": "m1", "content": "Changed"}])
        assert violations == []

    def test_on_returns_unsubscribe(self) -> None:
        ctx = CacheAwareContext()
        events: list[str] = []
        unsub = ctx.on(lambda e, d: events.append(e))
        ctx.calculate_cache_stats("Hello world")
        assert len(events) == 1
        unsub()
        ctx.calculate_cache_stats("Hello again")
        assert len(events) == 1


class TestStableStringify:
    def test_sorts_keys(self) -> None:
        result = stable_stringify({"z": 1, "a": 2, "m": 3})
        parsed = json.loads(result)
        assert list(parsed.keys()) == ["a", "m", "z"]

    def test_nested_sort(self) -> None:
        result = stable_stringify({"b": {"z": 1, "a": 2}})
        assert result.index('"a"') < result.index('"z"')

    def test_with_indent(self) -> None:
        result = stable_stringify({"a": 1}, indent=4)
        assert "\n" in result
        assert "    " in result

    def test_unicode(self) -> None:
        result = stable_stringify({"emoji": "hello"})
        assert "hello" in result


class TestNormalizeJson:
    def test_re_serializes_deterministically(self) -> None:
        json_str = '{"b":2,"a":1}'
        result = normalize_json(json_str)
        parsed = json.loads(result)
        assert list(parsed.keys()) == ["a", "b"]

    def test_invalid_json_returns_original(self) -> None:
        bad = "not json at all"
        assert normalize_json(bad) == bad


class TestAnalyzeCacheEfficiency:
    def test_detects_timestamps_at_start(self) -> None:
        prompt = "Generated at 2026-02-19T10:00:00\n\nYou are a helpful assistant..."
        result = analyze_cache_efficiency(prompt)
        assert len(result["warnings"]) > 0
        assert "dynamic content" in result["warnings"][0].lower()
        assert len(result["suggestions"]) > 0

    def test_detects_session_at_start(self) -> None:
        prompt = "Session: abc-123\n\nRules follow."
        result = analyze_cache_efficiency(prompt)
        assert len(result["warnings"]) > 0

    def test_no_warnings_for_good_prompt(self) -> None:
        prompt = "You are a helpful coding assistant.\n" * 20
        result = analyze_cache_efficiency(prompt)
        assert result["warnings"] == []

    def test_short_prompt_suggestion(self) -> None:
        prompt = "Short."
        result = analyze_cache_efficiency(prompt)
        assert any("short" in s.lower() for s in result["suggestions"])



# =============================================================================
# RecitationManager Tests
# =============================================================================


class TestRecitationManager:

    def test_should_inject_on_first_iteration(self) -> None:
        mgr = RecitationManager(RecitationConfig(frequency=5))
        assert mgr.should_inject(1) is True

    def test_should_inject_respects_frequency(self) -> None:
        mgr = RecitationManager(RecitationConfig(frequency=5))
        mgr._last_injection_iteration = 1
        assert mgr.should_inject(2) is False
        assert mgr.should_inject(3) is False
        assert mgr.should_inject(5) is False
        assert mgr.should_inject(6) is True

    def test_build_recitation_with_goal_plan_todos(self) -> None:
        mgr = RecitationManager(RecitationConfig(
            sources=["goal", "plan", "todo"],
        ))
        state = RecitationState(
            goal="Build a REST API",
            plan=PlanState(
                description="API plan",
                tasks=[
                    PlanTask(id="t1", description="Setup project", status="completed"),
                    PlanTask(id="t2", description="Add routes", status="pending"),
                    PlanTask(id="t3", description="Add tests", status="pending"),
                ],
            ),
            todos=[
                TodoItem(content="Write GET /users", status="pending"),
                TodoItem(content="Write POST /users", status="pending"),
                TodoItem(content="Done item", status="completed"),
            ],
        )
        content = mgr.build_recitation(state)
        assert content is not None
        assert "Goal: Build a REST API" in content
        assert "Plan: 1/3 tasks complete" in content
        assert "Next: Add routes" in content
        assert "Todos: 2 remaining" in content
        assert "Write GET /users" in content

    def test_build_recitation_returns_none_when_empty(self) -> None:
        mgr = RecitationManager(RecitationConfig(sources=["goal"]))
        state = RecitationState()
        result = mgr.build_recitation(state)
        assert result is None

    def test_build_recitation_truncates_to_max_tokens(self) -> None:
        mgr = RecitationManager(RecitationConfig(
            sources=["goal", "todo"],
            max_tokens=10,
        ))
        state = RecitationState(
            goal="A" * 100,
            todos=[TodoItem(content="B" * 100, status="pending")],
        )
        result = mgr.build_recitation(state)
        assert result is not None
        assert result.endswith("...")
        assert len(result) <= 40

    def test_inject_if_needed_inserts_before_last_user_msg(self) -> None:
        mgr = RecitationManager(RecitationConfig(frequency=1, sources=["goal"]))
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
            {"role": "user", "content": "Second question"},
        ]
        state = RecitationState(iteration=1, goal="Build API")
        result = mgr.inject_if_needed(messages, state)
        assert len(result) == 5
        assert result[3]["role"] == "system"
        assert "Current Status" in result[3]["content"]
        assert "Build API" in result[3]["content"]
        assert result[4]["role"] == "user"
        assert result[4]["content"] == "Second question"

    def test_inject_if_needed_does_not_inject_when_not_due(self) -> None:
        mgr = RecitationManager(RecitationConfig(frequency=10))
        mgr._last_injection_iteration = 5
        messages = [{"role": "user", "content": "Hello"}]
        state = RecitationState(iteration=6, goal="Something")
        result = mgr.inject_if_needed(messages, state)
        assert len(result) == 1

    def test_force_inject_always_injects(self) -> None:
        mgr = RecitationManager(RecitationConfig(frequency=100))
        mgr._last_injection_iteration = 99
        messages = [{"role": "user", "content": "Hello"}]
        state = RecitationState(iteration=100, goal="Important goal")
        result = mgr.force_inject(messages, state)
        assert len(result) == 2

    def test_history_tracking(self) -> None:
        mgr = RecitationManager(RecitationConfig(frequency=1, track_history=True, sources=["goal"]))
        messages = [{"role": "user", "content": "Hello"}]
        state = RecitationState(iteration=1, goal="Test goal")
        mgr.inject_if_needed(messages, state)
        history = mgr.get_history()
        assert len(history) == 1
        assert isinstance(history[0], RecitationEntry)
        assert history[0].iteration == 1
        assert "Test goal" in history[0].content
        mgr.clear_history()
        assert mgr.get_history() == []

    def test_inject_emits_injected_event(self) -> None:
        mgr = RecitationManager(RecitationConfig(frequency=1, sources=["goal"]))
        events: list[str] = []
        mgr.on(lambda e, d: events.append(e))
        messages = [{"role": "user", "content": "Hello"}]
        mgr.inject_if_needed(messages, RecitationState(iteration=1, goal="G"))
        assert "recitation.injected" in events

    def test_inject_emits_skipped_event(self) -> None:
        mgr = RecitationManager(RecitationConfig(frequency=10, sources=["goal"]))
        events: list[str] = []
        mgr.on(lambda e, d: events.append(e))
        messages = [{"role": "user", "content": "Hello"}]
        mgr._last_injection_iteration = 5
        mgr.inject_if_needed(messages, RecitationState(iteration=6, goal="G"))
        assert "recitation.skipped" in events

    def test_build_recitation_with_custom_and_errors(self) -> None:
        mgr = RecitationManager(RecitationConfig(sources=["goal"]))
        state = RecitationState(
            goal="Build X",
            recent_errors=["Error: File not found", "Error: Permission denied"],
            custom={"Phase": "Acting"},
        )
        result = mgr.build_recitation(state)
        assert result is not None
        assert "Recent error: Error: File not found" in result
        assert "Recent error: Error: Permission denied" in result
        assert "Phase: Acting" in result

    def test_update_config(self) -> None:
        mgr = RecitationManager(RecitationConfig(frequency=5))
        mgr.update_config(frequency=10)
        assert mgr._config.frequency == 10


class TestBuildQuickRecitation:
    def test_compact_format(self) -> None:
        state = RecitationState(
            goal="Build API",
            plan=PlanState(
                tasks=[
                    PlanTask(id="t1", description="Step 1", status="completed"),
                    PlanTask(id="t2", description="Step 2", status="pending"),
                ],
            ),
            todos=[
                TodoItem(content="TODO 1", status="pending"),
                TodoItem(content="TODO 2", status="completed"),
            ],
        )
        result = build_quick_recitation(state)
        assert "Goal: Build API" in result
        assert "Progress: 1/2" in result
        assert "Todos: 1 remaining" in result
        assert " | " in result

    def test_empty_state(self) -> None:
        result = build_quick_recitation(RecitationState())
        assert result == ""


class TestCalculateOptimalFrequency:
    def test_small_context(self) -> None:
        assert calculate_optimal_frequency(5_000) == 10

    def test_medium_context(self) -> None:
        assert calculate_optimal_frequency(20_000) == 7

    def test_large_context(self) -> None:
        assert calculate_optimal_frequency(50_000) == 5

    def test_very_large_context(self) -> None:
        assert calculate_optimal_frequency(100_000) == 3



# =============================================================================
# ReversibleCompactor Tests
# =============================================================================


class TestExtractFileReferences:
    def test_finds_absolute_paths(self) -> None:
        text = "Edit the file /src/main.ts and also /tests/unit/test.py"
        refs = extract_file_references(text)
        values = [r.value for r in refs]
        assert "/src/main.ts" in values
        assert "/tests/unit/test.py" in values

    def test_finds_relative_paths(self) -> None:
        text = "See ./src/utils.ts and ../config.json"
        refs = extract_file_references(text)
        values = [r.value for r in refs]
        assert "./src/utils.ts" in values
        assert "../config.json" in values

    def test_reference_has_correct_type(self) -> None:
        text = "File: /foo/bar.py"
        refs = extract_file_references(text)
        assert all(r.type == ReferenceType.FILE for r in refs)


class TestExtractUrlReferences:
    def test_finds_urls(self) -> None:
        text = "Visit https://example.com/api and http://localhost:3000/test"
        refs = extract_url_references(text)
        values = [r.value for r in refs]
        assert "https://example.com/api" in values
        assert "http://localhost:3000/test" in values

    def test_strips_trailing_punctuation(self) -> None:
        text = "See https://example.com/page."
        refs = extract_url_references(text)
        assert refs[0].value == "https://example.com/page"


class TestExtractFunctionReferences:
    def test_finds_python_defs(self) -> None:
        text = "def my_function(x):\n    pass\nasync def another_func():\n    pass"
        refs = extract_function_references(text)
        values = [r.value for r in refs]
        assert "my_function" in values
        assert "another_func" in values

    def test_finds_js_function(self) -> None:
        text = "function handleClick(event) {}"
        refs = extract_function_references(text)
        values = [r.value for r in refs]
        assert "handleClick" in values

    def test_finds_camelcase_calls(self) -> None:
        text = "result = fetchData(url)"
        refs = extract_function_references(text)
        values = [r.value for r in refs]
        assert "fetchData" in values


class TestExtractErrorReferences:
    def test_finds_error_types(self) -> None:
        text = "Got a FileNotFoundError and also a PermissionError"
        refs = extract_error_references(text)
        values = [r.value for r in refs]
        assert "FileNotFoundError" in values
        assert "PermissionError" in values

    def test_finds_error_messages(self) -> None:
        text = "Error: Could not connect to database server"
        refs = extract_error_references(text)
        values = [r.value for r in refs]
        assert any("Could not connect" in v for v in values)


class TestExtractCommandReferences:
    def test_finds_dollar_prefix_commands(self) -> None:
        text = "$ npm install\n$ git status"
        refs = extract_command_references(text)
        values = [r.value for r in refs]
        assert "npm install" in values
        assert "git status" in values

    def test_finds_code_block_commands(self) -> None:
        text = "```bash\npip install flask\npython app.py\n```"
        refs = extract_command_references(text)
        values = [r.value for r in refs]
        assert "pip install flask" in values
        assert "python app.py" in values

    def test_finds_cli_patterns(self) -> None:
        text = "Run npm install express and then docker build ."
        refs = extract_command_references(text)
        values = [r.value for r in refs]
        assert any("npm install" in v for v in values)
        assert any("docker build" in v for v in values)


class TestReversibleCompactor:
    @pytest.mark.asyncio
    async def test_compact_with_mock_summarize(self) -> None:
        compactor = ReversibleCompactor()
        messages = [
            {"content": "Edit /src/main.ts to fix the TypeError in handleClick(event)."},
            {"content": "Also check https://docs.example.com for reference."},
        ]

        async def mock_summarize(msgs: list) -> str:
            return "Fixed TypeError in handleClick by correcting types."

        result = await compactor.compact(messages, mock_summarize)
        assert isinstance(result, CompactionResult)
        assert result.summary == "Fixed TypeError in handleClick by correcting types."
        assert result.stats.original_messages == 2
        assert result.stats.original_tokens > 0
        assert result.stats.compacted_tokens > 0
        assert result.stats.references_extracted > 0
        assert len(result.references) > 0

    @pytest.mark.asyncio
    async def test_compact_with_sync_summarize(self) -> None:
        compactor = ReversibleCompactor()
        messages = [{"content": "Check /foo/bar.py please."}]

        def sync_summarize(msgs: list) -> str:
            return "Checked bar.py."

        result = await compactor.compact(messages, sync_summarize)
        assert result.summary == "Checked bar.py."

    def test_format_references_block_groups_by_type(self) -> None:
        compactor = ReversibleCompactor()
        refs = [
            Reference(id="r1", type="file", value="/src/main.ts"),
            Reference(id="r2", type="file", value="/src/utils.ts"),
            Reference(id="r3", type="url", value="https://example.com"),
            Reference(id="r4", type="error", value="TypeError"),
        ]
        block = compactor.format_references_block(refs)
        assert "[Preserved References]" in block
        assert "FILES:" in block
        assert "/src/main.ts" in block
        assert "/src/utils.ts" in block
        assert "URLS:" in block
        assert "https://example.com" in block
        assert "ERRORS:" in block
        assert "TypeError" in block

    def test_format_references_block_empty(self) -> None:
        compactor = ReversibleCompactor()
        assert compactor.format_references_block([]) == ""

    def test_search_references_by_value(self) -> None:
        compactor = ReversibleCompactor()
        compactor._references = [
            Reference(id="r1", type="file", value="/src/main.ts"),
            Reference(id="r2", type="file", value="/src/utils.ts"),
            Reference(id="r3", type="url", value="https://main-api.com"),
        ]
        results = compactor.search_references("main")
        values = [r.value for r in results]
        assert "/src/main.ts" in values
        assert "https://main-api.com" in values
        assert "/src/utils.ts" not in values

    @pytest.mark.asyncio
    async def test_deduplication(self) -> None:
        compactor = ReversibleCompactor(ReversibleCompactionConfig(deduplicate=True))
        messages = [
            {"content": "File /src/main.ts is broken."},
            {"content": "Again, /src/main.ts needs fixing."},
        ]

        async def summarize(msgs: list) -> str:
            return "Summary."

        result = await compactor.compact(messages, summarize)
        file_refs = [r for r in result.references if r.type == "file"]
        file_values = [r.value for r in file_refs]
        assert file_values.count("/src/main.ts") == 1

    @pytest.mark.asyncio
    async def test_no_deduplication(self) -> None:
        compactor = ReversibleCompactor(ReversibleCompactionConfig(deduplicate=False))
        messages = [
            {"content": "File /src/main.ts is broken."},
            {"content": "Again, /src/main.ts needs fixing."},
        ]

        async def summarize(msgs: list) -> str:
            return "Summary."

        result = await compactor.compact(messages, summarize)
        file_refs = [r for r in result.references if r.type == "file"]
        file_values = [r.value for r in file_refs]
        assert file_values.count("/src/main.ts") >= 2

    @pytest.mark.asyncio
    async def test_emits_compaction_completed_event(self) -> None:
        compactor = ReversibleCompactor()
        events: list[str] = []
        compactor.on(lambda e, d: events.append(e))
        messages = [{"content": "Some content."}]

        async def summarize(msgs: list) -> str:
            return "Done."

        await compactor.compact(messages, summarize)
        assert "compaction.completed" in events

    def test_get_references_by_type(self) -> None:
        compactor = ReversibleCompactor()
        compactor._references = [
            Reference(id="r1", type="file", value="/a.py"),
            Reference(id="r2", type="url", value="http://x.com"),
            Reference(id="r3", type="file", value="/b.py"),
        ]
        file_refs = compactor.get_references_by_type("file")
        assert len(file_refs) == 2
        url_refs = compactor.get_references_by_type("url")
        assert len(url_refs) == 1

    def test_get_reference_by_id(self) -> None:
        compactor = ReversibleCompactor()
        ref = Reference(id="r-abc", type="file", value="/x.py")
        compactor._references = [ref]
        found = compactor.get_reference("r-abc")
        assert found is not None
        assert found.value == "/x.py"
        assert compactor.get_reference("nonexistent") is None

    def test_clear(self) -> None:
        compactor = ReversibleCompactor()
        compactor._references = [Reference(id="r1", type="file", value="/a.py")]
        compactor.clear()
        assert compactor.get_preserved_references() == []


class TestCalculateRelevance:
    def test_base_score(self) -> None:
        ref = Reference(id="r1", type="file", value="/src/foo.py")
        score = calculate_relevance(ref)
        assert score == pytest.approx(0.55, abs=0.01)

    def test_goal_overlap_boosts_score(self) -> None:
        ref = Reference(id="r1", type="file", value="/src/authentication/module.py")
        score = calculate_relevance(ref, goal="Fix the authentication module")
        assert score > 0.6

    def test_recent_topics_boost(self) -> None:
        ref = Reference(id="r1", type="url", value="https://api.example.com")
        score = calculate_relevance(ref, recent_topics=["Check https://api.example.com docs"])
        assert score > 0.6

    def test_error_type_bonus(self) -> None:
        ref = Reference(id="r1", type="error", value="TypeError")
        score = calculate_relevance(ref)
        assert score == pytest.approx(0.6, abs=0.01)

    def test_score_capped_at_1(self) -> None:
        ref = Reference(id="r1", type="error", value="auth/login/error")
        score = calculate_relevance(
            ref,
            goal="Fix auth login error in the module",
            recent_topics=["auth issue", "login error", "error handling"],
        )
        assert score <= 1.0



# =============================================================================
# FailureTracker Tests
# =============================================================================


class TestFailureTracker:
    def test_record_failure_basic(self) -> None:
        tracker = FailureTracker()
        failure = tracker.record_failure(FailureInput(
            action="edit_file",
            error="File not found: /missing.py",
        ))
        assert failure.id.startswith("fail-")
        assert failure.action == "edit_file"
        assert failure.error == "File not found: /missing.py"
        assert failure.resolved is False
        assert failure.repeat_count >= 1

    def test_auto_categorization_not_found(self) -> None:
        tracker = FailureTracker()
        failure = tracker.record_failure(FailureInput(
            action="read_file",
            error="ENOENT: no such file or directory",
        ))
        assert failure.category == FailureCategory.NOT_FOUND

    def test_auto_categorization_permission(self) -> None:
        tracker = FailureTracker()
        failure = tracker.record_failure(FailureInput(
            action="write_file",
            error="permission denied: /etc/shadow",
        ))
        assert failure.category == FailureCategory.PERMISSION

    def test_auto_categorization_syntax(self) -> None:
        tracker = FailureTracker()
        failure = tracker.record_failure(FailureInput(
            action="run_bash",
            error="SyntaxError: unexpected token",
        ))
        assert failure.category == FailureCategory.SYNTAX

    def test_auto_categorization_type(self) -> None:
        tracker = FailureTracker()
        failure = tracker.record_failure(FailureInput(
            action="run_bash",
            error="TypeError: expected string got number",
        ))
        assert failure.category == FailureCategory.TYPE

    def test_auto_categorization_network(self) -> None:
        tracker = FailureTracker()
        failure = tracker.record_failure(FailureInput(
            action="fetch",
            error="ECONNREFUSED: Connection refused",
        ))
        assert failure.category == FailureCategory.NETWORK

    def test_auto_categorization_timeout(self) -> None:
        tracker = FailureTracker()
        failure = tracker.record_failure(FailureInput(
            action="run_bash",
            error="TimeoutError: command timed out after 60s",
        ))
        assert failure.category == FailureCategory.TIMEOUT

    def test_auto_categorization_validation(self) -> None:
        tracker = FailureTracker()
        failure = tracker.record_failure(FailureInput(
            action="api_call",
            error="ValueError: required field missing",
        ))
        assert failure.category == FailureCategory.VALIDATION

    def test_auto_categorization_resource(self) -> None:
        tracker = FailureTracker()
        failure = tracker.record_failure(FailureInput(
            action="run_bash",
            error="MemoryError: out of memory",
        ))
        assert failure.category == FailureCategory.RESOURCE

    def test_auto_categorization_runtime(self) -> None:
        tracker = FailureTracker()
        failure = tracker.record_failure(FailureInput(
            action="tool",
            error="RuntimeError: assertion failed",
        ))
        assert failure.category == FailureCategory.RUNTIME

    def test_auto_categorization_unknown(self) -> None:
        tracker = FailureTracker()
        failure = tracker.record_failure(FailureInput(
            action="tool",
            error="Something completely unexpected happened",
        ))
        assert failure.category == FailureCategory.UNKNOWN

    def test_manual_category_override(self) -> None:
        tracker = FailureTracker()
        failure = tracker.record_failure(FailureInput(
            action="tool",
            error="Something went wrong",
            category=FailureCategory.LOGIC,
        ))
        assert failure.category == FailureCategory.LOGIC

    def test_repeat_detection(self) -> None:
        tracker = FailureTracker()
        f1 = tracker.record_failure(FailureInput(action="edit_file", error="File not found: /x.py"))
        assert f1.repeat_count == 1
        f2 = tracker.record_failure(FailureInput(action="edit_file", error="File not found: /x.py"))
        assert f2.repeat_count == 2
        f3 = tracker.record_failure(FailureInput(action="edit_file", error="File not found: /x.py"))
        assert f3.repeat_count == 3

    def test_resolve_failure(self) -> None:
        tracker = FailureTracker()
        f = tracker.record_failure(FailureInput(action="tool", error="err"))
        assert tracker.resolve_failure(f.id) is True
        assert f.resolved is True
        assert tracker.resolve_failure("nonexistent") is False

    def test_get_unresolved_failures(self) -> None:
        tracker = FailureTracker()
        f1 = tracker.record_failure(FailureInput(action="a", error="e1"))
        f2 = tracker.record_failure(FailureInput(action="b", error="e2"))
        tracker.resolve_failure(f1.id)
        unresolved = tracker.get_unresolved_failures()
        assert len(unresolved) == 1
        assert unresolved[0].id == f2.id

    def test_get_failures_by_category(self) -> None:
        tracker = FailureTracker()
        tracker.record_failure(FailureInput(action="a", error="ENOENT: not found"))
        tracker.record_failure(FailureInput(action="b", error="permission denied"))
        tracker.record_failure(FailureInput(action="c", error="ENOENT: also not found"))
        not_found = tracker.get_failures_by_category(FailureCategory.NOT_FOUND)
        assert len(not_found) == 2

    def test_get_failures_by_action(self) -> None:
        tracker = FailureTracker()
        tracker.record_failure(FailureInput(action="edit_file", error="e1"))
        tracker.record_failure(FailureInput(action="run_bash", error="e2"))
        tracker.record_failure(FailureInput(action="edit_file", error="e3"))
        results = tracker.get_failures_by_action("edit_file")
        assert len(results) == 2

    def test_has_recent_failure(self) -> None:
        tracker = FailureTracker()
        tracker.record_failure(FailureInput(action="edit_file", error="err"))
        assert tracker.has_recent_failure("edit_file", within_ms=60000) is True
        assert tracker.has_recent_failure("other_action", within_ms=60000) is False

    def test_has_recent_failure_expired(self) -> None:
        tracker = FailureTracker()
        tracker.record_failure(FailureInput(action="edit_file", error="err"))
        tracker._failures[0].timestamp = time.time() - 120
        assert tracker.has_recent_failure("edit_file", within_ms=60000) is False

    def test_get_stats(self) -> None:
        tracker = FailureTracker()
        tracker.record_failure(FailureInput(action="edit_file", error="ENOENT: not found"))
        tracker.record_failure(FailureInput(action="edit_file", error="ENOENT: also not found"))
        tracker.record_failure(FailureInput(action="run_bash", error="permission denied"))
        f = tracker.record_failure(FailureInput(action="search", error="timeout"))
        tracker.resolve_failure(f.id)
        stats = tracker.get_stats()
        assert stats["total"] == 4
        assert stats["unresolved"] == 3
        assert FailureCategory.NOT_FOUND in stats["by_category"]
        assert stats["by_category"][FailureCategory.NOT_FOUND] == 2
        assert len(stats["most_failed_actions"]) > 0
        assert stats["most_failed_actions"][0] == ("edit_file", 2)

    def test_max_failures_eviction(self) -> None:
        tracker = FailureTracker(FailureTrackerConfig(max_failures=3))
        tracker.record_failure(FailureInput(action="a", error="e1"))
        tracker.record_failure(FailureInput(action="b", error="e2"))
        tracker.record_failure(FailureInput(action="c", error="e3"))
        tracker.record_failure(FailureInput(action="d", error="e4"))
        assert len(tracker._failures) == 3
        actions = [f.action for f in tracker._failures]
        assert "a" not in actions
        assert "d" in actions

    def test_max_failures_emits_evicted_event(self) -> None:
        tracker = FailureTracker(FailureTrackerConfig(max_failures=2))
        events: list[tuple[str, dict]] = []
        tracker.on(lambda e, d: events.append((e, d)))
        tracker.record_failure(FailureInput(action="a", error="e1"))
        tracker.record_failure(FailureInput(action="b", error="e2"))
        tracker.record_failure(FailureInput(action="c", error="e3"))
        evicted_events = [e for e, _ in events if e == "failure.evicted"]
        assert len(evicted_events) == 1

    def test_pattern_detection_repeated_action(self) -> None:
        tracker = FailureTracker(FailureTrackerConfig(repeat_warning_threshold=3))
        events: list[tuple[str, dict]] = []
        tracker.on(lambda e, d: events.append((e, d)))
        tracker.record_failure(FailureInput(action="edit_file", error="err1"))
        tracker.record_failure(FailureInput(action="edit_file", error="err2"))
        tracker.record_failure(FailureInput(action="edit_file", error="err3"))
        pattern_events = [d for e, d in events if e == "pattern.detected"]
        assert len(pattern_events) >= 1
        assert pattern_events[0]["pattern"].type == "repeated_action"

    def test_repeated_failure_event(self) -> None:
        tracker = FailureTracker(FailureTrackerConfig(repeat_warning_threshold=2))
        events: list[tuple[str, dict]] = []
        tracker.on(lambda e, d: events.append((e, d)))
        tracker.record_failure(FailureInput(action="edit_file", error="same error here"))
        tracker.record_failure(FailureInput(action="edit_file", error="same error here"))
        repeated = [d for e, d in events if e == "failure.repeated"]
        assert len(repeated) >= 1
        assert repeated[0]["count"] >= 2

    def test_record_failure_with_exception(self) -> None:
        tracker = FailureTracker()
        try:
            raise FileNotFoundError("no such file or directory: missing.py")
        except FileNotFoundError as exc:
            failure = tracker.record_failure(FailureInput(
                action="read_file",
                error=exc,
            ))
        assert "missing.py" in failure.error
        assert failure.category == FailureCategory.NOT_FOUND

    def test_clear(self) -> None:
        tracker = FailureTracker()
        tracker.record_failure(FailureInput(action="a", error="e"))
        tracker.clear()
        assert tracker.get_stats()["total"] == 0


class TestGenerateSuggestion:
    def test_each_category_has_suggestion(self) -> None:
        for cat in FailureCategory:
            f = Failure(
                id="f1",
                timestamp=time.time(),
                action="test",
                error="test error",
                category=cat,
            )
            suggestion = generate_suggestion(f)
            assert isinstance(suggestion, str)
            assert len(suggestion) > 0


class TestFormatFailureContext:
    def test_formats_failures(self) -> None:
        failures = [
            Failure(
                id="f1", timestamp=time.time(), action="edit_file",
                error="File not found", category=FailureCategory.NOT_FOUND,
                suggestion="Check the path.",
            ),
            Failure(
                id="f2", timestamp=time.time(), action="run_bash",
                error="Permission denied", category=FailureCategory.PERMISSION,
                resolved=True, suggestion="Use sudo.",
            ),
        ]
        ctx = format_failure_context(failures)
        assert "[Previous Failures" in ctx
        assert "edit_file" in ctx
        assert "File not found" in ctx
        assert "unresolved" in ctx
        assert "resolved" in ctx
        assert "Suggestion: Check the path." in ctx

    def test_empty_failures(self) -> None:
        assert format_failure_context([]) == ""


class TestCreateRepeatWarning:
    def test_basic_warning(self) -> None:
        msg = create_repeat_warning("edit_file", 3)
        assert "edit_file" in msg
        assert "3 times" in msg

    def test_warning_with_suggestion(self) -> None:
        msg = create_repeat_warning("edit_file", 5, suggestion="Try a different path.")
        assert "5 times" in msg
        assert "Try a different path." in msg



# =============================================================================
# DiverseSerializer Tests
# =============================================================================


class TestDiverseSerializer:
    def test_serialize_produces_valid_json(self) -> None:
        serializer = DiverseSerializer(DiverseSerializerConfig(seed=42))
        data = {"name": "Alice", "age": 30, "tags": ["dev", "python"]}
        result = serializer.serialize(data)
        parsed = json.loads(result)
        assert parsed["name"] == "Alice"
        assert parsed["age"] == 30
        assert parsed["tags"] == ["dev", "python"]

    def test_serialize_with_style_respects_indent(self) -> None:
        serializer = DiverseSerializer(DiverseSerializerConfig(seed=1))
        data = {"a": 1, "b": 2}
        style = SerializationStyle(indent=4, sort_keys=True, key_sort_order="asc")
        result = serializer.serialize_with_style(data, style)
        assert "    " in result
        assert len(result.strip().splitlines()) > 1

    def test_serialize_with_style_sort_keys_asc(self) -> None:
        serializer = DiverseSerializer(DiverseSerializerConfig(seed=1))
        data = {"z": 1, "a": 2, "m": 3}
        style = SerializationStyle(sort_keys=True, key_sort_order="asc", indent=None)
        result = serializer.serialize_with_style(data, style)
        parsed = json.loads(result)
        keys = list(parsed.keys())
        assert keys == ["a", "m", "z"]

    def test_serialize_with_style_sort_keys_desc(self) -> None:
        serializer = DiverseSerializer(DiverseSerializerConfig(seed=1))
        data = {"z": 1, "a": 2, "m": 3}
        style = SerializationStyle(sort_keys=True, key_sort_order="desc", indent=None)
        result = serializer.serialize_with_style(data, style)
        parsed = json.loads(result)
        keys = list(parsed.keys())
        assert keys == ["z", "m", "a"]

    def test_serialize_with_style_compact(self) -> None:
        serializer = DiverseSerializer(DiverseSerializerConfig(seed=1))
        data = {"a": 1}
        style = SerializationStyle(indent=None, space_after_colon=False)
        result = serializer.serialize_with_style(data, style)
        # Compact format: no spaces
        assert json.loads(result) == {"a": 1}
        assert ":" in result
        assert " : " not in result

    def test_generate_style_returns_serialization_style(self) -> None:
        serializer = DiverseSerializer(DiverseSerializerConfig(seed=42, variation_level=0.5))
        style = serializer.generate_style()
        assert isinstance(style, SerializationStyle)

    def test_get_consistent_style_returns_deterministic_defaults(self) -> None:
        serializer = DiverseSerializer()
        style = serializer.get_consistent_style()
        assert style.indent == 2
        assert style.sort_keys is True
        assert style.key_sort_order == "asc"
        assert style.space_after_colon is True
        assert style.omit_null is False

    def test_get_stats_tracks_serializations(self) -> None:
        serializer = DiverseSerializer(DiverseSerializerConfig(seed=42))
        assert serializer.get_stats().total_serializations == 0
        serializer.serialize({"a": 1})
        serializer.serialize({"b": 2})
        stats = serializer.get_stats()
        assert stats.total_serializations == 2
        assert len(stats.style_distribution) > 0

    def test_reset_stats(self) -> None:
        serializer = DiverseSerializer(DiverseSerializerConfig(seed=42))
        serializer.serialize({"a": 1})
        serializer.reset_stats()
        assert serializer.get_stats().total_serializations == 0

    def test_set_variation_level_clamps_to_0_1(self) -> None:
        serializer = DiverseSerializer()
        serializer.set_variation_level(-0.5)
        assert serializer._config.variation_level == 0.0
        serializer.set_variation_level(1.5)
        assert serializer._config.variation_level == 1.0
        serializer.set_variation_level(0.7)
        assert serializer._config.variation_level == pytest.approx(0.7)

    def test_omit_null_when_enabled(self) -> None:
        serializer = DiverseSerializer(DiverseSerializerConfig(seed=1))
        data = {"name": "Alice", "email": None, "age": 30}
        style = SerializationStyle(omit_null=True, sort_keys=True, key_sort_order="asc")
        result = serializer.serialize_with_style(data, style)
        parsed = json.loads(result)
        assert "email" not in parsed
        assert parsed["name"] == "Alice"
        assert parsed["age"] == 30

    def test_omit_null_disabled(self) -> None:
        serializer = DiverseSerializer(DiverseSerializerConfig(seed=1))
        data = {"name": "Alice", "email": None}
        style = SerializationStyle(omit_null=False, sort_keys=True, key_sort_order="asc")
        result = serializer.serialize_with_style(data, style)
        parsed = json.loads(result)
        assert "email" in parsed
        assert parsed["email"] is None

    def test_nested_dict_processing(self) -> None:
        serializer = DiverseSerializer(DiverseSerializerConfig(seed=1))
        data = {"outer": {"z": 1, "a": 2}, "top": 3}
        style = SerializationStyle(sort_keys=True, key_sort_order="asc")
        result = serializer.serialize_with_style(data, style)
        parsed = json.loads(result)
        outer_keys = list(parsed["outer"].keys())
        assert outer_keys == ["a", "z"]

    def test_on_events(self) -> None:
        serializer = DiverseSerializer(DiverseSerializerConfig(seed=42))
        events: list[str] = []
        unsub = serializer.on(lambda e, d: events.append(e))
        serializer.serialize({"a": 1})
        assert "serialization.performed" in events
        unsub()
        serializer.serialize({"b": 2})
        assert len(events) == 1


class TestAreSemanticEquivalent:
    def test_detects_equivalent_json(self) -> None:
        json1 = '{"b": 2, "a": 1}'
        json2 = '{"a": 1, "b": 2}'
        assert are_semantic_equivalent(json1, json2) is True

    def test_detects_non_equivalent_json(self) -> None:
        json1 = '{"a": 1}'
        json2 = '{"a": 2}'
        assert are_semantic_equivalent(json1, json2) is False

    def test_handles_invalid_json(self) -> None:
        assert are_semantic_equivalent("not json", '{"a": 1}') is False

    def test_handles_nested_equivalence(self) -> None:
        json1 = '{"a": {"c": 3, "b": 2}}'
        json2 = '{"a": {"b": 2, "c": 3}}'
        assert are_semantic_equivalent(json1, json2) is True


class TestGenerateVariations:
    def test_produces_different_outputs(self) -> None:
        data = {"name": "test", "value": 42, "items": [1, 2, 3]}
        variations = generate_variations(data, count=10, variation_level=1.0)
        assert len(variations) == 10
        for v in variations:
            parsed = json.loads(v)
            assert parsed["name"] == "test"
            assert parsed["value"] == 42
        unique = set(variations)
        assert len(unique) > 1

    def test_all_semantically_equivalent(self) -> None:
        data = {"x": 1, "y": [2, 3]}
        variations = generate_variations(data, count=5, variation_level=0.8)
        for v in variations:
            assert are_semantic_equivalent(v, json.dumps(data))
