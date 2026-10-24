"""Bounded, disposable JSON summaries for structural restarts (never executable data)."""
from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import fields, is_dataclass
from functools import lru_cache
from pathlib import Path
from typing import get_args, get_origin, get_type_hints

from .codebase_ast import FileAST
from .index_store import AST_SNAPSHOT_KEY

MAX_CACHE_BYTES = 32 * 2**20
MAX_FILE_BYTES = 2**20


@lru_cache(maxsize=128)
def _file_hash(path: str, mtime: int, ctime: int, size: int) -> str:
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def parser_identity(language: str) -> str | None:
    """Only cache installed direct grammars with inspectable code/binary identity.

    Optional downloaded grammars, regex and ctags keep their existing parse path.
    No package acquisition or subprocess is performed here.
    """
    from . import ts_parser
    config = ts_parser.LANGUAGE_CONFIGS.get('typescript' if language == 'tsx' else language)
    if config is None:
        return None
    try:
        modules = [importlib.import_module(name) for name in (
            'tree_sitter', config.grammar_module,
        )]
        import tree_sitter

        grammar = modules[1]
        language_fn = getattr(grammar, 'language_tsx' if language == 'tsx' else config.language_func)
        active = ts_parser._get_parser(language)
        if active is None or active.language != tree_sitter.Language(language_fn()):
            return None
        paths = {Path(__file__), Path(__file__).with_name('codebase_ast.py'),
                 Path(__file__).with_name('ts_parser.py'), Path(__file__).with_name('language_registry.py')}
        for module in modules:
            location = Path(module.__file__)
            paths.add(location)
            paths.update(p for p in location.parent.rglob('*') if '__pycache__' not in p.parts
                         and p.suffix in {'.py', '.so', '.pyd', '.dll', '.dylib'})
        digest = hashlib.sha256(language.encode())
        for path in sorted(paths):
            stat = path.stat()
            digest.update(str(path).encode())
            digest.update(_file_hash(str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size).encode())
        return digest.hexdigest()
    except (ImportError, OSError, TypeError, AttributeError, ValueError):
        return None


def _fields(value):
    if not is_dataclass(value):
        raise TypeError(type(value).__name__)
    return {f.name: getattr(value, f.name) for f in fields(value)}


def navigation_identity() -> str:
    """Bind reuse to the code that extracts/resolves persisted navigation."""
    digest = hashlib.sha256(b'navigation-fingerprint-v1')
    for name in ('ast_service.py', 'ast_snapshot.py', 'codebase_ast.py',
                 'ts_parser.py', 'parse_diagnostics.py', 'cross_references.py',
                 'syntax_evidence.py', 'module_resolution.py', 'index_repair.py',
                 'codebase_context.py', 'language_registry.py'):
        path = Path(__file__).with_name(name)
        stat = path.stat()
        digest.update(name.encode())
        digest.update(_file_hash(str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size).encode())
    return digest.hexdigest()


def _bounded_json(value, limit):
    chunks, size = [], 0
    for chunk in json.JSONEncoder(default=_fields, separators=(',', ':'), ensure_ascii=True).iterencode(value):
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return ''.join(chunks)


@lru_cache(maxsize=32)
def _decoder(kind):
    """Compile the fixed dataclass schema once, not per scalar in every file."""
    if get_origin(kind) is list:
        decode_item = _decoder(get_args(kind)[0])

        def decode_list(value):
            if type(value) is not list:
                raise ValueError('Expected list')
            return [decode_item(item) for item in value]
        return decode_list
    if is_dataclass(kind):
        decoders = {key: _decoder(t) for key, t in get_type_hints(kind).items()}

        def decode_record(value):
            if type(value) is not dict or value.keys() != decoders.keys():
                raise ValueError('Summary fields changed')
            return kind(**{key: decode(value[key]) for key, decode in decoders.items()})
        return decode_record
    if kind not in (str, int, bool):
        raise ValueError('Unsupported summary type')

    def decode_scalar(value):
        if type(value) is not kind:
            raise ValueError('Invalid summary scalar')
        return value
    return decode_scalar


def encode_summaries(asts: dict[str, FileAST], snapshot: str) -> str:
    """Retain a deterministic subset under one 32 MiB cache / 1 MiB file bound."""
    identities = {language: parser_identity(language) for language in sorted({a.language for a in asts.values()})}
    header = json.dumps({'snapshot': hashlib.sha256(snapshot.encode()).hexdigest(),
                         'parsers': identities}, separators=(',', ':'), ensure_ascii=True)
    chunks = [header[:-1] + ',"files":{']
    size = len(chunks[0]) + 2
    count = 0
    for path, ast in sorted(asts.items()):
        if (ast.parsing_tier != 'tree_sitter' or not ast.content_sha256
                or not identities.get(ast.language) or ast.parse_failures):
            continue
        entry = _bounded_json(ast, min(MAX_FILE_BYTES, MAX_CACHE_BYTES - size))
        key = json.dumps(path, ensure_ascii=True)
        if entry is None or size + len(key) + len(entry) + 2 > MAX_CACHE_BYTES:
            continue
        item = (',' if count else '') + key + ':' + entry
        chunks.append(item)
        size += len(item)
        count += 1
    chunks.append('}}')
    result = ''.join(chunks)
    return result if len(result) <= MAX_CACHE_BYTES else ''


def restore_summaries(store, snapshot: str, parseable) -> dict[str, FileAST] | None:
    raw = store.get_meta(AST_SNAPSHOT_KEY, max_bytes=MAX_CACHE_BYTES)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if data['snapshot'] != hashlib.sha256(snapshot.encode()).hexdigest():
            return None
        records, signatures = data['files'], data['parsers']
        if type(records) is not dict or type(signatures) is not dict:
            return None
        identities = {}
        restored = {}
        for fi in parseable:
            record = records.get(fi.relative_path)
            if record is None:
                continue
            try:
                ast = _decoder(FileAST)(record)
                if ast.path != fi.path or ast.parsing_tier != 'tree_sitter' or ast.parse_failures:
                    continue
                if ast.language not in identities:
                    identities[ast.language] = parser_identity(ast.language)
                if not identities[ast.language] or identities[ast.language] != signatures.get(ast.language):
                    return None
                content = Path(fi.path).read_text(encoding='utf-8', errors='replace')
                if hashlib.sha256(content.encode()).hexdigest() == ast.content_sha256:
                    restored[fi.relative_path] = ast
            except (OSError, ValueError, TypeError, KeyError, RecursionError):
                continue
        return restored
    except (ValueError, TypeError, KeyError, RecursionError):
        return None
