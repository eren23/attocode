"""Graph query DSL parser and executor for dependency graph queries.

Supports a simple Cypher-inspired syntax for traversing the import graph::

    MATCH "src/api/app.py" -[IMPORTS*1..3]-> target RETURN target
    MATCH file <-[IMPORTED_BY]- caller WHERE caller.language = "python" RETURN caller
    MATCH a -[IMPORTS]-> b -[IMPORTS]-> c RETURN a, c

Architecture:
- ``GraphQueryParser.parse(query) -> GraphQueryAST`` — regex tokenizer + recursive descent
- ``GraphQueryExecutor.execute(ast, dep_graph, files) -> list[dict]`` — BFS with depth constraints
"""

from __future__ import annotations

import fnmatch
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# AST dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class NodePattern:
    """A node in the MATCH pattern — either a concrete file or a variable."""

    variable: str  # Variable name (e.g. "target", "a") or empty for anonymous
    file_pattern: str | None = None  # Quoted literal path or glob (None = any file)


@dataclass(slots=True)
class EdgePattern:
    """A directed edge between two node patterns."""

    source: int  # Index into GraphQueryAST.nodes
    target: int  # Index into GraphQueryAST.nodes
    edge_type: str  # "IMPORTS" or "IMPORTED_BY"
    min_depth: int = 1  # Minimum hops
    max_depth: int = 1  # Maximum hops


@dataclass(slots=True)
class WhereClause:
    """A single WHERE filter condition: variable.field op value."""

    variable: str
    field_name: str  # "language", "line_count", "importance", "path", "fan_in", "fan_out"
    operator: str  # "=", "!=", ">", "<", ">=", "<=", "LIKE"
    value: str  # String value (numeric comparisons will be cast)


@dataclass(slots=True)
class ReturnSpec:
    """A variable (and optional field) to return."""

    variable: str
    field_name: str | None = None  # If None, return the file path


@dataclass(slots=True)
class GraphQueryAST:
    """Parsed representation of a graph DSL query."""

    nodes: list[NodePattern] = field(default_factory=list)
    edges: list[EdgePattern] = field(default_factory=list)
    where_clauses: list[WhereClause] = field(default_factory=list)
    return_specs: list[ReturnSpec] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

# Token types
_TOKEN_PATTERNS = [
    ("KEYWORD", r"\b(?:MATCH|WHERE|RETURN|AND|OR|LIKE|COUNT)\b"),
    ("EDGE_RIGHT", r"-\["),  # -[
    ("EDGE_RIGHT_CLOSE", r"\]->"),  # ]->
    ("EDGE_LEFT", r"<-\["),  # <-[
    ("EDGE_LEFT_CLOSE", r"\]-"),  # ]-
    ("RANGE", r"\*(\d+)\.\.(\d+)"),  # *1..3
    ("DEPTH_SINGLE", r"\*(\d+)"),  # *2  (single depth = min..max same)
    ("OP", r"[!><]=?|="),  # =, !=, >, <, >=, <=
    ("DOT", r"\."),
    ("COMMA", r","),
    ("QUOTED", r'"([^"]*)"'),  # "quoted string"
    ("QUOTED_SINGLE", r"'([^']*)'"),  # 'quoted string'
    ("IDENT", r"[A-Za-z_][A-Za-z0-9_]*"),
    ("NUMBER", r"\d+(?:\.\d+)?"),
    ("WS", r"\s+"),
]

_TOKEN_RE = re.compile("|".join(f"(?P<{name}>{pat})" for name, pat in _TOKEN_PATTERNS))


@dataclass(slots=True)
class Token:
    """A single token from the query string."""

    kind: str
    value: str
    pos: int  # Character position in original query


def _tokenize(query: str) -> list[Token]:
    """Split a query string into tokens."""
    tokens: list[Token] = []
    for m in _TOKEN_RE.finditer(query):
        kind = m.lastgroup
        if kind == "WS":
            continue
        value = m.group()
        tokens.append(Token(kind=kind, value=value, pos=m.start()))  # type: ignore[arg-type]
    return tokens


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class GraphQueryParser:
    """Parse a graph DSL query string into a ``GraphQueryAST``."""

    def parse(self, query: str) -> GraphQueryAST:
        """Parse *query* and return the AST.

        Raises ``ValueError`` on syntax errors with a descriptive message.
        """
        tokens = _tokenize(query.strip())
        if not tokens:
            raise ValueError("Empty query")

        self._tokens = tokens
        self._pos = 0
        self._ast = GraphQueryAST()

        self._parse_match()
        self._parse_optional_where()
        self._parse_return()

        if self._pos < len(self._tokens):
            tok = self._tokens[self._pos]
            raise ValueError(
                f"Unexpected token '{tok.value}' at position {tok.pos} "
                f"(expected end of query)"
            )

        return self._ast

    # -- Helpers --

    def _peek(self) -> Token | None:
        if self._pos < len(self._tokens):
            return self._tokens[self._pos]
        return None

    def _advance(self) -> Token:
        if self._pos >= len(self._tokens):
            raise ValueError("Unexpected end of query")
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _expect(self, kind: str, value: str | None = None) -> Token:
        tok = self._advance()
        if tok.kind != kind or (value is not None and tok.value.upper() != value.upper()):
            expected = f"'{value}'" if value else kind
            raise ValueError(
                f"Expected {expected} at position {tok.pos}, got '{tok.value}'"
            )
        return tok

    def _expect_keyword(self, keyword: str) -> Token:
        return self._expect("KEYWORD", keyword)

    # -- MATCH clause --

    def _parse_match(self) -> None:
        self._expect_keyword("MATCH")
        # Parse first node
        self._parse_node()

        # Parse alternating edge-node pairs
        while self._pos < len(self._tokens):
            tok = self._peek()
            if tok is None:
                break
            # Check for edge start: -[ or <-[
            if tok.kind in ("EDGE_RIGHT", "EDGE_LEFT"):
                src_idx = len(self._ast.nodes) - 1
                edge = self._parse_edge()
                self._parse_node()
                tgt_idx = len(self._ast.nodes) - 1
                edge.source = src_idx
                edge.target = tgt_idx
                self._ast.edges.append(edge)
            else:
                break

    def _parse_node(self) -> None:
        """Parse a node pattern: variable, "quoted path", or both."""
        tok = self._peek()
        if tok is None:
            raise ValueError("Expected node pattern, got end of query")

        variable = ""
        file_pattern: str | None = None

        if tok.kind in ("QUOTED", "QUOTED_SINGLE"):
            self._advance()
            # Extract the inner string (without quotes)
            file_pattern = self._extract_quoted(tok)
        elif tok.kind == "IDENT" and tok.value.upper() not in (
            "MATCH", "WHERE", "RETURN", "AND", "OR", "LIKE", "COUNT",
        ):
            self._advance()
            variable = tok.value
        else:
            raise ValueError(
                f"Expected variable name or quoted file path at position {tok.pos}, "
                f"got '{tok.value}'"
            )

        self._ast.nodes.append(NodePattern(variable=variable, file_pattern=file_pattern))

    def _parse_edge(self) -> EdgePattern:
        """Parse an edge pattern: -[TYPE*min..max]-> or <-[TYPE*min..max]-"""
        tok = self._advance()
        is_left = tok.kind == "EDGE_LEFT"  # <-[...]- means reverse direction

        # Parse edge type
        edge_type = "IMPORTS"
        min_depth = 1
        max_depth = 1

        # Read the edge contents (type and optional depth)
        tok = self._peek()
        if tok is not None and tok.kind == "IDENT":
            self._advance()
            edge_type = tok.value.upper()
            if edge_type not in ("IMPORTS", "IMPORTED_BY"):
                raise ValueError(
                    f"Unknown edge type '{edge_type}' at position {tok.pos}. "
                    f"Must be IMPORTS or IMPORTED_BY"
                )

        # Check for depth range: *min..max or *depth
        tok = self._peek()
        if tok is not None and tok.kind == "RANGE":
            self._advance()
            m = re.match(r"\*(\d+)\.\.(\d+)", tok.value)
            if m:
                min_depth = int(m.group(1))
                max_depth = int(m.group(2))
                if min_depth < 0 or max_depth < min_depth:
                    raise ValueError(
                        f"Invalid depth range *{min_depth}..{max_depth} "
                        f"at position {tok.pos}"
                    )
                max_depth = min(max_depth, 10)  # Safety cap
        elif tok is not None and tok.kind == "DEPTH_SINGLE":
            self._advance()
            m = re.match(r"\*(\d+)", tok.value)
            if m:
                d = int(m.group(1))
                min_depth = d
                max_depth = d
                max_depth = min(max_depth, 10)

        # Close the edge
        if is_left:
            self._expect("EDGE_LEFT_CLOSE")  # ]-
        else:
            self._expect("EDGE_RIGHT_CLOSE")  # ]->

        # For left-pointing edges (<-[TYPE]-), swap the semantics:
        # <-[IMPORTS]- means "is imported by" = follow reverse graph
        # <-[IMPORTED_BY]- means "imports" = follow forward graph
        if is_left:
            if edge_type == "IMPORTS":
                edge_type = "IMPORTED_BY"
            elif edge_type == "IMPORTED_BY":
                edge_type = "IMPORTS"

        return EdgePattern(
            source=-1,  # Will be set by caller
            target=-1,
            edge_type=edge_type,
            min_depth=min_depth,
            max_depth=max_depth,
        )

    # -- WHERE clause --

    def _parse_optional_where(self) -> None:
        tok = self._peek()
        if tok is None or tok.kind != "KEYWORD" or tok.value.upper() != "WHERE":
            return
        self._advance()  # consume WHERE

        self._parse_where_condition()
        while self._pos < len(self._tokens):
            tok = self._peek()
            if tok is not None and tok.kind == "KEYWORD" and tok.value.upper() == "AND":
                self._advance()
                self._parse_where_condition()
            else:
                break

    def _parse_where_condition(self) -> None:
        """Parse: variable.field op value"""
        var_tok = self._advance()
        if var_tok.kind != "IDENT":
            raise ValueError(
                f"Expected variable name in WHERE clause at position {var_tok.pos}, "
                f"got '{var_tok.value}'"
            )
        variable = var_tok.value

        self._expect("DOT")

        field_tok = self._advance()
        if field_tok.kind != "IDENT":
            raise ValueError(
                f"Expected field name after '.' at position {field_tok.pos}, "
                f"got '{field_tok.value}'"
            )
        field_name = field_tok.value

        # Operator: =, !=, >, <, >=, <=, or LIKE
        op_tok = self._peek()
        if op_tok is not None and op_tok.kind == "KEYWORD" and op_tok.value.upper() == "LIKE":
            self._advance()
            operator = "LIKE"
        elif op_tok is not None and op_tok.kind == "OP":
            self._advance()
            operator = op_tok.value
        else:
            raise ValueError(
                f"Expected comparison operator at position "
                f"{op_tok.pos if op_tok else 'end'}, "
                f"got '{op_tok.value if op_tok else 'end of query'}'"
            )

        # Value: quoted string or number or identifier
        val_tok = self._advance()
        if val_tok.kind in ("QUOTED", "QUOTED_SINGLE"):
            value = self._extract_quoted(val_tok)
        elif val_tok.kind == "NUMBER":
            value = val_tok.value
        elif val_tok.kind == "IDENT":
            value = val_tok.value
        else:
            raise ValueError(
                f"Expected value in WHERE clause at position {val_tok.pos}, "
                f"got '{val_tok.value}'"
            )

        valid_fields = {
            "language", "line_count", "importance", "path",
            "fan_in", "fan_out", "is_test", "is_config",
        }
        if field_name not in valid_fields:
            raise ValueError(
                f"Unknown field '{field_name}' in WHERE clause. "
                f"Valid fields: {', '.join(sorted(valid_fields))}"
            )

        self._ast.where_clauses.append(WhereClause(
            variable=variable,
            field_name=field_name,
            operator=operator,
            value=value,
        ))

    # -- RETURN clause --

    def _parse_return(self) -> None:
        self._expect_keyword("RETURN")

        self._parse_return_item()
        while self._pos < len(self._tokens):
            tok = self._peek()
            if tok is not None and tok.kind == "COMMA":
                self._advance()
                self._parse_return_item()
            else:
                break

    def _parse_return_item(self) -> None:
        """Parse: variable or variable.field or COUNT(variable)"""
        tok = self._peek()

        # COUNT(variable)
        if tok is not None and tok.kind == "KEYWORD" and tok.value.upper() == "COUNT":
            self._advance()
            # We treat COUNT as a special return — just return "count" field
            self._ast.return_specs.append(ReturnSpec(variable="*", field_name="count"))
            return

        var_tok = self._advance()
        if var_tok.kind != "IDENT":
            raise ValueError(
                f"Expected variable name in RETURN clause at position {var_tok.pos}, "
                f"got '{var_tok.value}'"
            )

        field_name: str | None = None
        dot_tok = self._peek()
        if dot_tok is not None and dot_tok.kind == "DOT":
            self._advance()
            field_tok = self._advance()
            if field_tok.kind != "IDENT":
                raise ValueError(
                    f"Expected field name after '.' at position {field_tok.pos}, "
                    f"got '{field_tok.value}'"
                )
            field_name = field_tok.value

        self._ast.return_specs.append(ReturnSpec(
            variable=var_tok.value,
            field_name=field_name,
        ))

    # -- Utilities --

    @staticmethod
    def _extract_quoted(tok: Token) -> str:
        """Extract the inner value from a QUOTED or QUOTED_SINGLE token."""
        v = tok.value
        if v.startswith('"') and v.endswith('"'):
            return v[1:-1]
        if v.startswith("'") and v.endswith("'"):
            return v[1:-1]
        return v


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

class GraphQueryExecutor:
    """Execute a parsed ``GraphQueryAST`` against a dependency graph.

    Uses the same ``DependencyGraph`` (forward/reverse dicts) and
    ``FileInfo`` list that the existing graph_query tool uses.
    """

    MAX_RESULTS = 100

    def execute(
        self,
        ast: GraphQueryAST,
        dep_graph: Any,  # DependencyGraph with forward/reverse dicts
        files: list[Any],  # list[FileInfo]
    ) -> list[dict[str, Any]]:
        """Execute the query and return a list of result dicts.

        Each result dict maps variable names to file paths (or field values
        if a specific field is requested in RETURN).
        """
        # Build file metadata lookup
        file_meta: dict[str, dict[str, Any]] = {}
        for fi in files:
            rel = fi.relative_path
            file_meta[rel] = {
                "path": rel,
                "language": fi.language,
                "line_count": fi.line_count,
                "importance": fi.importance,
                "is_test": fi.is_test,
                "is_config": fi.is_config,
            }

        # Compute fan_in / fan_out lazily
        all_known_files = set(file_meta.keys())
        if dep_graph is not None:
            for src in dep_graph.forward:
                all_known_files.add(src)
                all_known_files.update(dep_graph.forward[src])
            for tgt in dep_graph.reverse:
                all_known_files.add(tgt)
                all_known_files.update(dep_graph.reverse[tgt])

        for f in all_known_files:
            if f not in file_meta:
                file_meta[f] = {
                    "path": f,
                    "language": "",
                    "line_count": 0,
                    "importance": 0.0,
                    "is_test": False,
                    "is_config": False,
                }
            if dep_graph is not None:
                file_meta[f]["fan_in"] = len(dep_graph.reverse.get(f, set()))
                file_meta[f]["fan_out"] = len(dep_graph.forward.get(f, set()))
            else:
                file_meta[f]["fan_in"] = 0
                file_meta[f]["fan_out"] = 0

        # Resolve the query as a chain of node-edge-node patterns
        # Start with bindings for the first node
        bindings = self._resolve_start_node(ast.nodes[0], file_meta)

        # For each edge, expand bindings via BFS
        for edge in ast.edges:
            bindings = self._traverse_edge(edge, ast.nodes, bindings, dep_graph, file_meta)
            if not bindings:
                break

        # Apply WHERE filters
        for clause in ast.where_clauses:
            bindings = self._apply_where(clause, bindings, file_meta)

        # Build return dicts
        results = self._build_results(ast.return_specs, ast.nodes, bindings, file_meta)

        # Deduplicate
        seen: set[str] = set()
        unique_results: list[dict[str, Any]] = []
        for r in results:
            key = str(sorted(r.items()))
            if key not in seen:
                seen.add(key)
                unique_results.append(r)

        return unique_results[:self.MAX_RESULTS]

    # -- Internal --

    def _resolve_start_node(
        self,
        node: NodePattern,
        file_meta: dict[str, dict[str, Any]],
    ) -> list[dict[str, str]]:
        """Resolve the starting node to a list of variable bindings.

        Each binding is a dict mapping variable names to file paths.
        """
        if node.file_pattern is not None:
            # Concrete file or glob pattern
            matched = self._match_files(node.file_pattern, file_meta)
            if not matched:
                return []
            var = node.variable or "_anon_0"
            return [{var: f} for f in matched]
        else:
            # Unbound variable — starts from all known files
            var = node.variable or "_anon_0"
            return [{var: f} for f in file_meta]

    def _traverse_edge(
        self,
        edge: EdgePattern,
        nodes: list[NodePattern],
        bindings: list[dict[str, str]],
        dep_graph: Any,
        file_meta: dict[str, dict[str, Any]],
    ) -> list[dict[str, str]]:
        """Expand each binding by traversing the edge via BFS."""
        if dep_graph is None:
            return []

        src_node = nodes[edge.source]
        tgt_node = nodes[edge.target]
        src_var = src_node.variable or f"_anon_{edge.source}"
        tgt_var = tgt_node.variable or f"_anon_{edge.target}"

        use_reverse = edge.edge_type == "IMPORTED_BY"

        new_bindings: list[dict[str, str]] = []
        for binding in bindings:
            src_file = binding.get(src_var)
            if src_file is None:
                continue

            # BFS from src_file with depth constraints
            reachable = self._bfs(
                src_file, dep_graph, use_reverse,
                edge.min_depth, edge.max_depth,
            )

            # If target node has a file_pattern, filter reachable
            if tgt_node.file_pattern is not None:
                pattern_matches = set(self._match_files(tgt_node.file_pattern, file_meta))
                reachable = reachable & pattern_matches

            for target_file in reachable:
                new_binding = dict(binding)
                new_binding[tgt_var] = target_file
                new_bindings.append(new_binding)

        return new_bindings

    def _bfs(
        self,
        start: str,
        dep_graph: Any,
        use_reverse: bool,
        min_depth: int,
        max_depth: int,
    ) -> set[str]:
        """BFS traversal from *start*, returning files at depth [min_depth, max_depth]."""
        graph = dep_graph.reverse if use_reverse else dep_graph.forward

        visited: set[str] = set()
        result: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(start, 0)])

        while queue:
            current, depth = queue.popleft()
            if current in visited:
                continue
            visited.add(current)

            if min_depth <= depth <= max_depth and current != start:
                result.add(current)

            if depth < max_depth:
                neighbors = graph.get(current, set())
                for neighbor in neighbors:
                    if neighbor not in visited:
                        queue.append((neighbor, depth + 1))

        return result

    def _match_files(
        self,
        pattern: str,
        file_meta: dict[str, dict[str, Any]],
    ) -> list[str]:
        """Match files against a literal path or glob pattern."""
        # Exact match first
        if pattern in file_meta:
            return [pattern]

        # Try glob matching
        matched = [f for f in file_meta if fnmatch.fnmatch(f, pattern)]
        if matched:
            return sorted(matched)

        # Try suffix matching (user might omit leading path components)
        suffix_matched = [f for f in file_meta if f.endswith(pattern)]
        if suffix_matched:
            return sorted(suffix_matched)

        return []

    def _apply_where(
        self,
        clause: WhereClause,
        bindings: list[dict[str, str]],
        file_meta: dict[str, dict[str, Any]],
    ) -> list[dict[str, str]]:
        """Filter bindings by a WHERE condition."""
        result: list[dict[str, str]] = []
        for binding in bindings:
            file_path = binding.get(clause.variable)
            if file_path is None:
                continue
            meta = file_meta.get(file_path, {})
            field_val = meta.get(clause.field_name)
            if field_val is None:
                continue

            if self._eval_condition(field_val, clause.operator, clause.value):
                result.append(binding)

        return result

    @staticmethod
    def _eval_condition(field_val: Any, operator: str, raw_value: str) -> bool:
        """Evaluate a single comparison condition."""
        if operator == "LIKE":
            # LIKE uses fnmatch-style globbing
            return fnmatch.fnmatch(str(field_val), raw_value)

        # Try numeric comparison
        if isinstance(field_val, (int, float)):
            try:
                cmp_val = float(raw_value)
            except ValueError:
                return str(field_val) == raw_value
            if operator == "=":
                return field_val == cmp_val
            if operator == "!=":
                return field_val != cmp_val
            if operator == ">":
                return field_val > cmp_val
            if operator == "<":
                return field_val < cmp_val
            if operator == ">=":
                return field_val >= cmp_val
            if operator == "<=":
                return field_val <= cmp_val

        # Boolean comparison
        if isinstance(field_val, bool):
            cmp_val_bool = raw_value.lower() in ("true", "1", "yes")
            if operator == "=":
                return field_val == cmp_val_bool
            if operator == "!=":
                return field_val != cmp_val_bool

        # String comparison
        str_val = str(field_val)
        if operator == "=":
            return str_val == raw_value
        if operator == "!=":
            return str_val != raw_value
        if operator == ">":
            return str_val > raw_value
        if operator == "<":
            return str_val < raw_value
        if operator == ">=":
            return str_val >= raw_value
        if operator == "<=":
            return str_val <= raw_value

        return False

    def _build_results(
        self,
        return_specs: list[ReturnSpec],
        nodes: list[NodePattern],
        bindings: list[dict[str, str]],
        file_meta: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build the final result dicts from bindings and return specs."""
        # Handle COUNT special case
        if any(r.field_name == "count" and r.variable == "*" for r in return_specs):
            return [{"count": len(bindings)}]

        results: list[dict[str, Any]] = []
        for binding in bindings:
            row: dict[str, Any] = {}
            for spec in return_specs:
                file_path = binding.get(spec.variable)
                if file_path is None:
                    # Try to find the variable by node index
                    for i, node in enumerate(nodes):
                        if node.variable == spec.variable:
                            file_path = binding.get(node.variable)
                            break
                if file_path is None:
                    row[spec.variable] = None
                    continue

                if spec.field_name is not None:
                    meta = file_meta.get(file_path, {})
                    row[f"{spec.variable}.{spec.field_name}"] = meta.get(spec.field_name)
                else:
                    row[spec.variable] = file_path
            results.append(row)

        return results
