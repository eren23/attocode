"""Public saves must not publish settings their own readers cannot consume."""
import hashlib
import json
import tomllib

import pytest
from attocode_intel.config import RemoteConfig, load_perl_module_roots, save_remote_config

PREFIX = b'[perl]\nmodule_roots = ["custom/lib"]\n[padding]\ntext = '
LIMIT = 1_000_000


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _remote():
    return RemoteConfig(server='https://example.invalid', token='authored-fake-token',
                        repo_id='authored-repo')


@pytest.mark.parametrize('kind', ['remote-growth', 'serializer-growth', 'new-oversized-token'])
def test_save_cannot_publish_unreadable_size(tmp_path, record_property, kind):
    path = tmp_path / '.attocode/config.toml'
    path.parent.mkdir()
    (tmp_path / 'custom/lib').mkdir(parents=True)
    before = None
    rc = _remote()
    if kind == 'remote-growth':
        before = PREFIX + b'"' + b'x' * (999_980 - len(PREFIX) - 3) + b'"\n'
        assert len(before) == 999_980
    elif kind == 'serializer-growth':
        # Valid literal TOML needs one byte per slash; basic strings need two.
        before = PREFIX + b"'" + b'\\' * 600_000 + b"'\n"
    else:
        rc.token = 'authored-fake-' + 'x' * LIMIT
    if before is not None:
        path.write_bytes(before)
        assert len(before) <= LIMIT and tomllib.loads(before.decode())['perl']['module_roots'] == ['custom/lib']
        assert load_perl_module_roots(str(tmp_path)) == ['custom/lib']
    else:
        assert not path.exists() and len(rc.token.encode()) > LIMIT
    rejected = False
    try:
        save_remote_config(str(tmp_path), rc)
    except ValueError:
        rejected = True
    after = path.read_bytes() if path.exists() else None
    if not rejected:
        assert after is not None and len(after) > LIMIT
        assert tomllib.loads(after.decode())['remote']['server'] == 'https://example.invalid'
    record_property('qualified_input', 'true')
    record_property('credential_origin', 'authored-fake-only')
    record_property('kind', kind)
    record_property('before_bytes', str(len(before)) if before is not None else 'absent')
    record_property('after_bytes', str(len(after)) if after is not None else 'absent')
    record_property('before_sha256', _sha(before) if before is not None else 'absent')
    record_property('after_sha256', _sha(after) if after is not None else 'absent')
    record_property('effective_roots_after', json.dumps(load_perl_module_roots(str(tmp_path))))
    assert rejected and after == before, 'REGRESSION: settings save publishes a file its own loaders reject'
    assert [p.name for p in path.parent.iterdir()] == (['config.toml'] if before is not None else [])
    if before is not None:
        assert load_perl_module_roots(str(tmp_path)) == ['custom/lib']


def test_exact_input_limit_with_comments_can_be_saved(tmp_path):
    path = tmp_path / '.attocode/config.toml'
    path.parent.mkdir()
    head = b'[perl]\nmodule_roots = ["custom/lib"]\n#'
    raw = head + b'x' * (LIMIT - len(head))
    assert len(raw) == LIMIT and tomllib.loads(raw.decode())['perl']['module_roots'] == ['custom/lib']
    path.write_bytes(raw)
    save_remote_config(str(tmp_path), _remote())
    assert len(path.read_bytes()) < 1000
    assert load_perl_module_roots(str(tmp_path)) == ['custom/lib']


def test_below_output_limit_survives_repeated_save(tmp_path):
    path = tmp_path / '.attocode/config.toml'
    path.parent.mkdir()
    path.write_bytes(PREFIX + b'"' + b'x' * 800_000 + b'"\n')
    for _ in range(2):
        save_remote_config(str(tmp_path), _remote())
        assert 800_000 < len(path.read_bytes()) < LIMIT
        assert load_perl_module_roots(str(tmp_path)) == ['custom/lib']
        assert tomllib.loads(path.read_text())['remote']['token'] == 'authored-fake-token'
