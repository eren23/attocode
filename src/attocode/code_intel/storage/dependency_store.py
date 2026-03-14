"""Dependency storage — file-level dependency graph."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class DependencyStore:
    """Content-addressed dependency storage.

    Dependencies are between content SHAs, enabling deduplication.
    Branch-aware queries resolve through BranchOverlay.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def has_dependencies(self, source_sha: str) -> bool:
        """Check if dependencies already exist for a source SHA."""
        from sqlalchemy import func, select

        from attocode.code_intel.db.models import Dependency

        result = await self._session.execute(
            select(func.count()).where(Dependency.source_sha == source_sha)
        )
        return (result.scalar() or 0) > 0

    async def upsert_dependencies(
        self,
        source_sha: str,
        dependencies: list[dict],
    ) -> int:
        """Store dependencies from a source file.

        Each dependency dict: {target_sha, dep_type, weight?, metadata?}
        """
        from sqlalchemy import delete

        from attocode.code_intel.db.models import Dependency
        await self._session.execute(
            delete(Dependency).where(Dependency.source_sha == source_sha)
        )

        # Insert new
        for d in dependencies:
            dep = Dependency(
                source_sha=source_sha,
                target_sha=d["target_sha"],
                dep_type=d.get("dep_type", "imports"),
                weight=d.get("weight", 1.0),
                metadata_=d.get("metadata", {}),
            )
            self._session.add(dep)

        await self._session.flush()
        return len(dependencies)

    async def get_forward(
        self,
        content_sha: str,
    ) -> list[dict]:
        """Get dependencies FROM a file (what it imports)."""
        from sqlalchemy import select

        from attocode.code_intel.db.models import Dependency

        result = await self._session.execute(
            select(Dependency).where(Dependency.source_sha == content_sha)
        )
        return [
            {
                "target_sha": d.target_sha,
                "dep_type": d.dep_type,
                "weight": d.weight,
            }
            for d in result.scalars()
        ]

    async def get_reverse(
        self,
        content_sha: str,
    ) -> list[dict]:
        """Get reverse dependencies TO a file (what imports it)."""
        from sqlalchemy import select

        from attocode.code_intel.db.models import Dependency

        result = await self._session.execute(
            select(Dependency).where(Dependency.target_sha == content_sha)
        )
        return [
            {
                "source_sha": d.source_sha,
                "dep_type": d.dep_type,
                "weight": d.weight,
            }
            for d in result.scalars()
        ]

    async def get_graph_for_branch(
        self,
        branch_id: uuid.UUID,
    ) -> dict:
        """Build the full dependency graph for a branch.

        Returns {nodes: [...], edges: [...]} resolved through overlay.
        """
        from sqlalchemy import select

        from attocode.code_intel.db.models import Dependency
        from attocode.code_intel.storage.branch_overlay import BranchOverlay

        overlay = BranchOverlay(self._session)
        manifest = await overlay.resolve_manifest(branch_id)
        content_shas = set(manifest.values())
        sha_to_path = {sha: path for path, sha in manifest.items()}

        if not content_shas:
            return {"nodes": [], "edges": []}

        result = await self._session.execute(
            select(Dependency).where(
                Dependency.source_sha.in_(content_shas),
                Dependency.target_sha.in_(content_shas),
            )
        )

        nodes = [{"path": path, "sha": sha} for path, sha in manifest.items()]
        edges = []
        for dep in result.scalars():
            edges.append({
                "source": sha_to_path.get(dep.source_sha, dep.source_sha),
                "target": sha_to_path.get(dep.target_sha, dep.target_sha),
                "type": dep.dep_type,
                "weight": dep.weight,
            })

        return {"nodes": nodes, "edges": edges}
