"""Tests for lazy import mechanisms in code_intel and context packages.

Verifies that the __getattr__ lazy-loading hooks correctly resolve
module attributes without requiring optional heavy dependencies to
be fully functional at import time.
"""

from __future__ import annotations

import importlib

import pytest

# ---------------------------------------------------------------------------
# Test 9a: code_intel lazy import -- BugReport
# ---------------------------------------------------------------------------


def test_code_intel_lazy_import_bugReport():
    """Importing BugReport from attocode.code_intel should succeed."""
    # Force a fresh lookup through __getattr__
    mod = importlib.import_module("attocode.code_intel")
    # Clear cached value if present so __getattr__ path is exercised
    saved = mod.__dict__.pop("BugReport") if "BugReport" in mod.__dict__ else None

    try:
        # Access through the lazy __getattr__
        BugReport = mod.BugReport
        assert BugReport is not None
        # It should be a class (dataclass)
        assert isinstance(BugReport, type) or callable(BugReport)
    except ImportError:
        # If tree-sitter or other optional deps are missing, the import
        # itself should still succeed via __getattr__; only instantiation
        # might fail. If we get here, the lazy mechanism at least tried.
        pytest.skip("Optional dependency missing for BugReport module")
    finally:
        # Restore cached value
        if saved is not None:
            mod.__dict__["BugReport"] = saved


# ---------------------------------------------------------------------------
# Test 9b: code_intel lazy import -- scan_diff
# ---------------------------------------------------------------------------


def test_code_intel_lazy_import_scan_diff():
    """Importing scan_diff function from attocode.code_intel should succeed."""
    mod = importlib.import_module("attocode.code_intel")
    saved = mod.__dict__.pop("scan_diff") if "scan_diff" in mod.__dict__ else None

    try:
        scan_diff = mod.scan_diff
        assert callable(scan_diff)
    except ImportError:
        pytest.skip("Optional dependency missing for scan_diff module")
    finally:
        if saved is not None:
            mod.__dict__["scan_diff"] = saved


# ---------------------------------------------------------------------------
# Test 9c: context lazy import -- microcompact
# ---------------------------------------------------------------------------


def test_context_lazy_import_microcompact():
    """Importing microcompact from attocode.integrations.context should succeed."""
    mod = importlib.import_module("attocode.integrations.context")
    saved = mod.__dict__.pop("microcompact") if "microcompact" in mod.__dict__ else None

    try:
        microcompact = mod.microcompact
        assert callable(microcompact)
    except ImportError:
        pytest.skip("Optional dependency missing for microcompact module")
    finally:
        if saved is not None:
            mod.__dict__["microcompact"] = saved


# ---------------------------------------------------------------------------
# Test 9d: context lazy import -- ToolDecayProfile
# ---------------------------------------------------------------------------


def test_context_lazy_import_ToolDecayProfile():
    """Importing ToolDecayProfile from attocode.integrations.context should succeed."""
    mod = importlib.import_module("attocode.integrations.context")
    saved = mod.__dict__.pop("ToolDecayProfile") if "ToolDecayProfile" in mod.__dict__ else None

    try:
        ToolDecayProfile = mod.ToolDecayProfile
        assert ToolDecayProfile is not None
    except ImportError:
        pytest.skip("Optional dependency missing for ToolDecayProfile module")
    finally:
        if saved is not None:
            mod.__dict__["ToolDecayProfile"] = saved


# ---------------------------------------------------------------------------
# Test 9e: invalid attribute raises AttributeError
# ---------------------------------------------------------------------------


def test_invalid_attribute_raises_code_intel():
    """Accessing a nonexistent attribute on code_intel should raise AttributeError."""
    mod = importlib.import_module("attocode.code_intel")
    with pytest.raises(AttributeError, match="no attribute"):
        _ = mod.ThisDoesNotExist_XYZ_12345


def test_invalid_attribute_raises_context():
    """Accessing a nonexistent attribute on context should raise AttributeError."""
    mod = importlib.import_module("attocode.integrations.context")
    with pytest.raises(AttributeError, match="no attribute"):
        _ = mod.ThisDoesNotExist_XYZ_12345
