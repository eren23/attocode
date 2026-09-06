"""Compatibility exports for attocode_intel.rules.packs."""
from importlib import import_module as _import_module

def __getattr__(name):
    return getattr(_import_module("attocode_intel.rules.packs"), name)
