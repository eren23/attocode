"""TUI dialogs."""

from attocode.tui.dialogs.approval import ApprovalDialog, ApprovalResult
from attocode.tui.dialogs.budget import BudgetDialog
from attocode.tui.dialogs.setup import ApiKeyDialog, SetupResult, SetupWizard
from attocode.tui.dialogs.learning_validation import (
    LearningProposal,
    LearningValidationDialog,
)

__all__ = [
    "ApiKeyDialog",
    "ApprovalDialog",
    "ApprovalResult",
    "BudgetDialog",
    "SetupResult",
    "SetupWizard",
    # learning_validation
    "LearningProposal",
    "LearningValidationDialog",
]
