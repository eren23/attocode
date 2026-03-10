"""Shared state modules for cross-agent coordination.

Provides shared context, economics, and budget tracking for swarm workers.
"""

from attocode.shared.budget_tracker import (
    WorkerBudgetCheckResult,
    WorkerBudgetConfig,
    WorkerBudgetTracker,
)
from attocode.shared.context_engine import (
    SharedContextEngine,
    SharedContextEngineConfig,
    WorkerTask,
)
from attocode.shared.persistence import (
    JSONFilePersistenceAdapter,
    PersistenceAdapter,
    SQLitePersistenceAdapter,
)
from attocode.shared.shared_context_state import SharedContextConfig, SharedContextState
from attocode.shared.shared_economics_state import SharedEconomicsConfig, SharedEconomicsState

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
