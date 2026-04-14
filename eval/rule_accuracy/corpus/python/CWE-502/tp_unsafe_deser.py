# Unsafe deserialization — true positives for rule accuracy testing
# nosec — INTENTIONALLY insecure test corpus, not production code

import pickle  # nosec
import yaml  # nosec
import marshal  # nosec

def bad_pickle_load(data):  # nosec B301
    return pickle.loads(data)  # expect: security/python_pickle_loads

def bad_yaml_load(data):  # nosec B506
    return yaml.load(data)  # expect: security/python_yaml_unsafe

def bad_marshal(data):  # nosec
    return marshal.loads(data)  # expect: security/python_marshal_loads
