"""Exercise installation diagnostics through the actual stdio protocol."""

import pytest
from attocode_intel.onboarding import configure_client, diagnose


@pytest.mark.asyncio
@pytest.mark.parametrize("client", ["codex", "claude", "cursor"])
@pytest.mark.parametrize("profile", ["daily", "full"])
async def test_doctor_reads_both_wire_formats(tmp_path, client, profile):
    (tmp_path / "main.py").write_text("def example(): return 1\n")
    configure_client(client, tmp_path, profile=profile)
    result = await diagnose(client, tmp_path)
    assert result["status"] == "ok"
    assert result["metadata"]["workspace"] == str(tmp_path.resolve())
    assert result["tools"] > 0
    assert "python" in result["languages"]
    assert "typescript" in result["languages"]
