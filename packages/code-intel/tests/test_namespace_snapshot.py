"""Namespace reads keep stable membership while AST hydration publishes files."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest
from attocode_intel._internal.integrations.context.module_resolution import FileIndex


@pytest.mark.parametrize('mutation', ['grow', 'shrink'])
def test_namespace_lookup_snapshots_cache_during_hydration(mutation):
    reading, changed = Event(), Event()

    def ast(name):
        return SimpleNamespace(language='php', namespaces=[r'Acme\Core'],
                               classes=[SimpleNamespace(name=name)],
                               functions=[SimpleNamespace(name=name.lower())])

    class FirstAST:
        language = 'php'
        namespaces = [r'Acme\Core']
        functions = [SimpleNamespace(name='first')]

        @property
        def classes(self):
            if not reading.is_set():
                reading.set()
                assert changed.wait(5), 'hydration did not publish its cache update'
            return [SimpleNamespace(name='First')]

    cache = {'first.php': FirstAST(), 'second.php': ast('Second')}
    index = FileIndex({name: name for name in ('first.php', 'second.php', 'late.php')})

    def hydrate():
        try:
            assert reading.wait(5), 'namespace traversal did not start'
            if mutation == 'grow':
                cache['late.php'] = ast('Late')
            else:
                del cache['second.php']
        finally:
            changed.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        publication = pool.submit(hydrate)
        try:
            index.configure_namespaces(cache)
        finally:
            reading.set()
            publication.result(timeout=5)

    assert index.namespace_candidates('php', r'Acme\Core\First') == ['first.php']
    assert index.namespace_candidates('php', r'Acme\Core\first') == ['first.php']
    assert index.namespace_candidates('php', r'Acme\Core\Second') == ['second.php']
    assert index.namespace_candidates('php', r'Acme\Core\Late') == []

    # The next build sees the new membership; the snapshot is local to one read.
    index.configure_namespaces(cache)
    assert index.namespace_candidates('php', r'Acme\Core\Late') == (['late.php'] if mutation == 'grow' else [])
    assert index.namespace_candidates('php', r'Acme\Core\Second') == (['second.php'] if mutation == 'grow' else [])
