"""Security compliance scanning integrations."""

from attocode.integrations.security.scanner import (
    SecurityFinding,
    SecurityReport,
    SecurityScanner,
)
from attocode.integrations.security.patterns import (
    ANTI_PATTERNS,
    SECRET_PATTERNS,
    Category,
    SecurityPattern,
    Severity,
)
from attocode.integrations.security.dependency_audit import (
    DependencyAuditor,
    DependencyFinding,
)

__all__ = [
    "SecurityFinding",
    "SecurityReport",
    "SecurityScanner",
    "ANTI_PATTERNS",
    "Category",
    "SECRET_PATTERNS",
    "SecurityPattern",
    "Severity",
    "DependencyAuditor",
    "DependencyFinding",
]
