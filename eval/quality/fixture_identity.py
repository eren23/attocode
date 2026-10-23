"""Source-only fixture inventories; runtime indexes are excluded explicitly."""


def source_manifest(root):
    raise NotImplementedError('source inventory')


def pinned_manifest(cache, tree):
    raise NotImplementedError('committed source inventory')
