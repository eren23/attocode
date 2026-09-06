"""Heuristic code-to-natural-language summarizer for embedding enrichment.

Generates natural language summaries of code chunks so that embedding models
produce vectors closer to how developers describe code in natural language
queries. The original code text is still stored for display — only the
embedding input changes.

No LLM is needed. All summaries are deterministic and fast (pure string
manipulation + lightweight regex parsing).
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class CodeSummarizer:
    """Generate natural language summaries of code chunks for better semantic search."""

    def summarize(
        self,
        chunk_text: str,
        chunk_type: str,
        name: str,
        language: str,
    ) -> str:
        """Create a natural language summary of a code chunk.

        The returned string is *not* meant for display — it feeds the
        embedding model.  It combines a readable NL description with key
        identifiers so the resulting vector captures both semantic meaning
        and exact-match ability.

        Args:
            chunk_text: The code / structured text of the chunk (as produced
                by ``_chunk_single_file``).
            chunk_type: One of ``"function"``, ``"class"``, ``"method"``,
                ``"file"``.
            name: Symbol or file name (e.g. ``"parse_config"`` or
                ``"src/utils.py"``).
            language: Programming language (e.g. ``"python"``).

        Returns:
            A combined string:  NL summary + ``"\\n"`` + key identifiers.
        """
        if chunk_type == "function":
            nl = self._summarize_function(chunk_text, name, language)
        elif chunk_type == "method":
            nl = self._summarize_method(chunk_text, name, language)
        elif chunk_type == "class":
            nl = self._summarize_class(chunk_text, name, language)
        elif chunk_type == "file":
            nl = self._summarize_file(chunk_text, name, language)
        else:
            nl = f"Code chunk named {name}."

        identifiers = self._extract_identifiers(chunk_text, chunk_type, name)
        if identifiers:
            return nl + "\n" + identifiers
        return nl

    # ------------------------------------------------------------------
    # Per-type summarizers
    # ------------------------------------------------------------------

    def _summarize_function(
        self, chunk_text: str, name: str, language: str,
    ) -> str:
        """Summarize a function chunk.

        Target: "Function {name} that takes {params} and returns {return_type}.
                 {docstring_first_line}"
        """
        params = self._extract_params(chunk_text)
        return_type = self._extract_field(chunk_text, "returns")
        docstring = self._extract_field(chunk_text, "docstring") or self._extract_docstring_line(chunk_text)

        parts = [f"Function {name}"]
        if params:
            parts.append(f"that takes {params}")
        if return_type:
            parts.append(f"and returns {return_type}")
        summary = " ".join(parts) + "."
        if docstring:
            summary += f" {docstring}"
        return summary

    def _summarize_method(
        self, chunk_text: str, name: str, language: str,
    ) -> str:
        """Summarize a method chunk.

        Target: "Method {class}.{method} that takes {params} and returns
                 {return_type}. {docstring_first_line}"
        """
        params = self._extract_params(chunk_text)
        return_type = self._extract_field(chunk_text, "returns")
        docstring = self._extract_field(chunk_text, "docstring") or self._extract_docstring_line(chunk_text)

        parts = [f"Method {name}"]
        if params:
            parts.append(f"that takes {params}")
        if return_type:
            parts.append(f"and returns {return_type}")
        summary = " ".join(parts) + "."
        if docstring:
            summary += f" {docstring}"
        return summary

    def _summarize_class(
        self, chunk_text: str, name: str, language: str,
    ) -> str:
        """Summarize a class chunk.

        Target: "Class {name} extending {bases} with methods {method_names}.
                 {docstring_first_line}"
        """
        bases = self._extract_field(chunk_text, "extends")
        methods = self._extract_field(chunk_text, "methods")
        docstring = self._extract_field(chunk_text, "docstring") or self._extract_docstring_line(chunk_text)

        parts = [f"Class {name}"]
        if bases:
            parts.append(f"extending {bases}")
        if methods:
            parts.append(f"with methods {methods}")
        summary = " ".join(parts) + "."
        if docstring:
            summary += f" {docstring}"
        return summary

    def _summarize_file(
        self, chunk_text: str, name: str, language: str,
    ) -> str:
        """Summarize a file/module chunk.

        Target: "Module {name} containing {N} functions and {M} classes.
                 {module_docstring_first_line}"
        """
        defines = self._extract_field(chunk_text, "defines")
        imports = self._extract_field(chunk_text, "imports")
        docstring = self._extract_docstring_line(chunk_text)

        # Count defined symbols heuristically
        n_funcs = 0
        n_classes = 0
        if defines:
            symbols = [s.strip() for s in defines.split(",")]
            for sym in symbols:
                # Heuristic: class names start uppercase, functions lowercase/underscore
                if sym and sym[0].isupper():
                    n_classes += 1
                else:
                    n_funcs += 1

        parts = [f"Module {name}"]
        if n_funcs or n_classes:
            count_parts = []
            if n_funcs:
                count_parts.append(f"{n_funcs} function{'s' if n_funcs != 1 else ''}")
            if n_classes:
                count_parts.append(f"{n_classes} class{'es' if n_classes != 1 else ''}")
            parts.append(f"containing {' and '.join(count_parts)}")
        if imports:
            parts.append(f"importing {imports}")
        summary = " ".join(parts) + "."
        if docstring:
            summary += f" {docstring}"
        return summary

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------

    def _extract_field(self, chunk_text: str, field_name: str) -> str:
        """Extract a pipe-delimited field from chunk text.

        Chunk text from ``_chunk_single_file`` uses the format:
        ``"function foo | docstring line | params: a, b | returns: int"``

        This method extracts the value after ``"{field_name}: "`` up to the
        next pipe delimiter (or end of string).
        """
        # Try "field: value" pattern within pipe-delimited sections
        pattern = rf"(?:^|\|)\s*{re.escape(field_name)}:\s*(.+?)(?:\s*\||$)"
        m = re.search(pattern, chunk_text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return ""

    def _extract_params(self, chunk_text: str) -> str:
        """Extract parameter names from chunk text."""
        return self._extract_field(chunk_text, "params")

    def _extract_docstring_line(self, chunk_text: str) -> str:
        """Extract a docstring first line from chunk text.

        The chunk text format puts the docstring as the second
        pipe-delimited section (after the "function foo" or "class bar" label)
        if the docstring exists.

        E.g.: ``"function parse_config | Parse configuration from file | params: path"``
        """
        parts = [p.strip() for p in chunk_text.split("|")]
        if len(parts) < 2:
            return ""
        # The second part is the docstring IF it doesn't contain a "field:" pattern
        candidate = parts[1]
        if ":" in candidate:
            # Looks like a field (e.g. "params: x"), not a docstring
            # But could also be a docstring like "Parse config: the main entry"
            # Heuristic: if it starts with a known field prefix, skip it
            lower = candidate.lower().lstrip()
            for field_prefix in ("params", "returns", "extends", "methods", "imports", "defines"):
                if lower.startswith(field_prefix + ":"):
                    return ""
            # It has a colon but is not a known field — treat as docstring
        return candidate

    def _extract_identifiers(
        self, chunk_text: str, chunk_type: str, name: str,
    ) -> str:
        """Extract key identifiers for exact-match retrieval.

        Returns a space-separated string of symbol names, import modules,
        and other identifiers that should be preserved verbatim in the
        embedding input.
        """
        ids: list[str] = [name]

        # Split compound names (e.g. "ClassName.method_name")
        for part in name.replace(".", " ").replace("_", " ").split():
            if part and part not in ids:
                ids.append(part)

        # Extract identifiers from field values
        for field_name in ("params", "defines", "imports", "methods", "extends"):
            field_val = self._extract_field(chunk_text, field_name)
            if field_val:
                for token in re.split(r"[,\s]+", field_val):
                    token = token.strip()
                    if token and len(token) >= 2 and token not in ids:
                        ids.append(token)

        return " ".join(ids)


# ---------------------------------------------------------------------------
# Module-level singleton for performance
# ---------------------------------------------------------------------------

_summarizer: CodeSummarizer | None = None


def get_summarizer() -> CodeSummarizer:
    """Return a cached ``CodeSummarizer`` instance."""
    global _summarizer
    if _summarizer is None:
        _summarizer = CodeSummarizer()
    return _summarizer
