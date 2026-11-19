"""One frozen development diagnostic; this module is not product policy."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

BASE = 'b0fe056f35270359e0c5e6dce3fe4d2ee8dc080c'
CASES = [
    {'id': 'itsdangerous-manifest', 'repository': 'pallets/itsdangerous',
     'commit': '672971d66a2ef9f85151e53283113f33d642dabd',
     'target_sha256': '201c20759a79bd30b8fcb38ce5539ed1dc28ff2b39d4f9742a6a54d696033a79',
     'package': 'itsdangerous'},
    {'id': 'blinker-manifest', 'repository': 'pallets-eco/blinker',
     'commit': 'c3364059663df1ddce32799d6b1922af89a345f6',
     'target_sha256': '15282c47ae7a34e94d54691d8146dbbb708e6f9c270298fa68edae446a73fefc',
     'package': 'blinker'},
]
QUERY = 'pyproject'
TARGET = 'pyproject.toml'


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def tracked(root: Path) -> dict:
    paths = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z']).split(b'\0')
    rows = {}
    for value in paths:
        if value:
            rel = os.fsdecode(value)
            path = root / rel
            if path.is_symlink():
                rows[rel] = {'symlink': os.readlink(path)}
            else:
                body = path.read_bytes()
                rows[rel] = {'bytes': len(body), 'sha256': digest(body)}
    return rows


async def run_case(case: dict, parent: Path, out: Path, state: dict) -> dict:
    from attocode_intel.gateway import OperationGateway
    from attocode_intel.request_context import RequestContext, bind_request

    root = parent / case['package']
    root.mkdir()
    folder = out / case['id']
    folder.mkdir()
    with (folder / 'checkout.log').open('w') as log:
        for args in [
            ['init', '--quiet'],
            ['remote', 'add', 'origin', 'https://github.com/' + case['repository'] + '.git'],
            ['fetch', '--depth=1', 'origin', case['commit']],
            ['checkout', '--quiet', '--detach', 'FETCH_HEAD'],
        ]:
            subprocess.run(['git', '-C', str(root), *args], stdout=log, stderr=log,
                           check=True, timeout=120)
    assert git(root, 'rev-parse', 'HEAD') == case['commit']
    source = (root / TARGET).read_bytes()
    assert digest(source) == case['target_sha256'] and b'pyproject' not in source.lower()
    before = tracked(root)
    save(folder / 'tracked-before.json', before)
    gateway = OperationGateway(str(root), 'full', watch=False)
    records = []
    current = {'arm': 'setup', 'events': []}
    try:
        # Setup acquires the same request-owned service used by public execute.
        context = await gateway._acquire_workspace(RequestContext(str(root), str(root)))
        key = (str(root), 'local')
        try:
            with bind_request(context):
                manager = context.service._get_semantic_search()
                manager.warm()
                assert await asyncio.to_thread(manager.wait_for_body_index, 60)
                assert manager._kw_index_built and manager._body_index_built
                assert manager._provider is None
        finally:
            gateway._active[key] -= 1
        assert manager._get_trigram_index() is None, 'Fresh control already has trigram index'
        target_docs = [asdict(doc) for doc in manager._kw_docs if doc.file_path == TARGET]
        save(folder / 'keyword-target-before.json', target_docs)
        assert any(doc['term_freqs'].get(QUERY, 0) > 0 for doc in target_docs)
        keyword = manager._keyword_search
        body = manager._body_search
        prefilter = manager._trigram_prefilter

        def capture_keyword(*args, **kwargs):
            results = keyword(*args, **kwargs)
            current['events'].append({'stage': 'keyword', 'query': args[0],
                                      'results': [asdict(row) for row in results]})
            return results

        def capture_body(*args, **kwargs):
            results = body(*args, **kwargs)
            current['events'].append({'stage': 'body', 'terms': args[0],
                                      'results': [asdict(row) for row in results]})
            return results

        def capture_prefilter(tokens):
            results = prefilter(tokens)
            current['events'].append({'stage': 'prefilter', 'tokens': tokens,
                                      'candidates': None if results is None else sorted(results)})
            return results

        manager._keyword_search = capture_keyword
        manager._body_search = capture_body
        manager._trigram_prefilter = capture_prefilter

        async def primary(arm: str) -> dict:
            current.update(arm=arm, events=[])
            state['scientific_queries_issued'] += 1
            state['last_started_case'] = case['id']
            state['last_started_arm'] = arm
            save(out / 'progress.json', state)
            start = time.monotonic()
            result = await gateway.execute('semantic_search', {
                'query': QUERY, 'top_k': 5, 'file_filter': '', 'max_tokens': 2000,
            })
            raw = result.model_dump(mode='json', by_alias=True)
            save(folder / (arm + '-raw.json'), raw)
            assert not result.isError
            structured = result.structuredContent
            data = structured['data']
            public_text = '\n'.join(item.text for item in result.content if item.type == 'text')
            hits = data['results']
            assert len(hits) <= 5 and data['query'] == QUERY
            target_hits = [hit for hit in hits if hit['file_path'] == TARGET]
            visible = any(all(part in hit['snippet'] for part in ['[project]', case['package']])
                          for hit in target_hits)
            visible = visible and all(part in public_text for part in [TARGET, '[project]', case['package']])
            record = {'arm': arm, 'seconds_observed_no_sla': time.monotonic() - start,
                      'visible_target': visible, 'target_in_payload': bool(target_hits),
                      'public_truncated': structured['metadata']['truncated'],
                      'ranking': data['ranking'], 'events': list(current['events'])}
            save(folder / (arm + '-stages.json'), record)
            assert data['ranking']['index']['status'] == 'ready'
            assert not structured['metadata']['truncated']
            assert context.service._get_semantic_search() is manager
            records.append(record)
            return record

        control = await primary('no_index_control')
        state['setup_regex_calls'] += 1
        save(out / 'progress.json', state)
        regex = await gateway.execute('fast_search', {'pattern': QUERY, 'max_tokens': 2000})
        save(folder / 'fast-search-index-setup-raw.json', regex.model_dump(mode='json', by_alias=True))
        assert not regex.isError
        index = manager._get_trigram_index()
        assert index is not None and index.is_ready()
        baseline = await primary('ready_index_baseline')
        with patch.object(manager, '_trigram_prefilter', return_value=None):
            bypass = await primary('ready_index_filter_bypass')
        assert index.is_ready()
        post = tracked(root)
        save(folder / 'tracked-after.json', post)
        assert before == post
        pref = [event for event in baseline['events'] if event['stage'] == 'prefilter']
        assert len(pref) == 1 and pref[0]['tokens'] == [QUERY]
        hard_excluded = pref[0]['candidates'] is not None and TARGET not in pref[0]['candidates']
        def body_rows(record):
            return [event for event in record['events'] if event['stage'] == 'body']
        assert body_rows(baseline) == body_rows(bypass), 'Treatment changed body stage'
        recovered = (control['visible_target'] and not baseline['target_in_payload']
                     and bypass['visible_target'] and hard_excluded)
        return {'case': case, 'query': QUERY, 'top_k': 5, 'max_tokens': 2000,
                'control_visible': control['visible_target'], 'baseline_target_in_first5': baseline['target_in_payload'],
                'bypass_visible': bypass['visible_target'], 'raw_source_filter_excludes_target': hard_excluded,
                'body_unchanged': True, 'tracked_source_unchanged': True,
                'actionable_primary_recovery': recovered, 'stage_records': records}
    finally:
        await gateway.close()


async def main(out: Path) -> None:
    repo = Path.cwd()
    out.mkdir(parents=True, exist_ok=False)
    state = {'scientific_queries_issued': 0, 'setup_regex_calls': 0,
             'status': 'pre-query-setup', 'runtime_on': 'GitHub Actions only'}
    save(out / 'progress.json', state)
    parent = Path(tempfile.mkdtemp(prefix='trigram-checkouts-', dir=os.environ['RUNNER_TEMP']))
    report = {'status': 'started', 'baseline_engine': BASE, 'diagnostic_head': git(repo, 'rev-parse', 'HEAD'),
              'helper_sha256': digest(Path(__file__).read_bytes()), 'cases': [],
              'owned_checkouts_removed': False, 'role': 'source-exposed development diagnostic'}
    try:
        paths = git(repo, 'ls-tree', '-r', '--name-only', BASE, 'packages/code-intel/src').splitlines()
        paths += ['uv.lock', 'packages/code-intel/pyproject.toml']
        hashes = {}
        for path in paths:
            original = subprocess.check_output(['git', 'show', BASE + ':' + path])
            assert (repo / path).read_bytes() == original, path
            hashes[path] = digest(original)
        save(out / 'baseline-source-hashes.json', hashes)
        report['engine_source_files_exact_baseline'] = len(hashes)
        import tree_sitter_language_pack as pack
        pack.configure(cache_dir=os.environ['QUALITY_GRAMMAR_CACHE'])
        pack.download(['python', 'toml'])
        for case in CASES:
            report['cases'].append(await run_case(case, parent, out, state))
        assert state['scientific_queries_issued'] == 6 and state['setup_regex_calls'] == 2
        wins = sum(row['actionable_primary_recovery'] for row in report['cases'])
        report.update(status='complete', required_primary_recoveries=2, primary_recoveries=wins,
                      eligible_for_separate_candidate_contract=wins == 2,
                      decision='eligible' if wins == 2 else 'ineligible_stop_no_candidate')
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__, error=str(error))
        raise
    finally:
        shutil.rmtree(parent)
        report.update(owned_checkouts_removed=not parent.exists(), query_counts=dict(state))
        save(out / 'report.json', report)
        save(out / 'progress.json', {**state, 'status': report['status']})
        print(json.dumps({key: value for key, value in report.items() if key != 'cases'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    asyncio.run(main(parser.parse_args().out.resolve()))
