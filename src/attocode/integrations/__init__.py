"""Attocode integrations.

Each subdirectory is an independent integration domain with its own barrel.
"""

# Re-export security barrel for convenience
from attocode.integrations.security import (  # noqa: F401
    SecurityFinding,
    SecurityReport,
    SecurityScanner,
)

