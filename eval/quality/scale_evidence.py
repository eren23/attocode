"""Admission and lossless bounded evidence for one immutable scale campaign."""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
import zipfile
from pathlib import Path

PRODUCT = "b4ce67f3584aad4c2e324029fac8d9b9fcdc98a8"
WHEEL_SHA = "caadfebdeb3f25090878e78ea64f1034fc01a6b0edcf48e227bd402647fdc9dd"
CAMPAIGN = "20261029-scale-qualification"
BATCHES = ("capacity", "real", "lifecycle")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


def validate_reservation(data, batch, *, month):
    baseline = json.loads(data["baseline_raw"])
    ledger = data["ledger"]
    require(
        hashlib.sha256(data["baseline_raw"].encode()).hexdigest() == data["baseline_sha256"],
        "baseline hash changed",
    )
    require(len(baseline) == 23 and ledger[:23] == baseline, "original ledger changed")
    require(data["month"] == month == "2026-10", "campaign month changed")
    require(
        data["max_batches"] == 3 and data["monthly_reserved_limit_usd"] == 26,
        "unauthorized allowance",
    )
    require(data["product_commit"] == PRODUCT, "published product changed")
    require(batch in BATCHES and data["batch"] == batch, "wrong batch")
    ordinal = BATCHES.index(batch) + 1
    require(len(ledger) == 23 + ordinal, "wrong reservation ordinal")
    require(len({r["id"] for r in ledger}) == len(ledger), "duplicate reservation")
    require(
        all(r.get("cleanup_verified") is True for r in ledger[:-1]), "previous cleanup unresolved"
    )
    added = ledger[23:]
    require([r.get("selection") for r in added] == list(BATCHES[:ordinal]), "batch order changed")
    require(
        all(r.get("campaign") == CAMPAIGN and r["reserved_usd"] == 1 for r in added),
        "reservation authority changed",
    )
    require(
        sum(
            max(r.get("estimated_usd", 0), r["reserved_usd"]) for r in ledger if r["month"] == month
        )
        <= 26,
        "monthly allowance exceeded",
    )
    row = ledger[-1]
    require(
        isinstance(row.get("id"), str)
        and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", row["id"]) is not None,
        "unsafe reservation identity",
    )
    require(
        isinstance(row.get("run_tag"), str)
        and re.fullmatch(r"quality-scale-[a-z0-9-]{1,48}", row["run_tag"]) is not None,
        "unsafe worker tag",
    )
    require(
        row["id"] == data["reservation_id"]
        and row["month"] == month
        and row.get("cleanup_verified") is False
        and row.get("selection") == batch,
        "wrong or finished reservation",
    )
    require(
        isinstance(row.get("run_tag"), str) and row["run_tag"].startswith("quality-scale-"),
        "missing worker identity",
    )
    return row


def unique_dispatch(runs, own_run, title, attempt):
    require(attempt == 1, "rerun is forbidden")
    matching = [r for r in runs if r.get("display_title") == title]
    require(len(matching) == 1 and matching[0]["id"] == own_run, "duplicate or unobserved dispatch")


def dispatch_selection(data, batch, reservation_id):
    require(
        data["batch"] == batch and data["reservation_id"] == reservation_id,
        "dispatch batch/reservation differs from secret",
    )


def admit_qualification(receipt, run, jobs, tree, head):
    require(
        run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and run.get("run_attempt") == 1
        and run.get("event") in {"push", "workflow_dispatch"}
        and run.get("path") == ".github/workflows/quality-scale.yml",
        "qualification workflow incomplete",
    )
    require(
        receipt.get("stage") == "green"
        and receipt.get("head") == run.get("head_sha") == head
        and receipt.get("tree") == tree
        and receipt.get("run_id") == str(run.get("id"))
        and receipt.get("attempt") == "1",
        "qualification source/attempt mismatch",
    )
    require(
        receipt.get("new") == 68
        and receipt.get("old") == 58
        and receipt.get("failed") == receipt.get("errors") == 0,
        "qualification controls incomplete",
    )
    by_name = {j["name"]: j for j in jobs}
    require(
        all(
            by_name.get(name, {}).get("conclusion") == "success"
            for name in ("controls", "worker-smoke", "access-check")
        ),
        "actual worker smoke or controls missing/skipped",
    )


def admit_coverage(coverage, minimum):
    require(coverage.get("phase") == "ready", "hydration is not ready")
    require(coverage.get("discovery_truncated") is False, "discovery coverage unknown or truncated")
    parsed, total = coverage.get("parsed_files"), coverage.get("total_files")
    require(
        type(parsed) is int
        and type(total) is int
        and total == parsed == minimum
        and type(coverage.get("reference_indexed_files")) is int
        and coverage["reference_indexed_files"] == minimum,
        "parsed source coverage incomplete",
    )


def admit_identities(expected, parsed, referenced):
    expected = set(expected)
    require(
        expected and set(parsed) == expected and set(referenced) == expected,
        "indexed parse/reference identities differ from eligible inputs",
    )
    return {
        "files": len(expected),
        "paths_sha256": hashlib.sha256(
            json.dumps(sorted(expected), separators=(",", ":")).encode()
        ).hexdigest(),
    }


def admit_parsers(analysis, grammars, expected):
    require(
        grammars and all(value is True for value in grammars.values()), "required grammar missing"
    )
    tiers = analysis.get("files_by_parser")
    require(
        isinstance(tiers, dict)
        and tiers
        and set(tiers) <= {"tree_sitter", "generic_ts"}
        and all(type(n) is int and n >= 0 for n in tiers.values())
        and sum(tiers.values()) == expected,
        "parser tiers missing, degraded or incomplete",
    )
    require(
        type(analysis.get("files_with_parse_failures")) is int
        and analysis["files_with_parse_failures"] == 0,
        "native parse failure observed",
    )


def campaign_runs(fetch, month):
    """Inspect every relevant run; bounded pagination refuses incomplete history."""
    result = []
    for page in range(1, 101):
        rows = fetch(page)["workflow_runs"]
        require(isinstance(rows, list), "invalid workflow history")
        result.extend(r for r in rows if r["created_at"][:7] >= month)
        if len(rows) < 100 or (rows and rows[-1]["created_at"][:7] < month):
            return result
    raise ValueError("workflow history exceeds bounded complete admission")


def case_outcome(rows):
    return (
        "passed"
        if rows
        and all(
            r.get("status") == "passed"
            and r.get("cleanup_verified") is True
            and not r.get("log_truncated")
            for r in rows
        )
        else "incomplete"
    )


def attest_wheel(wheel, installed, expected_sha):
    wheel, installed = Path(wheel), Path(installed)
    require(
        hashlib.sha256(wheel.read_bytes()).hexdigest() == expected_sha, "published wheel changed"
    )
    with zipfile.ZipFile(wheel) as archive:
        files = {
            n.removeprefix("attocode_intel/"): hashlib.sha256(archive.read(n)).hexdigest()
            for n in archive.namelist()
            if n.startswith("attocode_intel/") and n.endswith(".py")
        }
    actual = {
        str(p.relative_to(installed)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in installed.rglob("*.py")
    }
    require(files and actual == files, "installed product differs from published wheel")
    return {
        "wheel_sha256": expected_sha,
        "python_files": len(files),
        "files": files,
        "installed_root": str(installed),
    }


def export_evidence(root, destination):
    """Keep complete JSON bytes; split JSONL at complete line boundaries."""
    root = Path(root)
    entries, total, splits = [], 0, {}
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), "symlink evidence refused")
        if not path.is_file():
            continue
        require(path.suffix in {".json", ".jsonl", ".log", ".xml"}, "unexpected evidence file")
        require(path.stat().st_size <= 256 * 2**20, "oversized remote evidence input")
        raw = path.read_bytes()
        if path.suffix == ".json":
            raw = json.dumps(json.loads(raw), separators=(",", ":"), ensure_ascii=False).encode()
        name = path.relative_to(root).as_posix()
        chunks = [raw]
        if len(raw) > 2 * 2**20 and path.suffix == ".json":
            chunks = [raw[i : i + 2 * 2**20] for i in range(0, len(raw), 2 * 2**20)]
            splits[name] = {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "parts": len(chunks),
            }
        if len(raw) > 2 * 2**20 and path.suffix == ".jsonl":
            chunks, current = [], bytearray()
            for line in raw.splitlines(keepends=True):
                require(len(line) <= 2 * 2**20, "single record exceeds export limit")
                if len(current) + len(line) > 2 * 2**20:
                    chunks.append(bytes(current))
                    current.clear()
                current.extend(line)
            if current:
                chunks.append(bytes(current))
            splits[name] = {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "parts": len(chunks),
            }
        for i, chunk in enumerate(chunks):
            total += len(chunk)
            require(len(chunk) <= 2 * 2**20 and total <= 20 * 2**20, "report export exceeds limit")
            entries.append((name if len(chunks) == 1 else name + f".part{i:03d}", chunk))
    manifest = json.dumps(
        {
            "schema": 1,
            "splits": splits,
            "entries": {
                name: {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
                for name, raw in entries
            },
        },
        separators=(",", ":"),
    ).encode()
    require(
        len(manifest) <= 2 * 2**20 and total + len(manifest) <= 20 * 2**20,
        "export manifest exceeds remaining allowance",
    )
    require(not (root / "export-manifest.json").exists(), "reserved export manifest collision")
    with tarfile.open(destination, "w:gz") as archive:
        for name, chunk in entries + [("export-manifest.json", manifest)]:
            info = tarfile.TarInfo(name)
            info.size = len(chunk)
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(chunk))
    return {
        "files": len(entries),
        "bytes": total + len(manifest),
        "splits": splits,
        "archive_sha256": hashlib.sha256(Path(destination).read_bytes()).hexdigest(),
    }


def safe_export(root, destination):
    """A failed complete export still carries bounded original failure diagnostics."""
    try:
        return {"complete": True, **export_evidence(root, destination)}
    except Exception as error:
        root = Path(root)
        paths = [] if root.is_symlink() else list(root.rglob("*"))

        def priority(path):
            if path.name in {"batch-result.json", "case-result.json", "result.json"}:
                level = 0
            elif path.suffix == ".log":
                level = 1
            elif path.name.startswith(("raw-", "offered-")):
                level = 2
            else:
                level = 3
            return level, path.as_posix()

        bodies, inventory, used, dropped = [], [], 0, 0
        for path in sorted(paths, key=priority):
            if path.is_dir() and not path.is_symlink():
                continue
            name = path.relative_to(root).as_posix()
            if path.is_symlink() or not path.is_file():
                inventory.append({"path": name, "reason": "unsafe-entry", "retained": False})
                continue
            size = path.stat().st_size
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            row = {"path": name, "bytes": size, "sha256": digest, "parts": []}
            budget = max(0, 16 * 2**20 - used)
            keep = min(size, budget)
            if size > 2 * 2**20 and path.suffix == ".log":
                keep = min(keep, 2 * 2**20)
                spans = [(0, keep // 2), (size - (keep - keep // 2), size)] if keep else []
            else:
                spans = [(i, min(i + 2 * 2**20, keep)) for i in range(0, keep, 2 * 2**20)]
            with path.open("rb") as stream:
                for i, (start, end) in enumerate(spans):
                    stream.seek(start)
                    raw = stream.read(end - start)
                    part = (
                        name if keep == size and len(spans) == 1 else name + f".failure-part{i:03d}"
                    )
                    if part in {"collection-failure.json", "export-manifest.json"}:
                        part = "original-" + part
                    bodies.append((part, raw))
                    used += len(raw)
                    row["parts"].append(
                        {
                            "path": part,
                            "start": start,
                            "end": end,
                            "sha256": hashlib.sha256(raw).hexdigest(),
                        }
                    )
            row["dropped_bytes"] = size - keep
            dropped += size - keep
            inventory.append(row)
        inventory_raw = json.dumps(inventory, separators=(",", ":")).encode()
        loss = {
            "complete": False,
            "reason": "complete-export-failed",
            "error": str(error)[:2000],
            "dropped_bytes": dropped,
            "original_entries": len(inventory),
            "inventory_sha256": hashlib.sha256(inventory_raw).hexdigest(),
            "inventory_limited": len(inventory_raw) > 2**20,
            "entries": inventory
            if len(inventory_raw) <= 2**20
            else inventory[:100] + inventory[-100:],
        }
        bodies.append(("collection-failure.json", json.dumps(loss, separators=(",", ":")).encode()))
        manifest = {
            "schema": 1,
            "complete": False,
            "entries": {
                name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                for name, raw in bodies
            },
        }
        bodies.append(
            ("export-manifest.json", json.dumps(manifest, separators=(",", ":")).encode())
        )
        require(
            sum(len(raw) for _, raw in bodies) <= 20 * 2**20
            and all(len(raw) <= 2 * 2**20 for _, raw in bodies),
            "bounded failure metadata overflow",
        )
        with tarfile.open(destination, "w:gz") as archive:
            for name, raw in bodies:
                info = tarfile.TarInfo(name)
                info.size = len(raw)
                info.mode = 0o600
                archive.addfile(info, io.BytesIO(raw))
        return {
            "complete": False,
            "files": len(bodies),
            "bytes": sum(len(raw) for _, raw in bodies),
            "dropped_bytes": dropped,
            "archive_sha256": hashlib.sha256(Path(destination).read_bytes()).hexdigest(),
        }
