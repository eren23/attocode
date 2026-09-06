"""Compatibility alias for attocode_intel.artifacts.hashing."""
import importlib as _importlib
import sys as _sys

_module = _importlib.import_module("attocode_intel.artifacts.hashing")
if __name__ == "__main__":
    _module.main()
else:
    _sys.modules[__name__] = _module
