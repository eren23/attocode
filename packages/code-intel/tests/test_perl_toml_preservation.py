"""Remote-settings saves preserve valid unrelated TOML data and Unicode."""
import hashlib
import json
import tomllib

import pytest
from attocode_intel.config import RemoteConfig, save_remote_config

CASES = [
    ('del-value', r'label = "escaped\u007fvalue"'),
    ('del-key', r'"escaped\u007fkey" = "value"'),
    ('del-section', '["escaped\\u007fsection"]\nlabel = "value"'),
    ('unicode', 'label = "astral \U0001f4a1 and café"'),
    ('control-escapes', r'label = "\u0000\b\t\n\f\r\u001b"'),
    ('nested-types', '''enabled = true
count = 42
ratio = 1.25
day = 2026-11-10
clock = 12:34:56.123
stamp = 2026-11-10T12:34:56Z
[nested]
"key.with.dots" = [{ items = ["one", "two"], flag = false }]
'''),
]


@pytest.mark.parametrize('case_id,raw', CASES, ids=[case[0] for case in CASES])
def test_remote_save_preserves_valid_toml_scalars_and_keys(
    tmp_path, record_property, case_id, raw,
):
    path = tmp_path / '.attocode/config.toml'
    path.parent.mkdir()
    path.write_text(raw + '\n', encoding='utf-8')
    before = tomllib.loads(path.read_text(encoding='utf-8'))
    assert before
    rc = RemoteConfig(server='https://example.invalid', token='authored-fake-token',
                      repo_id='authored-fake-repo', branch_auto_detect=False)
    saved = save_remote_config(str(tmp_path), rc)
    assert saved == path
    raw_after = path.read_text(encoding='utf-8')
    try:
        after = tomllib.loads(raw_after)
    except tomllib.TOMLDecodeError:
        after = None
    record_property('qualified_input', 'true')
    record_property('credential_origin', 'authored-fake-only')
    record_property('case_id', case_id)
    record_property('input_toml', raw)
    record_property('saved_toml', raw_after)
    record_property('saved_sha256', hashlib.sha256(path.read_bytes()).hexdigest())
    record_property('expected_data', json.dumps(before, default=str))
    record_property('saved_toml_valid', str(after is not None).lower())
    assert after is not None and {k: v for k, v in after.items() if k != 'remote'} == before, 'REGRESSION: remote save corrupts valid TOML characters or keys'
    assert after['remote'] == {'server': rc.server, 'token': rc.token,
                               'repo_id': rc.repo_id, 'branch_auto_detect': False}
