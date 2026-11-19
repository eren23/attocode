"""Frozen synthetic warm-query comparison; never a real-repository benchmark."""
from __future__ import annotations

import argparse
import ast
import builtins
import hashlib
import io
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from contextlib import ExitStack
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

BASE = 'b0fe056f35270359e0c5e6dce3fe4d2ee8dc080c'
SOURCE = 'packages/code-intel/src/attocode_intel/_internal/integrations/context/semantic_search.py'
METHOD_SHA = '77fec045bf8aed231c514f24a91f2ea2d3d20e896076274db7bd47c4ead89323'
QUERIES = ['manifestneedle', 'unaffectedneedle', 'io unaffectedneedle']
FILES = {
    'manifestneedle.toml': '[project]\nname = "fixture"\n',
    'alpha.py': 'def alpha():\n    """unaffectedneedle io"""\n    return 1\n',
    'beta.py': 'def beta():\n    """opaqueother"""\n    return 2\n',
    'other.toml': '[project]\nname = "other"\n',
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def tracked(repo):
    names = subprocess.check_output(['git', '-C', str(repo), 'ls-files', '-z']).split(b'\0')
    return {os.fsdecode(n): digest(os.readlink(repo / os.fsdecode(n)).encode()
                                  if (repo / os.fsdecode(n)).is_symlink()
                                  else (repo / os.fsdecode(n)).read_bytes()) for n in names if n}


def original_method(repo, module):
    source = subprocess.check_output(['git', '-C', str(repo), 'show', BASE + ':' + SOURCE]).decode()
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef)
               and n.name == 'SemanticSearchManager')
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_keyword_search')
    method = ast.get_source_segment(source, node)
    assert digest(method.encode()) == METHOD_SHA
    namespace = dict(vars(module))
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<trusted-baseline-keyword-method>', 'exec'), namespace)
    return namespace['_keyword_search'], namespace


def operation_probe(method, namespace, module, manager, query):
    calls = Counter()
    tokens = []
    tokenizer = module._tokenize

    def tokenize(text):
        tokens.append(text)
        return tokenizer(text)

    def observed(name, original):
        def call(*args, **kwargs):
            calls[name] += 1
            return original(*args, **kwargs)
        return call

    with ExitStack() as stack:
        for owner, name in [(builtins, 'open'), (io, 'open'), (os, 'open'), (os, 'stat')]:
            stack.enter_context(patch.object(owner, name, observed(owner.__name__ + '.' + name, getattr(owner, name))))
        stack.enter_context(patch.object(module, '_tokenize', tokenize))
        stack.enter_context(patch.dict(namespace, {'_tokenize': tokenize}))
        results = [asdict(row) for row in method(manager, query, 16, '')]
    return results, dict(calls), tokens


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    repo = Path.cwd()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    from attocode_intel._internal.integrations.context import semantic_search as module
    from attocode_intel._internal.integrations.context.trigram_index import TrigramIndex

    expected = subprocess.check_output(['git', 'show', args.candidate + ':' + SOURCE])
    assert (repo / SOURCE).read_bytes() == expected
    assert Path(module.__file__).resolve() == (repo / SOURCE).resolve()
    changed = subprocess.check_output(['git', 'diff', '--name-only', args.candidate], text=True).splitlines()
    assert sorted(changed) == sorted(['eval/quality/keyword_prefilter_cost.py', '.github/workflows/keyword-prefilter-cost.yml'])
    old, namespace = original_method(repo, module)
    new = module.SemanticSearchManager._keyword_search
    before = tracked(repo)
    save(output / 'tracked-before.json', before)
    root = Path(tempfile.mkdtemp(prefix='keyword-prefilter-cost-', dir=os.environ.get('RUNNER_TEMP')))
    manager = None
    index = None
    state = {'status': 'started', 'candidate': args.candidate, 'head': os.environ['GITHUB_SHA'],
             'run': os.environ['GITHUB_RUN_ID'], 'attempt': os.environ['GITHUB_RUN_ATTEMPT'],
             'source_sha256': digest(expected), 'baseline': BASE, 'baseline_method_sha256': METHOD_SHA,
             'real_repository_questions': 0, 'owned_root': str(root), 'queries': []}
    save(output / 'progress.json', state)
    try:
        for name, content in FILES.items():
            (root / name).write_text(content)
        manager = module.SemanticSearchManager(str(root), nl_mode='none')
        manager._build_keyword_index()
        assert manager._kw_index_built
        file_docs = [d for d in manager._kw_docs if d.chunk_type == 'file']
        functions = [d for d in manager._kw_docs if d.chunk_type == 'function']
        assert len(file_docs) == 4 and len(functions) == 2
        alpha = [doc for doc in functions if doc.file_path == 'alpha.py' and doc.name == 'alpha']
        assert len(alpha) == 1 and alpha[0].term_freqs.get('unaffectedneedle', 0) > 0
        assert alpha[0].term_freqs.get('io', 0) > 0
        assert set(manager._kw_path_terms) == set(FILES)
        index = TrigramIndex(index_dir=str(root / '.attocode' / 'index'))
        index_stats = index.build(str(root))
        assert index_stats['files_indexed'] == 4 and index.is_ready()
        index.close()
        assert manager._get_trigram_index().is_ready()
        assert manager._trigram_prefilter(['manifestneedle']) == set()
        assert manager._trigram_prefilter(['unaffectedneedle']) == {'alpha.py'}

        # Keep the actual file docs/path cache; expand only extracted functions.
        manager._kw_docs = file_docs + [replace(functions[i % 2], id=f'synthetic:{i:06d}:' + functions[i % 2].id)
                                      for i in range(20000 - len(file_docs))]
        frequency = Counter()
        for doc in manager._kw_docs:
            frequency.update(doc.term_freqs.keys())
        manager._kw_df = dict(frequency)
        manager._kw_avg_dl = sum(d.doc_len for d in manager._kw_docs) / len(manager._kw_docs)
        assert len(manager._kw_docs) == 20000
        shallow = sys.getsizeof(manager._kw_path_terms) + sum(sys.getsizeof(v) for v in manager._kw_path_terms.values())
        assert shallow <= 8192
        for doc in file_docs:
            assert all(any(term is key for key in doc.term_freqs) for term in manager._kw_path_terms[doc.file_path])
        state.update({'synthetic_docs': 20000, 'seed_files': 4, 'derived_map_tuple_bytes': shallow,
                      'shared_existing_term_keys': True, 'ready_index_stats': index_stats})
        for query in QUERIES:
            if query != 'manifestneedle':
                reference = old(manager, query, 16, '')
                assert any(row.file_path == 'alpha.py' and row.name == 'alpha'
                           and row.chunk_type == 'function' for row in reference)
            for _ in range(2):
                old(manager, query, 16, '')
                new(manager, query, 16, '')
            times = {'baseline': [], 'candidate': []}
            last = {}
            for round_no in range(7):
                order = [('baseline', old), ('candidate', new)]
                if round_no % 2:
                    order.reverse()
                for label, method in order:
                    started = time.perf_counter()
                    result = method(manager, query, 16, '')
                    times[label].append(time.perf_counter() - started)
                    last[label] = [asdict(row) for row in result]
            baseline = statistics.median(times['baseline'])
            candidate = statistics.median(times['candidate'])
            row = {'query': query, 'seconds': times, 'baseline_median': baseline,
                   'candidate_median': candidate, 'limit_seconds': baseline * 1.20 + 0.005,
                   'results': last}
            state['queries'].append(row)
            save(output / 'progress.json', state)
            assert candidate <= row['limit_seconds'], 'frozen warm-query latency gate failed'
            old_rows, old_ops, old_tokens = operation_probe(old, namespace, module, manager, query)
            new_rows, new_ops, new_tokens = operation_probe(new, namespace, module, manager, query)
            assert old_rows == last['baseline'] and new_rows == last['candidate']
            assert all(new_ops.get(k, 0) <= old_ops.get(k, 0) for k in set(old_ops) | set(new_ops))
            row['operations'] = {'baseline': old_ops, 'candidate': new_ops}
            row['tokenizations'] = {label: {'count': len(tokens), 'sha256': digest(json.dumps(tokens).encode())}
                                    for label, tokens in [('baseline', old_tokens), ('candidate', new_tokens)]}
            if query != 'manifestneedle':
                assert new_rows == old_rows and new_tokens == old_tokens
            else:
                assert not old_rows and len(new_rows) == 1
                assert new_rows[0]['file_path'] == 'manifestneedle.toml' and new_rows[0]['chunk_type'] == 'file'
                with patch.object(module.SemanticSearchManager, '_trigram_prefilter', return_value=None):
                    full_scan = [asdict(r) for r in old(manager, query, 16, '')]
                assert new_rows == full_scan
                # One admitted file may add its existing name tokenization only.
                assert new_tokens == old_tokens + ['manifestneedle.toml']
            row['gates_passed'] = True
            save(output / 'progress.json', state)
        state['status'] = 'passed'
    finally:
        if manager is not None:
            manager.close()
            state['owned_manager_closed'] = manager._closed
        if index is not None:
            index.close()
        shutil.rmtree(root)
        state['owned_root_removed'] = not root.exists()
        after = tracked(repo)
        save(output / 'tracked-after.json', after)
        state['tracked_source_unchanged'] = before == after
        save(output / 'report.json', state)
    assert state['status'] == 'passed' and state['owned_root_removed'] and state['tracked_source_unchanged']
    print(json.dumps({'status': state['status'], 'docs': state['synthetic_docs'],
                      'map_tuple_bytes': state['derived_map_tuple_bytes'], 'queries': len(state['queries'])}))


if __name__ == '__main__':
    main()
