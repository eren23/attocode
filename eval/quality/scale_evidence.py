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
        receipt.get("new") == 45
        and receipt.get("old") == 58
        and receipt.get("failed") == receipt.get("errors") == 0,
        "qualification controls incomplete",
    )
    by_name = {j["name"]: j for j in jobs}
    require(
        all(
            by_name.get(name, {}).get("conclusion") == "success"
            for name in ("controls", "worker-smoke")
        ),
        "actual worker smoke or controls missing/skipped",
    )


def admit_coverage(coverage, minimum):
    require(coverage.get("phase") == "ready", "hydration is not ready")
    require(coverage.get("discovery_truncated") is False, "discovery coverage unknown or truncated")
    parsed, total = coverage.get("parsed_files"), coverage.get("total_files")
    require(
        type(parsed) is int and type(total) is int and total >= parsed >= minimum,
        "parsed source coverage incomplete",
    )


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
