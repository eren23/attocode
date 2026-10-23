"""Record actual loaded Rust parser modules inside the diagnostic pytest worker."""
import hashlib
import importlib.metadata
import os
import sys
from pathlib import Path

from eval.quality.native_experiment import distribution_identity
from eval.quality.runner import write_json


def pytest_sessionfinish(session, exitstatus):
    distributions = distribution_identity(('tree-sitter', 'tree-sitter-rust'))
    paths = {}
    for name in distributions:
        dist = importlib.metadata.distribution(name)
        for relative, sha in distributions[name]['files']:
            paths[Path(dist.locate_file(relative)).resolve()] = (relative, sha)
    loaded = {}
    for name, module in list(sys.modules.items()):
        if (name == 'tree_sitter' or name.startswith('tree_sitter.')
                or name == 'tree_sitter_rust' or name.startswith('tree_sitter_rust.')):
            path = Path(module.__file__).resolve()
            if path not in paths:
                raise ValueError('native Rust module outside installed distribution')
            relative, expected = paths[path]
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError('native Rust module bytes changed')
            loaded[name] = {'path': relative, 'sha256': actual}
    if not any(name.startswith('tree_sitter_rust') for name in loaded):
        raise ValueError('Rust grammar module was never loaded')
    write_json(Path(os.environ['ATTOCODE_EXPERIMENT_EVIDENCE']) / 'rust-native-identity.json',
               {'exitstatus': exitstatus, 'distributions': distributions, 'loaded': loaded})
