"""The opt-in profile advertises useful calls without orphaned follow-ups."""

import json

import pytest
from attocode_intel.catalog import LEAN, tool_catalog
from attocode_intel.entrypoint import main
from attocode_intel.gateway import OperationGateway
from attocode_intel.onboarding import configure_client


@pytest.mark.parametrize("watch", [True, False])
@pytest.mark.asyncio
async def test_lean_surface_and_freshness(tmp_path, monkeypatch, watch):
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    path = tmp_path / "helper.py"
    path.write_text("def helper(): return 1\n")
    (tmp_path / "caller.py").write_text("from helper import helper\nhelper()\n")
    gateway = OperationGateway(str(tmp_path), "lean", watch=watch)
    try:
        names = {t.name for t in gateway.catalog(mcp=True)}
        assert names == LEAN | (set() if watch else {"notify_file_changed"})
        assert "optional" in gateway.instructions and "If you choose" in gateway.instructions
        for tool in gateway.catalog(mcp=True):
            assert tool.inputSchema["properties"]["max_tokens"]["default"] == 2000
        with pytest.raises(ValueError, match="full-profile"):
            await gateway.execute_mcp("dependencies", {"path": "caller.py"})
        result = json.loads((await gateway.execute_mcp("inspect_symbol", {
            "symbol_name": "helper", "file_path": "helper.py"})).content[0].text)
        data = result["data"]
        assert "references" not in data["follow_up"] and "imports" not in data["follow_up"]
        assert data["advanced_follow_up"]["references"]["profile"] == "full"
        assert data["follow_up"]["tests"]["tool"] == "suggest_tests"
        path.write_text("def helper(): return 99\n")
        if not watch:
            await gateway.execute_mcp("notify_file_changed", {"files": ["helper.py"]})
        data = json.loads((await gateway.execute_mcp("inspect_symbol", {
            "symbol_name": "helper", "file_path": "helper.py"})).content[0].text)["data"]
        assert "return 99" in data["source"]["text"]
        capability = json.loads((await gateway.execute_mcp("capabilities", {})).content[0].text)["data"]
        assert set(capability["tools"]) == names
        assert "dependencies" in capability["advanced_tools"]
        assert capability["advanced_profile"]["restart_required"]
    finally:
        await gateway.close()


@pytest.mark.parametrize("client", ["claude", "codex", "cursor"])
def test_local_install_and_remote_rejection(tmp_path, client):
    preview = configure_client(client, tmp_path, profile="lean", dry_run=True)
    assert "lean" in preview["configuration"]["args"]
    if client != "claude":
        assert "Code intelligence is optional" in preview["instructions"]
    with pytest.raises(ValueError, match="local-only"):
        configure_client(client, tmp_path, profile="lean", server="https://example.invalid", dry_run=True)
    assert not list(tmp_path.iterdir())
    with pytest.raises(ValueError, match="local profile"):
        tool_catalog("lean", remote=True)


def test_legacy_sse_rejects_lean():
    with pytest.raises(SystemExit) as exc:
        main(["--profile", "lean", "--transport", "sse"])
    assert exc.value.code == 2


def test_existing_advertisements_still_match():
    daily = {t.name for t in OperationGateway(profile="daily").catalog(mcp=True)}
    assert len(daily) == 16 and daily >= LEAN
    assert "dependencies" in daily
    full = {t.name for t in tool_catalog("full")}
    assert len(full) >= 135 and daily <= full
