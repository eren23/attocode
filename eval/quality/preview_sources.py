"""Declare the actual source producer before validating a delivered preview."""


def source_spans(page, root, policies):
    raise NotImplementedError('source producer controls must fail online first')


class SourceTracker:
    def __init__(self, root, journal):
        raise NotImplementedError('source producer controls must fail online first')
