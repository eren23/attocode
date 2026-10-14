"""Explicit CI/worker acquisition; product navigation never downloads grammars."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache', required=True, type=Path)
    args = parser.parse_args()
    if os.environ.get('QUALITY_ALLOW_DOWNLOADS') != '1':
        parser.error('Grammar acquisition requires QUALITY_ALLOW_DOWNLOADS=1 on CI/a disposable worker')
    if args.cache.exists():
        parser.error('Use a new disposable grammar cache')
    args.cache.mkdir(parents=True)
    import tree_sitter_language_pack as pack
    names = ['haskell', 'erlang', 'clojure', 'perl', 'dart', 'ocaml', 'fsharp', 'julia', 'nim', 'r', 'objc', 'crystal']
    pack.configure(cache_dir=str(args.cache.resolve()))
    available = set(pack.manifest_languages())
    unsupported = sorted(set(names) - available)
    # The locked 1.1.2 pack has no downloadable Crystal artifact. Preserve that
    # explicit unsupported row; an unexpected missing adapter still fails CI.
    if set(unsupported) - {'crystal'}:
        raise RuntimeError('Unexpected unavailable grammars: ' + ', '.join(unsupported))
    requested = [name for name in names if name in available]
    pack.download(requested)
    missing = sorted(set(requested) - set(pack.downloaded_languages()))
    print(json.dumps({'requested':requested, 'unsupported':unsupported, 'missing':missing,
                      'bytes':sum(p.stat().st_size for p in args.cache.rglob('*') if p.is_file())}), flush=True)
    if missing:
        raise RuntimeError('Required optional grammar acquisition incomplete: ' + ', '.join(missing))
    # Configuration is process local; pytest shares this exact configured loader.
    import pytest
    return pytest.main(['-c', 'packages/code-intel/pyproject.toml', '--confcutdir=packages/code-intel/tests',
                        'packages/code-intel/tests/test_language_capabilities.py', '-q'])


if __name__ == '__main__':
    raise SystemExit(main())
