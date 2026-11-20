"""Run the frozen freshness fixture and observe its real macOS backend."""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import os
import platform
import sys
import tempfile
from pathlib import Path

import watchfiles.main

from . import watch_freshness_audit as fixture


def main() -> int:
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    assert sys.platform == "darwin"
    assert Path(tempfile.gettempdir()).resolve() == Path(tempfile.gettempdir())
    assert not os.getenv("WATCHFILES_FORCE_POLLING")
    watchfiles_version = importlib.metadata.version("watchfiles")
    assert watchfiles_version == "1.1.1"

    backend_calls = []
    real_notify = watchfiles.main.RustNotify

    def observe_backend(paths, debug, force_polling, delay, recursive, ignore_permission_denied):
        watcher = real_notify(paths, debug, force_polling, delay, recursive, ignore_permission_denied)
        backend_calls.append({
            "paths": paths,
            "force_polling": force_polling,
            "backend": repr(watcher),
        })
        return watcher

    watchfiles.main.RustNotify = observe_backend
    try:
        result = asyncio.run(fixture.run(output / "audit"))
    finally:
        watchfiles.main.RustNotify = real_notify
        (output / "backend.json").write_text(json.dumps({
            "platform": sys.platform,
            "macos": platform.mac_ver()[0],
            "machine": platform.machine(),
            "python": platform.python_version(),
            "watchfiles": watchfiles_version,
            "calls": backend_calls,
        }, indent=2) + "\n")

    report = json.loads((output / "audit" / "report.json").read_text())
    routes = report["routes"]
    assert [route["watch"] for route in routes] == [True, False]
    assert len(backend_calls) == 1, backend_calls
    backend = backend_calls[0]
    assert backend["paths"] == [routes[0]["root"]]
    assert backend["force_polling"] is False
    assert backend["backend"].startswith("RustNotify(Recommended("), backend
    assert "fsevent" in backend["backend"].lower(), backend
    if result:
        return result

    stat = routes[1]
    assert "registration" not in stat
    assert all(row["root"] != stat["root"] for row in report["events"])
    for stage in stat["stages"]:
        assert stage["before_public"] == stage["before"]
        assert stage["after_public"]["generation"] > stage["before"]["generation"]
        assert stage["after_public"]["manifest"] == stage["expected_manifest"]
    for stage in routes[0]["stages"]:
        assert stage["before_public"]["generation"] > stage["before"]["generation"]
        assert stage["before_public"]["manifest"] == stage["expected_manifest"]
    return result


if __name__ == "__main__":
    raise SystemExit(main())
