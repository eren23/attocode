"""Tests for core type definitions."""

from __future__ import annotations

from attocode.types.agent import (
    AgentCompletionStatus,
    AgentConfig,
    AgentMetrics,
    AgentPlan,
    AgentResult,
    AgentState,
    AgentStatus,
    CompletionReason,
    OpenTaskSummary,
    PlanTask,
    RecoveryInfo,
    TaskStatus,
)
from attocode.types.budget import (
    DEEP_BUDGET,
    QUICK_BUDGET,
    STANDARD_BUDGET,
    SUBAGENT_BUDGET,
    BudgetCheckResult,
    BudgetEnforcementMode,
    BudgetStatus,
    ExecutionBudget,
)
from attocode.types.events import AgentEvent, EventType
from attocode.types.messages import (
    CacheControl,
    ChatOptions,
    ChatResponse,
    ImageContentBlock,
    ImageSource,
    Message,
    MessageWithStructuredContent,
    Role,
    StopReason,
    StreamChunk,
    StreamChunkType,
    TextContentBlock,
    TokenUsage,
    ToolCall,
    ToolDefinition,
    ToolResult,
    DangerLevel,
)


class TestRole:
    def test_values(self) -> None:
        assert Role.SYSTEM == "system"
        assert Role.USER == "user"
        assert Role.ASSISTANT == "assistant"
        assert Role.TOOL == "tool"

    def test_str_enum(self) -> None:
        assert str(Role.USER) == "user"
        assert f"role={Role.ASSISTANT}" == "role=assistant"


class TestStopReason:
    def test_values(self) -> None:
        assert StopReason.END_TURN == "end_turn"
        assert StopReason.TOOL_USE == "tool_use"
        assert StopReason.MAX_TOKENS == "max_tokens"


class TestDangerLevel:
    def test_values(self) -> None:
        assert DangerLevel.SAFE == "safe"
        assert DangerLevel.MODERATE == "moderate"
        assert DangerLevel.DANGEROUS == "dangerous"


class TestToolCall:
    def test_creation(self) -> None:
        tc = ToolCall(id="tc_1", name="read_file", arguments={"path": "foo.py"})
        assert tc.id == "tc_1"
        assert tc.name == "read_file"
        assert tc.arguments == {"path": "foo.py"}
        assert tc.parse_error is None

    def test_with_parse_error(self) -> None:
        tc = ToolCall(id="tc_2", name="bash", arguments={}, parse_error="bad json")
        assert tc.parse_error == "bad json"


class TestToolResult:
    def test_success(self) -> None:
        tr = ToolResult(call_id="tc_1", result="file content here")
        assert not tr.is_error
        assert tr.result == "file content here"

    def test_error(self) -> None:
        tr = ToolResult(call_id="tc_1", error="file not found")
        assert tr.is_error
        assert tr.error == "file not found"


class TestToolDefinition:
    def test_to_schema(self) -> None:
        td = ToolDefinition(
            name="read_file",
            description="Read a file",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        )
        schema = td.to_schema()
        assert schema["name"] == "read_file"
        assert schema["description"] == "Read a file"
        assert schema["input_schema"]["type"] == "object"


class TestTokenUsage:
    def test_defaults(self) -> None:
        u = TokenUsage()
        assert u.input_tokens == 0
        assert u.output_tokens == 0
        assert u.total_tokens == 0
        assert u.cost == 0.0

    def test_values(self) -> None:
        u = TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150, cost=0.01)
        assert u.input_tokens == 100
        assert u.cost == 0.01


class TestMessage:
    def test_basic(self) -> None:
        m = Message(role=Role.USER, content="hello")
        assert m.role == Role.USER
        assert m.content == "hello"
        assert not m.has_tool_calls

    def test_with_tool_calls(self) -> None:
        tc = ToolCall(id="1", name="bash", arguments={"command": "ls"})
        m = Message(role=Role.ASSISTANT, content="", tool_calls=[tc])
        assert m.has_tool_calls

    def test_tool_message(self) -> None:
        m = Message(role=Role.TOOL, content="result", tool_call_id="tc_1")
        assert m.role == Role.TOOL
        assert m.tool_call_id == "tc_1"


class TestMessageWithStructuredContent:
    def test_string_content(self) -> None:
        m = MessageWithStructuredContent(role=Role.USER, content="hello")
        assert isinstance(m.content, str)

    def test_block_content(self) -> None:
        blocks = [TextContentBlock(text="hello"), TextContentBlock(text="world")]
        m = MessageWithStructuredContent(role=Role.USER, content=blocks)
        assert isinstance(m.content, list)
        assert len(m.content) == 2


class TestChatOptions:
    def test_defaults(self) -> None:
        opts = ChatOptions()
        assert opts.model is None
        assert opts.max_tokens is None
        assert opts.stream is False

    def test_with_tools(self) -> None:
        td = ToolDefinition(name="t", description="d", parameters={})
        opts = ChatOptions(tools=[td])
        assert len(opts.tools) == 1


class TestChatResponse:
    def test_basic(self) -> None:
        r = ChatResponse(content="hello", stop_reason=StopReason.END_TURN)
        assert r.content == "hello"
        assert not r.has_tool_calls

    def test_with_tool_calls(self) -> None:
        tc = ToolCall(id="1", name="bash", arguments={})
        r = ChatResponse(content="", tool_calls=[tc], stop_reason=StopReason.TOOL_USE)
        assert r.has_tool_calls


class TestContentBlocks:
    def test_text_block(self) -> None:
        b = TextContentBlock(text="hello")
        assert b.text == "hello"
        assert b.type == "text"

    def test_text_block_with_cache(self) -> None:
        b = TextContentBlock(text="big text", cache_control=CacheControl(type="ephemeral"))
        assert b.cache_control is not None
        assert b.cache_control.type == "ephemeral"

    def test_image_block(self) -> None:
        src = ImageSource(type="base64", media_type="image/png", data="abc")
        b = ImageContentBlock(source=src)
        assert b.source.data == "abc"


class TestStreamChunk:
    def test_text_chunk(self) -> None:
        c = StreamChunk(type=StreamChunkType.TEXT, content="hi")
        assert c.type == StreamChunkType.TEXT
        assert c.content == "hi"

    def test_done_chunk(self) -> None:
        c = StreamChunk(type=StreamChunkType.DONE)
        assert c.content is None


# --- Agent types ---

class TestAgentStatus:
    def test_values(self) -> None:
        assert AgentStatus.IDLE == "idle"
        assert AgentStatus.RUNNING == "running"
        assert AgentStatus.COMPLETED == "completed"


class TestCompletionReason:
    def test_values(self) -> None:
        assert CompletionReason.COMPLETED == "completed"
        assert CompletionReason.BUDGET_LIMIT == "budget_limit"
        assert CompletionReason.OPEN_TASKS == "open_tasks"


class TestTaskStatus:
    def test_values(self) -> None:
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.COMPLETED == "completed"
        assert TaskStatus.BLOCKED == "blocked"


class TestAgentMetrics:
    def test_defaults(self) -> None:
        m = AgentMetrics()
        assert m.llm_calls == 0
        assert m.total_tokens == 0

    def test_add_usage(self) -> None:
        m = AgentMetrics()
        m.add_usage(input_tokens=100, output_tokens=50, cost=0.01)
        assert m.input_tokens == 100
        assert m.output_tokens == 50
        assert m.total_tokens == 150
        assert m.llm_calls == 1
        assert m.estimated_cost == 0.01

    def test_add_usage_cumulative(self) -> None:
        m = AgentMetrics()
        m.add_usage(input_tokens=100, output_tokens=50, cost=0.01)
        m.add_usage(input_tokens=200, output_tokens=100, cost=0.02)
        assert m.llm_calls == 2
        assert m.total_tokens == 450
        assert abs(m.estimated_cost - 0.03) < 1e-9


class TestOpenTaskSummary:
    def test_empty(self) -> None:
        s = OpenTaskSummary()
        assert s.total == 0
        assert not s.has_open

    def test_with_tasks(self) -> None:
        s = OpenTaskSummary(pending=3, in_progress=1, blocked=2)
        assert s.total == 6
        assert s.has_open


class TestAgentPlan:
    def test_empty_plan_complete(self) -> None:
        p = AgentPlan(goal="test")
        assert p.is_complete
        assert p.progress == 1.0
        assert p.current_task is None

    def test_plan_progress(self) -> None:
        tasks = [
            PlanTask(id="1", description="A", status=TaskStatus.COMPLETED),
            PlanTask(id="2", description="B", status=TaskStatus.PENDING),
        ]
        p = AgentPlan(goal="test", tasks=tasks)
        assert not p.is_complete
        assert p.progress == 0.5
        assert p.current_task is not None
        assert p.current_task.id == "2"

    def test_all_complete(self) -> None:
        tasks = [
            PlanTask(id="1", description="A", status=TaskStatus.COMPLETED),
            PlanTask(id="2", description="B", status=TaskStatus.COMPLETED),
        ]
        p = AgentPlan(goal="test", tasks=tasks)
        assert p.is_complete
        assert p.progress == 1.0


class TestAgentResult:
    def test_success(self) -> None:
        r = AgentResult(success=True, response="Done!")
        assert r.success
        assert r.response == "Done!"
        assert r.error is None

    def test_failure(self) -> None:
        r = AgentResult(success=False, response="", error="something broke")
        assert not r.success
        assert r.error == "something broke"


# --- Budget types ---

class TestBudgetEnforcementMode:
    def test_values(self) -> None:
        assert BudgetEnforcementMode.STRICT == "strict"
        assert BudgetEnforcementMode.ADVISORY == "advisory"


class TestExecutionBudget:
    def test_defaults(self) -> None:
        b = ExecutionBudget()
        assert b.max_tokens == 1_000_000
        assert b.enforcement_mode == BudgetEnforcementMode.STRICT

    def test_soft_ratio(self) -> None:
        b = ExecutionBudget(max_tokens=1000, soft_token_limit=800)
        assert b.soft_ratio == 0.8

    def test_soft_ratio_none(self) -> None:
        b = ExecutionBudget()
        assert b.soft_ratio is None


class TestBudgetCheckResult:
    def test_ok(self) -> None:
        r = BudgetCheckResult(status=BudgetStatus.OK)
        assert r.is_ok
        assert not r.should_stop

    def test_exhausted(self) -> None:
        r = BudgetCheckResult(
            status=BudgetStatus.EXHAUSTED,
            token_usage=1.0,
            should_stop=True,
        )
        assert not r.is_ok
        assert r.should_stop
        assert r.max_usage == 1.0

    def test_max_usage(self) -> None:
        r = BudgetCheckResult(
            status=BudgetStatus.WARNING,
            token_usage=0.5,
            cost_usage=0.8,
            duration_usage=0.3,
        )
        assert r.max_usage == 0.8


class TestPresetBudgets:
    def test_quick(self) -> None:
        assert QUICK_BUDGET.max_tokens == 200_000
        assert QUICK_BUDGET.max_iterations == 20

    def test_standard(self) -> None:
        assert STANDARD_BUDGET.max_tokens == 1_000_000

    def test_deep(self) -> None:
        assert DEEP_BUDGET.max_tokens == 5_000_000

    def test_subagent(self) -> None:
        assert SUBAGENT_BUDGET.enforcement_mode == BudgetEnforcementMode.STRICT


# --- Event types ---

class TestEventType:
    def test_values(self) -> None:
        assert EventType.START == "start"
        assert EventType.TOOL_START == "tool.start"
        assert EventType.LLM_COMPLETE == "llm.complete"


class TestAgentEvent:
    def test_creation(self) -> None:
        e = AgentEvent(type=EventType.START, task="test")
        assert e.type == EventType.START
        assert e.task == "test"

    def test_tool_event(self) -> None:
        e = AgentEvent(
            type=EventType.TOOL_COMPLETE,
            tool="read_file",
            result="content",
            tokens=100,
        )
        assert e.tool == "read_file"
        assert e.tokens == 100
