"""Literal Java call names retain valid dollar signs without admitting expressions."""

import pytest
from attocode_intel._internal.integrations.context.syntax_evidence import (
    reference_candidates,
    syntax_tree,
)


def java_calls(source):
    tree = syntax_tree('Driver.java', source, 'java')
    assert tree is not None, 'Bundled Java grammar must be available'
    assert not tree.root_node.has_error and tree.root_node.end_byte == len(source.encode())
    return reference_candidates('Driver.java', source, 'java')


@pytest.mark.parametrize('written', [
    '$Gson$Types.canonicalize',
    'com.google.gson.internal.$Gson$Types.canonicalize',
    '$canonicalize',
    '$Gson$Types.$canonicalize',
    'GsonTypes.canonicalize',
])
def test_java_literal_dollar_call_preserves_spelling_and_line(written):
    source = 'class Driver {\n  void run() {\n    ' + written + '(null);\n  }\n}\n'
    assert java_calls(source) == [(written, 'call', 3)]


def test_java_dollar_decoys_and_expression_receivers_stay_excluded():
    source = (
        'class Driver {\n'
        '  void run() {\n'
        '    // $Gson$Types.commentDecoy(null);\n'
        '    String text = "$Gson$Types.stringDecoy(null)";\n'
        '    factory().$canonicalize(null);\n'
        '    values[0].$canonicalize(null);\n'
        '    /* $Gson$Types.blockDecoy(null); */\n'
        '  }\n'
        '}\n'
    )
    assert java_calls(source) == [('factory', 'call', 5)]
