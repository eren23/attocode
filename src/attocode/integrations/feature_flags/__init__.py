"""Compatibility exports for attocode_intel._internal.integrations.feature_flags."""
from importlib import import_module as _import_module

def __getattr__(name):
    return getattr(_import_module("attocode_intel._internal.integrations.feature_flags"), name)
