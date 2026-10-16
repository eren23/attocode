"""Symbol storage — content-addressed symbol indexing with branch resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession


class SymbolStore:
    """Content-addressed symbol storage.

    Symbols are keyed by content SHA, so identical files share symbol data.
    Branch-aware queries resolve through BranchOverlay.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def has_symbols(self, content_sha: str) -> bool:
        """Check if symbols already exist for a content SHA. Used for dedup gating."""
        from sqlalchemy import select

        from attocode_intel.db.models import Symbol

        result = await self._session.execute(
            select(Symbol.id).where(Symbol.content_sha == content_sha).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def upsert_symbols(
        self,
        content_sha: str,
        symbols: list[dict],
        skip_if_exists: bool = False,
    ) -> int:
        """Insert or update symbols for a content hash.

        Each symbol dict should have: name, kind, line_start, line_end,
        signature (optional), exported (optional).

        If skip_if_exists=True, returns 0 immediately when SHA already has symbols.
        This is the content-hash dedup optimization — same content always produces
        the same symbols.

        Returns count of symbols stored.
        """
        from attocode_intel.db.models import Symbol

        if skip_if_exists and await self.has_symbols(content_sha):
            return 0

        # Bulk DELETE — O(N) individual ORM deletes are too slow here.
        from sqlalchemy import delete
        await self._session.execute(
            delete(Symbol).where(Symbol.content_sha == content_sha)
        )

        # Insert new
        for s in symbols:
            sym = Symbol(
                content_sha=content_sha,
                name=s["name"],
                kind=s["kind"],
                line_start=s.get("line_start"),
                line_end=s.get("line_end"),
                signature=s.get("signature"),
                exported=s.get("exported", False),
                metadata_=s.get("metadata", {}),
            )
            self._session.add(sym)

        await self._session.flush()
        return len(symbols)

    async def replace_references(self, content_sha: str, references: list[dict]) -> int:
        """Atomically replace one content's references, including an empty result.

        Reindexing repairs old duplicates instead of appending another copy.
        Lock the parent content row so PostgreSQL writers on different branches
        cannot interleave replacements for shared content. A failed flush rolls
        back this savepoint, preserving the previous complete reference set.
        The caller owns the outer transaction and its commit.
        """
        from sqlalchemy import delete, select

        from attocode_intel.db.models import FileContent, SymbolReference

        rows = [SymbolReference(
            content_sha=content_sha,
            symbol_name=ref["symbol_name"],
            ref_kind=ref["ref_kind"],
            line=ref["line"],
            caller_qualified_name=ref.get("caller_qualified_name", ""),
        ) for ref in references]
        async with self._session.begin_nested():
            # PostgreSQL FOR NO KEY UPDATE serializes replacements while
            # remaining compatible with foreign-key readers' KEY SHARE locks.
            parent = await self._session.execute(
                select(FileContent.sha256).where(FileContent.sha256 == content_sha)
                .with_for_update(key_share=True)
            )
            if parent.scalar_one_or_none() is None:
                raise ValueError("Store file content before replacing its references")
            await self._session.execute(delete(SymbolReference).where(SymbolReference.content_sha == content_sha))
            self._session.add_all(rows)
            await self._session.flush()
        return len(rows)

    async def search_symbols(
        self,
        repo_id: uuid.UUID,
        branch_id: uuid.UUID,
        pattern: str,
        limit: int = 50,
    ) -> list[dict]:
        """Search symbols by name pattern within a branch context.

        Resolves through the branch overlay to find relevant content SHAs.
        """
        from sqlalchemy import select

        from attocode_intel.db.models import Symbol
        from attocode_intel.storage.branch_overlay import BranchOverlay

        overlay = BranchOverlay(self._session)
        manifest = await overlay.resolve_manifest(branch_id)
        content_shas = set(manifest.values())

        if not content_shas:
            return []

        result = await self._session.execute(
            select(Symbol)
            .where(
                Symbol.content_sha.in_(content_shas),
                Symbol.name.ilike(f"%{pattern}%"),
            )
            .limit(limit)
        )

        # Build reverse map: sha → path
        sha_to_path = {sha: path for path, sha in manifest.items()}

        symbols = []
        for sym in result.scalars():
            symbols.append({
                "name": sym.name,
                "kind": sym.kind,
                "file": sha_to_path.get(sym.content_sha, "unknown"),
                "line_start": sym.line_start,
                "line_end": sym.line_end,
                "signature": sym.signature,
                "exported": sym.exported,
            })
        return symbols

    async def get_symbols_for_branch(
        self,
        branch_id: uuid.UUID,
    ) -> list[dict]:
        """Get all symbols for a branch, resolved through overlay."""
        from sqlalchemy import select

        from attocode_intel.db.models import Symbol
        from attocode_intel.storage.branch_overlay import BranchOverlay

        overlay = BranchOverlay(self._session)
        manifest = await overlay.resolve_manifest(branch_id)
        content_shas = set(manifest.values())

        if not content_shas:
            return []

        sha_to_path = {sha: path for path, sha in manifest.items()}

        result = await self._session.execute(
            select(Symbol).where(Symbol.content_sha.in_(content_shas))
        )

        symbols = []
        for sym in result.scalars():
            symbols.append({
                "name": sym.name,
                "kind": sym.kind,
                "file": sha_to_path.get(sym.content_sha, "unknown"),
                "line_start": sym.line_start,
                "line_end": sym.line_end,
                "signature": sym.signature,
                "exported": sym.exported,
            })
        return symbols
