"""Compatibility exports for attocode_intel.db."""
from importlib import import_module as _import_module

def __getattr__(name):
    return getattr(_import_module("attocode_intel.db"), name)
