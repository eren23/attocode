"""Replay fixed queries against a frozen engine; measures wire volume, not agent speed."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

from workflows import SCENARIOS, snapshot


async def run(args):
    import attocode_intel
    from attocode_intel._internal.integrations.utilities.token_estimate import count_tokens
    from attocode_intel.gateway import OperationGateway

    revisions = json.loads(args.revisions.read_text())
    rows = []
    with tempfile.TemporaryDirectory(prefix="intel-response-replay-") as temporary:
        for spec in SCENARIOS:
            source = args.project if spec["repo"] == "frontend" else args.repo_dir / spec["repo"]
            destination = Path(temporary) / spec["repo"]
            destination.mkdir()
            root = snapshot(source, destination, spec["repo"] == "frontend", revisions[spec["repo"]])
            gateway = OperationGateway(str(root), "daily", watch=False)
            queries = [("search_symbols", {"name": spec["symbol"]}),
                       ("cross_references", {"symbol_name": spec["symbol"]}),
                       ("dependencies", {"path": spec["file"]}),
                       ("suggest_tests", {"files": [spec["file"]]}),
                       ("search_symbols", {"name": "attocode_deliberately_absent_9273"})]
            try:
                for i, (name, arguments) in enumerate(queries):
                    tokens, size, pages, references = 0, 0, 0, []
                    start = time.monotonic()
                    while True:
                        operation = gateway.execute if args.legacy else gateway.execute_mcp
                        result = await operation(name, arguments)
                        wire = result.model_dump_json(exclude_none=True)
                        tokens += count_tokens(wire)
                        size += len(wire.encode())
                        pages += 1
                        data = result.structuredContent if args.legacy else json.loads(result.content[0].text)
                        payload = data.get("data")
                        if name == "cross_references":
                            references.extend(payload["references"])
                            if payload.get("next_cursor"):
                                arguments = {**arguments, "cursor": payload["next_cursor"]}
                                continue
                        break
                    # Known anchors remain a narrow regression check, not an agent correctness score.
                    if i == 0:
                        evidence = any(r["file_path"] == spec["file"] for r in payload)
                    elif name == "cross_references":
                        evidence = any(r["file_path"] == spec["caller"] for r in references)
                    elif name == "dependencies":
                        evidence = spec["importer"] in payload["imported_by"]
                    elif name == "suggest_tests":
                        evidence = spec["test"] in json.dumps(data) if spec["test"] else True
                    else:
                        evidence = payload == []
                    rows.append({"id": f"{spec['repo']}:{i}", "operation": name, "wire_tokens": tokens,
                                 "wire_bytes": size, "pages": pages, "evidence": evidence,
                                 "seconds": time.monotonic() - start})
            finally:
                await gateway.close()
    engine = hashlib.sha256()
    source_root = Path(attocode_intel.__file__).parent.parent
    for path in sorted(source_root.rglob("*.py")):
        engine.update(str(path.relative_to(source_root)).encode() + b"\0" + path.read_bytes())
    args.output.write_text(json.dumps({"legacy": args.legacy, "revisions": revisions, "engine_sha256": engine.hexdigest(),
                                       "measurement": "serialized_mcp_result_all_pages", "rows": rows}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--repo-dir", type=Path, required=True)
    parser.add_argument("--revisions", type=Path, required=True)
    parser.add_argument("--legacy", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.environ["ATTOCODE_INTEL_PRECISION"] = "off"
    asyncio.run(run(args))
