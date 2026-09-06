"""Reproducible local navigation acceptance gate. No network or model is needed."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import time
from pathlib import Path

from attocode_intel._internal.integrations.utilities.token_estimate import count_tokens
from attocode_intel.gateway import OperationGateway


async def evaluate(size: int, root: Path):
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname="intelligence-eval"\nversion="0.1.0"\n')
    for i in range(size):
        source = f"from module_{i - 1} import operation_{i - 1}\n" if i else ""
        (root / f"module_{i}.py").write_text(
            source + f"def operation_{i}(value: int) -> int:\n    return value + {i}\n"
        )
    result = {"files": size}
    for label in ("cold", "warm"):
        gateway = OperationGateway(str(root), profile="daily", watch=False)
        try:
            started = time.monotonic()
            bootstrap = await gateway.execute(
                "bootstrap", {"task_hint": f"operation_{size - 1}", "max_tokens": 2000}
            )
            result[f"{label}_bootstrap_ms"] = round((time.monotonic() - started) * 1000, 1)
            tokens = count_tokens(bootstrap.content[0].text)
            result[f"{label}_tokens"] = tokens
            assert tokens <= 2000
            assert result[f"{label}_bootstrap_ms"] < 30_000, "Bootstrap exceeded 30 second gate"
            started = time.monotonic()
            symbol = await gateway.execute("symbols", {"path": f"module_{size - 1}.py"})
            result[f"{label}_lookup_ms"] = round((time.monotonic() - started) * 1000, 1)
            assert f"operation_{size - 1}" in symbol.content[0].text
            assert result[f"{label}_lookup_ms"] < 5000, "Focused lookup exceeded 5 second gate"
            deadline = time.monotonic() + 90
            while True:
                status = await gateway.execute("hydration_status", {})
                coverage = status.structuredContent["metadata"]["coverage"]
                if coverage["phase"] == "ready":
                    break
                assert time.monotonic() < deadline, "Hydration exceeded 90 second gate"
                await asyncio.sleep(0.2)
            deps = await gateway.execute("dependencies", {"path": f"module_{size - 1}.py"})
            assert f"module_{size - 2}.py" in deps.content[0].text, (
                "Deferred dependency graph is empty"
            )
            assert not coverage.get("discovery_truncated"), "Discovery silently omitted files"
            assert coverage["dep_graph_files"] >= size - 1, "Dependency graph omitted import edges"
            result[f"{label}_coverage"] = coverage
        finally:
            await gateway.close()
    return result


async def run(args):
    results = []
    with tempfile.TemporaryDirectory(prefix="intelligence-eval-") as temp:
        for size in args.sizes:
            results.append(await evaluate(size, Path(temp) / str(size)))
            print(json.dumps(results[-1]), flush=True)
    Path(args.output).write_text(
        json.dumps({"workload": "python-import-chain", "results": results}, indent=2) + "\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", type=int, nargs="+", default=[100, 1000, 10000])
    parser.add_argument("--output", default="intelligence-eval.json")
    asyncio.run(run(parser.parse_args()))
