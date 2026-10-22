"""Contracts for retained experiment evidence; implemented after online RED."""


class Journal:
    def __init__(self, root, max_bytes):
        raise NotImplementedError('durable response journal')


def read_source(path, *, errors, newlines):
    raise NotImplementedError('producer source policy')


def validate_excerpt(source, snippet, start, end):
    raise NotImplementedError('contiguous source validation')


def assert_engine(root):
    raise NotImplementedError('engine_origin')
