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
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import psutil
from attocode_intel import output, search_evidence
from attocode_intel.gateway import OperationGateway
from attocode_intel.output import response_tokens

from eval.quality import corpus, runner
from eval.quality.preview_windows import window_preview

DESIGN = runner.REPO / 'packages/code-intel/evals/designs/2026-10-22-preview-windows.json'
BASELINE = search_evidence.snippet_window
GIB = 2**30


class BudgetGuard:
    """Sample this controller, all owned descendants, and every output root."""

    def __init__(self, roots, evidence, limits, deadline):
        self.roots, self.evidence, self.limits, self.deadline = roots, evidence, limits, deadline
        self.owner = psutil.Process()
        self.peaks = {'rss_bytes': 0, 'disk_bytes': 0, 'evidence_bytes': 0}
        self.violation = None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._watch, daemon=True)

    def sample(self):
        children = self.owner.children(recursive=True)
        rss = self.owner.memory_info().rss
        for child in children:
            try:
                rss += child.memory_info().rss
            except psutil.NoSuchProcess:
                pass
        values = {'rss_bytes': rss, 'disk_bytes': sum(runner.disk_bytes(p) for p in self.roots),
                  'evidence_bytes': runner.disk_bytes(self.evidence)}
        self.peaks = {key: max(self.peaks[key], value) for key, value in values.items()}
        reason = next((key + '_budget' for key, value in values.items() if value >= self.limits[key]), None)
        if time.monotonic() >= self.deadline:
            reason = 'complete_deadline'
        if reason:
            self.violation = self.violation or reason
            # Only descendants of this specific controller are owned here.
            for child in reversed(children):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass

    def _watch(self):
        try:
            while not self.stop.is_set():
                self.sample()
                self.stop.wait(.1)
        except (psutil.Error, OSError) as exc:
            self.violation = 'budget_inspection_failed:' + type(exc).__name__

    def start(self):
        self.sample()
        self.thread.start()

    def check(self):
        self.sample()
        if self.violation:
            raise RuntimeError(self.violation)

    def close(self):
        self.stop.set()
        if self.thread.ident is not None:
            self.thread.join(timeout=2)
        if self.thread.is_alive():
            self.violation = self.violation or 'budget_monitor_cleanup'
        self.sample()


def identity():
    paths = [*sorted((runner.REPO / 'packages/code-intel/src/attocode_intel').rglob('*.py')),
             DESIGN, Path(__file__), Path(__file__).with_name('preview_windows.py'),
             runner.REPO / 'tests/eval/test_preview_windows.py', runner.REPO / 'tests/eval/test_preview_trial.py',
             *[runner.REPO / path for path in ['eval/quality/corpus.py', 'eval/quality/sources.py',
                                               'eval/quality/runner.py', 'eval/matrix/run.py']]]
    return runner.fingerprint(paths)


def page_identity(data):
    return [{key: row.get(key) for key in ('file_path', 'name', 'chunk_type', 'score', 'line', 'end_line')}
            for row in data['data']['results']]


def source_spans(page, root):
    """Admit every delivered source snippet, with exact intersected line bounds."""
    spans = []
    for hit in page['data']['results']:
        first, last = hit.get('snippet_start_line'), hit.get('snippet_end_line')
        if first is None or last is None:
            assert first is None and last is None
            spans.append([])
            continue
        path = (root / hit['file_path']).resolve()
        assert path.is_relative_to(root.resolve())
        source = path.read_text()
        lines = source.splitlines(keepends=True)
        assert hit.get('line') and 1 <= hit['line'] <= first <= last <= hit['end_line'] <= len(lines)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))
        assert hit['snippet']
        window = source[offsets[first - 1]:offsets[last]]
        found, valid = window.find(hit['snippet']), []
        while found >= 0:
            begin = offsets[first - 1] + found
            end = begin + len(hit['snippet'])
            if begin < offsets[first] and end > offsets[last - 1]:
                valid.append((begin, end))
            found = window.find(hit['snippet'], found + 1)
        assert valid, {'file': hit['file_path'], 'first': first, 'last': last}
        spans.append(valid)
    return spans


def judgment(page, question, root, spans):
    hits = page['data']['results']
    source = (root / question['file']).read_text().splitlines(keepends=True)
    anchors = [(sum(map(len, source[:a['line'] - 1])), len(a['quote'])) for a in question['anchors']]
    found, visible = False, False
    for hit, possible in zip(hits, spans, strict=True):
        if hit['file_path'] != question['file']:
            continue
        found = True
        if any(all(begin <= position and position + size <= end for position, size in anchors)
               for begin, end in possible):
            visible = True
    return {'file': found, 'visible': visible}


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
                                          'judgment': judgment(decoded, question, root, source_spans(decoded, root)),
                                          'response': decoded})
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


def regression_phase(root, out, env, deadline, guard):
    command = [sys.executable, '-m', 'pytest', '-c', 'packages/code-intel/pyproject.toml',
               '--confcutdir=tests/eval', 'tests/eval/test_preview_windows.py', 'tests/eval/test_preview_trial.py',
               '-q', '-p', 'eval.quality.no_agent']
    rows = []
    for phase in ('baseline', 'candidate'):
        guard.check()
        xml = out / f'{phase}.xml'
        phase_env = dict(env, QUALITY_PREVIEW_BASELINE='1' if phase == 'baseline' else '0')
        row = runner.supervise([*command, '--junitxml=' + str(xml)], cwd=runner.REPO, env=phase_env,
                               root=root, log=out / f'{phase}.log', deadline=deadline,
                               max_bytes=2 * GIB, max_rss=2 * GIB)
        cases = ET.parse(xml).findall('.//testcase')
        failed = [c for c in cases if c.find('failure') is not None]
        guard.check()
        assert len(cases) == 13 and not any(c.find('error') is not None or c.find('skipped') is not None for c in cases)
        assert row['cleanup_verified'] and 'reason' not in row
        if phase == 'baseline':
            assert row['exit_code'] == 1 and len(failed) == 2
            assert all(c.attrib['name'].startswith('test_later_window_strictly_extends_baseline_positive_coverage[')
                       and c.find('failure').attrib.get('message', '').startswith('assert False')
                       for c in failed)
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
    guard = BudgetGuard([scratch, args.out], args.out, design['limits'], deadline)
    try:
        guard.start()
        regressions = regression_phase(scratch, args.out, env, deadline, guard)
        runner.write_json(args.out / 'regressions.json', regressions)
        for spec in design['packs']:
            guard.check()
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
            guard.check()
            assert runner.disk_bytes(args.out) <= design['limits']['evidence_bytes']
            report = json.loads(output_file.read_text())
            assert report['status'] == 'observed'
            reports.append(report)
            shutil.rmtree(work)
        result = decide(reports)
        guard.check()
        result.update(status='observed', runtimes=runtimes, regressions=regressions)
    except BaseException as exc:
        error = exc
        result = {'status': 'incomplete', 'error_type': type(exc).__name__, 'error': str(exc), 'runtimes': runtimes}
    finally:
        shutil.rmtree(scratch)
        result.update(seconds=time.monotonic() - started, cleanup_verified=not scratch.exists(),
                      identities_unchanged=identity() == before)
        guard.close()
        result.update(aggregate_sampled_peaks=guard.peaks, budget_violation=guard.violation)
        if guard.violation or time.monotonic() >= deadline:
            result['status'] = 'incomplete'
        if not result['identities_unchanged']:
            result['status'] = 'incomplete'
        runner.write_json(args.out / 'decision.json', result)
        if time.monotonic() >= deadline or runner.disk_bytes(args.out) >= design['limits']['evidence_bytes']:
            result.update(status='incomplete', budget_violation=guard.violation or 'finalization_budget')
            runner.write_json(args.out / 'decision.json', result)
        result['seconds'] = time.monotonic() - started
        runner.write_json(args.out / 'decision.json', result)
        print(json.dumps(result), flush=True)
    if error:
        raise error
    if result['status'] != 'observed':
        raise RuntimeError('Incomplete experiment; do not infer candidate outcome')


if __name__ == '__main__':
    main()
