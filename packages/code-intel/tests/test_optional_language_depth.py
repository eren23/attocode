"""Real optional grammars: explicitly acquired CI only, never navigation downloads."""
import hashlib
import json
import os
import urllib.request
from dataclasses import asdict
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get('QUALITY_LANGUAGE_DEPTH') != '1',
                                reason='Dedicated optional-grammar acquisition job is required')


def evidence(name, value):
    root = os.environ.get('QUALITY_LANGUAGE_EVIDENCE')
    if root:
        target = Path(root) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, ensure_ascii=True, indent=2) + '\n')


def native(path, source, language, case):
    from attocode_intel._internal.integrations.context import ts_parser
    from attocode_intel._internal.integrations.context.codebase_ast import parse_file
    from attocode_intel._internal.integrations.context.syntax_evidence import syntax_tree
    assert ts_parser.is_available(language), 'language coverage: explicit native grammar acquisition missing'
    tree = syntax_tree(path, source, language)
    ast = parse_file(path, source)
    evidence(case + '-native.json', {'path': path, 'source': source,
             'sha256': hashlib.sha256(source.encode()).hexdigest(), 'language': language,
             'tree': str(tree.root_node) if tree is not None else None,
             'tier': ast.parsing_tier, 'functions': [asdict(f) for f in ast.functions],
             'classes': [asdict(c) for c in ast.classes], 'imports': [asdict(i) for i in ast.imports]})
    assert ast.parsing_tier == 'tree_sitter', 'language coverage: native parse required'
    return ast


@pytest.fixture(scope='session')
def pinned_perl_sources():
    """Explicit CI fixture acquisition; these third-party sources are never executed."""
    assert os.environ.get('QUALITY_ALLOW_DOWNLOADS') == '1', 'Pinned source acquisition requires explicit CI opt-in'
    manifest = json.loads((Path(__file__).resolve().parents[1] / 'scripts/perl_depth_fixture.json').read_bytes())
    files = {}
    for name, expected in manifest['files'].items():
        url = f"https://raw.githubusercontent.com/{manifest['repo']}/{manifest['commit']}/{name}"
        with urllib.request.urlopen(url, timeout=30) as response:
            raw = response.read(expected['bytes'] + 1)
        assert len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'], 'Pinned Perl source changed: ' + name
        files[name] = raw
    for witness in manifest['witnesses'].values():
        assert files[witness['file']].decode().splitlines()[witness['line'] - 1] == witness['text'], 'Pinned Perl witness changed'
    evidence('perl-pinned-receipt.json', manifest)
    return manifest, files


def write_pinned_perl(root, files):
    for name, raw in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)


def test_perl_pinned_native_witnesses(pinned_perl_sources):
    from attocode_intel._internal.integrations.context.codebase_ast import detect_language
    from attocode_intel._internal.integrations.context.syntax_evidence import reference_candidates
    from attocode_intel._internal.integrations.context.ts_parser import ts_parse_file_generic
    manifest, files = pinned_perl_sources
    asts = {}
    for name, raw in files.items():
        assert detect_language(name) == 'perl', 'Pinned Perl test source lacks canonical language identity: ' + name
        asts[name] = native(name, raw.decode(), 'perl', 'perl-pinned-' + name.replace('/', '-'))
    target = manifest['witnesses']['definition']
    assert any(f.name == 'croak' and f.start_line <= target['line'] <= f.end_line for f in asts[target['file']].functions)
    importer = manifest['witnesses']['importer']['file']
    assert 'Carp' in {item.module for item in asts[importer].imports}
    caller = manifest['witnesses']['caller']
    generic = ts_parse_file_generic(caller['file'], files[caller['file']].decode())
    evidence('perl-pinned-generic.json', generic)
    assert generic is not None and generic['language'] == 'perl', 'Generic parser lost Perl .t identity'
    calls = reference_candidates(caller['file'], files[caller['file']].decode(), 'perl')
    evidence('perl-pinned-calls.json', calls)
    assert ('Carp.croak', 'call', caller['line']) in calls, 'Pinned native caller witness missing'


async def test_perl_pinned_inclusion_refresh_and_restart(tmp_path, monkeypatch, pinned_perl_sources):
    from attocode_intel._internal.integrations.context.codebase_context import (
        CodebaseContextManager,
    )
    from attocode_intel.freshness import FreshnessTracker
    from attocode_intel.gateway import OperationGateway
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    manifest, files = pinned_perl_sources
    write_pinned_perl(tmp_path, files)
    write_pinned_perl(tmp_path, {'dist/Other/generated.pm': b'sub unrelated_generated { return 0; }\n',
                               'build/generated.pm': b'sub build_generated { return 0; }\n'})
    recipe = '!dist/\ndist/*\n!dist/Carp/\n'
    evidence('perl-pinned-inclusion.json', {'workspace_scope': 'Perl repository root', 'config': recipe,
                                         'files': manifest['files']})
    async def definitions(peer):
        response = await peer.execute('search_symbols', {'name': 'croak'})
        assert not response.isError
        return {row['file_path'] for row in response.structuredContent['data']}
    target = manifest['witnesses']['definition']['file']
    peer = OperationGateway(str(tmp_path), 'daily', watch=False)
    try:
        assert target not in await definitions(peer)
        (tmp_path / '.gitignore').write_text(recipe)
        assert target in await definitions(peer)
        expected = set(files)
        assert {f.relative_path for f in CodebaseContextManager(str(tmp_path)).discover_files()} == expected
        assert set(FreshnessTracker(str(tmp_path)).scan_manifest()) == expected
    finally:
        await peer.close()
    peer = OperationGateway(str(tmp_path), 'daily', watch=False)
    try:
        assert target in await definitions(peer)
        (tmp_path / '.gitignore').write_text('dist/\n')
        assert target not in await definitions(peer)
        assert not FreshnessTracker(str(tmp_path)).scan_manifest()
    finally:
        await peer.close()


async def test_perl_pinned_distribution_workflow(tmp_path, monkeypatch, pinned_perl_sources):
    from eval.quality.corpus import evaluate
    from eval.quality.experiment_evidence import Journal
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    manifest, files = pinned_perl_sources
    write_pinned_perl(tmp_path, files)
    # The actual distribution root has a supported lib/ layout. This does not
    # assert repository-wide resolution through Perl's custom runtime @INC.
    root = tmp_path / manifest['distribution_root']
    spec = {'id': 'perl-pinned-distribution', 'language': 'perl', 'file': 'lib/Carp.pm',
            'symbol': 'croak', 'anchor': manifest['witnesses']['definition']['text'],
            'source_sha256': manifest['files']['dist/Carp/lib/Carp.pm']['sha256'],
            'caller': 't/Carp.t', 'importer': 'lib/Carp/Heavy.pm', 'test': 't/Carp.t', 'queries': []}
    evidence('perl-pinned-workflow-inputs.json', {'workspace_scope': manifest['distribution_root'], 'spec': spec})
    output = Path(os.environ['QUALITY_LANGUAGE_EVIDENCE']) / 'perl-pinned-workflow'
    checks = await evaluate(root, spec, journal=Journal(output, 4 * 2**20))
    evidence('perl-pinned-workflow-checks.json', checks)
    assert len(checks) == 8 and all(c['outcome'] == 'passed' for c in checks), repr([(c['name'], c['outcome']) for c in checks])
    assert all((tmp_path / name).read_bytes() == raw for name, raw in files.items()), 'Navigation changed pinned source'


async def test_perl_scoped_project_inclusion_refresh_and_restart(tmp_path, monkeypatch):
    from attocode_intel._internal.integrations.context.codebase_context import (
        CodebaseContextManager,
    )
    from attocode_intel.freshness import FreshnessTracker
    from attocode_intel.gateway import OperationGateway
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    source = 'package Carp;\nsub perl_entry { return $_[0]; }\n1;\n'
    native('dist/Carp/lib/Carp.pm', source, 'perl', 'perl-project')
    files = {'dist/Carp/lib/Carp.pm': source,
             'dist/Other/generated.pm': 'sub ignored_generated { return 0; }\n',
             'build/generated.pm': 'sub ignored_build { return 0; }\n'}
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    recipe = '!dist/\ndist/*\n!dist/Carp/\n'
    evidence('perl-project-inputs.json', {'root': str(tmp_path), 'files': files, 'config': recipe})
    async def visible(peer):
        response = await peer.execute('search_symbols', {'name': 'perl_entry'})
        assert not response.isError
        return {r['name'] for r in response.structuredContent['data']}
    peer = OperationGateway(str(tmp_path), 'daily', watch=False)
    try:
        assert 'perl_entry' not in await visible(peer), 'language coverage: default dist must stay excluded'
        (tmp_path / '.gitignore').write_text(recipe)
        assert 'perl_entry' in await visible(peer), 'language coverage: configured Perl definition missing'
        expected = {'dist/Carp/lib/Carp.pm'}
        assert {f.relative_path for f in CodebaseContextManager(str(tmp_path)).discover_files()} == expected, 'language coverage: unrelated generated source admitted'
        assert set(FreshnessTracker(str(tmp_path)).scan_manifest()) == expected
    finally:
        await peer.close()
    peer = OperationGateway(str(tmp_path), 'daily', watch=False)
    try:
        assert 'perl_entry' in await visible(peer), 'language coverage: configured Perl restart lost definition'
        (tmp_path / '.gitignore').write_text('dist/\n')
        assert 'perl_entry' not in await visible(peer), 'language coverage: removed inclusion retained stale symbol'
    finally:
        await peer.close()


@pytest.fixture(scope='session')
def pinned_gson_sources():
    """Acquire immutable Java source as data on the opted-in worker only."""
    assert os.environ.get('QUALITY_ALLOW_DOWNLOADS') == '1', 'Pinned source acquisition requires explicit CI opt-in'
    manifest = json.loads((Path(__file__).resolve().parents[1] / 'scripts/gson_depth_fixture.json').read_bytes())
    files = {}
    for name, expected in manifest['files'].items():
        url = f"https://raw.githubusercontent.com/{manifest['repo']}/{manifest['commit']}/{name}"
        with urllib.request.urlopen(url, timeout=30) as response:
            raw = response.read(expected['bytes'] + 1)
        assert len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'], 'Pinned Gson source changed: ' + name
        assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == expected['git_blob_sha1']
        files[name] = raw
    for witness in manifest['witnesses'].values():
        assert files[witness['file']].decode().splitlines()[witness['line'] - 1] == witness['text'], 'Pinned Gson witness changed'
    evidence('gson-pinned-receipt.json', manifest)
    return manifest, files


def test_gson_pinned_native_dollar_calls(pinned_gson_sources):
    from attocode_intel._internal.integrations.context.syntax_evidence import (
        reference_candidates,
        syntax_tree,
    )
    manifest, files = pinned_gson_sources
    asts, calls, validation = {}, {}, []
    for name, raw in files.items():
        asts[name] = native(name, raw.decode(), 'java', 'gson-pinned-' + name.replace('/', '-'))
        tree = syntax_tree(name, raw.decode(), 'java')
        validation.append({'path': name, 'has_error': tree.root_node.has_error,
                           'end_byte': tree.root_node.end_byte, 'bytes': len(raw)})
        assert not tree.root_node.has_error and tree.root_node.end_byte == len(raw)
        calls[name] = reference_candidates(name, raw.decode(), 'java')
    evidence('gson-pinned-native-validation.json', validation)
    evidence('gson-pinned-calls.json', calls)
    for role, symbol in [('definition', 'newParameterizedTypeWithOwner'), ('canonicalize_definition', 'canonicalize')]:
        witness = manifest['witnesses'][role]
        classes = [c for c in asts[witness['file']].classes if c.name == '$Gson$Types']
        assert len(classes) == 1
        assert any(f.name == symbol and f.start_line <= witness['line'] <= f.end_line
                   for f in classes[0].methods)
    for role in ['importer', 'test_importer']:
        witness = manifest['witnesses'][role]
        assert any(i.module == 'com.google.gson.internal.$Gson$Types' and i.line == witness['line']
                   for i in asts[witness['file']].imports)
    for role, symbol in [('caller', 'newParameterizedTypeWithOwner'), ('test', 'newParameterizedTypeWithOwner'),
                         ('canonicalize_caller', 'canonicalize'), ('canonicalize_test', 'canonicalize')]:
        witness = manifest['witnesses'][role]
        assert ('$Gson$Types.' + symbol, 'call', witness['line']) in calls[witness['file']], role


async def test_gson_pinned_dollar_workflow_and_unresolved_test(tmp_path, monkeypatch, pinned_gson_sources):
    from attocode_intel.gateway import OperationGateway

    from eval.quality.corpus import evaluate
    from eval.quality.experiment_evidence import Journal
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    manifest, files = pinned_gson_sources
    for name, raw in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    target = manifest['witnesses']['definition']['file']
    spec = {'id': 'gson-pinned-dollar', 'language': 'java', 'file': target,
            'symbol': 'newParameterizedTypeWithOwner', 'anchor': manifest['witnesses']['definition']['text'],
            'source_sha256': manifest['files'][target]['sha256'],
            'caller': manifest['witnesses']['caller']['file'], 'importer': manifest['witnesses']['importer']['file'],
            'test': manifest['witnesses']['test']['file'], 'queries': []}
    evidence('gson-pinned-workflow-inputs.json', {'workspace_scope': 'four unchanged pinned Gson files', 'spec': spec})
    output = Path(os.environ['QUALITY_LANGUAGE_EVIDENCE']) / 'gson-pinned-workflow'
    checks = await evaluate(tmp_path, spec, journal=Journal(output, 4 * 2**20))
    evidence('gson-pinned-workflow-checks.json', checks)
    assert len(checks) == 8 and all(c['outcome'] == 'passed' for c in checks), repr([(c['name'], c['outcome']) for c in checks])
    peer = OperationGateway(str(tmp_path), 'daily', watch=False)
    try:
        primary = await peer.execute('inspect_symbol', {'symbol_name': spec['symbol'],
                                     'file_path': target, 'line': manifest['witnesses']['definition']['line']})
        assert not primary.isError
        evidence('gson-pinned-selected-method.json', primary.structuredContent)
        selected_data = primary.structuredContent['data']
        assert selected_data['status'] == 'found'
        for role in ['caller', 'test']:
            witness = manifest['witnesses'][role]
            assert any(r['file_path'] == witness['file'] and r['line'] == witness['line']
                       and r['resolution'] == 'import_binding' for r in selected_data['references'])
        assert any(t['file_path'] == spec['test'] and t['evidence']['selected_symbol_reference']
                   for t in selected_data['tests'])
        selected = manifest['witnesses']['canonicalize_definition']
        response = await peer.execute('cross_references', {'symbol_name': 'canonicalize',
                                      'file_path': target, 'line': selected['line']})
        assert not response.isError
        proof = response.structuredContent
        evidence('gson-pinned-canonicalize-references.json', proof)
        data = proof['data']
        caller = manifest['witnesses']['canonicalize_caller']
        assert any(r['file_path'] == caller['file'] and r['line'] == caller['line']
                   and r['resolution'] == 'import_binding' for r in data['references'])
        test = manifest['witnesses']['canonicalize_test']
        assert not any(r['file_path'] == test['file'] for r in data['references'])
        assert any(r['file_path'] == test['file'] and r['line'] == test['line']
                   and r['resolution'] == 'same_name_candidate' for r in data['reference_candidates'])
        assert proof['metadata']['analysis']['absence_proven'] is False
    finally:
        await peer.close()
    assert all((tmp_path / name).read_bytes() == raw for name, raw in files.items()), 'Navigation changed pinned Gson source'


def test_gson_pinned_java_signature_metadata(pinned_gson_sources):
    import importlib.metadata

    import tree_sitter
    import tree_sitter_java
    from attocode_intel._internal.integrations.context import ts_parser
    from attocode_intel._internal.integrations.context.ast_chunker import chunk_file

    manifest, files = pinned_gson_sources
    target = manifest['witnesses']['definition']['file']
    source = files[target].decode()
    ast = native(target, source, 'java', 'gson-pinned-signature')
    cls = next(c for c in ast.classes if c.name == '$Gson$Types')
    methods = {m.name: m for m in cls.methods if m.name in {'newParameterizedTypeWithOwner', 'canonicalize'}}
    chunks = {c.name: c.metadata for c in chunk_file(target, target, content=source)
              if c.name in {'$Gson$Types.newParameterizedTypeWithOwner', '$Gson$Types.canonicalize'}}
    dist = importlib.metadata.distribution('tree-sitter-java')
    origin = Path(tree_sitter_java.__file__).resolve()
    assert any(Path(dist.locate_file(p)).resolve() == origin for p in dist.files or [])
    parser_matches = ts_parser._get_parser('java').language == tree_sitter.Language(tree_sitter_java.language())
    evidence('gson-pinned-signatures.json', {'path': target, 'source_sha256': manifest['files'][target]['sha256'],
             'java_origin': str(origin), 'java_version': dist.version, 'standalone_grammar_matches': parser_matches,
             'methods': {name: asdict(m) for name, m in methods.items()}, 'chunks': chunks})
    assert parser_matches, 'Native Java evidence must use the fingerprinted standalone grammar'
    method = methods['newParameterizedTypeWithOwner']
    assert [(p.name, p.type_annotation, p.is_rest) for p in method.parameters] == [
        ('ownerType', 'Type', False), ('rawType', 'Type', False), ('typeArguments', 'Type', True)]
    assert method.return_type == 'ParameterizedType'
    assert methods['canonicalize'].return_type == 'Type'
    assert 'newParameterizedTypeWithOwner(ownerType, rawType, typeArguments)' in chunks['$Gson$Types.newParameterizedTypeWithOwner']
    assert '-> ParameterizedType' in chunks['$Gson$Types.newParameterizedTypeWithOwner']


@pytest.fixture(scope='session')
def pinned_redis_c_source():
    assert os.environ.get('QUALITY_ALLOW_DOWNLOADS') == '1', 'Pinned source acquisition requires explicit CI opt-in'
    manifest = json.loads((Path(__file__).resolve().parents[1] / 'scripts/c_parameter_fixture.json').read_bytes())
    files = {}
    for name, expected in manifest['files'].items():
        url = f"https://raw.githubusercontent.com/{manifest['repo']}/{manifest['commit']}/{name}"
        with urllib.request.urlopen(url, timeout=30) as response:
            raw = response.read(expected['bytes'] + 1)
        assert len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256']
        assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == expected['git_blob_sha1']
        files[name] = raw
    for target in manifest['targets']:
        assert files[target['file']].decode().splitlines()[target['line'] - 1] == target['text']
    evidence('redis-c-parameter-receipt.json', manifest)
    return manifest, files


def test_redis_pinned_c_parameter_metadata(pinned_redis_c_source, tmp_path):
    import importlib.metadata
    import re
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

    import tree_sitter
    import tree_sitter_c
    from attocode_intel._internal.integrations.context import ast_service, codebase_ast, ts_parser
    from attocode_intel._internal.integrations.context.ast_chunker import chunk_file
    from attocode_intel._internal.integrations.context.ast_service import ASTService
    from attocode_intel._internal.integrations.context.syntax_evidence import syntax_tree

    manifest, files = pinned_redis_c_source
    name = manifest['targets'][0]['file']
    source = files[name].decode()
    ast = native(name, source, 'c', 'redis-c-parameters')
    tree = syntax_tree(name, source, 'c')
    parser_matches = ts_parser._get_parser('c').language == tree_sitter.Language(tree_sitter_c.language())
    dist = importlib.metadata.distribution('tree-sitter-c')
    origin = Path(tree_sitter_c.__file__).resolve()
    assert any(Path(dist.locate_file(p)).resolve() == origin for p in dist.files or [])
    chunks = {c.name: c.metadata for c in chunk_file(name, name, content=source) if c.chunk_type == 'function'}
    evidence('redis-c-parameter-results.json', {'path': name, 'has_error': tree.root_node.has_error,
             'end_byte': tree.root_node.end_byte, 'bytes': len(files[name]),
             'standalone_grammar_matches': parser_matches, 'c_origin': str(origin), 'c_version': dist.version,
             'functions': [asdict(f) for f in ast.functions], 'chunks': chunks})
    assert parser_matches and not tree.root_node.has_error and tree.root_node.end_byte == len(files[name])
    def tokens(text):
        return re.findall(r'[A-Za-z_]\w*|\d+|[^\s]', text)

    for target in manifest['targets']:
        function = next(f for f in ast.functions if f.name == target['symbol'])
        assert function.start_line <= target['line'] <= function.end_line
        assert [p.name for p in function.parameters] == [p['name'] for p in target['parameters']]
        for actual, expected in zip(function.parameters, target['parameters'], strict=True):
            assert tokens(actual.type_annotation) == tokens(expected['type']) and not actual.is_rest
        assert target['symbol'] + '(' + ', '.join(p['name'] for p in target['parameters']) + ')' in chunks[target['symbol']]

    with TemporaryDirectory(prefix='redis-c-cache-', dir=tmp_path) as directory:
        root = Path(directory)
        target = root / name
        target.parent.mkdir(parents=True)
        target.write_bytes(files[name])
        first = ASTService(str(root))
        try:
            first.initialize_skeleton(indexing_depth='eager')
            assert set(first._ast_cache) == {name}
            assert [asdict(f) for f in first._ast_cache[name].functions] == [asdict(f) for f in ast.functions]
            expected = {k: asdict(v) for k, v in first._ast_cache.items()}
            definitions = first._index.definitions.copy()
            assert {t['symbol'] for t in manifest['targets']} <= set(definitions)
            expected_symbols = {k: [asdict(loc) for loc in locations] for k, locations in definitions.items()}
            counts = first._store.stats()
        finally:
            first.stop_hydration()
            first._store.close()
        second = ASTService(str(root))
        try:
            with (patch.object(ast_service, 'parse_file', side_effect=AssertionError('restart reparsed')) as parse,
                  patch.object(codebase_ast, 'parse_file', side_effect=AssertionError('discovery reparsed')) as discover):
                assert second.initialize_skeleton().phase == 'ready'
            parse.assert_not_called()
            discover.assert_not_called()
            restored = {k: asdict(v) for k, v in second._ast_cache.items()}
            assert restored == expected
            assert second._index.definitions == definitions
            restored_symbols = {k: [asdict(loc) for loc in locations]
                                for k, locations in second._index.definitions.items()}
            assert second._store.stats() == counts
            assert target.read_bytes() == files[name]
        finally:
            second.stop_hydration()
            second._store.close()
    assert not root.exists()
    evidence('redis-c-cache-restart.json', {'path': name, 'source_sha256': hashlib.sha256(files[name]).hexdigest(),
             'expected': expected, 'restored': restored, 'definitions_equal': True, 'store_counts_equal': True,
             'expected_symbols': expected_symbols, 'restored_symbols': restored_symbols,
             'restart_parse_calls': parse.call_count, 'discovery_parse_calls': discover.call_count,
             'source_unchanged': True, 'owned_cleanup': not root.exists()})


def test_crystal_method_definition_native_range():
    ast = native('greet.cr', 'def greet(name)\n  name\nend\n', 'crystal', 'crystal-method')
    assert [(f.name, f.start_line, f.end_line) for f in ast.functions] == [('greet', 1, 3)], 'language coverage: Crystal native method definition missing'


def test_crystal_class_definition_native_range():
    ast = native('greeter.cr', 'class Greeter\nend\n', 'crystal', 'crystal-class')
    assert [(c.name, c.start_line, c.end_line) for c in ast.classes] == [('Greeter', 1, 2)], 'language coverage: Crystal native class definition missing'


def test_ocaml_native_call_candidates_exclude_decoys():
    from attocode_intel._internal.integrations.context.syntax_evidence import reference_candidates
    source = 'let greet x = x\nlet run () = Helper.greet "ok"\n(* Helper.decoy "no" *)\nlet text = "Helper.decoy nope"\n'
    native('driver.ml', source, 'ocaml', 'ocaml-calls')
    calls = reference_candidates('driver.ml', source, 'ocaml')
    evidence('ocaml-calls.json', calls)
    assert calls == [('Helper.greet', 'call', 2)], 'language coverage: OCaml native call candidates wrong'


@pytest.mark.parametrize('route', ['structure', 'references', 'generic'])
def test_ocaml_interface_native_grammar_route(route, monkeypatch):
    from attocode_intel._internal.integrations.context import syntax_evidence, ts_parser
    source = "open Helper\nval identity : 'a -> 'a\n"
    observations = []
    original = ts_parser.bounded_parse
    def observe(parser, data):
        tree = original(parser, data)
        observations.append({'language': parser.language.name, 'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest(), 'tree': str(tree.root_node) if tree else None,
            'has_error': tree.root_node.has_error if tree else None,
            'end_byte': tree.root_node.end_byte if tree else None})
        return tree
    monkeypatch.setattr(ts_parser, 'bounded_parse', observe)
    if route == 'structure':
        result = ts_parser.ts_parse_file('api.mli', source, 'ocaml')
    elif route == 'references':
        result = syntax_evidence.reference_candidates('api.mli', source, 'ocaml')
    else:
        result = ts_parser.ts_parse_file_generic('api.mli', source, 'ocaml')
    evidence('ocaml-interface-' + route + '.json', {'source': source, 'observations': observations, 'result': result})
    assert result is not None and observations, 'ocaml interface: native route unavailable'
    assert all(o['language'] == 'ocaml_interface' and o['has_error'] is False and o['end_byte'] == len(source.encode()) for o in observations), 'ocaml interface: native route used implementation or error tree'
    assert ts_parser.PARSE_TIMEOUT_MICROS == 100000


def test_ocaml_interface_native_value_signature_ranges():
    from attocode_intel._internal.integrations.context.codebase_ast import parse_file
    source = "(* val decoy : int *)\nval identity : 'a -> 'a\nval answer : int\n"
    result = parse_file('api.mli', source)
    evidence('ocaml-interface-values.json', {'source': source, 'tier': result.parsing_tier,
             'functions': [asdict(f) for f in result.functions], 'failures': [asdict(f) for f in result.parse_failures]})
    assert result.language == 'ocaml' and result.parsing_tier == 'tree_sitter'
    assert [(f.name, f.start_line, f.end_line) for f in result.functions] == [('identity', 2, 2), ('answer', 3, 3)], 'ocaml interface: value signatures missing or wrong ranges'
    assert not result.parse_failures


def test_perl_native_call_candidates_exclude_decoys():
    from attocode_intel._internal.integrations.context.syntax_evidence import reference_candidates
    source = ('sub greet { return $_[0]; }\nsub run { Lib::Helper::greet("ok"); }\n'
              '# Lib::Helper::decoy("no");\nmy $text = "Lib::Helper::decoy nope";\n'
              'my $fn = \\&greet;\n$fn("dynamic");\n')
    native('driver.pl', source, 'perl', 'perl-calls')
    calls = reference_candidates('driver.pl', source, 'perl')
    evidence('perl-calls.json', calls)
    assert calls == [('Lib.Helper.greet', 'call', 2)], 'language coverage: Perl native call candidates wrong'


async def workflow(root, files, spec, case, monkeypatch):
    from eval.quality.corpus import evaluate
    from eval.quality.experiment_evidence import Journal
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    spec = {**spec, 'source_sha256': hashlib.sha256(files[spec['file']].encode()).hexdigest(), 'queries': []}
    native(spec['file'], files[spec['file']], spec['language'], case)
    evidence(case + '-inputs.json', {'root': str(root), 'files': files, 'spec': spec})
    output = Path(os.environ['QUALITY_LANGUAGE_EVIDENCE']) / case
    try:
        checks = await evaluate(root, spec, journal=Journal(output, 4 * 2**20))
    except ValueError as error:
        evidence(case + '-failure.json', {'type': type(error).__name__, 'message': str(error)})
        raise AssertionError('language coverage: workflow stopped: ' + str(error)) from error
    evidence(case + '-checks.json', checks)
    assert len(checks) == 8 and all(c['outcome'] == 'passed' for c in checks), 'language coverage: cross-file workflow incomplete: ' + repr([(c['name'], c['outcome']) for c in checks])


async def test_ocaml_cross_file_workflow(tmp_path, monkeypatch):
    await workflow(tmp_path, {'helper.ml': 'let greet name = name\n',
        'driver.ml': 'open Helper\nlet run () = greet "ok"\n',
        'tests/test_helper.ml': 'open Helper\nlet case () = greet "test"\n'},
        {'id': 'ocaml-depth', 'language': 'ocaml', 'file': 'helper.ml', 'symbol': 'greet',
         'anchor': 'let greet', 'caller': 'driver.ml', 'importer': 'driver.ml', 'test': 'tests/test_helper.ml'},
        'ocaml-workflow', monkeypatch)


async def test_perl_cross_file_workflow(tmp_path, monkeypatch):
    await workflow(tmp_path, {'Lib/Helper.pm': 'package Lib::Helper;\nsub greet { return $_[0]; }\n1;\n',
        'driver.pl': 'use Lib::Helper;\nsub run { Lib::Helper::greet("ok"); }\n',
        'tests/test_helper.pl': 'use Lib::Helper;\nLib::Helper::greet("test");\n'},
        {'id': 'perl-depth', 'language': 'perl', 'file': 'Lib/Helper.pm', 'symbol': 'greet',
         'anchor': 'sub greet', 'caller': 'driver.pl', 'importer': 'driver.pl', 'test': 'tests/test_helper.pl'},
        'perl-workflow', monkeypatch)


async def test_crystal_cross_file_workflow(tmp_path, monkeypatch):
    await workflow(tmp_path, {'helper.cr': 'def greet(name)\n  name\nend\n',
        'driver.cr': 'require "./helper"\ndef run\n  greet("ok")\nend\n',
        'spec/helper_spec.cr': 'require "../helper"\ngreet("test")\n'},
        {'id': 'crystal-depth', 'language': 'crystal', 'file': 'helper.cr', 'symbol': 'greet',
         'anchor': 'def greet', 'caller': 'driver.cr', 'importer': 'driver.cr', 'test': 'spec/helper_spec.cr'},
        'crystal-workflow', monkeypatch)


@pytest.mark.parametrize('language,path,source,module,target', [
    ('ocaml', 'driver.ml', 'open Helper\nlet run () = greet "ok"\n', 'Helper', 'helper.ml'),
    ('perl', 'driver.pl', 'use Lib::Helper;\nLib::Helper::greet("ok");\n', 'Lib::Helper', 'Lib/Helper.pm'),
    ('crystal', 'driver.cr', 'require "./helper"\ngreet("ok")\n', './helper', 'helper.cr'),
], ids=['ocaml', 'perl', 'crystal'])
def test_optional_static_import_and_resolution(language, path, source, module, target):
    from attocode_intel._internal.integrations.context.codebase_context import (
        resolve_import_targets,
    )
    ast = native(path, source, language, language + '-imports')
    assert [item.module for item in ast.imports] == [module], 'language coverage: static native import lost or malformed'
    actual = resolve_import_targets(language, module, path, {path: path, target: target})
    evidence(language + '-import-targets.json', actual)
    assert actual == [target], 'language coverage: static workspace import not resolved'


@pytest.mark.parametrize('language,module,source,index', [
    ('ocaml', 'Helper', 'pkg/driver.ml', {'helper.ml': 'helper.ml', 'pkg/helper.ml': 'pkg/helper.ml'}),
    ('perl', 'Lib::Helper', 'driver.pl', {'Lib/Helper.pm': 'Lib/Helper.pm', 'lib/Lib/Helper.pm': 'lib/Lib/Helper.pm'}),
    ('crystal', 'json', 'driver.cr', {'json.cr': 'json.cr'}),
    ('crystal', '../../outside', 'src/driver.cr', {'../outside.cr': '../outside.cr'}),
    ('perl', '$module', 'driver.pl', {'$module.pm': '$module.pm'}),
    ('ocaml', 'Helper(X)', 'driver.ml', {'helper(X).ml': 'helper(X).ml'}),
    ('crystal', './parts/*', 'driver.cr', {'parts/a.cr': 'parts/a.cr'}),
    ('perl', '../../escape.pm', 'driver.pl', {'../../escape.pm': '../../escape.pm'}),
], ids=['ocaml-ambiguous', 'perl-ambiguous', 'crystal-external', 'crystal-escape',
        'perl-dynamic', 'ocaml-functor', 'crystal-glob', 'perl-escape'])
def test_optional_imports_preserve_uncertainty(language, module, source, index):
    from attocode_intel._internal.integrations.context.codebase_context import (
        resolve_import_targets,
    )
    assert resolve_import_targets(language, module, source, index) == [], 'language coverage: unsupported or ambiguous import claimed a local target'


@pytest.mark.parametrize('language,module,driver,target,valid_driver,valid_target', [
    ('ocaml', 'Helper', 'driver.ml', 'src/helper.ml', 'src/driver.ml', 'src/helper.ml'),
    ('perl', 'Lib::Helper', 'driver.pl', 'src/Lib/Helper.pm', 'driver.pl', 'lib/Lib/Helper.pm'),
    ('crystal', './helper', 'driver.cr', 'src/helper.cr', 'src/driver.cr', 'src/helper.cr'),
], ids=['ocaml', 'perl', 'crystal'])
def test_optional_imports_require_physical_paths(tmp_path, language, module, driver, target, valid_driver, valid_target):
    from types import SimpleNamespace

    from attocode_intel._internal.integrations.context.codebase_context import (
        _build_file_index,
        resolve_import_targets,
    )
    paths = {'src/pkg/__init__.py', target, driver}
    def index():
        for name in paths:
            file = tmp_path / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.touch()
        return _build_file_index([SimpleNamespace(relative_path=name) for name in sorted(paths)], str(tmp_path))
    misleading = index()
    assert misleading[target.removeprefix('src/')] == target
    assert resolve_import_targets(language, module, driver, misleading) == [], 'language coverage: Python import alias became a physical optional-language target'
    paths.update({valid_driver, valid_target})
    assert resolve_import_targets(language, module, valid_driver, index()) == [valid_target], 'language coverage: canonical physical target lost'
