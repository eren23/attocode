"""Tests for newly added utility modules:
- routing
- execution_policy
- complexity_classifier
- thinking_strategy
- tool_coercion
- resilient_fetch
"""

from __future__ import annotations

import pytest

# ============================================================
# Routing tests
# ============================================================


class TestRoutingManager:
    def test_create_routing_manager(self):
        from attocode.integrations.utilities.routing import RoutingManager, RoutingStrategy
        mgr = RoutingManager(strategy=RoutingStrategy.BALANCED)
        assert mgr.strategy == RoutingStrategy.BALANCED

    def test_register_provider(self):
        from attocode.integrations.utilities.routing import ProviderConfig, RoutingManager
        mgr = RoutingManager()
        mgr.register_provider(ProviderConfig(name="test", priority=0))
        assert "test" in mgr.get_stats()

    def test_route_by_cost(self):
        from attocode.integrations.utilities.routing import (
            ProviderConfig,
            RoutingManager,
            RoutingStrategy,
        )
        mgr = RoutingManager(strategy=RoutingStrategy.COST)
        mgr.register_provider(ProviderConfig(name="cheap", cost_per_1k_input=0.001))
        mgr.register_provider(ProviderConfig(name="expensive", cost_per_1k_input=0.01))
        decision = mgr.route()
        assert decision.provider_name == "cheap"

    def test_route_by_quality(self):
        from attocode.integrations.utilities.routing import (
            ProviderConfig,
            RoutingManager,
            RoutingStrategy,
        )
        mgr = RoutingManager(strategy=RoutingStrategy.QUALITY)
        mgr.register_provider(ProviderConfig(name="good", quality_score=0.95))
        mgr.register_provider(ProviderConfig(name="ok", quality_score=0.7))
        decision = mgr.route()
        assert decision.provider_name == "good"

    def test_route_by_latency(self):
        from attocode.integrations.utilities.routing import (
            ProviderConfig,
            RoutingManager,
            RoutingStrategy,
        )
        mgr = RoutingManager(strategy=RoutingStrategy.LATENCY)
        mgr.register_provider(ProviderConfig(name="fast", avg_latency_ms=100))
        mgr.register_provider(ProviderConfig(name="slow", avg_latency_ms=2000))
        decision = mgr.route()
        assert decision.provider_name == "fast"

    def test_circuit_breaker_trips(self):
        from attocode.integrations.utilities.routing import (
            ProviderConfig,
            RoutingManager,
        )
        mgr = RoutingManager(circuit_breaker_threshold=3, circuit_breaker_timeout=0.1)
        mgr.register_provider(ProviderConfig(name="flaky"))
        # Trip the circuit breaker
        for _ in range(3):
            mgr.record_failure("flaky")
        stats = mgr.get_stats()
        assert stats["flaky"].circuit_state == "open"

    def test_record_success_resets_circuit(self):
        from attocode.integrations.utilities.routing import (
            ProviderConfig,
            RoutingManager,
        )
        mgr = RoutingManager(circuit_breaker_threshold=3)
        mgr.register_provider(ProviderConfig(name="p1"))
        for _ in range(3):
            mgr.record_failure("p1")
        mgr.record_success("p1", 100.0, 1000, 0.01)
        stats = mgr.get_stats()
        assert stats["p1"].circuit_state == "closed"

    def test_fallback_chain(self):
        from attocode.integrations.utilities.routing import (
            ProviderConfig,
            RoutingManager,
            RoutingStrategy,
        )
        mgr = RoutingManager(strategy=RoutingStrategy.COST)
        mgr.register_provider(ProviderConfig(name="a", cost_per_1k_input=0.001))
        mgr.register_provider(ProviderConfig(name="b", cost_per_1k_input=0.01))
        mgr.register_provider(ProviderConfig(name="c", cost_per_1k_input=0.1))
        decision = mgr.route()
        assert len(decision.fallback_chain) == 2

    def test_set_strategy(self):
        from attocode.integrations.utilities.routing import RoutingManager, RoutingStrategy
        mgr = RoutingManager()
        mgr.set_strategy("cost")
        assert mgr.strategy == RoutingStrategy.COST

    def test_rules_routing(self):
        from attocode.integrations.utilities.routing import (
            ProviderConfig,
            RoutingManager,
            RoutingRule,
            RoutingStrategy,
        )
        mgr = RoutingManager(strategy=RoutingStrategy.RULES)
        mgr.register_provider(ProviderConfig(name="claude"))
        mgr.register_provider(ProviderConfig(name="gpt"))
        mgr.add_rule(RoutingRule(condition="model_contains", value="claude", provider_name="claude"))
        decision = mgr.route(model="claude-3-opus")
        assert decision.provider_name == "claude"


# ============================================================
# Execution Policy tests
# ============================================================


class TestExecutionPolicyManager:
    def test_default_allows(self):
        from attocode.integrations.utilities.execution_policy import ExecutionPolicyManager
        mgr = ExecutionPolicyManager()
        decision = mgr.evaluate("read_file", {})
        assert decision.action == "allow"

    def test_add_default_rules(self):
        from attocode.integrations.utilities.execution_policy import ExecutionPolicyManager
        mgr = ExecutionPolicyManager()
        mgr.add_default_rules()
        assert len(mgr.list_rules()) >= 3

    def test_deny_rm_rf(self):
        from attocode.integrations.utilities.execution_policy import ExecutionPolicyManager
        mgr = ExecutionPolicyManager()
        mgr.add_default_rules()
        decision = mgr.evaluate("bash", {"command": "rm -rf /"})
        assert decision.action == "deny"

    def test_warn_sudo(self):
        from attocode.integrations.utilities.execution_policy import ExecutionPolicyManager
        mgr = ExecutionPolicyManager()
        mgr.add_default_rules()
        decision = mgr.evaluate("bash", {"command": "sudo apt-get update"})
        assert decision.action == "warn"

    def test_ask_git_push(self):
        from attocode.integrations.utilities.execution_policy import ExecutionPolicyManager
        mgr = ExecutionPolicyManager()
        mgr.add_default_rules()
        decision = mgr.evaluate("bash", {"command": "git push origin main"})
        assert decision.action == "ask"

    def test_classify_intent_deliberate(self):
        from attocode.integrations.utilities.execution_policy import (
            ExecutionPolicyManager,
            IntentType,
        )
        mgr = ExecutionPolicyManager()
        intent = mgr.classify_intent("bash", {}, user_requested=True)
        assert intent == IntentType.DELIBERATE

    def test_classify_intent_accidental(self):
        from attocode.integrations.utilities.execution_policy import (
            ExecutionPolicyManager,
            IntentType,
        )
        mgr = ExecutionPolicyManager()
        intent = mgr.classify_intent("bash", {}, confidence=0.1)
        assert intent == IntentType.ACCIDENTAL

    def test_remove_rule(self):
        from attocode.integrations.utilities.execution_policy import ExecutionPolicyManager
        mgr = ExecutionPolicyManager()
        mgr.add_default_rules()
        count_before = len(mgr.list_rules())
        mgr.remove_rule("block_rm_rf_root")
        assert len(mgr.list_rules()) == count_before - 1


# ============================================================
# Complexity Classifier tests
# ============================================================


class TestComplexityClassifier:
    def test_trivial_short_prompt(self):
        from attocode.integrations.utilities.complexity_classifier import (
            Complexity,
            classify_complexity,
        )
        result = classify_complexity("fix typo")
        assert result.level == Complexity.TRIVIAL

    def test_complex_refactor(self):
        from attocode.integrations.utilities.complexity_classifier import (
            Complexity,
            classify_complexity,
        )
        result = classify_complexity("Refactor the authentication system to use JWT tokens")
        assert result.level == Complexity.COMPLEX

    def test_deep_research(self):
        from attocode.integrations.utilities.complexity_classifier import (
            Complexity,
            classify_complexity,
        )
        result = classify_complexity("Investigate performance bottlenecks in the API")
        assert result.level == Complexity.DEEP_RESEARCH

    def test_question_is_trivial(self):
        from attocode.integrations.utilities.complexity_classifier import (
            Complexity,
            classify_complexity,
        )
        result = classify_complexity("What is this function?")
        assert result.level == Complexity.TRIVIAL

    def test_multi_file_is_moderate(self):
        from attocode.integrations.utilities.complexity_classifier import (
            Complexity,
            classify_complexity,
        )
        result = classify_complexity("Update the error handling across all API files")
        assert result.level in (Complexity.MODERATE, Complexity.COMPLEX)

    def test_budget_multiplier_deep_research(self):
        from attocode.integrations.utilities.complexity_classifier import classify_complexity
        result = classify_complexity("Analyze and benchmark all database queries")
        assert result.suggested_budget_multiplier >= 1.5

    def test_estimated_iterations(self):
        from attocode.integrations.utilities.complexity_classifier import classify_complexity
        result = classify_complexity("help")
        assert result.estimated_iterations <= 5


# ============================================================
# Thinking Strategy tests
# ============================================================


class TestThinkingStrategy:
    def test_no_thinking_unsupported_model(self):
        from attocode.integrations.utilities.thinking_strategy import (
            ThinkingMode,
            select_thinking_strategy,
        )
        result = select_thinking_strategy(model="gpt-4o")
        assert result.mode == ThinkingMode.NONE

    def test_extended_thinking_complex_task(self):
        from attocode.integrations.utilities.thinking_strategy import (
            ThinkingMode,
            select_thinking_strategy,
        )
        result = select_thinking_strategy(model="claude-sonnet-4", complexity="complex")
        assert result.mode == ThinkingMode.EXTENDED

    def test_no_thinking_low_budget(self):
        from attocode.integrations.utilities.thinking_strategy import (
            ThinkingMode,
            select_thinking_strategy,
        )
        result = select_thinking_strategy(
            model="claude-sonnet-4",
            complexity="complex",
            budget_remaining_fraction=0.1,
        )
        assert result.mode == ThinkingMode.NONE

    def test_extended_thinking_planning(self):
        from attocode.integrations.utilities.thinking_strategy import (
            ThinkingMode,
            select_thinking_strategy,
        )
        result = select_thinking_strategy(model="claude-opus-4", is_planning=True)
        assert result.mode == ThinkingMode.EXTENDED

    def test_extended_thinking_debugging(self):
        from attocode.integrations.utilities.thinking_strategy import (
            ThinkingMode,
            select_thinking_strategy,
        )
        result = select_thinking_strategy(model="claude-opus-4", is_debugging=True)
        assert result.mode == ThinkingMode.EXTENDED


# ============================================================
# Tool Coercion tests
# ============================================================


class TestToolCoercion:
    def test_coerce_boolean_true_string(self):
        from attocode.integrations.utilities.tool_coercion import coerce_boolean
        assert coerce_boolean("true") is True
        assert coerce_boolean("yes") is True
        assert coerce_boolean("1") is True

    def test_coerce_boolean_false_string(self):
        from attocode.integrations.utilities.tool_coercion import coerce_boolean
        assert coerce_boolean("false") is False
        assert coerce_boolean("no") is False
        assert coerce_boolean("0") is False
        assert coerce_boolean("") is False

    def test_coerce_boolean_already_bool(self):
        from attocode.integrations.utilities.tool_coercion import coerce_boolean
        assert coerce_boolean(True) is True
        assert coerce_boolean(False) is False

    def test_coerce_string_none(self):
        from attocode.integrations.utilities.tool_coercion import coerce_string
        assert coerce_string(None) == ""

    def test_coerce_string_number(self):
        from attocode.integrations.utilities.tool_coercion import coerce_string
        assert coerce_string(42) == "42"
        assert coerce_string(3.14) == "3.14"

    def test_coerce_string_bool(self):
        from attocode.integrations.utilities.tool_coercion import coerce_string
        assert coerce_string(True) == "true"

    def test_coerce_integer_float(self):
        from attocode.integrations.utilities.tool_coercion import coerce_integer
        assert coerce_integer(3.7) == 3

    def test_coerce_integer_string(self):
        from attocode.integrations.utilities.tool_coercion import coerce_integer
        assert coerce_integer("42") == 42
        assert coerce_integer("3.14") == 3

    def test_coerce_integer_invalid(self):
        from attocode.integrations.utilities.tool_coercion import coerce_integer
        assert coerce_integer("not a number") == 0

    def test_coerce_number(self):
        from attocode.integrations.utilities.tool_coercion import coerce_number
        assert coerce_number("3.14") == 3.14
        assert coerce_number(42) == 42.0

    def test_coerce_tool_arguments(self):
        from attocode.integrations.utilities.tool_coercion import coerce_tool_arguments
        schema = {
            "properties": {
                "name": {"type": "string"},
                "count": {"type": "integer"},
                "flag": {"type": "boolean"},
            }
        }
        args = {"name": "test", "count": "5", "flag": "true"}
        result = coerce_tool_arguments(args, schema)
        assert result["name"] == "test"
        assert result["count"] == 5
        assert result["flag"] is True

    def test_coerce_tool_arguments_already_correct(self):
        from attocode.integrations.utilities.tool_coercion import coerce_tool_arguments
        schema = {"properties": {"name": {"type": "string"}}}
        args = {"name": "hello"}
        result = coerce_tool_arguments(args, schema)
        assert result["name"] == "hello"

    def test_coerce_tool_arguments_empty_schema(self):
        from attocode.integrations.utilities.tool_coercion import coerce_tool_arguments
        args = {"a": 1, "b": "test"}
        result = coerce_tool_arguments(args, {})
        assert result == args


# ============================================================
# Code Selector tests
# ============================================================


class TestCodeSelector:
    def _make_chunk(self, name: str, importance: float = 0.5, file_path: str = "test.py"):
        from attocode.integrations.context.code_analyzer import CodeChunk
        return CodeChunk(
            name=name,
            kind="function",
            start_line=1,
            end_line=10,
            content=f"def {name}(): pass",
            file_path=file_path,
            language="python",
            importance=importance,
        )

    def _make_analysis(self, path: str, chunks):
        from attocode.integrations.context.code_analyzer import FileAnalysis
        return FileAnalysis(path=path, language="python", chunks=chunks, line_count=100)

    def test_select_by_importance(self):
        from attocode.integrations.context.code_selector import CodeSelector, SelectionConfig
        sel = CodeSelector(SelectionConfig(max_tokens=1000))
        analyses = [
            self._make_analysis("a.py", [
                self._make_chunk("high", 0.9, "a.py"),
                self._make_chunk("low", 0.1, "a.py"),
            ]),
        ]
        result = sel.select(analyses)
        assert len(result.chunks) >= 1
        assert result.chunks[0].name == "high"

    def test_select_by_relevance(self):
        from attocode.integrations.context.code_selector import (
            CodeSelector,
            SelectionConfig,
            SelectionStrategy,
        )
        sel = CodeSelector(SelectionConfig(
            max_tokens=1000,
            strategy=SelectionStrategy.RELEVANCE,
            query="authentication login",
        ))
        analyses = [
            self._make_analysis("a.py", [
                self._make_chunk("login_handler", 0.5, "a.py"),
                self._make_chunk("sort_items", 0.5, "a.py"),
            ]),
        ]
        result = sel.select(analyses)
        assert result.chunks[0].name == "login_handler"

    def test_select_breadth_strategy(self):
        from attocode.integrations.context.code_selector import (
            CodeSelector,
            SelectionConfig,
            SelectionStrategy,
        )
        sel = CodeSelector(SelectionConfig(
            max_tokens=1000,
            strategy=SelectionStrategy.BREADTH,
        ))
        analyses = [
            self._make_analysis("a.py", [self._make_chunk("a1", 0.5, "a.py")]),
            self._make_analysis("b.py", [self._make_chunk("b1", 0.5, "b.py")]),
        ]
        result = sel.select(analyses)
        assert result.files_represented == 2

    def test_budget_respected(self):
        from attocode.integrations.context.code_selector import CodeSelector, SelectionConfig
        sel = CodeSelector(SelectionConfig(max_tokens=5))  # Very small budget
        analyses = [
            self._make_analysis("a.py", [
                self._make_chunk("very_long_function_name_that_uses_many_tokens", 0.9, "a.py"),
            ]),
        ]
        result = sel.select(analyses)
        assert result.total_tokens <= 5

    def test_format_selection(self):
        from attocode.integrations.context.code_selector import CodeSelector, SelectionConfig
        sel = CodeSelector(SelectionConfig(max_tokens=1000))
        analyses = [
            self._make_analysis("a.py", [self._make_chunk("func1", 0.9, "a.py")]),
        ]
        result = sel.select(analyses)
        text = sel.format_selection(result)
        assert "a.py" in text


# ============================================================
# Dead Letter Queue tests
# ============================================================


class TestDeadLetterQueue:
    def test_add_and_get(self):
        from attocode.integrations.quality.dead_letter_queue import DeadLetterQueue
        dlq = DeadLetterQueue()
        dlq.add("tool_call", "bash", {"command": "test"}, "timeout")
        assert dlq.size == 1
        all_letters = dlq.get_all()
        assert len(all_letters) == 1
        assert all_letters[0].name == "bash"

    def test_drain_retryable(self):
        from attocode.integrations.quality.dead_letter_queue import DeadLetterQueue
        dlq = DeadLetterQueue()
        dlq.add("tool_call", "bash", {}, "error1", max_retries=2)
        dlq.add("tool_call", "grep", {}, "error2", max_retries=0)
        retryable = dlq.drain_retryable()
        assert len(retryable) == 1
        assert retryable[0].name == "bash"
        assert dlq.size == 1  # exhausted one remains

    def test_max_size(self):
        from attocode.integrations.quality.dead_letter_queue import DeadLetterQueue
        dlq = DeadLetterQueue(max_size=5)
        for i in range(10):
            dlq.add("op", f"tool_{i}", {}, "error")
        assert dlq.size == 5

    def test_remove(self):
        from attocode.integrations.quality.dead_letter_queue import DeadLetterQueue
        dlq = DeadLetterQueue()
        dl = dlq.add("tool_call", "bash", {}, "error")
        assert dlq.remove(dl.id)
        assert dlq.size == 0

    def test_clear(self):
        from attocode.integrations.quality.dead_letter_queue import DeadLetterQueue
        dlq = DeadLetterQueue()
        dlq.add("op", "tool", {}, "err")
        dlq.add("op", "tool", {}, "err")
        count = dlq.clear()
        assert count == 2
        assert dlq.size == 0

    def test_serialization(self):
        from attocode.integrations.quality.dead_letter_queue import DeadLetterQueue
        dlq = DeadLetterQueue()
        dlq.add("tool_call", "bash", {"cmd": "ls"}, "timeout", session_id="s1")
        data = dlq.to_serializable()
        dlq2 = DeadLetterQueue()
        dlq2.load_from_serializable(data)
        assert dlq2.size == 1
        assert dlq2.get_all()[0].session_id == "s1"

    def test_filter_by_operation(self):
        from attocode.integrations.quality.dead_letter_queue import DeadLetterQueue
        dlq = DeadLetterQueue()
        dlq.add("tool_call", "bash", {}, "err")
        dlq.add("mcp_call", "server1", {}, "err")
        assert len(dlq.get_by_operation("tool_call")) == 1
        assert len(dlq.get_by_name("server1")) == 1

    def test_format_summary(self):
        from attocode.integrations.quality.dead_letter_queue import DeadLetterQueue
        dlq = DeadLetterQueue()
        dlq.add("tool_call", "bash", {}, "timeout error")
        summary = dlq.format_summary()
        assert "bash" in summary
        assert "1 entries" in summary


# ============================================================
# Enhanced Bash Tool tests
# ============================================================


class TestEnhancedBashTool:
    def test_timeout_normalization(self):
        from attocode.tools.bash import _normalize_timeout
        assert _normalize_timeout(30) == 30.0  # seconds
        assert _normalize_timeout(5000) == 5.0  # milliseconds → seconds
        assert _normalize_timeout(300) == 0.3  # >= 300 treated as ms

    def test_sanitize_env(self):
        import os
        from attocode.tools.bash import _sanitize_env
        env = _sanitize_env()
        assert env["TERM"] == "dumb"
        assert "AWS_SECRET_ACCESS_KEY" not in env

    def test_classify_danger_level_safe(self):
        from attocode.tools.bash import classify_danger_level
        from attocode.types.messages import DangerLevel
        level = classify_danger_level("ls -la")
        assert level == DangerLevel.SAFE

    def test_classify_danger_level_dangerous(self):
        from attocode.tools.bash import classify_danger_level
        from attocode.types.messages import DangerLevel
        level = classify_danger_level("rm -rf /")
        assert level == DangerLevel.DANGEROUS

    def test_create_bash_tool(self):
        from attocode.tools.bash import create_bash_tool
        tool = create_bash_tool()
        assert tool.name == "bash"
        assert "timeout" in tool.spec.parameters["properties"]

    @pytest.mark.asyncio
    async def test_execute_bash_simple(self):
        from attocode.tools.bash import execute_bash
        result = await execute_bash({"command": "echo hello"})
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_execute_bash_nonexistent_dir(self):
        from attocode.tools.bash import execute_bash
        result = await execute_bash({"command": "ls"}, working_dir="/nonexistent/path")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_execute_bash_exit_code(self):
        from attocode.tools.bash import execute_bash
        result = await execute_bash({"command": "false"})
        assert "Exit code:" in result
