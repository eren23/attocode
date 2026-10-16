"""Pytest guard proving intelligence checks do not depend on archived agent code."""
from __future__ import annotations

import importlib.abc
import importlib.metadata
import sys

import pytest

_ARCHIVED = frozenset({"attocode", "attoswarm", "attocode_core"})


class _NoAgent(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in _ARCHIVED:
            raise ImportError(f"Archived agent import forbidden in intelligence tests: {fullname}")
        return None


sys.meta_path.insert(0, _NoAgent())


def pytest_sessionstart(session):
    try:
        importlib.metadata.distribution('attocode')
    except importlib.metadata.PackageNotFoundError:
        pass
    else:
        raise pytest.UsageError('Use a clean standalone environment without the attocode distribution')
    loaded = [name for name in sys.modules if name.split('.')[0] in _ARCHIVED]
    if loaded:
        raise pytest.UsageError(f'Archived agent modules were loaded before the guard: {loaded}')
