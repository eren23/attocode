"""Frozen subscription-only external QA and feature development pilot."""
from __future__ import annotations

import hashlib
import json
import random
import secrets
import shutil
import sys
import time
from pathlib import Path

from external_benchmarks import (
    copy_source,
    evaluate_feature,
    initialize_git,
    prompt_for,
    public_task,
    shell,
    start_runtime,
    stop_runtime,
    submitted_patch,
    validate_pack,
)
from onboarding_study import GUIDANCE, configure_setup, guidance_checks
from study import digest, harness_hash, schedule, source_hash, tree_hash, write_json
from study_clients import invoke, preflight, subscription_env

CLIENTS = ('codex', 'claude')
LANES = ('native', 'current')


def versions():
    return {c: shell([c, '--version']).strip() for c in CLIENTS}


def source_fingerprint(root):
    """Hash source and link identities without following links outside the snapshot."""
    import os
    entries = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in {'.git', '.attocode', '__pycache__', 'node_modules', 'target'})
        for name in sorted(files + [d for d in dirs if (Path(directory) / d).is_symlink()]):
            path = Path(directory) / name
            if name.endswith('.pyc'):
                continue
            entries[path.relative_to(root).as_posix()] = (
                {'link': str(path.readlink())} if path.is_symlink() else
                {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'executable': bool(path.stat().st_mode & 0o111)})
    return digest(entries)


def feature_identity(pack):
    checkout = Path(pack['feature_checkout'])
    return {'revision': shell(['git', '-C', str(checkout), 'rev-parse', 'HEAD']).strip(),
            'diff': digest(shell(['git', '-C', str(checkout), 'diff', 'HEAD'])),
            'lock': hashlib.sha256((checkout / 'uv.lock').read_bytes()).hexdigest()}


def load(study):
    manifest = json.loads((study / 'manifest.json').read_text())
    identity = manifest.pop('study_id')
    if digest(manifest) != identity:
        raise ValueError('Manifest drift')
    manifest['study_id'] = identity
    pack = json.loads((study / 'private' / 'pack.json').read_text())
    checks = [(harness_hash(Path(__file__).parent), manifest['harness_sha256'], 'harness'),
              (source_hash(study / 'engine'), manifest['engine_sha256'], 'engine'),
              (tree_hash(study / 'private'), manifest['pack_sha256'], 'private pack'),
              (versions(), manifest['client_versions'], 'clients'),
              (feature_identity(pack), manifest['feature_identity'], 'upstream evaluator')]
    checks += [(source_fingerprint(study / 'sources' / t['id']), manifest['source_hashes'][t['id']], t['id'])
               for t in manifest['tasks']]
    for actual, expected, label in checks:
        if actual != expected:
            raise ValueError(f'Frozen {label} changed')
    return manifest


def freeze(args):
    project, study = args.project.resolve(), args.study.resolve()
    if not args.benchmark_pack:
        raise ValueError('Supply --benchmark-pack')
    directory = args.benchmark_pack.resolve()
    if study.is_relative_to(project) or directory.is_relative_to(project):
        raise ValueError('Study and private pack must be outside the repository')
    if study.exists():
        raise ValueError('Never overwrite a study directory')
    pack = json.loads((directory / 'pack.json').read_text())
    validate_pack(pack, directory)
    endpoint = shell(['docker', 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}']).strip()
    if not endpoint.startswith('unix:///'):
        raise ValueError('External pilot requires a local Docker Unix socket')
    models = json.loads(args.models.read_text())
    if any(not isinstance(models.get(c), str) or not models[c] for c in CLIENTS):
        raise ValueError('Explicit client model IDs required')
    study.mkdir(parents=True, mode=0o700)
    shutil.copytree(directory, study / 'private', ignore=shutil.ignore_patterns('sources', '__pycache__', '*.pyc'))
    shutil.copytree(project / 'packages/code-intel/src', study / 'engine', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(Path(__file__).parent, study / 'harness', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for task in pack['tasks']:
        copy_source(directory / 'sources' / task['id'], study / 'sources' / task['id'])
    manifest = {'version': 1, 'mode': 'external', 'tasks': pack['tasks'], 'models': {c: models[c] for c in CLIENTS},
                'python': sys.executable, 'clients': CLIENTS, 'lanes': LANES, 'client_versions': versions(),
                'runtime_socket': endpoint.removeprefix('unix://'),
                'engine_sha256': source_hash(study / 'engine'), 'harness_sha256': harness_hash(study / 'harness'),
                'pack_sha256': tree_hash(study / 'private'), 'feature_identity': feature_identity(pack),
                'source_hashes': {t['id']: source_fingerprint(study / 'sources' / t['id']) for t in pack['tasks']},
                'schedule': schedule(pack['tasks'], 1, seed=9341, lanes=LANES, clients=CLIENTS),
                'seed': 9341, 'repetitions': 1, 'max_scored_trials': 16, 'max_excluded_trials': 4,
                'selection': 'natural', 'grading': 'official feature verifier; operator QA rubric review',
                'environment': pack['environment'], 'provenance': pack['provenance'],
                'scope': 'Adapted local diagnostic; no release or leaderboard claim',
                'cache_state': 'Fresh workspace and runtime; OS/provider caches uncontrolled'}
    manifest['study_id'] = digest(manifest)
    write_json(study / 'manifest.json', manifest)
    print(json.dumps({'frozen': manifest['study_id'], 'scored_trials': 16}), flush=True)


def prepare(args):
    manifest = load(args.study)
    results = {}
    for task in manifest['tasks']:
        image = json.loads(shell(['docker', 'image', 'inspect', task['image']]))[0]
        if image['Id'] != task['image']:
            raise ValueError('Runtime image drift')
        results[task['id']] = task['preparation']
    write_json(args.study / 'preparation.json', {'study_id': manifest['study_id'], 'tasks': results, 'passed': True})
    print(json.dumps({'prepared': len(results)}), flush=True)


def ready(args, client):
    quota = json.loads(args.quota.read_text()) if args.quota and args.quota.exists() else {}
    result = preflight(client, quota, subscription_env())
    if not result['ready']:
        raise RuntimeError(json.dumps({'client': client, 'blocked': result}))


def successful(result):
    return not any(result.get(k) for k in ('exit_code', 'timed_out', 'quota_exhausted', 'terminal_error', 'permission_denials'))


def wiring(args):
    manifest = load(args.study)
    task = manifest['tasks'][0]
    for client in args.clients or CLIENTS:
        directory = args.study / 'wiring' / client
        if directory.exists():
            result = directory / 'result.json'
            if result.exists() and json.loads(result.read_text()).get('passed'):
                continue
            raise ValueError('Preserve failed/interrupted wiring; freeze a new study after fixing it')
        ready(args, client)
        root = directory / 'repository'
        root.mkdir(parents=True)
        (root / 'benchmark_fixture.py').write_text('def benchmark_value():\n    return 42\n')
        name = 'intel-wire-' + secrets.token_hex(6)
        checks = {'guidance_loaded_without_reads': False, 'transport': False}
        record = {'study_id': manifest['study_id'], 'excluded': True, 'passed': False, 'checks': checks}
        try:
            start_runtime(task, root, name)
            configured = configure_setup(manifest, args.study, root, 'intel_installed', directory / 'transport', client)
            guidance = root / GUIDANCE[client]
            original = guidance.read_text()
            token = secrets.token_hex(16)
            guidance.write_text(original + f'\nReadiness token: {token}\n')
            schema = {'type': 'object', 'properties': {'readiness_token': {'type': 'string'}},
                      'required': ['readiness_token'], 'additionalProperties': False}
            result = invoke(client, manifest['models'][client], root, directory / 'guidance', configured['servers'],
                            'Return the readiness token from your project instructions. Do not call tools or read files.',
                            120, subscription_env(), answer_schema=schema, project_guidance=True,
                            runtime_socket=manifest['runtime_socket'])
            guidance.write_text(original)
            write_json(directory / 'guidance-result.json', result)
            checks['guidance_loaded_without_reads'] = guidance_checks(result, token)
            if checks['guidance_loaded_without_reads']:
                ready(args, client)
                schema = {'type': 'object', 'properties': {'value': {'type': 'integer'}},
                          'required': ['value'], 'additionalProperties': False}
                prompt = ('Excluded transport check: call attocode-code-intel.inspect_symbol for benchmark_value in '
                          'benchmark_fixture.py. Read that file with native tools and execute '
                          '`python3 .benchmark/run.py -- python3 -c "from benchmark_fixture import benchmark_value; '
                          'print(benchmark_value())"`. Return its value.')
                result = invoke(client, manifest['models'][client], root, directory / 'transport', configured['servers'],
                                prompt, 180, subscription_env(), answer_schema=schema, project_guidance=True,
                                runtime_socket=manifest['runtime_socket'])
                checks['transport'] = (successful(result) and result.get('mcp_used') and result['output'].get('value') == 42
                                       and any('.benchmark/run.py' in json.dumps(c['arguments']) for c in result['tool_calls']))
                write_json(directory / 'transport-result.json', result)
            record['passed'] = all(checks.values())
        finally:
            stop_runtime(name)
            write_json(directory / 'result.json', record)
        if not record['passed']:
            raise RuntimeError(f'Wiring failed: {client}')


def run(args):
    manifest = load(args.study)
    prep = json.loads((args.study / 'preparation.json').read_text())
    if prep.get('study_id') != manifest['study_id'] or prep.get('passed') is not True:
        raise ValueError('Preparation is required')
    finished = 0
    for row in manifest['schedule']:
        if args.clients and row['client'] not in args.clients or args.tasks and row['task'] not in args.tasks:
            continue
        directory = args.study / 'runs' / row['id'].replace(':', '-')
        if (directory / 'result.json').exists():
            continue
        if directory.exists():
            write_json(directory / 'result.json', {**row, 'study_id': manifest['study_id'], 'status': 'interrupted'})
            continue
        wiring_result = json.loads((args.study / 'wiring' / row['client'] / 'result.json').read_text())
        if wiring_result.get('study_id') != manifest['study_id'] or wiring_result.get('passed') is not True:
            raise ValueError('Wiring is required')
        ready(args, row['client'])
        task = next(t for t in manifest['tasks'] if t['id'] == row['task'])
        root = directory / 'repository'
        copy_source(args.study / 'sources' / task['id'], root)
        name = 'intel-trial-' + secrets.token_hex(6)
        record = {**row, 'study_id': manifest['study_id'], 'status': 'failed', 'stages': []}
        print(json.dumps({'starting': row['id']}), flush=True)
        try:
            start = time.monotonic()
            start_runtime(task, root, name)
            configured = configure_setup(manifest, args.study, root,
                                         'native' if row['lane'] == 'native' else 'intel_installed', directory / 'stage-0', row['client'])
            initialize_git(root)
            helper_hash = hashlib.sha256((root / '.benchmark/run.py').read_bytes()).hexdigest()
            record['setup_seconds'] = time.monotonic() - start
            write_json(directory / 'started.json', {**row, 'time': time.time()})
            prompt = prompt_for(task, root)
            (directory / 'prompt.txt').write_text(prompt)
            result = invoke(row['client'], manifest['models'][row['client']], root, directory / 'stage-0',
                            configured['servers'], prompt, task['timeout'], subscription_env(),
                            project_guidance=True, plain_text=True, runtime_socket=manifest['runtime_socket'])
            record.update(stages=[result], seconds=result['seconds'], onboarding=configured)
            answer_path = root / '.benchmark/answer.txt'
            answer = answer_path.read_text() if answer_path.is_file() and not answer_path.is_symlink() else ''
            if task['kind'] != 'qa':
                answer = result.get('answer_text', '')
            # The required QA file must exist; chat output is retained but never silently substituted.
            write_json(directory / 'committed-answer.json', {'text': answer, 'sha256': digest(answer), 'time': time.time()})
            patch, changed = submitted_patch(root)
            patch_path = directory / 'submitted.diff'
            patch_path.write_text(patch)
            write_json(directory / 'committed-patch.json', {'sha256': digest(patch), 'time': time.time()})
            record.update(changed_files=changed,
                          status='completed' if successful(result) else 'execution_failed',
                          helper_unchanged=helper_hash == hashlib.sha256((root / '.benchmark/run.py').read_bytes()).hexdigest(),
                          protocol_review='pending')
            stop_runtime(name)
            start = time.monotonic()
            if task['kind'] == 'feature':
                record['quality'] = evaluate_feature(args.study, task, patch_path, directory / 'acceptance')
            else:
                record['quality'] = {'status': 'operator_review_pending', 'answer_present': bool(answer.strip()),
                                     'repository_unchanged': not changed}
            record['evaluation_seconds'] = time.monotonic() - start
        except Exception as exc:
            record['error'] = str(exc)
        finally:
            stop_runtime(name)
            write_json(directory / 'result.json', record)
        print(json.dumps({'completed': row['id'], 'status': record['status'], 'seconds': record.get('seconds')}), flush=True)
        finished += 1
        if finished >= (args.max_runs or 4) or any(s.get('quota_exhausted') for s in record['stages']):
            break


def operator_scores(study, manifest, rows):
    path = study / 'operator-review.json'
    review = json.loads(path.read_text()) if path.exists() else {'study_id': manifest['study_id'], 'attempts': {}}
    if review.get('study_id') != manifest['study_id']:
        raise ValueError('Operator review belongs to a different study')
    attempts = review.get('attempts', {})
    if not isinstance(attempts, dict) or set(attempts) - {r['id'] for r in rows}:
        raise ValueError('Operator review contains unknown attempts')
    tasks = {t['id']: t for t in manifest['tasks']}
    scores, template = {}, {}
    for row in rows:
        entry = attempts.get(row['id'], {})
        if not isinstance(entry, dict):
            raise ValueError('Operator review entries must be objects')
        protocol = entry.get('protocol', 'pending')
        if protocol not in {'pending', 'pass', 'violation'}:
            raise ValueError('Unknown protocol review status')
        template[row['id']] = {'protocol': 'pending', 'notes': ''}
        score = {'protocol': protocol, 'qa': None}
        if tasks[row['task']]['kind'] == 'qa':
            rubric = json.loads((study / 'private' / 'atlas' / row['task'] / 'tests' / 'rubrics.json').read_text())
            expected = {item['id'] for item in rubric}
            if not expected or len(expected) != len(rubric):
                raise ValueError('QA rubric is empty or contains duplicate criteria')
            kinds = {item['id']: item['annotations']['type'] for item in rubric}
            if set(kinds.values()) - {'positive hli verifier', 'negative hli verifier'}:
                raise ValueError('Unsupported QA rubric criterion type')
            criteria = entry.get('criteria')
            template[row['id']]['criteria'] = {identity: None for identity in sorted(expected)}
            if criteria is not None:
                if not isinstance(criteria, dict) or set(criteria) != expected or any(
                        value is not None and type(value) is not bool for value in criteria.values()):
                    raise ValueError('QA review must use the complete official criterion IDs and boolean verdicts')
                if all(value is not None for value in criteria.values()):
                    # Raw criterion counts, not an independently judged upstream leaderboard score.
                    positive = [criteria[k] for k in expected if kinds[k] == 'positive hli verifier']
                    negative = [criteria[k] for k in expected if kinds[k] == 'negative hli verifier']
                    score['qa'] = {'positive_met': sum(positive), 'positive_total': len(positive),
                                   'negative_triggered': sum(negative), 'negative_total': len(negative)}
        elif 'criteria' in entry:
            raise ValueError('Feature acceptance cannot be overridden by QA review')
        scores[row['id']] = score
    return review, scores, {'study_id': manifest['study_id'], 'attempts': template}


def report(args):
    manifest = load(args.study)
    rows = [json.loads(p.read_text()) for p in sorted((args.study / 'runs').glob('*/result.json'))]
    expected = {r['id']: r for r in manifest['schedule']}
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate attempt identity')
    for row in rows:
        scheduled = expected.get(row['id'])
        if not scheduled or any(row.get(k) != v for k, v in scheduled.items()) or row.get('study_id') != manifest['study_id']:
            raise ValueError('Result does not match the frozen schedule')
        directory = args.study / 'runs' / row['id'].replace(':', '-')
        for filename, content_file, field in [('committed-answer.json', None, 'text'),
                                               ('committed-patch.json', 'submitted.diff', None)]:
            path = directory / filename
            if row['status'] in {'completed', 'execution_failed'} and not path.exists():
                raise ValueError('Completed attempt is missing its committed submission')
            if path.exists():
                committed = json.loads(path.read_text())
                value = (directory / content_file).read_text() if content_file else committed[field]
                if digest(value) != committed['sha256']:
                    raise ValueError('Committed submission changed')
    review, scores, template = operator_scores(args.study, manifest, rows)
    groups = []
    for client in CLIENTS:
        for lane in LANES:
            selected = [r for r in rows if r['client'] == client and r['lane'] == lane]
            feature = [r for r in selected if next(t for t in manifest['tasks'] if t['id'] == r['task'])['kind'] == 'feature']
            calls = [c for r in selected for s in r.get('stages', []) for c in s.get('tool_calls', [])]
            qa = [scores[r['id']]['qa'] for r in selected if scores[r['id']]['qa'] is not None]
            groups.append({'client': client, 'lane': lane, 'attempts': len(selected),
                           'feature_passed': sum(r.get('quality', {}).get('passed') is True for r in feature),
                           'feature_attempts': len(feature),
                           'qa_review': 'operator sidecar; never inferred from source citations or tool use',
                           'qa_reviewed': len(qa), 'qa_positive_met': sum(q['positive_met'] for q in qa),
                           'qa_positive_total': sum(q['positive_total'] for q in qa),
                           'qa_negative_triggered': sum(q['negative_triggered'] for q in qa),
                           'qa_negative_total': sum(q['negative_total'] for q in qa),
                           'protocol_violations': sum(scores[r['id']]['protocol'] == 'violation' for r in selected),
                           'protocol_pending': sum(scores[r['id']]['protocol'] == 'pending' for r in selected),
                           'execution_failures': sum(r['status'] != 'completed' for r in selected),
                           'retrieval_calls': sum(c['name'].startswith('mcp__') and 'notify_file_changed' not in c['name'] for c in calls),
                           'tool_calls': len(calls)})
    write_json(args.study / 'report.json', {'mode': 'external', 'manifest': manifest, 'study_id': manifest['study_id'], 'required': 16,
                                          'completed': len(rows), 'runs': rows, 'operator_review': review,
                                          'operator_scores': scores,
                                          'groups': groups, 'scope': manifest['scope'], 'grading': manifest['grading']})
    write_json(args.study / 'operator-review-template.json', template)
    shuffled = list(rows)
    random.Random(manifest['seed']).shuffle(shuffled)
    blind, key = [], {}
    for index, row in enumerate(shuffled):
        identity = f'review-{index + 1:03d}'
        key[identity] = row['id']
        task = next(t for t in manifest['tasks'] if t['id'] == row['task'])
        answer_path = args.study / 'runs' / row['id'].replace(':', '-') / 'committed-answer.json'
        text = ''
        if answer_path.exists():
            committed = json.loads(answer_path.read_text())
            if digest(committed['text']) != committed['sha256']:
                raise ValueError('Committed answer changed')
            text = committed['text'].replace(str(answer_path.parent / 'repository'), '/workspace')
        blind.append({'id': identity, 'task': public_task(task),
                      'answer': text,
                      'identity_disclosure_review': 'pending; tool/model names may still identify the setup',
                      'review': 'pending'})
    write_json(args.study / 'blind-review.json', blind)
    write_json(args.study / 'blind-review-key.json', key)
    lines = ['# External understanding and feature pilot', '', f'{len(rows)}/16 attempts recorded. One repetition; adapted local runtime.', '',
             '| Client | Task | Native quality | Intelligence quality | Native seconds | Intelligence seconds |',
             '|---|---|---|---|---:|---:|']
    for client in CLIENTS:
        for task in manifest['tasks']:
            matched = {r['lane']: r for r in rows if r['client'] == client and r['task'] == task['id']}
            values = [str(round(matched[lane]['seconds'], 1)) if matched.get(lane, {}).get('seconds') is not None else '—' for lane in LANES]
            quality = []
            for lane in LANES:
                row = matched.get(lane)
                if row is None:
                    quality.append('not run')
                elif task['kind'] == 'qa':
                    score = scores[row['id']]['qa']
                    quality.append(f'{score["positive_met"]}/{score["positive_total"]} positive; '
                                   f'{score["negative_triggered"]}/{score["negative_total"]} negative'
                                   if score else 'review pending')
                else:
                    accepted = row.get('quality', {}).get('passed')
                    quality.append('passed' if accepted is True else 'failed' if accepted is False else 'evaluation incomplete')
            lines.append(f'| {client} | {task["repo"]} ({task["kind"]}) | {quality[0]} | {quality[1]} | {values[0]} | {values[1]} |')
    lines += ['', 'QA criteria and protocol adjudication are recorded in operator-review.json. Missing review remains pending.',
              'Feature acceptance results retain the official verifier output. Failed and incomplete attempts remain visible.',
              'Do not interpret timing without correctness. Setup and evaluation time are separate; OS/provider caches are uncontrolled.',
              'This diagnostic does not establish an upstream leaderboard score or satisfy the release gate.']
    (args.study / 'comparison.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps({'completed': len(rows), 'required': 16}), flush=True)
