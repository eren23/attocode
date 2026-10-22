"""Cached native parsers must not resume another thread's failed document."""
import threading

from attocode_intel._internal.integrations.context import ts_parser
from attocode_intel._internal.integrations.context.codebase_ast import parse_file
from attocode_intel._internal.integrations.context.parse_diagnostics import collect_parse_failures


def test_new_document_cannot_resume_another_threads_timed_out_parse(monkeypatch):
    original_get_parser = ts_parser._get_parser
    # Warm the installed grammar before controlling the native reset boundary.
    assert original_get_parser('python') is not None
    paused_reset = threading.Event()
    release_reset = threading.Event()
    second_finished = threading.Event()
    wrappers = {}
    wrappers_lock = threading.Lock()
    outputs, errors = {}, []

    class ControlledNativeParser:
        def __init__(self, native):
            self.native = native

        def __getattr__(self, name):
            return getattr(self.native, name)

        @property
        def timeout_micros(self):
            return self.native.timeout_micros

        @timeout_micros.setter
        def timeout_micros(self, value):
            # Inject the existing native timeout path only in the first worker.
            self.native.timeout_micros = 1 if threading.current_thread().name == 'timeout-owner' else value

        def parse(self, source):
            return self.native.parse(source)

        def reset(self):
            if threading.current_thread().name == 'timeout-owner':
                paused_reset.set()
                assert release_reset.wait(5), 'Test failed to release the native reset'
            self.native.reset()

    def parser(language):
        native = original_get_parser(language)
        with wrappers_lock:
            return wrappers.setdefault(id(native), ControlledNativeParser(native))

    monkeypatch.setattr(ts_parser, '_get_parser', parser)

    def first():
        try:
            with collect_parse_failures() as failures:
                outputs['first'] = ts_parser.bounded_parse(
                    parser('python'), b'def stale_header():\n' + b'    value = 1\n' * 10000)
            outputs['first_failures'] = failures
        except BaseException as error:
            errors.append(error)

    def second():
        try:
            outputs['second'] = parse_file('fresh.py', 'def fresh(value):\n    return value + 1\n')
        except BaseException as error:
            errors.append(error)
        finally:
            second_finished.set()

    owner = threading.Thread(target=first, name='timeout-owner')
    reader = threading.Thread(target=second, name='new-document')
    owner.start()
    try:
        assert paused_reset.wait(5), 'Native timeout did not reach its reset boundary'
        reader.start()
        # A serialized implementation may wait for reset; an isolated parser can
        # finish immediately. In either case, only the new document may be returned.
        second_finished.wait(.5)
    finally:
        release_reset.set()
        owner.join(5)
        if reader.ident is not None:
            reader.join(5)
    assert not owner.is_alive() and not reader.is_alive()
    assert not errors
    assert outputs['first'] is None
    assert len(outputs['first_failures']) == 1
    ast = outputs['second']
    assert ast.parsing_tier == 'tree_sitter'
    assert [(f.name, f.start_line, f.end_line) for f in ast.functions] == [('fresh', 1, 2)]
    assert ast.parse_failures == []
