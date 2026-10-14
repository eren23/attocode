"""Discovery and live refresh share explicit project source inclusions."""
from attocode_intel._internal.integrations.context.codebase_context import CodebaseContextManager
from attocode_intel.freshness import FreshnessTracker
from attocode_intel.gateway import OperationGateway


async def test_build_named_source_needs_explicit_inclusion_and_refreshes(tmp_path, monkeypatch):
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    (tmp_path / 'dist').mkdir()
    (tmp_path / 'dist' / 'real.py').write_text('def source_entry(): return 1\n')
    (tmp_path / 'build').mkdir()
    (tmp_path / 'build' / 'generated.py').write_text('def generated_entry(): return 0\n')
    gateway = OperationGateway(str(tmp_path), 'daily', watch=False)
    async def names():
        response = await gateway.execute('search_symbols', {'name': 'source_entry'})
        assert not response.isError
        return {r['name'] for r in response.structuredContent['data']}
    try:
        assert 'source_entry' not in await names()
        assert FreshnessTracker(str(tmp_path)).scan_manifest() == {}
        (tmp_path / '.gitignore').write_text('!dist/\n')
        assert 'source_entry' in await names()
        discovered = {f.relative_path for f in CodebaseContextManager(str(tmp_path)).discover_files()}
        assert discovered == {'dist/real.py'}
        assert set(FreshnessTracker(str(tmp_path)).scan_manifest()) == discovered
        (tmp_path / '.gitignore').write_text('dist/\n')
        assert 'source_entry' not in await names()
    finally:
        await gateway.close()
