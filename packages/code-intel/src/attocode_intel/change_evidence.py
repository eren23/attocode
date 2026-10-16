"""Bounded Git snapshots and portable evidence; no checkout or user-code execution."""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import stat
import subprocess
import time
from pathlib import Path

FILE_BYTES = 512 * 1024
SNAPSHOT_BYTES = 16 * 1024 * 1024
GIT_BYTES = 8 * 1024 * 1024
SCHEMA = "attocode.change-evidence.v1"


def digest(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()


class GitWorkspace:
    def __init__(self, project):
        self.root = Path(project).resolve()
        self.deadline = time.monotonic() + 45
        self.anchor_bytes = 0
        self.filter_overrides = []
        self.disabled_filters = set()
        config = self.git("config", "--null", "--list")
        for item in config.split(b"\0"):
            key, _, value = item.partition(b"\n")
            if (
                key.startswith(b"filter.")
                and key.endswith((b".clean", b".process"))
                and value.strip()
            ):
                self.disabled_filters.add(key.decode().rsplit(".", 1)[0])
        for driver in sorted(self.disabled_filters):
            self.filter_overrides.extend(
                [
                    "-c",
                    driver + ".clean=",
                    "-c",
                    driver + ".process=",
                    "-c",
                    driver + ".required=false",
                ]
            )
        actual = Path(self.git("rev-parse", "--show-toplevel").decode().strip()).resolve()
        if actual != self.root:
            raise ValueError("Select the Git repository root as workspace")

    def git(self, *args, limit=GIT_BYTES):
        self.check_deadline()
        # Disable hooks, external diff/textconv and fsmonitor. Capture with a hard
        # byte/deadline bound, rather than communicate() buffering arbitrary output.
        command = [
            "git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            *self.filter_overrides,
            "--literal-pathspecs",
            *args,
        ]
        env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
        with subprocess.Popen(
            command, cwd=self.root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        ) as process:
            chunks, size, deadline = [], 0, time.monotonic() + 15
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    while True:
                        if time.monotonic() > deadline:
                            raise ValueError("Git command exceeded its 15-second deadline")
                        if not selector.select(0.1):
                            continue
                        chunk = os.read(process.stdout.fileno(), min(65536, limit + 1 - size))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        size += len(chunk)
                        if size > limit:
                            raise ValueError("Git output exceeded its bounded byte limit")
                code = process.wait(timeout=1)
                if code:
                    raise ValueError("Git command failed; check repository state and revision")
                return b"".join(chunks)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)

    def check_deadline(self):
        if time.monotonic() > self.deadline:
            raise ValueError(
                "Investigation exceeded its 45-second collection budget; reduce the requested limits"
            )

    def revision(self, name):
        if not name or name.startswith("-") or len(name) > 256:
            raise ValueError("Expected a Git revision name")
        return (
            self.git("rev-parse", "--verify", "--end-of-options", name + "^{commit}", limit=256)
            .decode()
            .strip()
        )

    def path(self, name):
        path = self.root / name
        if (
            Path(name).is_absolute()
            or ".." in Path(name).parts
            or not path.resolve().is_relative_to(self.root)
        ):
            raise ValueError("Evidence path must remain inside the repository")
        if path.is_symlink():
            raise ValueError("Symbolic links are not source evidence")
        return path

    def read(self, name):
        self.check_deadline()
        path = self.path(name)
        if not path.exists():
            return None
        if not path.is_file():
            raise ValueError("Expected a regular source file")
        before = path.stat()
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("Expected a regular source file")
            content = stream.read(FILE_BYTES + 1)
        after = path.stat()
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError("Source path changed during evidence collection")
        if len(content) > FILE_BYTES:
            raise ValueError("Source file exceeds the 512 KiB evidence limit")
        if (before.st_mtime_ns, before.st_ctime_ns, before.st_size) != (
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_size,
        ):
            raise ValueError("Source changed during evidence collection; retry")
        return content

    def snapshot(self, base=""):
        head = self.revision("HEAD")
        status = self.git("status", "--porcelain=v1", "-z", "--untracked-files=all")
        fields = status.split(b"\0")
        paths, i = set(), 0
        while i < len(fields) and fields[i]:
            item = fields[i]
            paths.add(os.fsdecode(item[3:]))
            i += 1
            if b"R" in item[:2] or b"C" in item[:2]:
                paths.add(os.fsdecode(fields[i]))
                i += 1
        if len(paths) > 256:
            raise ValueError(
                "More than 256 dirty/untracked paths; narrow or clean the workspace first"
            )
        fingerprints, total = {}, 0
        for name in sorted(paths):
            raw = self.read(name)
            total += len(raw or b"")
            if total > SNAPSHOT_BYTES:
                raise ValueError("Dirty source exceeds the 16 MiB snapshot limit")
            fingerprints[name] = digest(raw) if raw is not None else None
        return {
            "workspace": str(self.root),
            "head": head,
            "branch": self.git("rev-parse", "--abbrev-ref", "HEAD", limit=1024).decode().strip(),
            "base_revision": self.revision(base) if base else None,
            "index_sha256": digest(self.git("ls-files", "--stage", "-z")),
            "status_sha256": digest(status),
            "dirty_files": fingerprints,
            "disabled_filters": sorted(self.disabled_filters),
        }

    def changes(self, mode, base=""):
        if mode not in {"working", "staged", "unstaged", "branch"}:
            raise ValueError("mode must be working, staged, unstaged or branch")
        if bool(base) != (mode == "branch"):
            raise ValueError("base is required only for branch mode")
        if mode == "branch":
            start = (
                self.git("merge-base", self.revision(base), self.revision("HEAD"), limit=256)
                .decode()
                .strip()
            )
            comparison = [start]
        elif mode == "staged":
            start, comparison = self.revision("HEAD"), ["--cached", "HEAD"]
        elif mode == "working":
            start, comparison = self.revision("HEAD"), ["HEAD"]
        else:
            start, comparison = "index", []
        fields = self.git(
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--raw",
            "-z",
            "--no-abbrev",
            "--find-renames",
            *comparison,
            "--",
        ).split(b"\0")
        rows, i = [], 0
        while i < len(fields) and fields[i]:
            old_mode, new_mode, old_blob, new_blob, status = fields[i][1:].decode().split()
            old_path = os.fsdecode(fields[i + 1])
            i += 2
            new_path = old_path
            if status.startswith(("R", "C")):
                new_path = os.fsdecode(fields[i])
                i += 1
            if status == "U":
                raise ValueError("Resolve unmerged paths before collecting change evidence")
            rows.append(
                {
                    "status": status,
                    "old_path": old_path,
                    "file_path": new_path,
                    "old_blob": old_blob,
                    "new_blob": new_blob,
                    "old_mode": old_mode,
                    "new_mode": new_mode,
                }
            )
        if mode != "staged":
            untracked = self.git("ls-files", "--others", "--exclude-standard", "-z")
            rows.extend(
                {
                    "status": "?",
                    "old_path": os.fsdecode(p),
                    "file_path": os.fsdecode(p),
                    "old_blob": "0" * 40,
                    "new_blob": "0" * 40,
                    "old_mode": "000000",
                    "new_mode": "100644",
                }
                for p in untracked.split(b"\0")
                if p
            )
        return start, rows

    def blob(self, oid):
        return None if not oid.strip("0") else self.git("cat-file", "blob", oid, limit=FILE_BYTES)


def seal(report):
    if len(canonical(report)) > 1000000:
        raise ValueError("Evidence exceeds the 1 MiB report limit; reduce max_symbols or depth")
    report["schema"] = SCHEMA
    report["report_id"] = digest(canonical({k: v for k, v in report.items() if k != "report_id"}))
    return report


def validate_report(report):
    if not isinstance(report, dict) or report.get("schema") != SCHEMA:
        raise ValueError("Expected an attocode change-evidence v1 report")
    if len(canonical(report)) > 1024 * 1024:
        raise ValueError("Report exceeds the 1 MiB limit")
    if report.get("report_id") != digest(
        canonical({k: v for k, v in report.items() if k != "report_id"})
    ):
        raise ValueError("Report integrity check failed; use the untrimmed JSON export")


def check_report(project, report):
    validate_report(report)
    git = GitWorkspace(project)
    if report["snapshot"]["workspace"] != str(git.root):
        raise ValueError("Report belongs to a different workspace")
    now = git.snapshot(report["request"].get("base", ""))
    reasons = [key for key in now if now[key] != report["snapshot"].get(key)]
    for path, expected in report.get("anchors", {}).items():
        raw = git.read(path)
        if (digest(raw) if raw is not None else None) != expected:
            reasons.append("anchor:" + path)
    return {
        "report_id": report["report_id"],
        "status": "stale" if reasons else "current",
        "reasons": reasons,
        "absence_proven": False,
        "note": "Current means Git snapshot and recorded source hashes match; it is not complete impact or test coverage.",
    }
