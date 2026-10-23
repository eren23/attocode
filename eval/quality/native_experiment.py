"""CI-only native diagnostics; observers never alter product parsing limits."""


class ParserObserver:
    def __init__(self, parser, record, language):
        raise NotImplementedError('native observer controls must fail online before implementation')
