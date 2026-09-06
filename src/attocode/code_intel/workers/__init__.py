"""Compatibility exports for attocode_intel.workers."""
from importlib import import_module as _import_module

def __getattr__(name):
    return getattr(_import_module("attocode_intel.workers"), name)
