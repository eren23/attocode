"""Real optional grammars: explicitly acquired CI only, never navigation downloads."""
import hashlib
import json
import os
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


def test_perl_native_call_candidates_exclude_decoys():
    from attocode_intel._internal.integrations.context.syntax_evidence import reference_candidates
    source = 'sub greet { return $_[0]; }\nsub run { Lib::Helper::greet("ok"); }\n# Lib::Helper::decoy("no");\nmy $text = "Lib::Helper::decoy nope";\n'
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
