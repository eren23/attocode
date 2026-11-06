"""One-off, source-known diagnostic; no candidate or product change."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile


async def run(root):
    from attocode_intel.gateway import OperationGateway
    from eval.quality.corpus import ready_search
    from eval.quality.corpus_capture import RecordedGateway, digest
    from eval.quality.experiment_evidence import Journal, assert_engine
    from eval.quality.fixture_identity import source_manifest
    from eval.quality.mcp_search import decode, engine_identity, evidence_hits, inspect_hits, observe
    from eval.quality.runner import write_json

    repository = Path.cwd()
    evidence = root / 'evidence'
    evidence.mkdir(parents=True, exist_ok=True)
    manifest_path = repository / 'eval/quality/first_page_questions.json'
    manifest = json.loads(manifest_path.read_text())
    baseline = manifest['fixture_commit']
    subprocess.run(['git', 'diff', '--quiet', baseline, 'HEAD', '--',
                    'packages/code-intel/src', 'packages/code-intel/pyproject.toml', 'uv.lock',
                    'eval/quality/mcp_search.py', 'eval/quality/corpus.py',
                    'eval/quality/corpus_capture.py', 'eval/quality/experiment_evidence.py',
                    'eval/quality/fixture_identity.py', 'eval/quality/runner.py'], check=True)
    engine = repository / 'packages/code-intel/src/attocode_intel'
    journal = Journal(evidence / 'journal', 64 * 2**20)
    report = {'status': 'incomplete', 'fixture_commit': baseline,
              'operator_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
              'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
              'scope': manifest['scope'], 'cases': []}
    write_json(evidence / 'questions.json', manifest)
    write_json(evidence / 'report.json', report)
    origins = assert_engine(engine)
    engine_hash = engine_identity()
    journal.response({'event': 'engine_before'}, {'origins': origins, 'source_sha256': engine_hash})
    work = root / 'work'
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fixture-', dir=work) as directory:
        fixture = Path(directory)
        archive = root / 'fixture.tar'
        with archive.open('wb') as stream:
            subprocess.run(['git', 'archive', '--format=tar', baseline], stdout=stream, check=True)
        report['fixture_archive_sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
        with tarfile.open(archive) as source:
            source.extractall(fixture, filter='data')
        archive.unlink()
        before = source_manifest(fixture)
        for name in ('first_page_diagnostic.py', 'first_page_questions.json'):
            assert not (fixture / 'eval/quality' / name).exists(), 'diagnostic leaked into source fixture'
        for case in manifest['cases']:
            path = fixture / case['file']
            assert hashlib.sha256(path.read_bytes()).hexdigest() == case['source_sha256']
            assert case['quote'] in path.read_text().splitlines()[case['line'] - 1]
        for name, entry in before.items():
            if entry['kind'] == 'file':
                raw = (fixture / name).read_bytes()
                assert all(c['query'].encode() not in raw for c in manifest['cases']), 'question text leaked into fixture'
        journal.response({'event': 'source_before'}, before)
        peer = OperationGateway(str(fixture), manifest['profile'], watch=False)
        gateway = RecordedGateway(peer, fixture, journal)
        try:
            response, warmup = await ready_search(gateway, {
                'query': 'first_page_readiness_control_20261106', 'top_k': 1, 'max_tokens': 2000,
            }, timeout=180)
            index = decode(response)['data']['ranking']['index']
            assert index['status'] == 'ready' and index['body_index_available'] and index['body_index_ready']
            report['warmup'] = warmup
            report['initial_index'] = index
            # Freeze all default pages before any label-guided control or inspection.
            for case in manifest['cases']:
                row = {**case, 'pages': {}}
                report['cases'].append(row)
                journal.response({'event': 'consume_question', 'id': case['id']}, {'query': case['query']})
                page = await observe(gateway, case['query'], top_k=10, budget=2000, capture_generation=True)
                page['hits'] = evidence_hits(page['response']['data']['results'], [case])
                row['pages']['default'] = page
                write_json(evidence / 'report.json', report)
            for row in report['cases']:
                for name, depth, budget, file_filter in [('deep', 24, 8000, ''),
                                                         ('scoped', 5, 4000, row['file'])]:
                    page = await observe(gateway, row['query'], top_k=depth, budget=budget,
                                         file_filter=file_filter, capture_generation=True)
                    page['hits'] = evidence_hits(page['response']['data']['results'], [row])
                    row['pages'][name] = page
                    write_json(evidence / 'report.json', report)
                request = {'symbol_name': row['symbol'], 'file_path': row['file'],
                           'line': row['definition_line'], 'task_hint': row['query'], 'max_tokens': 8000}
                inspection = {'request': request, 'response': decode(await gateway.execute_mcp('inspect_symbol', request))}
                row['inspection'] = inspection
                row['inspection_hits'] = inspect_hits(inspection, [row])
                write_json(evidence / 'report.json', report)
        finally:
            await gateway.close()
            after = source_manifest(fixture)
            journal.response({'event': 'source_after'}, after)
            assert before == after, 'fixture source changed'
            report['fixture_source_sha256'] = digest(before)
            report['source_unchanged'] = True
            write_json(evidence / 'report.json', report)
    assert engine_identity() == engine_hash
    journal.response({'event': 'engine_after'}, {'origins': assert_engine(engine), 'source_sha256': engine_hash})
    report.update(status='complete', engine_sha256=engine_hash, fixture_removed=True)
    write_json(evidence / 'report.json', report)
    print(json.dumps({'status': report['status'], 'cases': [
        {'id': r['id'], 'default_hits': r['pages']['default']['hits'], 'inspection_hits': r['inspection_hits']}
        for r in report['cases']]}))


if __name__ == '__main__':
    assert os.environ.get('GITHUB_ACTIONS') == 'true', 'Runtime is permitted only in GitHub Actions'
    asyncio.run(run(Path(sys.argv[1]).resolve()))
