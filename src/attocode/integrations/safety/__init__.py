"""Safety integrations."""

from attocode.integrations.safety.bash_policy import (
    CommandClassification,
    CommandRisk,
    classify_command,
    extract_command_name,
)
from attocode.integrations.safety.edit_validator import (
    EditValidator,
    ValidationResult,
)
from attocode.integrations.safety.policy_engine import (
    PROTECTED_PATHS,
    DangerLevel,
    PolicyDecision,
    PolicyEngine,
    PolicyResult,
    PolicyRule,
    is_protected_path,
)

__all__ = [
    "CommandClassification",
    "CommandRisk",
    "DangerLevel",
    "PolicyDecision",
    "PolicyEngine",
    "PolicyResult",
    "PolicyRule",
    "PROTECTED_PATHS",
    "classify_command",
    "is_protected_path",
    "extract_command_name",
    # edit_validator
    "EditValidator",
    "ValidationResult",
]
