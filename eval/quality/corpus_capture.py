"""Opt-in raw capture for bounded compatibility experiments."""
class RecordedGateway:
    def __init__(self, peer, root, journal):
        self.peer, self.root, self.journal = peer, root, journal

    async def execute_mcp(self, tool, arguments):
        raise NotImplementedError('durable broad response capture')
