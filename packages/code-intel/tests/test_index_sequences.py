"""Mixed changes must agree with a fresh index and known source definitions."""
import random
import re
import time

import pytest
from attocode_intel._internal.integrations.context.ast_service import ASTService
from attocode_intel._internal.integrations.context.index_store import IndexStore
from test_edit_restart import evidence


def close(ast):
    ast.stop_hydration()
    ast._store.close()


def check_sequence(root, seed, online):
    rng = random.Random(seed)
    for i in range(6):
        (root / f"module_{i}.py").write_text(f"def symbol_{i}():\n    return {i}\n")
    (root / "caller.py").write_text("from module_0 import symbol_0\ndef caller():\n    return symbol_0()\n")
    ast = ASTService(str(root))
    started = time.monotonic()
    try:
        ast.initialize_skeleton()
        for step, op in enumerate(("edit", "rename", "add", "ignore", "delete", "unignore") * 2):
            assert time.monotonic() - started < 30, "Mixed-edit diagnostic exceeded its deadline"
            if not online:
                close(ast)
                ast = None
            selected = rng.choice(sorted(p for p in root.glob("*.py") if p.name != "caller.py"))
            if op == "edit":
                selected.write_text(f"def revised_{seed}_{step}():\n    return {step}\n")
            elif op == "rename":
                selected.rename(root / f"moved_{step}.py")
            elif op == "add":
                (root / f"added_{step}.py").write_text(f"def added_{seed}_{step}():\n    return {step}\n")
            elif op == "delete":
                selected.unlink()
            elif op == "ignore":
                (root / ".gitignore").write_text(selected.name + "\n")
            else:
                (root / ".gitignore").unlink(missing_ok=True)
            if online:
                ast.repair_changed_files()
            else:
                ast = ASTService(str(root))
                ast.initialize_skeleton()
            clean = ASTService(str(root), store=IndexStore(db_path=":memory:"))
            try:
                clean.initialize_skeleton()
                assert evidence(ast) == evidence(clean), (seed, online, step, op, "fresh-index mismatch")
                ignored = (root / ".gitignore").read_text().splitlines() if (root / ".gitignore").exists() else []
                expected = {(p.name, match.group(1)) for p in root.glob("*.py") if p.name not in ignored
                            for match in re.finditer(r"^def (\w+)\(", p.read_text(), re.M)}
                actual = {(d.file_path, d.name) for ds in ast.index.definitions.values() for d in ds}
                assert actual == expected, (seed, online, step, op, "source definitions mismatch")
            finally:
                close(clean)
    finally:
        if ast is not None:
            close(ast)


@pytest.mark.parametrize("seed", [7, 29, 101])
@pytest.mark.parametrize("online", [False, True], ids=["reopened", "live"])
def test_mixed_edits_match_clean_index(tmp_path, seed, online):
    check_sequence(tmp_path, seed, online)


def test_mixed_edit_oracle_rejects_disabled_repair(tmp_path, monkeypatch):
    monkeypatch.setattr(ASTService, "repair_changed_files", lambda self: False)
    with pytest.raises(AssertionError, match="fresh-index mismatch"):
        check_sequence(tmp_path, 7, True)
