from attocode.tracing.analysis._helpers import safe_float, safe_int


def test_safe_int_valid():
    assert safe_int({"k": 5}, "k") == 5
    assert safe_int({"k": "7"}, "k") == 7


def test_safe_int_missing_key():
    assert safe_int({}, "k") == 0


def test_safe_int_none_value():
    assert safe_int({"k": None}, "k") == 0


def test_safe_int_malformed():
    assert safe_int({"k": "abc"}, "k") == 0
    assert safe_int({"k": object()}, "k") == 0


def test_safe_float_valid():
    assert safe_float({"k": 1.5}, "k") == 1.5
    assert safe_float({"k": "2.25"}, "k") == 2.25
    assert safe_float({"k": 3}, "k") == 3.0


def test_safe_float_missing_key():
    assert safe_float({}, "k") == 0.0


def test_safe_float_none_value():
    assert safe_float({"k": None}, "k") == 0.0


def test_safe_float_malformed():
    assert safe_float({"k": "nope"}, "k") == 0.0
    assert safe_float({"k": object()}, "k") == 0.0
