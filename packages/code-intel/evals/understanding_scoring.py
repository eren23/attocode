"""Versioned executable outcomes, independent of citation formatting and prose review."""
from __future__ import annotations

import json
import shlex


def obj(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


STRING = {'type': 'string'}
REFERENCES = {'type': 'array', 'items': STRING}
ANSWER_SCHEMA = obj({
    'schema_version': {'type': 'integer', 'enum': [1]},
    'predictions': {'type': 'array', 'items': obj({'id': STRING, 'predicted_json': STRING,
                                                'explanation': STRING, 'references': REFERENCES})},
    'impacts': {'type': 'array', 'items': obj({'id': STRING, 'changed': {'type': 'boolean'},
                                            'explanation': STRING, 'references': REFERENCES})},
    'diagnosis': STRING,
    'references': {'type': 'array', 'items': obj({'id': STRING, 'path': STRING,
                                               'start_line': {'type': 'integer'},
                                               'end_line': {'type': 'integer'}})},
    'test_files': REFERENCES,
})


def exact_json(left, right):
    # Python equality conflates true with 1. Compare canonical JSON instead.
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def grade(root, task, answer, expected, changed, repair=None):
    if not isinstance(answer, dict):
        answer = {}
    from jsonschema import Draft202012Validator
    schema_errors = [e.message for e in Draft202012Validator(ANSWER_SCHEMA).iter_errors(answer)]
    predictions = answer.get('predictions') if isinstance(answer.get('predictions'), list) else []
    impacts = answer.get('impacts') if isinstance(answer.get('impacts'), list) else []
    scores, impact_scores = {}, {}
    for identity, target in expected.items():
        matches = [p for p in predictions if isinstance(p, dict) and p.get('id') == identity]
        try:
            scores[identity] = len(matches) == 1 and exact_json(json.loads(matches[0]['predicted_json']), target)
        except (ValueError, TypeError, KeyError):
            scores[identity] = False
        matches = [p for p in impacts if isinstance(p, dict) and p.get('id') == identity]
        impact_scores[identity] = len(matches) == 1 and matches[0].get('changed') is changed[identity]
    references, seen = [], set()
    for ref in answer.get('references', []) or []:
        if not isinstance(ref, dict):
            continue
        valid, reason = False, 'invalid location'
        try:
            path = (root / ref['path']).resolve()
            start, end = ref['start_line'], ref['end_line']
            valid = (path.is_relative_to(root.resolve()) and path.is_file() and
                     type(start) is int and type(end) is int and 1 <= start <= end <= len(path.read_text().splitlines()))
            identity = (ref['path'], start, end)
            if identity in seen or ref['id'] in {r['id'] for r in references}:
                valid, reason = False, 'duplicate reference'
            seen.add(identity)
        except (KeyError, TypeError, OSError, UnicodeError):
            pass
        references.append({'id': ref.get('id'), 'location_valid': valid,
                           'reason': None if valid else reason, 'support': 'needs_blinded_review'})
    tests = sorted({p for p in answer.get('test_files', []) or [] if isinstance(p, str)})
    test_locations = {p: (root / p).resolve().is_relative_to(root.resolve()) and (root / p).is_file() for p in tests}
    authored = set(task.get('required_tests', []))
    return {'schema_version': 1, 'analysis': {'predictions': scores, 'impacts': impact_scores,
            'prediction_accuracy': sum(scores.values()) / len(scores) if scores else None,
            'impact_accuracy': sum(impact_scores.values()) / len(impact_scores) if impact_scores else None,
            'score': (sum(scores.values()) + sum(impact_scores.values())) / (2 * len(scores)) if scores else None}
            if task['kind'] == 'analysis' else None,
            'repair': repair if task['kind'] == 'repair' else None,
            'references': references, 'test_locations': test_locations,
            'required_tests_found': sorted(authored.intersection(tests)),
            'alternative_tests_for_review': [p for p in tests if p not in authored and test_locations[p]],
            'prose_review': 'pending', 'answer_schema_valid': not schema_errors, 'schema_errors': schema_errors,
            'unresolved_reference_ids': sorted({ref for row in predictions + impacts if isinstance(row, dict)
                for ref in row.get('references', []) or [] if isinstance(ref, str)} - {r['id'] for r in references})}


def protocol_audit(root, calls, kind, changed_files):
    """Conservative trace audit, not an OS access sandbox. Ambiguous shells need review."""
    violations, review = [], []
    private_markers = ('../', 'intelligence-evaluations', 'manifest.json', 'case_pack', 'acceptance', '/private/')
    for call in calls:
        name, args = call.get('name', ''), call.get('arguments', {})
        text = json.dumps(args)
        if any(marker in text for marker in private_markers):
            review.append({'call': call.get('id'), 'reason': 'possible access outside public case; inspect trace'})
        if isinstance(args, dict):
            from pathlib import Path
            for key in ('file_path', 'path', 'cwd', 'workdir'):
                path = args.get(key)
                if isinstance(path, str) and not (root / Path(path)).resolve().is_relative_to(root.resolve()):
                    violations.append({'call': call.get('id'), 'reason': 'path outside public workspace'})
        if kind == 'analysis' and name in {'Edit', 'Write', 'apply_patch'}:
            violations.append({'call': call.get('id'), 'reason': 'modification during prediction'})
        if name in {'shell', 'Bash', 'shellToolCall'}:
            command = args.get('command', args.get('cmd', '')) if isinstance(args, dict) else str(args)
            try:
                words = shlex.split(command)
            except ValueError:
                words = []
            if kind == 'analysis' and words and (words[0] in {'node', 'npm', 'pytest', 'uv', 'cargo'} or
                    (words[0].endswith('python') and any(w in words for w in ('-m',)) )):
                violations.append({'call': call.get('id'), 'reason': 'execution during prediction', 'command': command})
            # Only simple known reads are automatically cleared. Never infer that an
            # arbitrary Python/shell program is read-only from its stated purpose.
            if words and words[0] in {'cat', 'sed', 'rg', 'head', 'tail', 'pwd', 'ls', 'wc'} and not any(
                    token in command for token in (';', '|', '>', '$', '`', '&&', '-exec')):
                continue
            review.append({'call': call.get('id'), 'reason': 'shell requires protocol review', 'command': command})
    if kind == 'analysis' and changed_files:
        violations.append({'reason': 'public source modified before prediction commit', 'paths': changed_files})
    return {'violations': violations, 'review_required': review,
            'status': 'violation' if violations else 'needs_review' if review else 'clear',
            'boundary': 'trace and source audit; private material is outside workspace, not OS-isolated'}
