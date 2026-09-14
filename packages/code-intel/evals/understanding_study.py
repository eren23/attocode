"""Private case packs and frozen native/starting/candidate understanding comparisons."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from onboarding_study import configure_setup
from study import (
    digest,
    environment_versions,
    harness_hash,
    schedule,
    source_hash,
    tree_hash,
    write_json,
)
from study_clients import invoke, preflight, subscription_env
from understanding_scoring import ANSWER_SCHEMA, grade, protocol_audit

CLIENTS = ('codex', 'claude')
LANES = ('native', 'previous', 'current')
IGNORE = shutil.ignore_patterns('.git', '__pycache__', '*.pyc', 'node_modules', '.attocode')


def pack_at(path):
    spec = importlib.util.spec_from_file_location('private_understanding_pack', path / 'case_pack.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def versions():
    return {c: subprocess.check_output([c, '--version'], text=True, timeout=20).strip() for c in CLIENTS}


def load(study):
    manifest = json.loads((study / 'manifest.json').read_text())
    identity = manifest.pop('study_id')
    if digest(manifest) != identity:
        raise ValueError('Manifest drift')
    manifest['study_id'] = identity
    checks = [(harness_hash(Path(__file__).parent), manifest['harness_sha256'], 'harness'),
              (tree_hash(study / 'private'), manifest['pack_sha256'], 'private case pack'),
              (environment_versions(), manifest['environment'], 'environment'),
              (versions(), manifest['client_versions'], 'clients')]
    checks += [(source_hash(study / 'versions' / lane / 'engine'), sha, lane)
               for lane, sha in manifest['engine_hashes'].items()]
    checks += [(tree_hash(study / 'sources' / repo), sha, repo) for repo, sha in manifest['source_hashes'].items()]
    for actual, expected, label in checks:
        if actual != expected:
            raise ValueError(f'Frozen {label} changed')
    return manifest, pack_at(study / 'private')


def freeze(args):
    study, project = args.study.resolve(), args.project.resolve()
    if not args.case_pack or not (args.case_pack / 'case_pack.py').is_file():
        raise ValueError('Supply --case-pack containing case_pack.py')
    if study.is_relative_to(project) or args.case_pack.resolve().is_relative_to(project):
        raise ValueError('Study and private case pack must be outside the repository')
    if (study / 'manifest.json').exists():
        raise ValueError('Never overwrite a frozen study')
    if not args.baseline_src or not (args.baseline_src / 'attocode_intel/entrypoint.py').exists():
        raise ValueError('Supply the frozen starting source with --baseline-src')
    study.mkdir(parents=True, exist_ok=True, mode=0o700)
    study.chmod(0o700)
    previous = study / 'versions/previous/engine'
    if previous.exists():
        if source_hash(previous) != source_hash(args.baseline_src):
            raise ValueError('Existing starting engine differs')
    else:
        shutil.copytree(args.baseline_src, previous, ignore=IGNORE)
    shutil.copytree(project / 'packages/code-intel/src', study / 'versions/current/engine', ignore=IGNORE)
    shutil.copytree(Path(__file__).parent, study / 'harness', ignore=IGNORE)
    shutil.copytree(args.case_pack, study / 'private', ignore=IGNORE)
    pack = pack_at(study / 'private')
    tasks = pack.TASKS
    if len(tasks) != 4 or sorted(t['kind'] for t in tasks) != ['analysis', 'analysis', 'repair', 'repair']:
        raise ValueError('Initial diagnostic requires two analysis and two repair cases')
    revisions = {}
    for repo in {t['repo'] for t in tasks}:
        source = args.repo_dir / repo
        revisions[repo] = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
        if revisions[repo] != pack.REVISIONS[repo]:
            raise ValueError(f'Unexpected source revision: {repo}')
        dirty = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True)
        if dirty.strip():
            raise ValueError(f'Source checkout must be clean: {repo}')
        shutil.copytree(source, study / 'sources' / repo, ignore=IGNORE)
    models = json.loads(args.models.read_text())
    models = {c: models[c] for c in CLIENTS}
    if not all(isinstance(m, str) and m for m in models.values()):
        raise ValueError('Explicit model IDs required')
    manifest = {'version': 1, 'mode': 'understanding', 'models': models, 'client_versions': versions(),
                'python': str(Path(__import__('sys').executable).absolute()), 'tasks': tasks, 'lanes': LANES,
                'repetitions': 1, 'seed': 9341, 'timeout': 600, 'selection': 'natural',
                'schedule': schedule(tasks, 1, seed=9341, lanes=LANES, clients=CLIENTS),
                'engine_hashes': {v: source_hash(study / 'versions' / v / 'engine') for v in LANES[1:]},
                'harness_sha256': harness_hash(study / 'harness'), 'pack_sha256': tree_hash(study / 'private'),
                'source_hashes': {repo: tree_hash(study / 'sources' / repo) for repo in revisions},
                'revisions': revisions, 'environment': environment_versions(),
                'cache_state': 'Fresh repository and MCP process; OS/provider caching uncontrolled',
                'max_scored_trials': 24, 'max_excluded_trials': 8,
                'scope': 'Development diagnostic, one repetition; no release or held-out advantage claim'}
    manifest['study_id'] = digest(manifest)
    write_json(study / 'manifest.json', manifest)
    print(json.dumps({'frozen': manifest['study_id'], 'scored_trials': 24}), flush=True)


def mutate(root, edits):
    for edit in edits:
        path = (root / edit['path']).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError('Mutation escapes source')
        text = path.read_text()
        if text.count(edit['before']) != 1:
            raise ValueError(f'Mutation anchor changed: {edit["path"]}')
        path.write_text(text.replace(edit['before'], edit['after']))


def oracle(pack, root, task, extended=False):
    result = pack.probe(root, task, extended=extended)
    if not isinstance(result, dict) or not result:
        raise ValueError('Empty or invalid oracle output')
    return result


def prepare(args):
    manifest, pack = load(args.study)
    result = {}
    for task in manifest['tasks']:
        with tempfile.TemporaryDirectory(prefix='understanding-control-') as temp:
            root = Path(temp) / 'repository'
            shutil.copytree(args.study / 'sources' / task['repo'], root, ignore=IGNORE)
            clean = oracle(pack, root, task, extended=True)
            if hasattr(pack, 'verify_clean'):
                pack.verify_clean(task['repo'], clean)
            checks = []
            edits = task['counterfactual'] if task['kind'] == 'analysis' else task['faults']
            for group in [[e] for e in edits] + ([edits] if len(edits) > 1 else []):
                originals = {e['path']: (root / e['path']).read_bytes() for e in group}
                try:
                    mutate(root, group)
                    observed = oracle(pack, root, task, extended=True)
                finally:
                    for path, content in originals.items():
                        (root / path).write_bytes(content)
                changed = sorted(k for k in clean if clean[k] != observed[k])
                preserved = sorted(k for k in clean if clean[k] == observed[k])
                intended = {identity for edit in group for identity in edit.get('expected_changes', [])}
                controls = set.intersection(*(set(edit.get('preserved_controls', [])) for edit in group))
                if not intended.issubset(changed) or not controls.issubset(preserved):
                    raise ValueError(f'Intended fault/negative controls failed: {task["id"]}')
                if not changed or not preserved:
                    raise ValueError(f'Fixture needs changed and unaffected controls: {task["id"]}')
                checks.append({'edit_count': len(group), 'changed': changed, 'preserved': preserved})
            result[task['id']] = {'clean': clean, 'controls': checks, 'passed': True}
    write_json(args.study / 'preparation.json', {'study_id': manifest['study_id'], 'tasks': result})
    print(json.dumps({'fixtures_passed': len(result)}), flush=True)


def ready(args, client):
    quota = json.loads(args.quota.read_text()) if args.quota and args.quota.exists() else {}
    status = preflight(client, quota, subscription_env())
    if not status['ready']:
        raise RuntimeError(json.dumps({'client': client, 'blocked': status}))


def setup(study, manifest, root, lane, stage, client):
    return configure_setup(manifest, study / 'versions' / (lane if lane != 'native' else 'current'), root,
                           'native' if lane == 'native' else 'intel_installed', stage, client)


def successful(result):
    return not any(result.get(k) for k in ('exit_code', 'timed_out', 'quota_exhausted', 'terminal_error', 'permission_denials'))


def wiring(args):
    import secrets

    from onboarding_study import GUIDANCE, guidance_checks
    manifest, _ = load(args.study)
    schema = {'type': 'object', 'properties': {'readiness_token': {'type': 'string'}},
              'required': ['readiness_token'], 'additionalProperties': False}
    for client in args.clients or CLIENTS:
        for lane in LANES[1:]:
            directory = args.study / 'wiring' / client / lane
            if directory.exists():
                saved = json.loads((directory / 'result.json').read_text())
                if not saved['passed'] or saved['study_id'] != manifest['study_id']:
                    raise ValueError('Preserve failed or interrupted wiring; repair before a new study')
                continue
            ready(args, client)
            root = directory / 'repository'
            root.mkdir(parents=True)
            (root / 'utility.py').write_text('def total(left, right):\n    return left + right\n')
            (root / 'test_utility.py').write_text('from utility import total\ndef test_total():\n    assert total(2, 3) == 5\n')
            configured = setup(args.study, manifest, root, lane, directory / 'transport', client)
            guidance = root / GUIDANCE[client]
            original, token = guidance.read_text(), secrets.token_hex(16)
            guidance.write_text(original + '\nReadiness token: ' + token + '\n')
            try:
                loaded = invoke(client, manifest['models'][client], root, directory / 'guidance', configured['servers'],
                                'Excluded readiness check: return the readiness token already in your project instructions. '
                                'Do not use tools, read files, edit or delegate. Return missing if absent.',
                                120, subscription_env(), answer_schema=schema, project_guidance=True)
            finally:
                guidance.write_text(original)
            transport = invoke(client, manifest['models'][client], root, directory / 'transport', configured['servers'],
                               'Excluded connection check. Read utility.py with a native tool, discover the connected '
                               'inspect_symbol tool using ToolSearch if needed and call it for total in utility.py. '
                               'Return readiness_token=connected if it returns exact source. Do not edit or delegate.',
                               180, subscription_env(), answer_schema=schema, project_guidance=True)
            calls = transport.get('tool_calls', [])
            passed = guidance_checks(loaded, token) and successful(transport) and transport['output'].get('readiness_token') == 'connected'
            passed &= any(c['name'].endswith('__inspect_symbol') for c in calls)
            passed &= any(c['name'] in {'Read', 'shell', 'Bash'} for c in calls)
            write_json(directory / 'result.json', {'study_id': manifest['study_id'], 'excluded': True,
                                                   'passed': bool(passed), 'guidance': loaded, 'transport': transport})
            print(json.dumps({'wiring': [client, lane], 'passed': bool(passed)}), flush=True)
            if not passed:
                raise RuntimeError('Connection check failed; scored trials not started')


def reconstruct_submission(control, root, implementation_roots):
    """Overlay only implementation, keeping independent tests and config intact."""
    for base in implementation_roots:
        if not base or base == '.' or Path(base).is_absolute() or '..' in Path(base).parts:
            raise ValueError('Implementation root escapes submitted source')
        original, submitted = control / base, root / base
        if original.is_dir():
            shutil.rmtree(original)
        else:
            original.unlink(missing_ok=True)
        if submitted.is_symlink() or any(p.is_symlink() for p in submitted.rglob('*')):
            raise ValueError('Symlink in submitted implementation')
        if submitted.is_dir():
            shutil.copytree(submitted, original, ignore=IGNORE)
        elif submitted.is_file():
            shutil.copy2(submitted, original)


def public_prompt(pack, task):
    # Never pass fault locations, expected outcomes, or private controls to the
    # public prompt renderer. A counterfactual exposes only the supplied edit.
    public = {key: task[key] for key in ('id', 'repo', 'kind')}
    if task['kind'] == 'analysis':
        public['counterfactual'] = [{key: edit[key] for key in ('path', 'before', 'after')}
                                    for edit in task['counterfactual']]
    return pack.prompt(public) + (
        '\nReturn schema_version=1. Predictions use scenario IDs and predicted_json containing a JSON-encoded '
        'output object, with brief explanations. Impacts say whether that scenario output changes under the supplied edit. '
        'Deduplicate references into source ranges with IDs; cite their IDs in predictions/impacts. '
        'List relevant test_files. For repairs return diagnosis, references, and empty predictions/impacts. '
        'Use any available connected or native tools voluntarily. Do not delegate. Stay inside this repository; '
        'do not inspect parent directories, study metadata, private checks, other trials, or evaluator processes. '
        + ('Inspect source only: do not execute repository code, run tests, or modify files before committing your final predictions. '
           'The evaluator executes the behavior after your answer is captured.' if task['kind'] == 'analysis' else
           'You may edit implementation, add tests, and run available tests. Independent checks run after completion.'))


def run(args):
    manifest, pack = load(args.study)
    prep = json.loads((args.study / 'preparation.json').read_text())
    if prep['study_id'] != manifest['study_id'] or not all(t['passed'] for t in prep['tasks'].values()):
        raise ValueError('Fixture validation required')
    finished = 0
    for row in manifest['schedule']:
        if args.clients and row['client'] not in args.clients or args.tasks and row['task'] not in args.tasks:
            continue
        directory = args.study / 'runs' / row['id'].replace(':', '-')
        if (directory / 'result.json').exists():
            continue
        if directory.exists():
            write_json(directory / 'result.json', {**row, 'status': 'interrupted', 'study_id': manifest['study_id'], 'stages': []})
            continue
        for lane in LANES[1:]:
            check = json.loads((args.study / 'wiring' / row['client'] / lane / 'result.json').read_text())
            if not check['passed'] or check['study_id'] != manifest['study_id']:
                raise ValueError('Wiring not ready')
        ready(args, row['client'])
        task = next(t for t in manifest['tasks'] if t['id'] == row['task'])
        root, stage = directory / 'repository', directory / 'stage-0'
        shutil.copytree(args.study / 'sources' / task['repo'], root, ignore=IGNORE)
        if task['kind'] == 'repair':
            mutate(root, task['faults'])
        configured = setup(args.study, manifest, root, row['lane'], stage, row['client'])
        subprocess.run(['git', 'init', '-q', str(root)], check=True)
        from hashlib import sha256
        before = {p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest()
                  for p in root.rglob('*') if p.is_file() and '.git' not in p.parts}
        write_json(directory / 'started.json', {**row, 'study_id': manifest['study_id'], 'time': time.time()})
        print(json.dumps({'starting': row['id']}), flush=True)
        record = {**row, 'study_id': manifest['study_id'], 'stages': [], 'status': 'failed'}
        try:
            result = invoke(row['client'], manifest['models'][row['client']], root, stage, configured['servers'],
                            public_prompt(pack, task), manifest['timeout'], subscription_env(),
                            answer_schema=ANSWER_SCHEMA, project_guidance=True)
            # Immutable answer commit precedes all behavior execution/acceptance.
            write_json(directory / 'committed-answer.json', {'answer': result['output'], 'time': time.time(),
                                                             'sha256': digest(result['output'])})
            record.update(stages=[result], seconds=result['seconds'], onboarding=configured)
            changed_files = [p for p, old in before.items() if not (root / p).is_file() or sha256((root / p).read_bytes()).hexdigest() != old]
            new_files = [p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()
                         and '.git' not in p.parts and '.attocode' not in p.parts and p.relative_to(root).as_posix() not in before]
            audit = protocol_audit(root, result['tool_calls'], task['kind'], changed_files + new_files)
            expected, impacts, repair = {}, {}, None
            with tempfile.TemporaryDirectory(prefix='understanding-acceptance-') as temp:
                control = Path(temp) / 'repository'
                shutil.copytree(args.study / 'sources' / task['repo'], control, ignore=IGNORE)
                if task['kind'] == 'analysis':
                    expected = oracle(pack, control, task)
                    mutate(control, task['counterfactual'])
                    altered = oracle(pack, control, task)
                    impacts = {k: expected[k] != altered[k] for k in expected}
                else:
                    # Reconstruct from clean source; never execute agent-modified tests/config.
                    reconstruct_submission(control, root, task['implementation_roots'])
                    target = prep['tasks'][task['id']]['clean']
                    acceptance_error = None
                    try:
                        actual = oracle(pack, control, task, extended=True)
                    except (OSError, ValueError, subprocess.SubprocessError) as exc:
                        actual, acceptance_error = {}, str(exc)
                    checks = {k: k in actual and actual[k] == v for k, v in target.items()}
                    repair = {'passed': all(checks.values()), 'checks': checks, 'execution_error': acceptance_error}
                    patches = []
                    for base in task['implementation_roots']:
                        patch = subprocess.run(['git', 'diff', '--no-index', '--',
                            str(args.study / 'sources' / task['repo'] / base), str(root / base)],
                            capture_output=True, text=True, timeout=30)
                        patches.append(patch.stdout)
                    (directory / 'submitted.diff').write_text('\n'.join(patches))
            record.update(status='completed' if successful(result) else 'execution_failed',
                          protocol=audit, changed_files=changed_files, new_files=new_files,
                          quality=grade(root, task, result['output'], expected, impacts, repair))
        except Exception as exc:
            record['error'] = str(exc)
        write_json(directory / 'result.json', record)
        print(json.dumps({'completed': row['id'], 'status': record['status'], 'seconds': record.get('seconds')}), flush=True)
        finished += 1
        if finished >= (args.max_runs or 6) or any(s.get('quota_exhausted') for s in record['stages']):
            break


def report(args):
    import statistics
    manifest, _ = load(args.study)
    rows = [json.loads(p.read_text()) for p in sorted((args.study / 'runs').glob('*/result.json'))]
    # Original automatic grades are immutable; adjudications are an explicit sidecar.
    adjudications_path = args.study / 'adjudications.json'
    adjudications = json.loads(adjudications_path.read_text()) if adjudications_path.exists() else {}
    groups = []
    for client in CLIENTS:
        for lane in LANES:
            selected = [r for r in rows if r['client'] == client and r['lane'] == lane]
            analysis = [r['quality']['analysis']['score'] for r in selected if r.get('quality', {}).get('analysis')]
            repairs = [int(r['quality']['repair']['passed']) for r in selected if r.get('quality', {}).get('repair')]
            groups.append({'client': client, 'lane': lane, 'completed': len(selected),
                           'analysis_mean_observed': statistics.mean(analysis) if analysis else None,
                           'repair_pass_rate_observed': statistics.mean(repairs) if repairs else None,
                           'execution_failures': sum(r['status'] != 'completed' for r in selected),
                           'protocol_pending_or_failed': sum(r.get('protocol', {}).get('status') != 'clear' for r in selected),
                           'intelligence_adoption': sum(any(s.get('mcp_used') for s in r['stages']) for r in selected),
                           'seconds': [r.get('seconds') for r in selected]})
    write_json(args.study / 'report.json', {'study_id': manifest['study_id'], 'required': 24,
                                          'completed': len(rows), 'groups': groups, 'runs': rows, 'adjudications': adjudications,
                                          'interpretation': 'Development cases; one repetition. Protocol and prose review remain separate. No release claim.'})
    import random
    blinded = list(rows)
    random.Random(manifest['seed']).shuffle(blinded)
    review, key = [], {}
    for index, row in enumerate(blinded):
        identity = f'review-{index + 1:03d}'
        key[identity] = row['id']
        task = next(t for t in manifest['tasks'] if t['id'] == row['task'])
        review.append({'id': identity, 'repo': task['repo'], 'kind': task['kind'],
                       'answer': row['stages'][0].get('output') if row['stages'] else None,
                       'support_review': 'pending', 'alternative_evidence_review': 'pending'})
    write_json(args.study / 'blind-review.json', review)
    write_json(args.study / 'blind-review-key.json', key)
    print(json.dumps({'completed': len(rows), 'required': 24, 'groups': groups}), flush=True)
