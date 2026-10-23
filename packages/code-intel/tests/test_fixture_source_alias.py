"""Captured aliases must resolve to pinned content without touching the host."""
import pytest

from eval.quality.fixture_identity import source_entry


def test_alias_and_nested_alias_resolve_to_the_original_content_entry():
    body = {'kind': 'file', 'bytes': 5, 'sha256': 'a' * 64}
    inventory = {'AGENTS.md': body, 'CLAUDE.md': {'kind': 'symlink', 'target': 'AGENTS.md'},
                 'docs/link': {'kind': 'symlink', 'target': '../CLAUDE.md'},
                 'source': {'kind': 'symlink', 'target': 'real'}, 'real/main.py': body}
    assert source_entry(inventory, 'CLAUDE.md') is body
    assert source_entry(inventory, 'docs/link') is body
    assert source_entry(inventory, 'source/main.py') is body
    assert source_entry(inventory, 'AGENTS.md') is body


@pytest.mark.parametrize('target', ['/etc/passwd', '../../outside', 'missing', 'link'])
def test_external_missing_and_cyclic_source_aliases_are_rejected(target):
    with pytest.raises(ValueError):
        source_entry({'link': {'kind': 'symlink', 'target': target}}, 'link')


def test_alias_chain_and_path_growth_are_bounded():
    inventory = {f'link{n}': {'kind': 'symlink', 'target': f'link{n + 1}'} for n in range(42)}
    inventory['link42'] = {'kind': 'file', 'bytes': 0, 'sha256': 'a' * 64}
    with pytest.raises(ValueError, match='forty'):
        source_entry(inventory, 'link0')
    with pytest.raises(ValueError, match='invalid|oversized'):
        source_entry({'link': {'kind': 'symlink', 'target': 'long/' * 1000}}, 'link')


def test_parent_components_are_interpreted_after_directory_alias_expansion():
    wanted = {'kind': 'file', 'bytes': 1, 'sha256': 'a' * 64}
    unrelated = {'kind': 'file', 'bytes': 1, 'sha256': 'b' * 64}
    inventory = {'dir': {'kind': 'symlink', 'target': 'real/nested'},
                 'link': {'kind': 'symlink', 'target': 'dir/../module.py'},
                 'real/nested/marker': wanted, 'real/module.py': wanted, 'module.py': unrelated}
    assert source_entry(inventory, 'link') is wanted


@pytest.mark.parametrize('target', ['missing/../file', 'file/../file', 'file/.'])
def test_alias_cannot_skip_missing_directories_or_walk_through_files(target):
    with pytest.raises(ValueError):
        source_entry({'link': {'kind': 'symlink', 'target': target},
                      'file': {'kind': 'file', 'bytes': 1, 'sha256': 'a' * 64}}, 'link')
