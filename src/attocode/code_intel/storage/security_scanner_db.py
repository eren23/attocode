"""DB-backed security scanning — runs regex patterns on ContentStore content.

For remote repos without a local clone, this provides security scanning
by reading file content from the database and applying the same patterns
used by the local scanner.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from attocode.integrations.security.matcher import iter_pattern_matches

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Scannable file extensions (same as local scanner)
_SCANNABLE_EXTENSIONS = {
    ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".rs", ".go", ".java", ".kt", ".rb", ".php", ".swift", ".cs",
    ".c", ".cpp", ".h", ".hpp", ".lua", ".sh", ".bash", ".zsh",
    ".yaml", ".yml", ".toml", ".json", ".env", ".cfg", ".ini", ".conf",
}

# Max file size to scan (200KB)
_MAX_SCAN_SIZE = 200 * 1024

# Max files to scan per run
_MAX_SCAN_FILES = 500


def _detect_language(path: str) -> str:
    """Detect language from file extension."""
    import os
    ext = os.path.splitext(path)[1].lower()
    lang_map = {
        ".py": "python", ".pyi": "python",
        ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
        ".ts": "typescript", ".tsx": "typescript",
        ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin",
        ".rb": "ruby", ".php": "php", ".swift": "swift", ".cs": "csharp",
        ".c": "c", ".cpp": "cpp", ".h": "c", ".hpp": "cpp",
    }
    return lang_map.get(ext, "")


def _is_scannable(path: str) -> bool:
    """Check if a file path is scannable by extension or filename."""
    import os
    basename = os.path.basename(path)
    ext = os.path.splitext(path)[1].lower()
    # Handle dotfiles like .env (ext is ".env", basename is ".env")
    if not ext and basename.startswith("."):
        ext = basename.lower()
    return ext in _SCANNABLE_EXTENSIONS


async def db_security_scan(
    session: AsyncSession,
    branch_id: uuid.UUID,
    manifest: dict[str, str],
    *,
    mode: str = "full",
    path_filter: str = "",
) -> dict:
    """Run security scan on DB-stored file contents.

    Args:
        session: Async DB session.
        branch_id: Branch UUID for scoping.
        manifest: Resolved manifest (path → content_sha).
        mode: Scan mode — "quick" (secrets only), "full" (secrets + patterns),
              "secrets", "patterns".
        path_filter: Optional path prefix filter.

    Returns:
        Dict with findings, total_findings, summary.
    """
    from attocode.code_intel.storage.content_store import ContentStore

    # Import patterns
    from attocode.integrations.security.patterns import (
        ANTI_PATTERNS,
        SECRET_PATTERNS,
        Category,
    )

    content_store = ContentStore(session)

    # Select which patterns to use based on mode
    patterns = []
    if mode in ("full", "quick", "secrets"):
        patterns.extend(SECRET_PATTERNS)
    if mode in ("full", "patterns"):
        patterns.extend(ANTI_PATTERNS)

    # Filter and limit files
    scannable: list[tuple[str, str]] = []  # (path, sha)
    for path, sha in sorted(manifest.items()):
        if path_filter and not path.startswith(path_filter):
            continue
        if not _is_scannable(path):
            continue
        scannable.append((path, sha))
        if len(scannable) >= _MAX_SCAN_FILES:
            break

    findings: list[dict] = []
    files_scanned = 0
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}

    for path, sha in scannable:
        content_bytes = await content_store.get(sha)
        if content_bytes is None:
            continue
        if len(content_bytes) > _MAX_SCAN_SIZE:
            continue

        try:
            text = content_bytes.decode("utf-8", errors="replace")
        except Exception:
            continue

        files_scanned += 1
        file_lang = _detect_language(path)

        for line_no, line, pat in iter_pattern_matches(text, patterns, file_lang):
            sev = str(pat.severity)
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
            findings.append({
                "pattern": pat.name,
                "severity": sev,
                "category": str(pat.category),
                "cwe_id": pat.cwe_id,
                "file": path,
                "line": line_no,
                "message": pat.message,
                "recommendation": pat.recommendation,
                "snippet": line.strip()[:200],
            })

    # Compute compliance score
    score = 100 - (
        severity_counts.get("critical", 0) * 20
        + severity_counts.get("high", 0) * 10
        + severity_counts.get("medium", 0) * 3
        + severity_counts.get("low", 0) * 1
    )
    score = max(0, min(100, score))

    return {
        "mode": mode,
        "path": path_filter,
        "findings": findings,
        "total_findings": len(findings),
        "summary": {
            "files_scanned": files_scanned,
            "compliance_score": score,
            **severity_counts,
        },
    }
