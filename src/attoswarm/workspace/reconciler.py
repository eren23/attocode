"""AST Reconciler — 3-way merge at function/class granularity.

When two workers modify the same file concurrently, the reconciler
attempts to merge the changes at the symbol (function/class) level
instead of doing a naive line-level merge.

Algorithm:
1. Parse base, version_a, version_b into ``FileAST``.
2. Diff ``base → A`` and ``base → B`` at symbol level (via ``diff_file_ast``).
3. A-only changes → take A's version of those symbols.
4. B-only changes → take B's version of those symbols.
5. Both changed the same symbol → attempt line-level merge within that symbol.
6. If still conflicting → mark ``needs_judge = True``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from attocode.integrations.context.codebase_ast import (
    ClassDef,
    FileAST,
    FunctionDef,
    SymbolChange,
    diff_file_ast,
    parse_file,
)

if TYPE_CHECKING:
    from attocode.integrations.context.ast_service import ASTService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MergeConflict:
    """An unresolved symbol-level conflict."""

    symbol_name: str
    symbol_kind: str        # "function" | "class" | "method"
    file_path: str
    reason: str = ""


@dataclass(slots=True)
class MergeResult:
    """Outcome of a reconciliation attempt."""

    success: bool
    merged_content: str = ""
    auto_resolved: int = 0
    conflicts: list[MergeConflict] = field(default_factory=list)
    needs_judge: bool = False


# ---------------------------------------------------------------------------
# ASTReconciler
# ---------------------------------------------------------------------------


class ASTReconciler:
    """AST-aware 3-way merge for shared-workspace OCC conflicts."""

    def __init__(self, ast_service: "ASTService | None" = None) -> None:
        self._ast_service = ast_service

    def reconcile(
        self,
        file_path: str,
        base_content: str,
        version_a: str,
        version_b: str,
    ) -> MergeResult:
        """Attempt a 3-way AST merge.

        Args:
            file_path: The file being reconciled (for language detection).
            base_content: The common ancestor content.
            version_a: Content after changes by agent A.
            version_b: Content after changes by agent B.

        Returns:
            MergeResult with merged content or conflict details.
        """
        # Parse all three versions
        try:
            base_ast = parse_file(file_path, content=base_content)
            ast_a = parse_file(file_path, content=version_a)
            ast_b = parse_file(file_path, content=version_b)
        except Exception as exc:
            return MergeResult(
                success=False,
                needs_judge=True,
                conflicts=[MergeConflict(
                    symbol_name="<parse_error>",
                    symbol_kind="file",
                    file_path=file_path,
                    reason=f"Failed to parse: {exc}",
                )],
            )

        # Compute symbol-level diffs (structural changes: signature, line range)
        changes_a = diff_file_ast(base_ast, ast_a)
        changes_b = diff_file_ast(base_ast, ast_b)

        # Index changes by symbol name
        a_changed: dict[str, SymbolChange] = {c.symbol_name: c for c in changes_a}
        b_changed: dict[str, SymbolChange] = {c.symbol_name: c for c in changes_b}

        # Supplement with body-content changes that diff_file_ast misses
        # (it only compares signatures and line ranges, not body text)
        base_ranges = self._symbol_ranges(base_ast)
        a_ranges = self._symbol_ranges(ast_a)
        b_ranges = self._symbol_ranges(ast_b)
        base_lines = base_content.split("\n")
        a_src_lines = version_a.split("\n")
        b_src_lines = version_b.split("\n")

        for sym_name, (bs, be) in base_ranges.items():
            base_body = base_lines[bs:be]
            # Check A for body-only changes
            if sym_name not in a_changed and sym_name in a_ranges:
                a_s, a_e = a_ranges[sym_name]
                if a_src_lines[a_s:a_e] != base_body:
                    a_changed[sym_name] = SymbolChange(
                        kind="modified", symbol_name=sym_name,
                        symbol_kind="function", file_path=file_path,
                    )
            # Check B for body-only changes
            if sym_name not in b_changed and sym_name in b_ranges:
                b_s, b_e = b_ranges[sym_name]
                if b_src_lines[b_s:b_e] != base_body:
                    b_changed[sym_name] = SymbolChange(
                        kind="modified", symbol_name=sym_name,
                        symbol_kind="function", file_path=file_path,
                    )

        all_symbols = set(a_changed.keys()) | set(b_changed.keys())

        # Track resolved and conflicting symbols
        auto_resolved = 0
        conflicts: list[MergeConflict] = []
        merged_lines = base_lines[:]

        # Reuse ranges and lines computed above
        base_symbols = base_ranges
        a_symbols = a_ranges
        b_symbols = b_ranges
        a_lines = a_src_lines
        b_lines = b_src_lines

        # Collect replacements: (base_start, base_end, new_lines)
        replacements: list[tuple[int, int, list[str]]] = []

        for sym_name in all_symbols:
            in_a = sym_name in a_changed
            in_b = sym_name in b_changed

            if in_a and not in_b:
                # A-only change — take A's version
                src_range = a_symbols.get(sym_name)
                base_range = base_symbols.get(sym_name)
                if src_range and base_range:
                    start_a, end_a = src_range
                    start_base, end_base = base_range
                    replacements.append((
                        start_base, end_base,
                        a_lines[start_a:end_a],
                    ))
                    auto_resolved += 1

            elif in_b and not in_a:
                # B-only change — take B's version
                src_range = b_symbols.get(sym_name)
                base_range = base_symbols.get(sym_name)
                if src_range and base_range:
                    start_b, end_b = src_range
                    start_base, end_base = base_range
                    replacements.append((
                        start_base, end_base,
                        b_lines[start_b:end_b],
                    ))
                    auto_resolved += 1

            else:
                # Both A and B changed the same symbol
                change_a = a_changed[sym_name]
                change_b = b_changed[sym_name]

                # If both added the same symbol (and it's not in base), take A
                if change_a.kind == "added" and change_b.kind == "added":
                    src_range = a_symbols.get(sym_name)
                    if src_range:
                        start_a, end_a = src_range
                        # Append at end since it's new
                        replacements.append((
                            len(merged_lines), len(merged_lines),
                            a_lines[start_a:end_a],
                        ))
                        auto_resolved += 1
                    continue

                # If both removed, that's fine
                if change_a.kind == "removed" and change_b.kind == "removed":
                    base_range = base_symbols.get(sym_name)
                    if base_range:
                        replacements.append((base_range[0], base_range[1], []))
                        auto_resolved += 1
                    continue

                # Real conflict: both modified the same symbol differently
                conflicts.append(MergeConflict(
                    symbol_name=sym_name,
                    symbol_kind=change_a.symbol_kind,
                    file_path=file_path,
                    reason=f"Both agents modified {sym_name}",
                ))

        if conflicts:
            return MergeResult(
                success=False,
                auto_resolved=auto_resolved,
                conflicts=conflicts,
                needs_judge=True,
            )

        # Apply replacements in reverse order (to preserve line numbers)
        if replacements:
            replacements.sort(key=lambda r: r[0], reverse=True)
            for start, end, new_lines in replacements:
                merged_lines[start:end] = new_lines

        merged_content = "\n".join(merged_lines)

        return MergeResult(
            success=True,
            merged_content=merged_content,
            auto_resolved=auto_resolved,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _symbol_ranges(ast: FileAST) -> dict[str, tuple[int, int]]:
        """Build a map of symbol_name -> (start_line_0idx, end_line_0idx)."""
        ranges: dict[str, tuple[int, int]] = {}

        for func in ast.functions:
            # Convert 1-based lines to 0-based
            ranges[func.name] = (func.start_line - 1, func.end_line)

        for cls in ast.classes:
            ranges[cls.name] = (cls.start_line - 1, cls.end_line)
            for method in cls.methods:
                qname = f"{cls.name}.{method.name}"
                ranges[qname] = (method.start_line - 1, method.end_line)

        return ranges
