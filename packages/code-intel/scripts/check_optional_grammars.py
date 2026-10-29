"""Explicit CI/worker acquisition; product navigation never downloads grammars."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache', required=True, type=Path)
    parser.add_argument('--depth-evidence', type=Path)
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
    # pack-only absence separately; standalone Crystal is verified below.
    if set(unsupported) - {'crystal'}:
        raise RuntimeError('Unexpected unavailable grammars: ' + ', '.join(unsupported))
    requested = [name for name in names if name in available]
    pack.download(requested)
    missing = sorted(set(requested) - set(pack.downloaded_languages()))
    print(json.dumps({'requested':requested, 'pack_unsupported':unsupported, 'missing':missing,
                      'bytes':sum(p.stat().st_size for p in args.cache.rglob('*') if p.is_file())}), flush=True)
    if missing:
        raise RuntimeError('Required optional grammar acquisition incomplete: ' + ', '.join(missing))
    # Configuration is process local; pytest shares this exact configured loader.
    import pytest
    command = ['-c', 'packages/code-intel/pyproject.toml', '--confcutdir=packages/code-intel/tests',
               'packages/code-intel/tests/test_language_capabilities.py', '-q']
    if args.depth_evidence is None:
        return pytest.main(command)
    from eval.quality.experiment_evidence import assert_engine
    from eval.quality.native_experiment import distribution_identity, grammar_identity
    from eval.quality.runner import REPO, write_json
    root = args.depth_evidence.resolve()
    root.mkdir(parents=True, exist_ok=False)
    engine = REPO / 'packages/code-intel/src/attocode_intel'
    direct = json.loads(importlib.metadata.distribution('tree-sitter-crystal').read_text('direct_url.json'))
    if direct['vcs_info']['commit_id'] != '50ca9e6fcfb16a2cbcad59203cfd8ad650e25c49':
        raise ValueError('Unexpected Crystal grammar source')
    inputs = [*engine.rglob('*.py'), *(REPO / 'eval/quality').glob('*.py'),
              REPO / 'packages/code-intel/tests/test_optional_language_depth.py',
              REPO / 'packages/code-intel/tests/test_language_capabilities.py', Path(__file__).resolve()]
    sources = {p.relative_to(REPO).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    before = {'grammar': grammar_identity(args.cache), 'crystal': distribution_identity(('tree-sitter-crystal',)),
              'direct_url': direct}
    report = {'schema_version': 1, 'pid': os.getpid(), 'status': 'incomplete', 'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
              'files': sources, 'origins': assert_engine(engine), 'before': before}
    write_json(root / 'report.json', report)
    os.environ.update(QUALITY_LANGUAGE_DEPTH='1', QUALITY_LANGUAGE_EVIDENCE=str(root / 'native-depth'),
                      ATTOCODE_EXPERIMENT_ENGINE=str(engine), ATTOCODE_EXPERIMENT_EVIDENCE=str(root))
    command += ['packages/code-intel/tests/test_optional_language_depth.py', '-p', 'eval.quality.experiment_origin',
                '--junitxml=' + str(root / 'optional-depth.xml'), '--basetemp=' + str(args.cache.parent / 'optional-depth-pytest')]
    result = pytest.main(command)
    after = {'grammar': grammar_identity(args.cache), 'crystal': distribution_identity(('tree-sitter-crystal',)),
             'direct_url': direct}
    report.update(exit_code=int(result), after=after, final_origins=assert_engine(engine))
    unchanged = all(hashlib.sha256((REPO / name).read_bytes()).hexdigest() == sha for name, sha in sources.items())
    report['source_unchanged'] = unchanged
    shutil.rmtree(args.cache)
    scratch = args.cache.parent / 'optional-depth-pytest'
    if scratch.exists():
        shutil.rmtree(scratch)
    report['owned_scratch_removed'] = not args.cache.exists() and not scratch.exists()
    if int(result) == 0 and before == after and unchanged and report['owned_scratch_removed']:
        report['status'] = 'complete'
    write_json(root / 'report.json', report)
    return 0 if report['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
