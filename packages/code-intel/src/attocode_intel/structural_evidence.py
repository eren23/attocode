"""Syntax-local evidence groups; this does not resolve data flow or earlier exits."""
from __future__ import annotations

import re
from pathlib import Path

LANGUAGES = {'.py': 'python', '.js': 'javascript', '.mjs': 'javascript', '.cjs': 'javascript',
             '.ts': 'typescript', '.tsx': 'tsx', '.jsx': 'javascript'}
CONTROLS = {'if_statement', 'elif_clause', 'else_clause', 'for_statement', 'for_in_statement',
            'while_statement', 'with_statement', 'try_statement', 'except_clause',
            'catch_clause', 'finally_clause', 'switch_statement', 'switch_case', 'switch_default'}
BLOCKS = {'block', 'statement_block', 'switch_body'}
LEAVES = {'identifier', 'property_identifier', 'string', 'integer', 'float', 'number',
          'true', 'false', 'none', 'null'}


def evidence_terms(value):
    from attocode_intel.focused_evidence import terms
    return terms(value) | set(re.findall(r'--[\w-]*|(?<!\w)\d+(?!\w)', value))


def structural_excerpts(source, definition, hint, preview_end):
    """Return None when structural context is unavailable, otherwise ranked groups.

    Each list member owns its context so the response budget drops it atomically.
    Context ranges describe enclosing syntax, not complete executable reachability.
    """
    language = LANGUAGES.get(Path(definition.file_path).suffix)
    if not language:
        return None
    from attocode_intel._internal.integrations.context.ts_parser import _get_parser
    parser = _get_parser(language)
    if parser is None:
        return None
    raw = '\n'.join(source).encode()
    tree = parser.parse(raw)  # No awaits between parse and traversal of this local tree.
    if tree.root_node.has_error:
        return None
    query = evidence_terms(hint)
    first, last = definition.start_line, min(definition.end_line, len(source))

    def bounds(node):
        return node.start_point.row + 1, node.end_point.row + bool(node.end_point.column)

    def header(node):
        bodies = [c for c in node.children if c.type in BLOCKS]
        for field in ('consequence', 'body'):
            child = node.child_by_field_name(field)
            if child is not None:
                bodies.append(child)
        a, b = bounds(node)
        if bodies:
            body = min(bodies, key=lambda c: c.start_byte)
            # Keep a same-line statement verbatim; do not invent sliced source lines.
            b = max(a, body.start_point.row + (body.type == 'statement_block'))
        return a, b

    def controls(node):
        ranges = []
        child, parent = node, node.parent
        while parent is not None and bounds(parent)[0] >= first:
            if parent.type in CONTROLS:
                ranges.append(header(parent))
                # Python elif/else are sibling clauses, so include preceding guards.
                for sibling in parent.named_children:
                    if sibling.start_byte >= child.start_byte:
                        break
                    if sibling.type == 'elif_clause':
                        ranges.append(header(sibling))
            child, parent = parent, parent.parent
        return ranges

    def tokens(node, interval=None):
        if interval and (bounds(node)[1] < interval[0] or bounds(node)[0] > interval[1]):
            return set()
        if node.type in {'comment', 'comment_block'}:
            return set()
        # A bare Python string statement is documentation, not an executable literal.
        if node.type == 'expression_statement' and node.named_children and node.named_children[0].type == 'string':
            return set()
        if node.type in LEAVES:
            return evidence_terms(raw[node.start_byte:node.end_byte].decode())
        result = set()
        for child in node.named_children:
            result.update(tokens(child, interval))
        return result

    candidates = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        a, b = bounds(node)
        if b < first or a > last:
            continue
        stack.extend(reversed(node.named_children))
        is_control = node.type in CONTROLS
        is_statement = node.type.endswith('_statement') or node.type in {'lexical_declaration', 'variable_declaration'}
        if not (is_control or is_statement) or a < first or b > last:
            continue
        # Compound statements contribute a header or a small complete branch.
        if is_control:
            effect = (a, b) if b - a < 18 and node.type in {'if_statement', 'elif_clause', 'else_clause'} else header(node)
        else:
            if any(c.type in BLOCKS for c in node.named_children):
                continue
            effect = (a, b)
        if effect[1] <= preview_end:
            continue
        hits = tokens(node, effect) & query
        if not hits:
            continue
        intervals = sorted(set([effect, *controls(node)]))
        merged = []
        for begin, end in intervals:
            if merged and (begin <= merged[-1][1] + 1 or end - merged[-1][0] < 12):
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((begin, end))
        # Prefer one small contiguous excerpt. Large gaps stay explicitly linked.
        if merged[-1][1] - merged[0][0] < 12:
            merged = [(merged[0][0], merged[-1][1])]
        main = next(r for r in merged if r[0] <= effect[0] and r[1] >= effect[1])
        context = [r for r in merged if r != main]
        candidates.append((len(hits) + int(effect == (a, b)), hits, main, context))

    def excerpt(interval):
        a, b = interval
        return {'file_path': definition.file_path, 'start_line': a, 'end_line': b,
                'text': '\n'.join(source[a-1:b])}

    selected, covered, occupied = [], set(), set()
    while candidates and len(selected) < 3:
        score, hits, main, context = max(candidates, key=lambda r: (r[0] + 4 * len(r[1] - covered), -r[2][0]))
        selected.append({**excerpt(main), 'matched_terms': sorted(hits),
                         'context_ranges': [excerpt(r) for r in context],
                         'context_relation': 'enclosing branch and preceding alternative guards',
                         'context_incomplete': False})
        covered.update(hits)
        occupied.update(range(main[0], main[1] + 1))
        candidates = [r for r in candidates if not occupied.intersection(range(r[2][0], r[2][1]+1))]
    return selected
