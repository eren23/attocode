"""Per-parse grammar failures, isolated between threads and nested callers."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(slots=True)
class ParseFailure:
    outcome: str
    elapsed_micros: int
    limit_micros: int
    error_type: str = ''
    stage: str = 'structure'


_failures = ContextVar('attocode_parse_failures', default=None)


@contextmanager
def collect_parse_failures():
    failures = []
    token = _failures.set(failures)
    try:
        yield failures
    finally:
        _failures.reset(token)


def record_parse_failure(outcome, elapsed_micros, limit_micros, error_type=''):
    failures = _failures.get()
    if failures is not None and len(failures) < 8:
        failures.append(ParseFailure(outcome, elapsed_micros, limit_micros, error_type))
