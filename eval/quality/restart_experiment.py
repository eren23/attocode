"""Frozen restart comparison, guarded by a baseline-only self-consistency pair."""
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def navigation_requests(spec):
    raise NotImplementedError('restart navigation requests')


def canonical(operation, data):
    raise NotImplementedError('ordered canonical evidence')


async def navigate(workspace, spec, evidence, journal):
    raise NotImplementedError('durable restart phase')


def admit_phase(evidence, workspace, spec, summary):
    raise NotImplementedError('restart raw response admission')


def decide(rows, expected):
    raise NotImplementedError('frozen restart gates')
