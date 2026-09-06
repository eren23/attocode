"""Smoke-test a built image with disposable source files and container state."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path

import httpx


def run(image):
    with tempfile.TemporaryDirectory(prefix="intelligence-image-", dir="/tmp") as temp:
        root = Path(temp).resolve()
        (root / ".attocode").mkdir()
        (root / "helper.py").write_text("def container_navigation(): return 1\n")
        container = subprocess.check_output(
            [
                "docker",
                "run",
                "--rm",
                "-d",
                "-p",
                "127.0.0.1::8080",
                "-e",
                "ATTOCODE_PROJECT_DIR=/project",
                "-e",
                "ATTOCODE_API_KEY=smoke-test-token",
                "--mount",
                f"type=bind,src={root},dst=/project,readonly",
                "--tmpfs",
                "/project/.attocode",
                image,
            ],
            text=True,
        ).strip()
        try:
            port = (
                subprocess.check_output(["docker", "port", container, "8080"], text=True)
                .strip()
                .rsplit(":", 1)[1]
            )
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=15) as client:
                deadline = time.monotonic() + 60
                while True:
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if time.monotonic() > deadline:
                        logs = subprocess.check_output(["docker", "logs", container], text=True)
                        raise AssertionError("Image failed to start: " + logs)
                    time.sleep(0.3)
                assert "text/html" in client.get("/").headers["content-type"]
                headers = {
                    "Accept": "application/json, text/event-stream",
                    "Authorization": "Bearer smoke-test-token",
                }
                body = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "image-smoke", "version": "1"},
                    },
                }
                assert client.post("/mcp/", json=body).status_code == 401
                response = client.post("/mcp/", json=body, headers=headers)
                assert response.status_code == 200, response.text
                body.update(
                    method="tools/call",
                    params={"name": "symbols", "arguments": {"path": "helper.py"}},
                )
                result = client.post("/mcp/", json=body, headers=headers).json()["result"]
                assert not result.get("isError"), result
                assert "container_navigation" in result["content"][0]["text"]
                print(
                    json.dumps(
                        {
                            "image": image,
                            "health": "ok",
                            "dashboard": "ok",
                            "mcp_auth": "ok",
                            "navigation": "ok",
                        }
                    )
                )
        finally:
            subprocess.run(["docker", "stop", container], check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    run(parser.parse_args().image)
