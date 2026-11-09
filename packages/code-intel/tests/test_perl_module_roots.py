"""Configured Perl roots resolve only physically discovered workspace modules."""
import hashlib
import json
import tomllib
from pathlib import Path

import pytest
from attocode_intel import config
from attocode_intel._internal.integrations.context.ast_service import ASTService
from attocode_intel._internal.integrations.context.codebase_context import (
    CodebaseContextManager,
    _build_file_index,
    resolve_import_targets,
)
from attocode_intel._internal.integrations.context.index_store import IndexStore

DEFAULT_ROOTS = ['.', 'lib']
MODULE = 'Acme::Widget'
LEAF = 'Acme/Widget.pm'
ROOT_CASES = [
    {'id':'default-root','paths':['Acme/Widget.pm'],'expected':['Acme/Widget.pm'],'loaded':['.','lib']},
    {'id':'default-lib','paths':['lib/Acme/Widget.pm'],'expected':['lib/Acme/Widget.pm'],'loaded':['.','lib']},
    {'id':'default-ambiguity','paths':['Acme/Widget.pm','lib/Acme/Widget.pm'],'expected':[],'loaded':['.','lib']},
    {'id':'unrelated-section','paths':['lib/Acme/Widget.pm'],'raw':'[other]\nflag=true\n','expected':['lib/Acme/Widget.pm'],'loaded':['.','lib']},
    {'id':'malformed-toml','paths':['lib/Acme/Widget.pm'],'raw':'[perl\n','expected':['lib/Acme/Widget.pm'],'loaded':['.','lib']},
    {'id':'wrong-list-type','paths':['lib/Acme/Widget.pm'],'roots':'lib','expected':['lib/Acme/Widget.pm'],'loaded':['.','lib']},
    {'id':'custom-root','paths':['custom/lib/Acme/Widget.pm'],'roots':['custom/lib'],'expected':['custom/lib/Acme/Widget.pm'],'loaded':['custom/lib']},
    {'id':'replace-defaults','paths':['lib/Acme/Widget.pm','custom/lib/Acme/Widget.pm'],'roots':['custom/lib'],'expected':['custom/lib/Acme/Widget.pm'],'loaded':['custom/lib']},
    {'id':'explicit-empty','paths':['lib/Acme/Widget.pm'],'roots':[],'expected':[],'loaded':[]},
    {'id':'missing-root','paths':['lib/Acme/Widget.pm'],'roots':['absent'],'expected':[],'loaded':['absent']},
    {'id':'deduplicated-roots','paths':['custom/lib/Acme/Widget.pm'],'roots':['./custom/lib','custom/lib/'],'expected':['custom/lib/Acme/Widget.pm'],'loaded':['custom/lib']},
    {'id':'custom-ambiguity','paths':['one/lib/Acme/Widget.pm','two/lib/Acme/Widget.pm'],'roots':['one/lib','two/lib'],'expected':[],'loaded':['one/lib','two/lib']},
    {'id':'absolute-root','paths':['lib/Acme/Widget.pm'],'roots':['__ABS__'],'expected':[],'loaded':[]},
    {'id':'parent-root','paths':['lib/Acme/Widget.pm'],'roots':['../outside'],'expected':[],'loaded':[]},
    {'id':'backslash-parent','paths':['lib/Acme/Widget.pm'],'roots':['..\\outside'],'expected':[],'loaded':[]},
    {'id':'windows-drive','paths':['lib/Acme/Widget.pm'],'roots':['C:\\outside'],'expected':[],'loaded':[]},
    {'id':'mixed-safe-unsafe','paths':['lib/Acme/Widget.pm','custom/lib/Acme/Widget.pm'],'roots':[42,'../outside','custom/lib',''],'expected':['custom/lib/Acme/Widget.pm'],'loaded':['custom/lib']},
    {'id':'internal-symlink','paths':['lib/Acme/Widget.pm','custom/lib/Acme/Widget.pm'],'roots':['linked'],'symlink':'inside','expected':['custom/lib/Acme/Widget.pm'],'loaded':['custom/lib']},
    {'id':'external-symlink','paths':['lib/Acme/Widget.pm'],'roots':['linked'],'symlink':'outside','expected':[],'loaded':[]},
    {'id':'external-config','paths':['lib/Acme/Widget.pm','custom/lib/Acme/Widget.pm'],'roots':['custom/lib'],'external_config':True,'expected':['lib/Acme/Widget.pm'],'loaded':['.','lib']},
    {'id':'oversized-config','paths':['lib/Acme/Widget.pm','custom/lib/Acme/Widget.pm'],'roots':['custom/lib'],'oversize':True,'expected':['lib/Acme/Widget.pm'],'loaded':['.','lib']},
    {'id':'quoted-root','paths':['custom/it\'s "quoted"/Acme/Widget.pm'],'roots':['custom/it\'s "quoted"'],'expected':['custom/it\'s "quoted"/Acme/Widget.pm'],'loaded':['custom/it\'s "quoted"']},
    {'id':'generated-exclusion','paths':['lib/Acme/Widget.pm','dist/lib/Acme/Widget.pm'],'roots':['dist/lib'],'expected':[],'loaded':['dist/lib']},
    {'id':'physical-not-python-alias','paths':['lib/Acme/Widget.pm','lib/pkg/__init__.py'],'roots':['.'],'expected':[],'loaded':['.']},
]


def _write_config(root, roots, **other):
    path = root / '.attocode/config.toml'
    path.parent.mkdir(parents=True, exist_ok=True)
    text = '[perl]\nmodule_roots = ' + json.dumps(roots) + '\n'
    if other:
        text += '[remote]\n' + '\n'.join(k + ' = ' + json.dumps(v) for k,v in other.items()) + '\n'
    path.write_text(text)
    return path


@pytest.mark.parametrize('case', ROOT_CASES, ids=[c['id'] for c in ROOT_CASES])
def test_perl_roots_follow_explicit_workspace_policy(tmp_path, record_property, case):
    root, outside = tmp_path / 'repo', tmp_path / 'outside'
    root.mkdir()
    (outside / 'Acme').mkdir(parents=True)
    (outside / LEAF).write_text('package Acme::Widget; sub outside { 0 }\n1;\n')
    for name in [*case['paths'], 'consumer.t']:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('SENTINEL = 1\n' if name.endswith('.py') else
                        'use Acme::Widget;\n' if name.endswith('.t') else
                        'package Acme::Widget; sub answer { 1 }\n1;\n')
    if case.get('symlink'):
        (root / 'linked').symlink_to(root / 'custom/lib' if case['symlink']=='inside' else outside,
                                   target_is_directory=True)
    path = root / '.attocode/config.toml'
    if 'roots' in case:
        roots = [str(outside) if x=='__ABS__' else x for x in case['roots']] if isinstance(case['roots'],list) else case['roots']
        _write_config(root, roots)
    elif 'raw' in case:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(case['raw'])
    if case.get('oversize'):
        path.write_text(path.read_text() + '#' + 'x' * 1_000_000)
    if case.get('external_config'):
        target = outside / 'config.toml'
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
    files = CodebaseContextManager(str(root)).discover_files()
    physical = {f.relative_path for f in files}
    assert 'consumer.t' in physical and not any(p.startswith('dist/') for p in physical)
    assert not any(p.startswith('linked/') for p in physical)
    assert set(case['expected']) <= physical
    index = _build_file_index(files, str(root))
    actual = resolve_import_targets('perl', MODULE, 'consumer.t', index)
    record_property('qualified_input', 'true')
    record_property('physical_files', json.dumps(sorted(physical)))
    record_property('expected_candidates', json.dumps(case['expected']))
    record_property('actual_candidates', json.dumps(actual))
    record_property('config_sha256', hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else 'absent')
    assert actual == case['expected'], 'REGRESSION: explicit Perl module roots are not respected'
    loader = getattr(config, 'load_perl_module_roots', None)
    if callable(loader):
        assert loader(str(root)) == case['loaded'], 'REGRESSION: Perl roots loader admits an unsafe or incorrect root'


def test_perl_config_loader_is_public_and_read_bounded(tmp_path, monkeypatch, record_property):
    path = _write_config(tmp_path, ['lib'])
    (tmp_path / 'lib').mkdir()
    record_property('qualified_input', 'true')
    record_property('config_bytes', path.stat().st_size)
    loader = getattr(config, 'load_perl_module_roots', None)
    assert callable(loader), 'REGRESSION: bounded Perl configuration loader is unavailable'
    opened, read_text, requests = Path.open, Path.read_text, []

    class Reader:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            self.stream.__enter__()
            return self
        def __exit__(self, *args):
            return self.stream.__exit__(*args)
        def read(self, size=-1):
            requests.append(size)
            assert 0 <= size <= 1_000_001, 'Unbounded Perl config read'
            return self.stream.read(size)

    def bounded_open(p, *args, **kwargs):
        stream = opened(p, *args, **kwargs)
        return Reader(stream) if p == path else stream

    def forbid_unbounded_text(p, *args, **kwargs):
        assert p != path, 'Unbounded Perl config read_text'
        return read_text(p, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', bounded_open)
    monkeypatch.setattr(Path, 'read_text', forbid_unbounded_text)
    assert loader(str(tmp_path)) == ['lib']
    assert requests


@pytest.mark.parametrize('change', ['roots', 'order', 'remote'])
def test_snapshot_tracks_effective_perl_policy_without_source_edits(tmp_path, record_property, change):
    for directory in ['one/lib','two/lib']:
        path = tmp_path / directory / LEAF
        path.parent.mkdir(parents=True)
        path.write_text('package Acme::Widget; sub answer { 1 }\n1;\n')
    initial = ['one/lib','two/lib'] if change=='order' else ['one/lib']
    _write_config(tmp_path, initial, token='authored-fake-token-one')
    service = ASTService(str(tmp_path), store=IndexStore(db_path=':memory:'))
    try:
        before = service._snapshot_identity()
        roots = ['two/lib'] if change=='roots' else list(reversed(initial)) if change=='order' else initial
        _write_config(tmp_path, roots, token='authored-fake-token-two')
        after = service._snapshot_identity()
        assert before['files'] == after['files']
        record_property('qualified_input', 'true')
        record_property('source_stamps_unchanged', 'true')
        record_property('before_identity', json.dumps(before))
        record_property('after_identity', json.dumps(after))
        assert (before != after) == (change=='roots'), 'REGRESSION: snapshot identity ignores effective Perl module roots'
    finally:
        service._store.close()


@pytest.mark.parametrize('roots', [
    ['custom/it\'s "quoted"', 'space lib'],
    ['custom\\library', 'space lib'],
], ids=['mixed-quotes','backslashes'])
def test_remote_settings_save_preserves_perl_and_other_sections(tmp_path, record_property, roots):
    path = _write_config(tmp_path, roots)
    path.write_text(path.read_text() + '[other]\nlabel = "keep"\nstrings = ["one", "two"]\n[other.nested]\nflag = true\n')
    before = tomllib.loads(path.read_text())
    assert before['perl']['module_roots'] == roots
    rc = config.RemoteConfig(server='https://example.invalid', token='authored-fake-token',
                             repo_id='authored-fake-repo', branch_auto_detect=False)
    config.save_remote_config(str(tmp_path), rc)
    try:
        after = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError:
        after = None
    record_property('qualified_input', 'true')
    record_property('credential_origin', 'authored-fake-only')
    record_property('saved_toml_valid', str(after is not None).lower())
    record_property('expected_roots', json.dumps(roots))
    assert after is not None and after.get('perl') == before['perl'] and after.get('other') == before['other'], 'REGRESSION: remote settings save corrupts existing Perl/TOML configuration'
    assert after['remote']=={'server':rc.server,'token':rc.token,'repo_id':rc.repo_id,'branch_auto_detect':False}
