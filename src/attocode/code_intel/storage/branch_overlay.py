"""Branch overlay model — multi-branch indexing with parent chain resolution."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class BranchOverlay:
    """Manages branch-level file overlays on top of a default branch.

    Resolution algorithm:
    1. Load default branch manifest (all file paths → content SHAs)
    2. Walk from target branch → parent → default via parent_branch_id chain
    3. Apply overlays in order: default → intermediate → target
    4. Additions/modifications replace entries; deletions remove them
    5. Result: complete dict[str, str] (path → content_sha)

    Branch version is incremented on every write for consistency tracking.
    Clients can pass If-Match headers with branch version for strict consistency.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _bump_version(self, branch_id: uuid.UUID) -> int:
        """Increment branch version counter. Returns new version.

        M10 fix: Raises clear ValueError if branch_id doesn't exist.
        """
        from sqlalchemy import update

        from attocode.code_intel.db.models import Branch

        result = await self._session.execute(
            update(Branch)
            .where(Branch.id == branch_id)
            .values(version=Branch.version + 1)
            .returning(Branch.version)
        )
        new_version = result.scalar_one_or_none()
        if new_version is None:
            raise ValueError(f"Branch not found: {branch_id}")
        return new_version

    async def get_version(self, branch_id: uuid.UUID) -> int:
        """Get current branch version for consistency checks."""
        from sqlalchemy import select

        from attocode.code_intel.db.models import Branch

        result = await self._session.execute(
            select(Branch.version).where(Branch.id == branch_id)
        )
        return result.scalar_one_or_none() or 0

    async def check_version(self, branch_id: uuid.UUID, expected: int) -> None:
        """Verify branch version matches expected. Raises ValueError on mismatch.

        Used for If-Match optimistic concurrency control.
        """
        current = await self.get_version(branch_id)
        if current != expected:
            raise ValueError(
                f"Branch version mismatch: expected {expected}, current {current}. "
                "Another update occurred — retry with the latest version."
            )

    async def set_file(
        self,
        branch_id: uuid.UUID,
        path: str,
        content_sha: str,
        status: str = "modified",
    ) -> None:
        """Set a file in the branch overlay. Bumps branch version."""
        from sqlalchemy import select

        from attocode.code_intel.db.models import BranchFile

        result = await self._session.execute(
            select(BranchFile).where(
                BranchFile.branch_id == branch_id,
                BranchFile.path == path,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.content_sha = content_sha
            existing.status = status
        else:
            bf = BranchFile(
                branch_id=branch_id,
                path=path,
                content_sha=content_sha,
                status=status,
            )
            self._session.add(bf)

        await self._bump_version(branch_id)
        await self._session.flush()

    async def set_files_batch(
        self,
        branch_id: uuid.UUID,
        files: list[tuple[str, str, str]],
        expected_version: int | None = None,
    ) -> None:
        """Set multiple files in one operation. Each tuple: (path, content_sha, status).

        Single version bump for the batch.
        """
        from sqlalchemy import select

        from attocode.code_intel.db.models import BranchFile

        if not files:
            return

        if expected_version is not None:
            await self.check_version(branch_id, expected_version)

        # Load existing entries for these paths in one query
        paths = [f[0] for f in files]
        result = await self._session.execute(
            select(BranchFile).where(
                BranchFile.branch_id == branch_id,
                BranchFile.path.in_(paths),
            )
        )
        existing_map = {bf.path: bf for bf in result.scalars()}

        for path, content_sha, status in files:
            if path in existing_map:
                existing_map[path].content_sha = content_sha
                existing_map[path].status = status
            else:
                bf = BranchFile(
                    branch_id=branch_id,
                    path=path,
                    content_sha=content_sha,
                    status=status,
                )
                self._session.add(bf)

        await self._bump_version(branch_id)
        await self._session.flush()

    async def delete_file(self, branch_id: uuid.UUID, path: str) -> None:
        """Mark a file as deleted in the branch overlay. Bumps branch version."""
        from sqlalchemy import select

        from attocode.code_intel.db.models import BranchFile

        result = await self._session.execute(
            select(BranchFile).where(
                BranchFile.branch_id == branch_id,
                BranchFile.path == path,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.content_sha = None
            existing.status = "deleted"
        else:
            bf = BranchFile(
                branch_id=branch_id,
                path=path,
                content_sha=None,
                status="deleted",
            )
            self._session.add(bf)

        await self._bump_version(branch_id)
        await self._session.flush()

    async def resolve_file(
        self,
        branch_id: uuid.UUID,
        path: str,
    ) -> str | None:
        """Resolve a single file through the overlay chain.

        Returns the content_sha or None if file doesn't exist.
        """
        manifest = await self.resolve_manifest(branch_id)
        return manifest.get(path)

    async def resolve_manifest(
        self,
        branch_id: uuid.UUID,
    ) -> dict[str, str]:
        """Resolve the complete file manifest for a branch.

        Walks the overlay chain from default → intermediate → target branch.
        C3 fix: Uses visited set to detect and break cyclic parent_branch_id chains.
        """
        from sqlalchemy import select

        from attocode.code_intel.db.models import Branch, BranchFile

        # Build the chain from target to default
        chain: list[uuid.UUID] = []
        visited: set[uuid.UUID] = set()
        current_id: uuid.UUID | None = branch_id

        while current_id is not None:
            if current_id in visited:
                logger.warning(
                    "Cyclic parent_branch_id detected at %s in chain %s — breaking",
                    current_id, [str(b) for b in chain],
                )
                break
            visited.add(current_id)
            chain.append(current_id)
            result = await self._session.execute(
                select(Branch.parent_branch_id).where(Branch.id == current_id)
            )
            parent_id = result.scalar_one_or_none()
            current_id = parent_id

        # Reverse: default first, target last
        chain.reverse()

        # Build manifest by applying overlays in order
        manifest: dict[str, str] = {}

        for bid in chain:
            result = await self._session.execute(
                select(BranchFile).where(BranchFile.branch_id == bid)
            )
            for bf in result.scalars():
                if bf.status == "deleted":
                    manifest.pop(bf.path, None)
                elif bf.content_sha:
                    manifest[bf.path] = bf.content_sha

        return manifest

    async def diff_branches(
        self,
        branch_a_id: uuid.UUID,
        branch_b_id: uuid.UUID,
    ) -> dict[str, str]:
        """Compare two branches. Returns dict of path → change_type.

        change_type: added|modified|deleted
        """
        manifest_a = await self.resolve_manifest(branch_a_id)
        manifest_b = await self.resolve_manifest(branch_b_id)

        diff: dict[str, str] = {}
        all_paths = set(manifest_a.keys()) | set(manifest_b.keys())

        for path in all_paths:
            sha_a = manifest_a.get(path)
            sha_b = manifest_b.get(path)

            if sha_a is None and sha_b is not None:
                diff[path] = "added"
            elif sha_a is not None and sha_b is None:
                diff[path] = "deleted"
            elif sha_a != sha_b:
                diff[path] = "modified"

        return diff

    async def merge_branch(
        self,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        *,
        delete_source: bool = False,
    ) -> dict:
        """Merge source branch overlay into target branch.

        Resolves both manifests, computes the diff, and applies source changes
        to the target overlay. Optionally deletes the source branch after merge.

        Returns merge statistics.
        """
        from datetime import datetime, timezone

        from sqlalchemy import select

        from attocode.code_intel.db.models import Branch

        diff = await self.diff_branches(target_id, source_id)

        # Apply source changes to target overlay
        files_to_set: list[tuple[str, str, str]] = []
        source_manifest = await self.resolve_manifest(source_id)
        deleted = 0

        for path, change_type in diff.items():
            if change_type == "added":
                sha = source_manifest.get(path)
                if sha:
                    files_to_set.append((path, sha, "added"))
            elif change_type == "modified":
                sha = source_manifest.get(path)
                if sha:
                    files_to_set.append((path, sha, "modified"))
            elif change_type == "deleted":
                await self.delete_file(target_id, path)
                deleted += 1

        if files_to_set:
            await self.set_files_batch(target_id, files_to_set)

        stats = {
            "added": sum(1 for _, _, s in files_to_set if s == "added"),
            "modified": sum(1 for _, _, s in files_to_set if s == "modified"),
            "deleted": deleted,
            "total": len(diff),
        }

        if delete_source:
            # Mark source as merged and delete
            result = await self._session.execute(
                select(Branch).where(Branch.id == source_id)
            )
            source_branch = result.scalar_one_or_none()
            if source_branch:
                source_branch.merged_at = datetime.now(timezone.utc)
                await self._session.delete(source_branch)
                await self._session.flush()

        return stats

    async def get_overlay_stats(self, branch_id: uuid.UUID) -> dict:
        """Get statistics about a branch's overlay (files added/modified/deleted)."""
        from sqlalchemy import func, select

        from attocode.code_intel.db.models import BranchFile

        result = await self._session.execute(
            select(BranchFile.status, func.count())
            .where(BranchFile.branch_id == branch_id)
            .group_by(BranchFile.status)
        )
        stats = {"added": 0, "modified": 0, "deleted": 0, "total": 0}
        for status, count in result:
            stats[status] = count
            stats["total"] += count
        return stats
