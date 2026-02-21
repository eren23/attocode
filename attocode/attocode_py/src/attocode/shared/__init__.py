"""Shared state modules for cross-agent coordination.

Provides shared context, economics, and budget tracking for swarm workers.
"""

from attocode.shared.shared_context_state import SharedContextState, SharedContextConfig
from attocode.shared.shared_economics_state import SharedEconomicsState, SharedEconomicsConfig
from attocode.shared.budget_tracker import WorkerBudgetTracker, WorkerBudgetConfig, WorkerBudgetCheckResult
from attocode.shared.context_engine import SharedContextEngine, SharedContextEngineConfig, WorkerTask
from attocode.shared.persistence import (
    PersistenceAdapter,
    JSONFilePersistenceAdapter,
    SQLitePersistenceAdapter,
)

__all__ = [
    "SharedContextState",
    "SharedContextConfig",
    "SharedEconomicsState",
    "SharedEconomicsConfig",
    "WorkerBudgetTracker",
    "WorkerBudgetConfig",
    "WorkerBudgetCheckResult",
    "SharedContextEngine",
    "SharedContextEngineConfig",
    "WorkerTask",
    "PersistenceAdapter",
    "JSONFilePersistenceAdapter",
    "SQLitePersistenceAdapter",
]
