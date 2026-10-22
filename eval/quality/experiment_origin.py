"""Assert the selected engine inside the preflight pytest subprocess itself."""
import os
from pathlib import Path

from eval.quality.experiment_evidence import assert_engine
from eval.quality.runner import write_json


def pytest_sessionstart(session):
    assert_engine(os.environ['ATTOCODE_EXPERIMENT_ENGINE'])


def pytest_sessionfinish(session, exitstatus):
    origins = assert_engine(os.environ['ATTOCODE_EXPERIMENT_ENGINE'])
    evidence = Path(os.environ['ATTOCODE_EXPERIMENT_EVIDENCE'])
    write_json(evidence / 'pytest-origin.json', {'pid': os.getpid(), 'origins': origins,
                                               'exitstatus': exitstatus})
