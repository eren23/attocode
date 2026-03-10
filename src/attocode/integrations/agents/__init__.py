"""Agent management: registry, blackboard, delegation, synthesis."""

from attocode.integrations.agents.async_subagent import (
    AsyncSubagentConfig,
    AsyncSubagentManager,
    SubagentHandle,
    SubagentStatus,
)
from attocode.integrations.agents.blackboard import (
    BlackboardEntry,
    BlackboardMetrics,
    NamespaceMetrics,
    SharedBlackboard,
    Subscriber,
)
from attocode.integrations.agents.delegation import (
    DelegationProtocol,
    DelegationRequest,
    DelegationResult,
    DelegationStatus,
)
from attocode.integrations.agents.registry import BUILTIN_AGENTS, AgentDefinition, AgentRegistry
from attocode.integrations.agents.result_synthesizer import (
    AgentOutput,
    ConflictSeverity,
    ConflictType,
    FileChange,
    FileConflict,
    OutputType,
    ResolutionStrategy,
    ResultSynthesizer,
    ResultSynthesizerConfig,
    SynthesisMethod,
    SynthesisResult,
    SynthesisStats,
    build_synthesis_prompt,
    create_result_synthesizer,
)
from attocode.integrations.agents.subagent_output_store import (
    SubagentOutput,
    SubagentOutputStore,
)

__all__ = [
    # blackboard
    "BlackboardEntry",
    "BlackboardMetrics",
    "NamespaceMetrics",
    "SharedBlackboard",
    "Subscriber",
    # registry
    "AgentDefinition",
    "AgentRegistry",
    "BUILTIN_AGENTS",
    # delegation
    "DelegationProtocol",
    "DelegationRequest",
    "DelegationResult",
    "DelegationStatus",
    # result_synthesizer
    "AgentOutput",
    "ConflictSeverity",
    "ConflictType",
    "FileChange",
    "FileConflict",
    "OutputType",
    "ResolutionStrategy",
    "ResultSynthesizer",
    "ResultSynthesizerConfig",
    "SynthesisMethod",
    "SynthesisResult",
    "SynthesisStats",
    "build_synthesis_prompt",
    "create_result_synthesizer",
    # async_subagent
    "AsyncSubagentConfig",
    "AsyncSubagentManager",
    "SubagentHandle",
    "SubagentStatus",
    # subagent_output_store
    "SubagentOutput",
    "SubagentOutputStore",
]
