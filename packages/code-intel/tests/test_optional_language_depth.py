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


def _perl_roots_fixture(root, manifest, files, roots, prefix):
    """Same immutable sources, with explicit discovery and separate resolution policy."""
    write_pinned_perl(root, files)
    (root / '.gitignore').write_text('!dist/\ndist/*\n!dist/Carp/\n')
    config = root / '.attocode/config.toml'
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text('[perl]\nmodule_roots = ' + json.dumps(roots) + '\n')
    asts = {name:native(name, raw.decode(), 'perl', prefix + '-' + name.replace('/', '-'))
            for name,raw in files.items()}
    target = manifest['witnesses']['definition']
    importer = manifest['witnesses']['importer']['file']
    assert any(f.name == 'croak' and f.start_line <= target['line'] <= f.end_line
               for f in asts[target['file']].functions)
    assert 'Carp' in {i.module for i in asts[importer].imports}
    return config


async def test_perl_configured_repository_workflow(
        tmp_path, monkeypatch, pinned_perl_sources, record_property):
    from eval.quality.corpus import evaluate
    from eval.quality.experiment_evidence import Journal

    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    manifest, files = pinned_perl_sources
    roots = ['dist/Carp/lib']
    _perl_roots_fixture(tmp_path, manifest, files, roots, 'perl-roots-repository')
    spec = {'id':'perl-configured-repository','language':'perl',
            'file':'dist/Carp/lib/Carp.pm','symbol':'croak',
            'anchor':manifest['witnesses']['definition']['text'],
            'source_sha256':manifest['files']['dist/Carp/lib/Carp.pm']['sha256'],
            'caller':'dist/Carp/t/Carp.t','importer':'dist/Carp/lib/Carp/Heavy.pm',
            'test':'dist/Carp/t/Carp.t','queries':[]}
    evidence('perl-roots-repository-inputs.json', {'roots':roots,'spec':spec,
             'workspace_scope':'Perl repository root','manifest':manifest})
    output = Path(os.environ['QUALITY_LANGUAGE_EVIDENCE']) / 'perl-roots-repository-workflow'
    record_property('qualified_input', 'true')
    record_property('native_pinned_files', str(len(files)))
    try:
        checks = await evaluate(tmp_path, spec, journal=Journal(output, 4 * 2**20))
    except ValueError as error:
        # The RAW-capturing evaluator stops at a failed contract. Translate
        # only this healthy missing-importer response, preserving other errors.
        if str(error) != 'failed compatibility check: dependencies':
            raise
        events = [json.loads(line) for line in (output / 'events.jsonl').read_bytes().splitlines()]
        event = next(e for e in reversed(events) if e['request'].get('event')=='mcp_response'
                     and e['request'].get('tool')=='dependencies')
        ref = event['response']
        raw = (output / ref['path']).read_bytes()
        assert len(raw)==ref['bytes'] and hashlib.sha256(raw).hexdigest()==ref['sha256']
        response = json.loads(raw)
        assert response['isError'] is False
        data = json.loads(response['content'][0]['text'])['data']
        assert data['path']==spec['file'] and isinstance(data['imported_by'],list)
        assert spec['importer'] not in data['imported_by']
        assert all((tmp_path / name).read_bytes()==content for name,content in files.items())
        evidence('perl-roots-repository-stopped.json', {'contract':'dependencies','response_ref':ref,
                 'observed_importers':data['imported_by'],'source_unchanged':True})
        raise AssertionError('REGRESSION: configured Perl repository roots do not satisfy navigation contracts') from error
    evidence('perl-roots-repository-checks.json', checks)
    assert all((tmp_path / name).read_bytes() == raw for name,raw in files.items())
    record_property('workflow_checks', json.dumps([(c['name'],c['outcome']) for c in checks]))
    assert len(checks)==8 and all(c['outcome']=='passed' for c in checks), 'REGRESSION: configured Perl repository roots do not satisfy navigation contracts'


@pytest.mark.parametrize('online', [False,True,'notified','partial'], ids=[
    'edited-while-closed','edited-in-session','edited-after-notify','controlled-partial',
])
async def test_perl_config_only_refresh_and_restart(
        tmp_path, monkeypatch, pinned_perl_sources, record_property, online):
    from attocode_intel.gateway import OperationGateway

    from eval.quality.corpus_capture import RecordedGateway
    from eval.quality.experiment_evidence import Journal

    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    manifest, files = pinned_perl_sources
    tag = {'notified':'perl-roots-notified','partial':'perl-roots-partial'}.get(
        online, 'perl-roots-live' if online else 'perl-roots-closed')
    config = _perl_roots_fixture(tmp_path, manifest, files, ['missing/lib'], tag)
    stamps = {name:(tmp_path / name).stat() for name in files}
    stamps = {name:[s.st_mtime_ns,s.st_ctime_ns,s.st_size] for name,s in stamps.items()}
    journal = Journal(Path(os.environ['QUALITY_LANGUAGE_EVIDENCE']) / (tag + '-workflow'), 4 * 2**20)
    target = manifest['witnesses']['definition']['file']
    importer = manifest['witnesses']['importer']['file']
    peer, generation, closed = None, -1, []
    rows = []

    def open_peer():
        nonlocal peer, generation
        generation += 1
        peer = RecordedGateway(OperationGateway(str(tmp_path),'daily',watch=False),
                               tmp_path,journal,generation=generation)

    async def dependencies(stage):
        response = await peer.execute_mcp('dependencies', {'path':target,'max_tokens':4000})
        assert not response.isError
        payload = json.loads(response.content[0].text)
        rows.append({'stage':stage,'gateway':generation,'response':payload})
        return payload['data']

    async def close_peer():
        nonlocal peer
        if peer is not None:
            await peer.close()
            closed.append(generation)
            peer = None

    try:
        open_peer()
        before = await dependencies('before-config-change')
        assert not before['imported_by']
        record_property('qualified_input', 'true')
        record_property('native_pinned_files', str(len(files)))
        if online in ('notified','partial'):
            stores = next(iter(peer.peer._stores.values()))
            ast = stores['service']._ast_service
            assert ast._hydration_state.phase == 'ready' and ast._snapshot_start is not None
            response = await peer.execute_mcp('notify_file_changed', {'files':[importer],'max_tokens':4000})
            assert not response.isError
            assert ast._hydration_state.phase == 'ready' and ast._snapshot_start is None
            record_property('notified_ready_without_snapshot', 'true')
            if online == 'partial':
                # Explicit controlled incomplete state, not a naturally slow
                # hydration claim. Real pinned parsing/gateway stay in use.
                ast.stop_hydration()
                ast._hydration_state.phase = 'references'
                record_property('controlled_partial_state', 'true')
            evidence(tag + '-pre-policy-state.json', {
                'phase':ast._hydration_state.phase,'snapshot_absent':ast._snapshot_start is None,
                'controlled_partial':online=='partial',
            })
        if not online:
            await close_peer()
        config.write_text('[perl]\nmodule_roots = ["dist/Carp/lib"]\n')
        if not online:
            open_peer()
        await dependencies('after-config-only-change')
        if online in ('notified','partial'):
            await dependencies('repeated-after-config-change')
        await close_peer()
        open_peer()
        await dependencies('reopened-after-change')
    finally:
        await close_peer()
        after = {name:(tmp_path / name).stat() for name in files}
        after = {name:[s.st_mtime_ns,s.st_ctime_ns,s.st_size] for name,s in after.items()}
        evidence(tag + '-observations.json', {'rows':rows,'closed':closed,
                 'expected_importer':importer,'source_stamps_before':stamps,
                 'source_stamps_after':after,'source_unchanged':all(
                     (tmp_path / name).read_bytes()==raw for name,raw in files.items())})
    assert stamps==after and all((tmp_path / name).read_bytes()==raw for name,raw in files.items())
    record_property('source_stamps_unchanged', 'true')
    record_property('observed_importers', json.dumps([r['response']['data']['imported_by'] for r in rows]))
    expected_rows = 4 if online in ('notified','partial') else 3
    assert len(rows)==expected_rows and all(importer in r['response']['data']['imported_by'] for r in rows[1:]), 'REGRESSION: Perl config-only dependencies remain stale across refresh or reopen'


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


@pytest.fixture(scope='session')
def pinned_cli_go_source():
    assert os.environ.get('QUALITY_ALLOW_DOWNLOADS') == '1', 'Pinned source acquisition requires explicit CI opt-in'
    manifest = json.loads((Path(__file__).resolve().parents[1] / 'scripts/go_signature_fixture.json').read_bytes())
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
    evidence('cli-go-signature-receipt.json', manifest)
    return manifest, files


def test_cli_pinned_go_signature_metadata(pinned_cli_go_source, tmp_path):
    import importlib.metadata
    import re
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

    import tree_sitter
    import tree_sitter_go
    from attocode_intel._internal.integrations.context import ast_service, codebase_ast, ts_parser
    from attocode_intel._internal.integrations.context.ast_chunker import chunk_file
    from attocode_intel._internal.integrations.context.ast_service import ASTService
    from attocode_intel._internal.integrations.context.syntax_evidence import syntax_tree

    manifest, files = pinned_cli_go_source
    name = manifest['targets'][0]['file']
    source = files[name].decode()
    ast = native(name, source, 'go', 'cli-go-signatures')
    raw = ts_parser.ts_parse_file(name, source, 'go')
    tree = syntax_tree(name, source, 'go')
    parser_matches = ts_parser._get_parser('go').language == tree_sitter.Language(tree_sitter_go.language())
    dist = importlib.metadata.distribution('tree-sitter-go')
    origin = Path(tree_sitter_go.__file__).resolve()
    assert any(Path(dist.locate_file(p)).resolve() == origin for p in dist.files or [])
    chunks = {c.name: c.metadata for c in chunk_file(name, name, content=source) if c.chunk_type == 'function'}
    evidence('cli-go-signature-results.json', {'path': name, 'has_error': tree.root_node.has_error,
             'end_byte': tree.root_node.end_byte, 'bytes': len(files[name]),
             'standalone_grammar_matches': parser_matches, 'go_origin': str(origin), 'go_version': dist.version,
             'raw_functions': raw['functions'], 'functions': [asdict(f) for f in ast.functions], 'chunks': chunks})
    assert parser_matches and dist.version == manifest['grammar_version']
    assert not tree.root_node.has_error and tree.root_node.end_byte == len(files[name])

    def tokens(text):
        return re.findall(r'[A-Za-z_]\w*|\d+|[^\s]', text)

    for target in manifest['targets']:
        function = next(f for f in ast.functions if f.name == target['symbol'])
        raw_function = next(f for f in raw['functions'] if f['name'] == target['symbol'])
        assert function.start_line <= target['line'] <= function.end_line
        assert raw_function['parameters'] == [p.name for p in function.parameters] == [p['name'] for p in target['parameters']]
        for actual, expected in zip(function.parameters, target['parameters'], strict=True):
            assert tokens(raw_function['param_types'][expected['name']]) == tokens(actual.type_annotation) == tokens(expected['type'])
            assert actual.is_rest is expected['is_rest']
        assert tokens(raw_function['return_type']) == tokens(function.return_type) == tokens(target['return_type'])
        assert target['symbol'] + '(' + ', '.join(p['name'] for p in target['parameters']) + ')' in chunks[target['symbol']]
        assert '-> ' + target['return_type'] in chunks[target['symbol']]

    with TemporaryDirectory(prefix='cli-go-cache-', dir=tmp_path) as directory:
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
    evidence('cli-go-cache-restart.json', {'path': name, 'source_sha256': hashlib.sha256(files[name]).hexdigest(),
             'expected': expected, 'restored': restored, 'expected_symbols': expected_symbols,
             'restored_symbols': restored_symbols, 'definitions_equal': True, 'store_counts_equal': True,
             'restart_parse_calls': parse.call_count, 'discovery_parse_calls': discover.call_count,
             'source_unchanged': True, 'owned_cleanup': not root.exists()})


def test_cli_pinned_go_module_binding_scope(pinned_cli_go_source, tmp_path):
    import importlib.metadata
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

    import tree_sitter
    import tree_sitter_go
    from attocode_intel._internal.integrations.context import ast_service, codebase_ast, ts_parser
    from attocode_intel._internal.integrations.context.ast_service import ASTService
    from attocode_intel._internal.integrations.context.syntax_evidence import syntax_tree

    signature_manifest, files = pinned_cli_go_source
    manifest = json.loads((Path(__file__).resolve().parents[1] / 'scripts/go_binding_fixture.json').read_bytes())
    assert (manifest['repo'], manifest['commit'], manifest['files']) == (
        signature_manifest['repo'], signature_manifest['commit'], signature_manifest['files'])
    target = manifest['local_declaration']
    name = target['file']
    raw_bytes = files[name]
    expected_file = manifest['files'][name]
    assert len(raw_bytes) == expected_file['bytes'] and hashlib.sha256(raw_bytes).hexdigest() == expected_file['sha256']
    assert hashlib.sha1(b'blob ' + str(len(raw_bytes)).encode() + b'\0' + raw_bytes).hexdigest() == expected_file['git_blob_sha1']
    source = raw_bytes.decode()
    assert source.splitlines()[target['line'] - 1] == target['text']
    assert source.splitlines()[target['function_start'] - 1] == target['function_header']
    evidence('cli-go-binding-receipt.json', manifest)
    ast = native(name, source, 'go', 'cli-go-bindings')
    raw = ts_parser.ts_parse_file(name, source, 'go')
    tree = syntax_tree(name, source, 'go')
    dist = importlib.metadata.distribution('tree-sitter-go')
    origin = Path(tree_sitter_go.__file__).resolve()
    assert any(Path(dist.locate_file(p)).resolve() == origin for p in dist.files or [])
    parser_matches = ts_parser._get_parser('go').language == tree_sitter.Language(tree_sitter_go.language())
    root, closed, restart_closed = None, False, False
    try:
        with TemporaryDirectory(prefix='cli-go-bindings-', dir=tmp_path) as directory:
            root = Path(directory)
            path = root / name
            path.parent.mkdir(parents=True)
            path.write_bytes(raw_bytes)
            service = ASTService(str(root))
            try:
                service.initialize_skeleton(indexing_depth='eager')
                variables = [asdict(loc) for loc in service.get_file_symbols(name)
                             if loc.kind == 'variable' and loc.qualified_name == loc.name]
                definitions = {k: [asdict(loc) for loc in values]
                               for k, values in service._index.definitions.items()}
                function = next(f for f in ast.functions if f.name == target['enclosing_function'])
                evidence('cli-go-binding-results.json', {'path': name, 'bytes': len(raw_bytes),
                         'has_error': tree.root_node.has_error, 'end_byte': tree.root_node.end_byte,
                         'standalone_grammar_matches': parser_matches, 'go_version': dist.version, 'go_origin': str(origin),
                         'raw_bindings': raw['top_level_vars'], 'ast_bindings': ast.top_level_vars,
                         'cached_bindings': service._ast_cache[name].top_level_vars, 'indexed_globals': variables,
                         'definitions': definitions, 'enclosing_function': asdict(function),
                         'source_unchanged': path.read_bytes() == raw_bytes})
                assert parser_matches and dist.version == manifest['grammar_version']
                assert not tree.root_node.has_error and tree.root_node.end_byte == len(raw_bytes)
                assert function.start_line == target['function_start'] < target['line'] < target['function_end'] == function.end_line
                assert set(manifest['required_functions']) <= set(definitions)
                assert raw['top_level_vars'] == ast.top_level_vars == service._ast_cache[name].top_level_vars == manifest['expected_global_bindings']
                assert [loc['name'] for loc in variables] == manifest['expected_global_bindings']
                assert target['name'] not in definitions
                assert path.read_bytes() == raw_bytes
                expected = {k: asdict(v) for k, v in service._ast_cache.items()}
                counts = service._store.stats()
            finally:
                service.stop_hydration()
                service._store.close()
                closed = True
            second = ASTService(str(root))
            try:
                with (patch.object(ast_service, 'parse_file', side_effect=AssertionError('restart reparsed')) as parse,
                      patch.object(codebase_ast, 'parse_file', side_effect=AssertionError('discovery reparsed')) as discover):
                    assert second.initialize_skeleton().phase == 'ready'
                parse.assert_not_called()
                discover.assert_not_called()
                restored = {k: asdict(v) for k, v in second._ast_cache.items()}
                restored_symbols = {k: [asdict(loc) for loc in values]
                                    for k, values in second._index.definitions.items()}
                evidence('cli-go-binding-restart.json', {'expected': expected, 'restored': restored,
                         'expected_symbols': definitions, 'restored_symbols': restored_symbols,
                         'restart_parse_calls': parse.call_count, 'discovery_parse_calls': discover.call_count,
                         'store_counts_equal': second._store.stats() == counts,
                         'source_unchanged': path.read_bytes() == raw_bytes})
                assert restored == expected
                assert restored_symbols == definitions
                assert set(manifest['required_functions']) <= set(restored_symbols)
                assert target['name'] not in restored_symbols
                assert restored[name]['top_level_vars'] == manifest['expected_global_bindings']
                assert second._store.stats() == counts and path.read_bytes() == raw_bytes
            finally:
                second.stop_hydration()
                second._store.close()
                restart_closed = True
    finally:
        evidence('cli-go-binding-lifecycle.json', {'owned_cleanup': root is not None and not root.exists(),
                                                'service_closed': closed, 'restart_service_closed': restart_closed})


@pytest.fixture(scope='session')
def pinned_go_ast_source():
    """Acquire immutable Go source and its license as data, never execute them."""
    assert os.environ.get('QUALITY_ALLOW_DOWNLOADS') == '1'
    manifest = json.loads((Path(__file__).resolve().parents[1] / 'scripts/go_type_fixture.json').read_bytes())
    files = {}
    for name, expected in manifest['files'].items():
        url = f"https://raw.githubusercontent.com/{manifest['repo']}/{manifest['commit']}/{name}"
        with urllib.request.urlopen(url, timeout=30) as response:
            raw = response.read(expected['bytes'] + 1)
        assert len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256']
        assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == expected['git_blob_sha1']
        files[name] = raw
    lines = files[manifest['source_path']].decode().splitlines()
    for target in manifest['targets']:
        assert lines[target['start_line'] - 1] == target['header']
        assert lines[target['end_line'] - 1].strip() == '}'
        assert '\n'.join(lines[i - 1].strip()[2:].strip() for i in target['doc_lines']) == target['docstring']
        for method in target['methods']:
            assert lines[method['start_line'] - 1] == method['header']
    for function in manifest['required_functions']:
        assert lines[function['line'] - 1] == function['header']
    evidence('go-ast-type-receipt.json', manifest)
    license_bytes = files[manifest['license_path']]
    evidence('go-ast-type-license.json', {'path': manifest['license_path'], 'source': license_bytes.decode(),
                                       'bytes': len(license_bytes), 'sha256': hashlib.sha256(license_bytes).hexdigest()})
    return manifest, files


def test_go_ast_pinned_type_bindings(pinned_go_ast_source, tmp_path):
    import importlib.metadata
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

    import tree_sitter
    import tree_sitter_go
    from attocode_intel._internal.integrations.context import ast_service, codebase_ast, ts_parser
    from attocode_intel._internal.integrations.context.ast_service import ASTService
    from attocode_intel._internal.integrations.context.syntax_evidence import syntax_tree

    manifest, files = pinned_go_ast_source
    name = manifest['source_path']
    source = files[name].decode()
    ast = native(name, source, 'go', 'go-ast-types')
    raw = ts_parser.ts_parse_file(name, source, 'go')
    tree = syntax_tree(name, source, 'go')
    dist = importlib.metadata.distribution('tree-sitter-go')
    origin = Path(tree_sitter_go.__file__).resolve()
    assert any(Path(dist.locate_file(p)).resolve() == origin for p in dist.files or [])
    parser_matches = ts_parser._get_parser('go').language == tree_sitter.Language(tree_sitter_go.language())
    root, first_closed, second_closed = None, False, False
    try:
        with TemporaryDirectory(prefix='go-ast-types-', dir=tmp_path) as directory:
            root = Path(directory)
            for path_name, data in files.items():
                path = root / path_name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            first = ASTService(str(root))
            try:
                first.initialize_skeleton(indexing_depth='eager')
                expected = {k: asdict(v) for k, v in first._ast_cache.items()}
                definitions = {k: [asdict(loc) for loc in values] for k, values in first._index.definitions.items()}
                counts = first._store.stats()
                evidence('go-ast-type-results.json', {'path': name, 'bytes': len(files[name]),
                         'has_error': tree.root_node.has_error, 'end_byte': tree.root_node.end_byte,
                         'go_version': dist.version, 'go_origin': str(origin), 'standalone_grammar_matches': parser_matches,
                         'raw_classes': raw['classes'], 'raw_functions': raw['functions'],
                         'classes': [asdict(c) for c in ast.classes], 'functions': [asdict(f) for f in ast.functions],
                         'cached_classes': [asdict(c) for c in first._ast_cache[name].classes],
                         'definitions': definitions, 'files_unchanged': all((root / k).read_bytes() == v for k, v in files.items())})
            finally:
                first.stop_hydration()
                first._store.close()
                first_closed = True
            second = ASTService(str(root))
            try:
                with (patch.object(ast_service, 'parse_file', side_effect=AssertionError('restart reparsed')) as parse,
                      patch.object(codebase_ast, 'parse_file', side_effect=AssertionError('discovery reparsed')) as discover):
                    assert second.initialize_skeleton().phase == 'ready'
                parse.assert_not_called()
                discover.assert_not_called()
                restored = {k: asdict(v) for k, v in second._ast_cache.items()}
                restored_symbols = {k: [asdict(loc) for loc in values] for k, values in second._index.definitions.items()}
                evidence('go-ast-type-restart.json', {'expected': expected, 'restored': restored,
                         'expected_symbols': definitions, 'restored_symbols': restored_symbols,
                         'restart_parse_calls': parse.call_count, 'discovery_parse_calls': discover.call_count,
                         'store_counts_equal': second._store.stats() == counts,
                         'files_unchanged': all((root / k).read_bytes() == v for k, v in files.items())})
                assert expected == restored and definitions == restored_symbols
                assert second._store.stats() == counts
                assert all((root / k).read_bytes() == v for k, v in files.items())
            finally:
                second.stop_hydration()
                second._store.close()
                second_closed = True
    finally:
        evidence('go-ast-type-lifecycle.json', {'owned_cleanup': root is not None and not root.exists(),
                                             'first_closed': first_closed, 'second_closed': second_closed})
    assert parser_matches and dist.version == manifest['grammar_version']
    assert not tree.root_node.has_error and tree.root_node.end_byte == len(files[name])
    assert set(manifest['required_control_types']) <= {c.name for c in ast.classes}
    assert {f['name'] for f in manifest['required_functions']} <= set(definitions)
    assert set(expected) == {name}
    assert [asdict(c) for c in ast.classes] == expected[name]['classes']
    for target in manifest['targets']:
        actual = [c for c in ast.classes if c.name == target['name']]
        raw_actual = [c for c in raw['classes'] if c['name'] == target['name']]
        assert len(actual) == len(raw_actual) == 1, 'Pinned named type missing: ' + target['name']
        cls, raw_cls = actual[0], raw_actual[0]
        assert cls.start_line == raw_cls['start_line'] == target['start_line']
        assert cls.end_line == raw_cls['end_line'] == target['end_line']
        assert cls.docstring == raw_cls['docstring'] == target['docstring']
        assert any(loc['kind'] == 'class' and loc['start_line'] == target['start_line'] and
                   loc['end_line'] == target['end_line'] for loc in definitions[target['name']])
        assert [m.name for m in cls.methods] == [m['name'] for m in raw_cls['methods']] == [m['name'] for m in target['methods']]
        for method, raw_method, wanted in zip(cls.methods, raw_cls['methods'], target['methods'], strict=True):
            assert raw_method['parent_class'] == cls.name
            assert method.start_line == raw_method['start_line'] == wanted['start_line']
            assert method.end_line == raw_method['end_line'] == wanted['end_line']
            assert method.visibility == raw_method['visibility'] == wanted['visibility']
            assert any(loc['qualified_name'] == cls.name + '.' + method.name and loc['kind'] == 'method' and
                       loc['start_line'] == wanted['start_line'] for loc in definitions.get(cls.name + '.' + method.name, []))


@pytest.fixture(scope='session')
def pinned_go_receiver_source():
    """Acquire immutable Go source and its license as data, never execute them."""
    assert os.environ.get('QUALITY_ALLOW_DOWNLOADS') == '1'
    manifest = json.loads((Path(__file__).resolve().parents[1] / 'scripts/go_receiver_fixture.json').read_bytes())
    files = {}
    for name, expected in manifest['files'].items():
        url = f"https://raw.githubusercontent.com/{manifest['repo']}/{manifest['commit']}/{name}"
        with urllib.request.urlopen(url, timeout=30) as response:
            raw = response.read(expected['bytes'] + 1)
        assert len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256']
        assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == expected['git_blob_sha1']
        files[name] = raw
    lines = files[manifest['source_path']].decode().splitlines()
    for target in manifest['targets']:
        assert lines[target['start_line'] - 1] == target['header']
        assert lines[target['end_line'] - 1].strip() == '}'
        assert '\n'.join(lines[i - 1].strip()[2:].strip() for i in target['doc_lines']) == target['docstring']
        for method in target['methods']:
            assert lines[method['start_line'] - 1] == method['header']
    for function in manifest['required_functions']:
        assert lines[function['line'] - 1] == function['header']
    evidence('go-atomic-receiver-receipt.json', manifest)
    license_bytes = files[manifest['license_path']]
    evidence('go-atomic-receiver-license.json', {'path': manifest['license_path'], 'source': license_bytes.decode(),
                                       'bytes': len(license_bytes), 'sha256': hashlib.sha256(license_bytes).hexdigest()})
    return manifest, files


def test_go_atomic_pinned_receiver_ownership(pinned_go_receiver_source, tmp_path):
    import importlib.metadata
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

    import tree_sitter
    import tree_sitter_go
    from attocode_intel._internal.integrations.context import ast_service, codebase_ast, ts_parser
    from attocode_intel._internal.integrations.context.ast_service import ASTService
    from attocode_intel._internal.integrations.context.syntax_evidence import syntax_tree

    manifest, files = pinned_go_receiver_source
    name = manifest['source_path']
    source = files[name].decode()
    ast = native(name, source, 'go', 'go-atomic-receivers')
    raw = ts_parser.ts_parse_file(name, source, 'go')
    tree = syntax_tree(name, source, 'go')
    dist = importlib.metadata.distribution('tree-sitter-go')
    origin = Path(tree_sitter_go.__file__).resolve()
    assert any(Path(dist.locate_file(p)).resolve() == origin for p in dist.files or [])
    parser_matches = ts_parser._get_parser('go').language == tree_sitter.Language(tree_sitter_go.language())
    root, first_closed, second_closed = None, False, False
    try:
        with TemporaryDirectory(prefix='go-atomic-receivers-', dir=tmp_path) as directory:
            root = Path(directory)
            for path_name, data in files.items():
                path = root / path_name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            first = ASTService(str(root))
            try:
                first.initialize_skeleton(indexing_depth='eager')
                expected = {k: asdict(v) for k, v in first._ast_cache.items()}
                definitions = {k: [asdict(loc) for loc in values] for k, values in first._index.definitions.items()}
                counts = first._store.stats()
                evidence('go-atomic-receiver-results.json', {'path': name, 'bytes': len(files[name]),
                         'has_error': tree.root_node.has_error, 'end_byte': tree.root_node.end_byte,
                         'go_version': dist.version, 'go_origin': str(origin), 'standalone_grammar_matches': parser_matches,
                         'raw_classes': raw['classes'], 'raw_functions': raw['functions'],
                         'classes': [asdict(c) for c in ast.classes], 'functions': [asdict(f) for f in ast.functions],
                         'cached_classes': [asdict(c) for c in first._ast_cache[name].classes],
                         'definitions': definitions, 'files_unchanged': all((root / k).read_bytes() == v for k, v in files.items())})
            finally:
                first.stop_hydration()
                first._store.close()
                first_closed = True
            second = ASTService(str(root))
            try:
                with (patch.object(ast_service, 'parse_file', side_effect=AssertionError('restart reparsed')) as parse,
                      patch.object(codebase_ast, 'parse_file', side_effect=AssertionError('discovery reparsed')) as discover):
                    assert second.initialize_skeleton().phase == 'ready'
                parse.assert_not_called()
                discover.assert_not_called()
                restored = {k: asdict(v) for k, v in second._ast_cache.items()}
                restored_symbols = {k: [asdict(loc) for loc in values] for k, values in second._index.definitions.items()}
                evidence('go-atomic-receiver-restart.json', {'expected': expected, 'restored': restored,
                         'expected_symbols': definitions, 'restored_symbols': restored_symbols,
                         'restart_parse_calls': parse.call_count, 'discovery_parse_calls': discover.call_count,
                         'store_counts_equal': second._store.stats() == counts,
                         'files_unchanged': all((root / k).read_bytes() == v for k, v in files.items())})
                assert expected == restored and definitions == restored_symbols
                assert second._store.stats() == counts
                assert all((root / k).read_bytes() == v for k, v in files.items())
            finally:
                second.stop_hydration()
                second._store.close()
                second_closed = True
    finally:
        evidence('go-atomic-receiver-lifecycle.json', {'owned_cleanup': root is not None and not root.exists(),
                                             'first_closed': first_closed, 'second_closed': second_closed})
    assert parser_matches and dist.version == manifest['grammar_version']
    assert not tree.root_node.has_error and tree.root_node.end_byte == len(files[name])
    assert set(manifest['required_control_types']) <= {c.name for c in ast.classes}
    assert {f['name'] for f in manifest['required_functions']} <= set(definitions)
    assert set(expected) == {name}
    assert [f.name for f in ast.functions] == [f['name'] for f in raw['functions']] == ['b32']
    assert (ast.functions[0].start_line, ast.functions[0].end_line) == (31, 36)
    assert [asdict(c) for c in ast.classes] == expected[name]['classes']
    for target in manifest['targets']:
        actual = [c for c in ast.classes if c.name == target['name']]
        raw_actual = [c for c in raw['classes'] if c['name'] == target['name']]
        assert len(actual) == len(raw_actual) == 1, 'Pinned named type missing: ' + target['name']
        cls, raw_cls = actual[0], raw_actual[0]
        assert cls.start_line == raw_cls['start_line'] == target['start_line']
        assert cls.end_line == raw_cls['end_line'] == target['end_line']
        assert cls.docstring == raw_cls['docstring'] == target['docstring']
        assert any(loc['kind'] == 'class' and loc['start_line'] == target['start_line'] and
                   loc['end_line'] == target['end_line'] for loc in definitions[target['name']])
        assert [m.name for m in cls.methods] == [m['name'] for m in raw_cls['methods']] == [m['name'] for m in target['methods']]
        for method, raw_method, wanted in zip(cls.methods, raw_cls['methods'], target['methods'], strict=True):
            assert raw_method['parent_class'] == cls.name
            assert method.start_line == raw_method['start_line'] == wanted['start_line']
            assert method.end_line == raw_method['end_line'] == wanted['end_line']
            assert method.visibility == raw_method['visibility'] == wanted['visibility']
            assert raw_method['parameters'] == [p.name for p in method.parameters] == wanted['parameters']
            assert raw_method.get('param_types', {}) == {p.name: p.type_annotation for p in method.parameters} == wanted['param_types']
            assert raw_method['return_type'] == method.return_type == wanted['return_type']
            assert not any(p.is_rest or p.is_kwargs for p in method.parameters)
            assert any(loc['qualified_name'] == cls.name + '.' + method.name and loc['kind'] == 'method' and
                       loc['start_line'] == wanted['start_line'] for loc in definitions.get(cls.name + '.' + method.name, []))


def test_crystal_method_definition_native_range():
    ast = native('greet.cr', 'def greet(name)\n  name\nend\n', 'crystal', 'crystal-method')
    assert [(f.name, f.start_line, f.end_line) for f in ast.functions] == [('greet', 1, 3)], 'language coverage: Crystal native method definition missing'


@pytest.fixture(scope='session')
def pinned_go_stdlib_sources():
    """The real std module, source, caller/test and license are data only."""
    assert os.environ.get('QUALITY_ALLOW_DOWNLOADS') == '1'
    manifest = json.loads((Path(__file__).resolve().parents[1] / 'scripts/go_stdlib_fixture.json').read_bytes())
    files = {}
    for name, expected in manifest['files'].items():
        with urllib.request.urlopen(f"https://raw.githubusercontent.com/{manifest['repo']}/{manifest['commit']}/{name}", timeout=30) as response:
            raw = response.read(expected['bytes'] + 1)
        assert len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256']
        assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == expected['git_blob_sha1']
        files[name] = raw
    for witness in manifest['witnesses'].values():
        assert files[witness['file']].decode().splitlines()[witness['line'] - 1] == witness['text']
    evidence('go-stdlib-receipt.json', manifest)
    evidence('go-stdlib-data-files.json', {name: raw.decode() for name, raw in files.items() if not name.endswith('.go')})
    return manifest, files


async def test_go_stdlib_pinned_import_and_test_workflow(tmp_path, monkeypatch, pinned_go_stdlib_sources):
    import importlib.metadata
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

    import tree_sitter
    import tree_sitter_go
    from attocode_intel._internal.integrations.context import ast_service, codebase_ast, ts_parser
    from attocode_intel._internal.integrations.context.ast_service import ASTService
    from attocode_intel._internal.integrations.context.syntax_evidence import (
        reference_candidates,
        syntax_tree,
    )
    from attocode_intel.gateway import OperationGateway

    from eval.quality.corpus_capture import RecordedGateway
    from eval.quality.experiment_evidence import Journal

    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    manifest, files = pinned_go_stdlib_sources
    source, test = manifest['source_path'], manifest['test_path']
    asts, syntax, calls = {}, {}, {}
    for name in (source, test):
        text = files[name].decode()
        asts[name] = native(name, text, 'go', 'go-stdlib-' + Path(name).name)
        tree = syntax_tree(name, text, 'go')
        syntax[name] = {'has_error': tree.root_node.has_error, 'end_byte': tree.root_node.end_byte,
                        'bytes': len(files[name]), 'tree': str(tree.root_node)}
        calls[name] = reference_candidates(name, text, 'go')
    dist = importlib.metadata.distribution('tree-sitter-go')
    origin = Path(tree_sitter_go.__file__).resolve()
    assert any(Path(dist.locate_file(p)).resolve() == origin for p in dist.files or [])
    matches = ts_parser._get_parser('go').language == tree_sitter.Language(tree_sitter_go.language())
    evidence('go-stdlib-native-validation.json', {'syntax': syntax, 'calls': calls,
             'go_version': dist.version, 'go_origin': str(origin), 'standalone_grammar_matches': matches,
             'imports': {name: [asdict(i) for i in ast.imports] for name, ast in asts.items()}})
    assert matches and dist.version == manifest['grammar_version']
    assert all(not r['has_error'] and r['end_byte'] == r['bytes'] for r in syntax.values())
    journal = Journal(Path(os.environ['QUALITY_LANGUAGE_EVIDENCE']) / 'go-stdlib-workflow', 8 * 2**20)
    responses = {}
    root = None
    closed = {'gateway_first': False, 'gateway_restart': False, 'cache_first': False, 'cache_restart': False}
    try:
        with TemporaryDirectory(prefix='go-stdlib-', dir=tmp_path) as directory:
            root = Path(directory)
            for name, data in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)

            async def request(peer, tag, tool, arguments):
                result = await peer.execute_mcp(tool, {'max_tokens': 4000, **arguments})
                responses[tag] = {'is_error': result.isError, 'response': json.loads(result.content[0].text)}
                evidence('go-stdlib-public-responses.json', responses)

            peer = RecordedGateway(OperationGateway(str(root), 'daily', watch=False), root, journal)
            try:
                for tag, tool, arguments in [
                    ('definition', 'inspect_symbol', {'symbol_name': 'Pointer.Load', 'file_path': source, 'line': 54}),
                    ('test_definition', 'inspect_symbol', {'symbol_name': 'TestLoadPointerMethod', 'file_path': test, 'line': 1605}),
                    ('dependencies', 'dependencies', {'path': source}),
                    ('impact', 'impact_analysis', {'changed_files': [source]}),
                    ('tests', 'suggest_tests', {'files': [source], 'symbol_name': 'Pointer.Load'}),
                    ('member_references', 'cross_references', {'symbol_name': 'Pointer.Load', 'file_path': source, 'line': 54}),
                    ('test_dependencies', 'dependencies', {'path': test}),
                ]:
                    await request(peer, tag, tool, arguments)
            finally:
                await peer.close()
                closed['gateway_first'] = True

            first = ASTService(str(root))
            try:
                first.initialize_skeleton(indexing_depth='eager')
                expected = {k: asdict(v) for k, v in first._ast_cache.items()}
                definitions = {k: [asdict(loc) for loc in values] for k, values in first._index.definitions.items()}
                counts = first._store.stats()
                evidence('go-stdlib-cache-before.json', {'asts': expected, 'symbols': definitions, 'counts': counts})
            finally:
                first.stop_hydration()
                first._store.close()
                closed['cache_first'] = True
            second = ASTService(str(root))
            try:
                with (patch.object(ast_service, 'parse_file', side_effect=AssertionError('restart reparsed')) as parse,
                      patch.object(codebase_ast, 'parse_file', side_effect=AssertionError('discovery reparsed')) as discover):
                    assert second.initialize_skeleton().phase == 'ready'
                restored = {k: asdict(v) for k, v in second._ast_cache.items()}
                symbols = {k: [asdict(loc) for loc in values] for k, values in second._index.definitions.items()}
                evidence('go-stdlib-cache-restart.json', {'asts': restored, 'symbols': symbols,
                         'counts': second._store.stats(), 'service_parse_calls': parse.call_count,
                         'discovery_parse_calls': discover.call_count})
                assert expected == restored and definitions == symbols and second._store.stats() == counts
                assert parse.call_count == discover.call_count == 0
            finally:
                second.stop_hydration()
                second._store.close()
                closed['cache_restart'] = True

            peer = RecordedGateway(OperationGateway(str(root), 'daily', watch=False), root, journal, generation=1)
            try:
                with (patch.object(ast_service, 'parse_file', side_effect=AssertionError('public restart reparsed')) as parse,
                      patch.object(codebase_ast, 'parse_file', side_effect=AssertionError('public discovery reparsed')) as discover):
                    await request(peer, 'restart_dependencies', 'dependencies', {'path': source})
                evidence('go-stdlib-public-restart.json', {'service_parse_calls': parse.call_count,
                         'discovery_parse_calls': discover.call_count})
                assert parse.call_count == discover.call_count == 0
            finally:
                await peer.close()
                closed['gateway_restart'] = True
            evidence('go-stdlib-source-after.json', {'files_unchanged': all((root / name).read_bytes() == raw for name, raw in files.items())})
            assert all((root / name).read_bytes() == raw for name, raw in files.items())
    finally:
        evidence('go-stdlib-lifecycle.json', {**closed, 'owned_cleanup': root is not None and not root.exists()})

    assert set(expected) == {source, test}
    for name, ast in asts.items():
        assert expected[name]['classes'] == [asdict(c) for c in ast.classes]
        assert expected[name]['functions'] == [asdict(f) for f in ast.functions]
    imported = manifest['witnesses']['importer']
    assert any(i.module == imported['module'] and i.alias == '.' and i.line == 13 for i in asts[test].imports)
    for role in ('store_call', 'load_call'):
        wanted = manifest['witnesses'][role]
        assert (wanted['callee'], 'call', wanted['line']) in calls[test]
    assert all(not r['is_error'] for r in responses.values())
    for tag, path, line in [('definition', source, 54), ('test_definition', test, 1605)]:
        data = responses[tag]['response']['data']
        assert data['status'] == 'found' and data['definition']['file_path'] == path
        assert data['definition']['start_line'] == line
    refs = responses['member_references']['response']
    assert not any(r['file_path'] == test and r['line'] == 1618 for r in refs['data']['references'])
    assert refs['metadata']['absence_proven'] is False
    for tag in ('dependencies', 'restart_dependencies'):
        assert responses[tag]['response']['data']['imported_by'] == [test]
    assert test in responses['impact']['response']['data']['impacted_files']
    assert any(r['file_path'] == test and r['evidence']['import_distance'] == 1
               for r in responses['tests']['response']['data']['candidates'])


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


@pytest.fixture(scope='session')
def pinned_go_crossfile_sources():
    """The real std module, source, caller/test and license are data only."""
    assert os.environ.get('QUALITY_ALLOW_DOWNLOADS') == '1'
    manifest = json.loads((Path(__file__).resolve().parents[1] / 'scripts/go_crossfile_fixture.json').read_bytes())
    files = {}
    for name, expected in manifest['files'].items():
        with urllib.request.urlopen(f"https://raw.githubusercontent.com/{manifest['repo']}/{manifest['commit']}/{name}", timeout=30) as response:
            raw = response.read(expected['bytes'] + 1)
        assert len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256']
        assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == expected['git_blob_sha1']
        files[name] = raw
    for witness in manifest['witnesses'].values():
        assert files[witness['file']].decode().splitlines()[witness['line'] - 1] == witness['text']
    evidence('go-crossfile-receipt.json', manifest)
    evidence('go-crossfile-data-files.json', {name: raw.decode() for name, raw in files.items() if not name.endswith('.go')})
    return manifest, files


async def test_go_regexp_crossfile_method_workflow(tmp_path, monkeypatch, record_property, pinned_go_crossfile_sources):
    import importlib.metadata
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

    import tree_sitter
    import tree_sitter_go
    from attocode_intel._internal.integrations.context import ast_service, codebase_ast, ts_parser
    from attocode_intel._internal.integrations.context.ast_service import ASTService
    from attocode_intel._internal.integrations.context.syntax_evidence import (
        reference_candidates,
        syntax_tree,
    )
    from attocode_intel.gateway import OperationGateway

    from eval.quality.corpus_capture import RecordedGateway
    from eval.quality.experiment_evidence import Journal

    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    manifest, files = pinned_go_crossfile_sources
    source, test = manifest['source_path'], manifest['test_path']
    asts, syntax, calls = {}, {}, {}
    for name in (manifest['type_path'], source, test):
        text = files[name].decode()
        asts[name] = native(name, text, 'go', 'go-crossfile-' + Path(name).name)
        tree = syntax_tree(name, text, 'go')
        syntax[name] = {'has_error': tree.root_node.has_error, 'end_byte': tree.root_node.end_byte,
                        'bytes': len(files[name]), 'tree': str(tree.root_node)}
        calls[name] = reference_candidates(name, text, 'go')
    dist = importlib.metadata.distribution('tree-sitter-go')
    origin = Path(tree_sitter_go.__file__).resolve()
    assert any(Path(dist.locate_file(p)).resolve() == origin for p in dist.files or [])
    matches = ts_parser._get_parser('go').language == tree_sitter.Language(tree_sitter_go.language())
    evidence('go-crossfile-native-validation.json', {'syntax': syntax, 'calls': calls,
             'go_version': dist.version, 'go_origin': str(origin), 'standalone_grammar_matches': matches,
             'imports': {name: [asdict(i) for i in ast.imports] for name, ast in asts.items()}})
    assert matches and dist.version == manifest['grammar_version']
    assert all(not r['has_error'] and r['end_byte'] == r['bytes'] for r in syntax.values())
    record_property('qualified_input', 'true')
    evidence('go-crossfile-raw.json', {name: ts_parser.ts_parse_file(name, files[name].decode(), 'go') for name in asts})
    journal = Journal(Path(os.environ['QUALITY_LANGUAGE_EVIDENCE']) / 'go-crossfile-workflow', 8 * 2**20)
    responses = {}
    root = None
    closed = {'gateway_first': False, 'gateway_restart': False, 'cache_first': False, 'cache_restart': False}
    try:
        with TemporaryDirectory(prefix='go-crossfile-', dir=tmp_path) as directory:
            root = Path(directory)
            for name, data in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)

            async def request(peer, tag, tool, arguments):
                result = await peer.execute_mcp(tool, {'max_tokens': 4000, **arguments})
                responses[tag] = {'is_error': result.isError, 'response': json.loads(result.content[0].text)}
                evidence('go-crossfile-public-responses.json', responses)

            peer = RecordedGateway(OperationGateway(str(root), 'daily', watch=False), root, journal)
            try:
                for tag, tool, arguments in [
                    ('definition', 'inspect_symbol', {'symbol_name': 'Regexp.doMatch', 'file_path': source, 'line': 513}),
                    ('execute_definition', 'inspect_symbol', {'symbol_name': 'Regexp.doExecute', 'file_path': source, 'line': 521}),
                    ('dependencies', 'dependencies', {'path': source}),
                    ('impact', 'impact_analysis', {'changed_files': [source]}),
                    ('tests', 'suggest_tests', {'files': [source], 'symbol_name': 'Regexp.doExecute'}),
                    ('member_references', 'cross_references', {'symbol_name': 'Regexp.doExecute', 'file_path': source, 'line': 521}),
                    ('test_dependencies', 'dependencies', {'path': test}),
                ]:
                    await request(peer, tag, tool, arguments)
            finally:
                await peer.close()
                closed['gateway_first'] = True

            first = ASTService(str(root))
            try:
                first.initialize_skeleton(indexing_depth='eager')
                expected = {k: asdict(v) for k, v in first._ast_cache.items()}
                definitions = {k: [asdict(loc) for loc in values] for k, values in first._index.definitions.items()}
                counts = first._store.stats()
                evidence('go-crossfile-cache-before.json', {'asts': expected, 'symbols': definitions, 'counts': counts})
            finally:
                first.stop_hydration()
                first._store.close()
                closed['cache_first'] = True
            second = ASTService(str(root))
            try:
                with (patch.object(ast_service, 'parse_file', side_effect=AssertionError('restart reparsed')) as parse,
                      patch.object(codebase_ast, 'parse_file', side_effect=AssertionError('discovery reparsed')) as discover):
                    assert second.initialize_skeleton().phase == 'ready'
                restored = {k: asdict(v) for k, v in second._ast_cache.items()}
                symbols = {k: [asdict(loc) for loc in values] for k, values in second._index.definitions.items()}
                evidence('go-crossfile-cache-restart.json', {'asts': restored, 'symbols': symbols,
                         'counts': second._store.stats(), 'service_parse_calls': parse.call_count,
                         'discovery_parse_calls': discover.call_count})
                assert expected == restored and definitions == symbols and second._store.stats() == counts
                assert parse.call_count == discover.call_count == 0
            finally:
                second.stop_hydration()
                second._store.close()
                closed['cache_restart'] = True

            peer = RecordedGateway(OperationGateway(str(root), 'daily', watch=False), root, journal, generation=1)
            try:
                with (patch.object(ast_service, 'parse_file', side_effect=AssertionError('public restart reparsed')) as parse,
                      patch.object(codebase_ast, 'parse_file', side_effect=AssertionError('public discovery reparsed')) as discover):
                    await request(peer, 'restart_dependencies', 'dependencies', {'path': source})
                evidence('go-crossfile-public-restart.json', {'service_parse_calls': parse.call_count,
                         'discovery_parse_calls': discover.call_count})
                assert parse.call_count == discover.call_count == 0
            finally:
                await peer.close()
                closed['gateway_restart'] = True
            evidence('go-crossfile-source-after.json', {'files_unchanged': all((root / name).read_bytes() == raw for name, raw in files.items())})
            assert all((root / name).read_bytes() == raw for name, raw in files.items())
    finally:
        evidence('go-crossfile-lifecycle.json', {**closed, 'owned_cleanup': root is not None and not root.exists()})

    assert set(expected) == {manifest['type_path'], source, test}
    for name, ast in asts.items():
        assert expected[name]['classes'] == [asdict(c) for c in ast.classes]
        assert expected[name]['functions'] == [asdict(f) for f in ast.functions]
    assert any(i.module == 'regexp' and i.line == 9 for i in asts[test].imports)
    assert ('re.doExecute', 'call', 514) in calls[source]
    assert all(not r['is_error'] for r in responses.values())
    # All original responses, source and restart/cleanup evidence precede the
    # semantic assertion; a normal not-found response is a legitimate RED.
    for tag, symbol, line, end in [('definition', 'Regexp.doMatch', 513, 515),
                                   ('execute_definition', 'Regexp.doExecute', 521, 550)]:
        data = responses[tag]['response']['data']
        assert data.get('status') == 'found', 'REGRESSION: Go pinned cross-file method identity'
        definition = data['definition']
        assert (definition['qualified_name'], definition['kind'], definition['file_path'],
                definition['start_line'], definition['end_line']) == (symbol, 'method', source, line, end)
        assert manifest['witnesses']['definition' if tag == 'definition' else 'execute']['text'] in data['source']['text']
        assert any(f.qualified_name == symbol and f.is_method and f.start_line == line and f.end_line == end
                   for f in asts[source].functions)
        assert any(loc['qualified_name'] == symbol and loc['kind'] == 'method' and loc['file_path'] == source
                   and loc['start_line'] == line and loc['end_line'] == end
                   for values in definitions.values() for loc in values)
    refs = responses['member_references']['response']
    assert refs['metadata']['absence_proven'] is False and isinstance(refs['metadata']['analysis'], str)
    for tag in ('dependencies', 'restart_dependencies'):
        assert responses[tag]['response']['data']['imported_by'] == [test]
    assert test in responses['impact']['response']['data']['impacted_files']
    assert any(r['file_path'] == test and r['evidence']['import_distance'] == 1
               for r in responses['tests']['response']['data']['candidates'])


def test_go_pinned_whole_file_deletion_events(tmp_path, record_property, pinned_go_crossfile_sources):
    import runpy
    from tempfile import TemporaryDirectory

    # An exact source path avoids depending on pytest's namespace import mode.
    helper = runpy.run_path(str(Path(__file__).with_name('test_go_deletion_events.py')))['observe_deletion']
    manifest, files = pinned_go_crossfile_sources
    name = manifest['source_path']
    for source in (manifest['type_path'], name, manifest['test_path']):
        native(source, files[source].decode(), 'go', 'go-deletion-' + Path(source).name)
        from attocode_intel._internal.integrations.context.syntax_evidence import syntax_tree
        tree = syntax_tree(source, files[source].decode(), 'go')
        assert tree is not None and not tree.root_node.has_error
        assert tree.root_node.end_byte == len(files[source])
    records = []
    for consumer in ['notify', 'refresh', 'context']:
        root = None
        try:
            with TemporaryDirectory(prefix='go-deletion-', dir=tmp_path) as directory:
                root = Path(directory)
                for path, raw in files.items():
                    target = root / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(raw)
                result = helper(root, name, consumer)
                for symbol, line, end in [('Regexp.doMatch', 513, 515), ('Regexp.doExecute', 521, 550)]:
                    assert any(f['qualified_name'] == symbol and f['is_method']
                               and f['start_line'] == line and f['end_line'] == end
                               for f in result['before_ast']['functions'])
                result['remaining_sources_unchanged'] = all(
                    not (root / path).exists() if path == name else (root / path).read_bytes() == raw
                    for path, raw in files.items())
                assert result['remaining_sources_unchanged']
                records.append(result)
        finally:
            if records and records[-1]['consumer'] == consumer:
                records[-1]['owned_cleanup'] = root is not None and not root.exists()
            evidence('go-deletion-observations.json', records)
    assert len(records) == 3 and all(r['closed'] and r['owned_cleanup'] for r in records)
    record_property('qualified_input', 'true')
    for result in records:
        changes = result['changes']
        for symbol, line, end in [('Regexp.doMatch', 513, 515), ('Regexp.doExecute', 521, 550)]:
            assert any(c['kind'] == 'removed' and c['symbol_name'] == symbol and c['symbol_kind'] == 'method'
                       and c['file_path'] == name and c['previous']['qualified_name'] == symbol
                       and c['previous']['start_line'] == line and c['previous']['end_line'] == end
                       for c in changes), 'REGRESSION: Go pinned deletion event identity'


def test_go_pinned_semantic_chunk_cache(tmp_path, monkeypatch, record_property, pinned_go_crossfile_sources):
    import runpy
    from tempfile import TemporaryDirectory

    from attocode_intel._internal.integrations.context.ast_chunker import chunk_file
    from attocode_intel._internal.integrations.context.vector_store import VectorEntry

    helpers = runpy.run_path(str(Path(__file__).with_name('test_go_semantic_chunks.py')))
    manifest, files = pinned_go_crossfile_sources
    name = manifest['source_path']
    ast = native(name, files[name].decode(), 'go', 'go-semantic-exec')
    canonical = {f.qualified_name: f for f in ast.functions if f.is_method and f.qualified_name}
    assert {'Regexp.doMatch', 'Regexp.doExecute'} <= canonical.keys()
    provider = helpers['DeterministicProvider']()
    root = None
    record = {'closed': False}
    try:
        with TemporaryDirectory(prefix='go-semantic-', dir=tmp_path) as directory:
            root = Path(directory)
            record['inputs'] = helpers['qualified_files'](root, {p: raw.decode() for p, raw in files.items() if p.endswith('.go')})
            for p, raw in files.items():
                target = root / p
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            record['structural'] = [asdict(c) for c in chunk_file(str(root / name), name)]
            with helpers['manager'](root, provider, monkeypatch) as value:
                chunks = value._chunk_single_file(name, str(root / name))
                record['vector_chunks'] = chunks
                legacy_entries = []
                for chunk in chunks:
                    cid, path, kind, display = chunk[:4]
                    qualified = cid.removeprefix('method:' + name + ':')
                    if cid.startswith('method:' + name + ':') and qualified in canonical:
                        bare = canonical[qualified].name
                        cid, kind = 'func:' + name + ':' + bare, 'function'
                        display = display.replace('method ' + qualified, 'function ' + bare, 1)
                    legacy_entries.append(VectorEntry(cid, path, kind, cid.split(':')[-1], display, [1.0, 0.0, 0.0]))
                value._store.upsert_batch(legacy_entries)
                value._store.upsert(VectorEntry('preserve-other', 'other.txt', 'file', 'other', 'keep', [0.0, 1.0, 0.0]))
                stamp = (root / name).stat().st_mtime_ns
                value._store.set_file_metadata(name, (root / name).stat().st_mtime, len(legacy_entries))
                record['legacy_rows'] = helpers['rows'](value._store, name)
                other = helpers['rows'](value._store, 'other.txt')
                record['repair_count'] = value.reindex_stale_files()
                record['repaired_rows'] = helpers['rows'](value._store, name)
                assert helpers['rows'](value._store, 'other.txt') == other
                assert (root / name).stat().st_mtime_ns == stamp
            with helpers['manager'](root, provider, monkeypatch) as reopened:
                record['restored_rows'] = helpers['rows'](reopened._store, name)
                calls = len(provider.calls)
                reopened.reindex_stale_files()
                assert len(provider.calls) == calls
                assert helpers['rows'](reopened._store, name) == record['restored_rows']
            record['source_unchanged'] = all((root / p).read_bytes() == raw for p, raw in files.items())
            assert record['source_unchanged']
            record['embed_calls'] = provider.calls
            record['closed'] = True
    finally:
        record['owned_cleanup'] = root is not None and not root.exists()
        evidence('go-semantic-observation.json', record)
    assert record['closed'] and record['owned_cleanup']
    record_property('qualified_input', 'true')
    for qualified in ['Regexp.doMatch', 'Regexp.doExecute']:
        wanted = 'method:' + name + ':' + qualified
        assert any(c['id'] == wanted and c['chunk_type'] == 'method' and c['name'] == qualified
                   for c in record['structural']), 'REGRESSION: Go pinned semantic chunk identity'
        assert any(row[0] == wanted and row[1] == 'method' and row[2] == qualified
                   for row in record['repaired_rows']), 'REGRESSION: Go pinned semantic chunk identity'
    assert record['repaired_rows'] == record['restored_rows']
