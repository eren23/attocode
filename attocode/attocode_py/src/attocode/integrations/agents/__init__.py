"""Agent management: registry, blackboard, delegation, synthesis, coordination."""

from attocode.integrations.agents.blackboard import (
    BlackboardEntry,
    BlackboardMetrics,
    NamespaceMetrics,
    SharedBlackboard,
    Subscriber,
)
from attocode.integrations.agents.registry import AgentDefinition, AgentRegistry, BUILTIN_AGENTS
from attocode.integrations.agents.delegation import (
    DelegationProtocol,
    DelegationRequest,
    DelegationResult,
    DelegationStatus,
)
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
from attocode.integrations.agents.multi_agent import (
    AgentRole,
    AgentTaskResult,
    CoordinationEvent,
    CoordinationEventType,
    ConsensusStrategy,
    Decision,
    MultiAgentCoordinator,
    TeamResult,
    CODER_ROLE,
    REVIEWER_ROLE,
    ARCHITECT_ROLE,
    RESEARCHER_ROLE,
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
    # multi_agent
    "AgentRole",
    "AgentTaskResult",
    "CoordinationEvent",
    "CoordinationEventType",
    "ConsensusStrategy",
    "Decision",
    "MultiAgentCoordinator",
    "TeamResult",
    "CODER_ROLE",
    "REVIEWER_ROLE",
    "ARCHITECT_ROLE",
    "RESEARCHER_ROLE",
]
