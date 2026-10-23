"""Source-bound admission of the existing Rust real-server diagnostic fixture."""
import hashlib
from pathlib import Path

SOURCES = ('eval/quality/lsp_trace.py',
           'packages/code-intel/src/attocode_intel/_internal/integrations/lsp/client.py',
           'packages/code-intel/tests/test_real_language_server.py')


def expected_sources():
    root = Path(__file__).resolve().parents[2]
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SOURCES}


def verify_diagnostic(raw, sources):
    raise NotImplementedError('capture admission must fail online before implementation')
