"""The analysis engine must ship usable: load the shipped example packs
(10 language packs incl. ast-grep structural rules) by default, so the live
registry isn't just the 109 builtin regex rules.

``discover_packs`` keeps its documented project-local contract (only
``.attocode/packs/``); the auto-load lives in ``load_all_packs`` and is
opt-out via ``ATTOCODE_NO_SHIPPED_PACKS``.
"""

from __future__ import annotations


def test_load_all_packs_includes_shipped_example_packs_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("ATTOCODE_NO_SHIPPED_PACKS", raising=False)
    from attocode.code_intel.rules.packs.pack_loader import load_all_packs

    manifests, rules = load_all_packs(str(tmp_path))  # fresh project, no .attocode/packs

    names = {m.name for m in manifests}
    assert {"python", "go", "typescript"} <= names

    rule_ids = {r.id for r in rules}
    # a Tier-2 ast-grep structural rule from the python pack is now active
    assert "py-debug-print-leftover" in rule_ids


def test_shipped_packs_opt_out(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTOCODE_NO_SHIPPED_PACKS", "1")
    from attocode.code_intel.rules.packs.pack_loader import load_all_packs

    manifests, rules = load_all_packs(str(tmp_path))
    assert manifests == []  # only user packs (none in a fresh project)
    assert rules == []


def test_user_pack_takes_precedence_over_shipped(tmp_path, monkeypatch):
    monkeypatch.delenv("ATTOCODE_NO_SHIPPED_PACKS", raising=False)
    from attocode.code_intel.rules.packs.pack_loader import install_pack, load_all_packs

    install_pack("python", str(tmp_path))  # user installs python into .attocode/packs
    manifests, _ = load_all_packs(str(tmp_path))

    # exactly one 'python' manifest (user copy), not duplicated by the shipped one
    assert [m.name for m in manifests].count("python") == 1
