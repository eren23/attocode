"""Agent module - orchestration and execution."""

from attocode.agent.agent import ProductionAgent
from attocode.agent.builder import AgentBuilder
from attocode.agent.context import AgentContext
from attocode.agent.feature_initializer import (
    FeatureConfig,
    get_feature_summary,
    initialize_features,
)
from attocode.agent.message_builder import (
    FORK_PLACEHOLDER_RESULT,
    FORK_TAG,
    build_context_attachment,
    build_forked_messages,
    build_initial_messages,
    build_system_prompt,
)
from attocode.agent.session_api import SessionAPI, SessionSnapshot, SessionSummary

__all__ = [
    "AgentBuilder",
    "AgentContext",
    "FORK_PLACEHOLDER_RESULT",
    "FORK_TAG",
    "FeatureConfig",
    "ProductionAgent",
    "SessionAPI",
    "SessionSnapshot",
    "SessionSummary",
    "build_context_attachment",
    "build_forked_messages",
    "build_initial_messages",
    "build_system_prompt",
    "get_feature_summary",
    "initialize_features",
]
