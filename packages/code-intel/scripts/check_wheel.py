"""Run using only the installed wheel in a clean environment."""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import sys
import tempfile
from pathlib import Path

try:
    importlib.metadata.distribution("attocode")
except importlib.metadata.PackageNotFoundError:
    pass
else:
    raise AssertionError("Wheel verification must run without the attocode distribution")


class NoAgent:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {
            "attocode",
            "attoswarm",
            "attocode_core",
            "textual",
            "anthropic",
            "openai",
        }:
            raise AssertionError(f"Standalone intelligence imported {fullname}")
        return None


sys.meta_path.insert(0, NoAgent())


async def check():
    from attocode_intel.catalog import tool_catalog
    from attocode_intel.gateway import OperationGateway

    assert len(tool_catalog("full")) >= 135
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / "helper.py").write_text("def independently_installed(): return 1\n")
        gateway = OperationGateway(str(root), watch=False)
        try:
            result = await gateway.execute("symbols", {"path": "helper.py"})
            assert "independently_installed" in result.content[0].text
        finally:
            await gateway.close()
    from attocode_intel.rules.loader import load_builtin_rules

    assert load_builtin_rules(), "Builtin assets missing from wheel"
    print(
        json.dumps(
            {
                "version": importlib.metadata.version("attocode-code-intel"),
                "tools": len(tool_catalog()),
                "agent_required": False,
            }
        )
    )


asyncio.run(check())
