"""One frozen, runner-only preview comparison. Does not execute corpus code."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from attocode_intel import output, search_evidence
from attocode_intel.gateway import OperationGateway
from attocode_intel.output import response_tokens

from eval.quality import corpus, runner
from eval.quality.preview_windows import window_preview

DESIGN = runner.REPO / 'packages/code-intel/evals/designs/2026-10-22-preview-windows.json'
BASELINE = search_evidence.snippet_window
GIB = 2**30


def identity():
    paths = [*sorted((runner.REPO / 'packages/code-intel/src/attocode_intel').rglob('*.py')),
             DESIGN, Path(__file__), Path(__file__).with_name('preview_windows.py'),
             runner.REPO / 'tests/eval/test_preview_windows.py',
             *[runner.REPO / path for path in ['eval/quality/corpus.py', 'eval/quality/sources.py',
                                               'eval/quality/runner.py', 'eval/matrix/run.py']]]
    return runner.fingerprint(paths)


def page_identity(data):
    return [{key: row.get(key) for key in ('file_path', 'name', 'chunk_type', 'score', 'line', 'end_line')}
            for row in data['data']['results']]


def judgment(page, question, root):
    hits = page['data']['results']
    found = [hit for hit in hits if hit['file_path'] == question['file']]
    source = (root / question['file']).read_text().splitlines()
    visible = False
    for hit in found:
        first, last = hit.get('snippet_start_line'), hit.get('snippet_end_line')
        if first is None or last is None:
            continue
        assert 1 <= first <= last <= len(source)
        # Every coordinate-bearing excerpt must be a contiguous substring of
        # exactly its declared source range, including partial-line previews.
        raw_lines = (root / question['file']).read_text().splitlines(keepends=True)
        assert hit['snippet'] in ''.join(raw_lines[first - 1:last])
        if all(first <= anchor['line'] <= last and anchor['quote'] in hit['snippet']
               for anchor in question['anchors']):
            visible = True
    return {'file': bool(found), 'visible': visible}


async def observe(spec, root, report):
    gateway = OperationGateway(str(root), 'daily', watch=False)
    pages = []
    before = {path: hashlib.sha256((root / path).read_bytes()).hexdigest()
              for path in spec['source_sha256']}
    assert before == spec['source_sha256']
    for question in spec['questions']:
        lines = (root / question['file']).read_text().splitlines()
        assert all(lines[a['line'] - 1] == a['quote'] for a in question['anchors'])
    frozen = json.loads(DESIGN.read_text())
    try:
        warmup, warm = await corpus.ready_search(gateway, {
            'query': spec['questions'][0]['query'], 'top_k': 5, 'max_tokens': 2000})
        assert not warmup.isError
        for round_id, arms in enumerate(frozen['rounds']):
            for arm in arms:
                function = BASELINE if arm == 'baseline' else window_preview
                with patch.object(search_evidence, 'snippet_window', function), patch.object(output, 'snippet_window', function):
                    for question in spec['questions']:
                        requests = [(depth, budget, '') for depth in frozen['requests']['depths']
                                    for budget in frozen['requests']['budgets']]
                        requests.append((5, 2000, question['file']))
                        for depth, budget, scope in requests:
                            args = {'query': question['query'], 'top_k': depth,
                                    'max_tokens': budget, 'file_filter': scope}
                            timings, decoded = [], None
                            for _sample in range(1 if scope else 3):
                                started = time.perf_counter()
                                response = await gateway.execute_mcp('semantic_search', args)
                                timings.append((time.perf_counter() - started) * 1000)
                                assert not response.isError, response.content
                                assert response_tokens(response) <= budget
                                current = json.loads(response.content[0].text)
                                assert current['data']['ranking']['index']['status'] == 'ready'
                                if decoded is not None:
                                    assert current['data'] == decoded['data'], 'unstable repeated page'
                                decoded = current
                            pages.append({'round': round_id, 'arm': arm, 'question': question['id'],
                                          'kind': question['kind'], 'arguments': args, 'timings_ms': timings,
                                          'judgment': judgment(decoded, question, root), 'response': decoded})
                            runner.write_json(report, {'status': 'in_progress', 'pack': spec['id'],
                                                       'source': before, 'warmup': warm, 'pages': pages})
    finally:
        await gateway.close()
    assert before == {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in before}
    return {'status': 'observed', 'pack': spec['id'], 'source': before, 'warmup': warm, 'pages': pages}


def worker(args):
    frozen = json.loads(DESIGN.read_text())
    spec = next(p for p in frozen['packs'] if p['id'] == args.pack)
    root = args.root / 'source'
    root.mkdir()
    tree = corpus.materialize(spec, root, args.root / 'cache')
    result = asyncio.run(observe(spec, root, args.out))
    result['source_tree'] = tree
    runner.write_json(args.out, result)


def decide(reports):
    losses, identity_losses, control_changes = [], [], []
    gains, timing = {}, {'baseline': [], 'candidate': []}
    totals = {'baseline': {'file_at5': 0, 'visible_at5': 0},
              'candidate': {'file_at5': 0, 'visible_at5': 0}}
    for report in reports:
        baseline = {}
        for row in report['pages']:
            args = row['arguments']
            key = (row['round'], row['question'], args['top_k'], args['max_tokens'], args['file_filter'])
            if not args['file_filter']:
                timing[row['arm']].extend(row['timings_ms'])
            if args['top_k'] == 5 and not args['file_filter']:
                for metric in ('file', 'visible'):
                    totals[row['arm']][metric + '_at5'] += row['judgment'][metric]
            if row['arm'] == 'baseline':
                baseline[key] = row
        for row in report['pages']:
            if row['arm'] != 'candidate':
                continue
            args = row['arguments']
            key = (row['round'], row['question'], args['top_k'], args['max_tokens'], args['file_filter'])
            old = baseline[key]
            for metric in ('file', 'visible'):
                if old['judgment'][metric] and not row['judgment'][metric]:
                    losses.append({'pack': report['pack'], 'key': key, 'metric': metric})
            if page_identity(old['response']) != page_identity(row['response']):
                identity_losses.append({'pack': report['pack'], 'key': key})
            if row['kind'] == 'control' and old['response']['data'] != row['response']['data']:
                control_changes.append({'pack': report['pack'], 'key': key})
            if (args['top_k'] == 5 and not args['file_filter']
                    and row['judgment']['visible'] and not old['judgment']['visible']):
                gains.setdefault(row['round'], set()).add((report['pack'], row['question']))
    p95 = {arm: sorted(values)[math.ceil(.95 * len(values)) - 1] for arm, values in timing.items()}
    gain_gate = all(len(gains.get(r, set())) >= 2 and len({p for p, _q in gains.get(r, set())}) >= 2
                    for r in range(3))
    passed = (not losses and not identity_losses and not control_changes and gain_gate
              and p95['candidate'] <= max(100, 1.5 * p95['baseline']))
    return {'decision': 'retain' if passed else 'reject', 'totals': totals,
            'losses': losses, 'identity_changes': identity_losses, 'control_changes': control_changes,
            'gains_at5_by_round': {str(k): sorted(v) for k, v in gains.items()},
            'gain_gate': gain_gate, 'warm_p95_ms': p95,
            'limits': 'Non-exhaustive implementer-authored judgments. No ranking or agent-completion gain established.'}


def regression_phase(root, out, env, deadline):
    command = [sys.executable, '-m', 'pytest', '-c', 'packages/code-intel/pyproject.toml',
               '--confcutdir=tests/eval', 'tests/eval/test_preview_windows.py', '-q', '-p', 'eval.quality.no_agent']
    rows = []
    for phase in ('baseline', 'candidate'):
        xml = out / f'{phase}.xml'
        phase_env = dict(env, QUALITY_PREVIEW_BASELINE='1' if phase == 'baseline' else '0')
        row = runner.supervise([*command, '--junitxml=' + str(xml)], cwd=runner.REPO, env=phase_env,
                               root=root, log=out / f'{phase}.log', deadline=deadline,
                               max_bytes=2 * GIB, max_rss=2 * GIB)
        cases = ET.parse(xml).findall('.//testcase')
        failed = [c for c in cases if c.find('failure') is not None]
        assert len(cases) == 9 and not any(c.find('error') is not None or c.find('skipped') is not None for c in cases)
        assert row['cleanup_verified'] and 'reason' not in row
        if phase == 'baseline':
            assert row['exit_code'] == 1 and len(failed) == 2
            assert all(c.attrib['name'].startswith('test_later_window_strictly_extends_baseline_positive_coverage[')
                       and c.find('failure').attrib['type'] == 'AssertionError' for c in failed)
        else:
            assert row['status'] == 'passed' and not failed
        rows.append(dict(phase=phase, runtime=row, tests=len(cases), assertion_failures=len(failed)))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--pack')
    parser.add_argument('--root', type=Path)
    args = parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('Runtime experiments run only on GitHub Actions; no local fallback.')
    if args.pack:
        worker(args)
        return
    assert not args.out.exists()
    args.out.mkdir(parents=True)
    design = json.loads(DESIGN.read_text())
    before = identity()
    runner.write_json(args.out / 'freeze.json', {'design': design, 'identities': before,
                       'head': subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode().strip(),
                       'run_id': os.environ['GITHUB_RUN_ID'], 'attempt': os.environ['GITHUB_RUN_ATTEMPT']})
    started, runtimes, reports = time.monotonic(), [], []
    deadline = started + design['limits']['total_seconds']
    scratch = Path(tempfile.mkdtemp(prefix='preview-windows-', dir=os.environ['RUNNER_TEMP']))
    runner.managed_root(scratch)
    env = dict(runner.environment(scratch), QUALITY_ALLOW_DOWNLOADS='1')
    for name in ('TMPDIR', 'TMP', 'TEMP'):
        os.environ[name] = env[name]
    error = None
    try:
        regressions = regression_phase(scratch, args.out, env, deadline)
        runner.write_json(args.out / 'regressions.json', regressions)
        for spec in design['packs']:
            work = scratch / 'work' / spec['id']
            work.mkdir()
            output_file = args.out / (spec['id'] + '.json')
            runtime = runner.supervise([sys.executable, '-m', 'eval.quality.preview_trial',
                      '--pack', spec['id'], '--root', str(work), '--out', str(output_file)],
                      cwd=runner.REPO, env=env, root=scratch, log=args.out / (spec['id'] + '.log'),
                      deadline=min(deadline, time.monotonic() + design['limits']['pack_seconds']),
                      max_bytes=design['limits']['disk_bytes'] - design['limits']['evidence_bytes'],
                      max_rss=design['limits']['rss_bytes'])
            runtimes.append(dict(pack=spec['id'], runtime=runtime))
            runner.write_json(args.out / 'runtime.json', runtimes)
            assert runtime['status'] == 'passed' and runtime['cleanup_verified'], runtime
            assert runner.disk_bytes(args.out) <= design['limits']['evidence_bytes']
            report = json.loads(output_file.read_text())
            assert report['status'] == 'observed'
            reports.append(report)
            shutil.rmtree(work)
        result = decide(reports)
        result.update(status='observed', runtimes=runtimes, regressions=regressions)
    except BaseException as exc:
        error = exc
        result = {'status': 'incomplete', 'error_type': type(exc).__name__, 'error': str(exc), 'runtimes': runtimes}
    finally:
        shutil.rmtree(scratch)
        result.update(seconds=time.monotonic() - started, cleanup_verified=not scratch.exists(),
                      identities_unchanged=identity() == before)
        if not result['identities_unchanged']:
            result['status'] = 'incomplete'
        runner.write_json(args.out / 'decision.json', result)
        print(json.dumps(result), flush=True)
    if error:
        raise error


if __name__ == '__main__':
    main()
