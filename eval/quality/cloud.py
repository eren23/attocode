"""Opt-in DigitalOcean CPU batches with a persistent budget ledger and TTL reaper.

The controller retains credentials; disposable workers receive public committed
source only. 'quote' is free. 'run' creates a billed resource. No model calls.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import ipaddress
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from filelock import FileLock

from eval.quality.runner import (
    GIB,
    MARKER,
    REPO,
    disk_bytes,
    environment,
    managed_root,
    supervise,
    write_json,
)

TAG = "attocode-quality-v1"
SIZE = "c-8"
REGION = "fra1"
BATCH_USD = 1.0
MONTH_USD = 10.0
TTL_SECONDS = 7200


class API:
    def __init__(self, token=None):
        self.token = token or os.environ.get("DIGITALOCEAN_ACCESS_TOKEN")
        if not self.token:
            raise ValueError("DigitalOcean is not authenticated: configure DIGITALOCEAN_ACCESS_TOKEN on the controller; do not put it in the repo")

    def request(self, method, path, data=None):
        request = urllib.request.Request("https://api.digitalocean.com/v2" + path,
                  data=json.dumps(data).encode() if data is not None else None, method=method,
                  headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(2**22 + 1)
            if len(raw) > 2**22:
                raise ValueError("Provider response exceeds limit")
            return json.loads(raw) if raw else {}

    def list(self, resource, query=""):
        rows = []
        for page in range(1, 101):
            data = self.request("GET", f"/{resource}?per_page=200&page={page}" + query)
            rows.extend(data[resource])
            if not data.get("links", {}).get("pages", {}).get("next"):
                return rows
        raise ValueError("Provider pagination exceeds limit")


def quote(api):
    sizes = api.list("sizes")
    size = next((s for s in sizes if s["slug"] == SIZE and s.get("available") and REGION in s["regions"]), None)
    if not size or size["vcpus"] < 8 or size["memory"] < 16384:
        raise ValueError("Selected CPU capacity unavailable; no automatic size/region substitution")
    rate = float(size["price_hourly"])
    if rate <= 0 or rate * (TTL_SECONDS / 3600) + .10 > BATCH_USD:
        raise ValueError("Current quote exceeds batch budget")
    return {"size": SIZE, "region": REGION, "hourly_usd": rate,
            "estimated_40_minutes_usd": round(rate * 40 / 60, 4),
            "estimated_70_minutes_usd": round(rate * 70 / 60, 4),
            "reserved_usd": BATCH_USD, "monthly_limit_usd": MONTH_USD,
            "ttl_seconds": TTL_SECONDS, "scope": "Compute estimate before tax; no models, backups or extra volumes"}


def tagged(api, run_tag=None):
    rows = api.list("droplets", "&tag_name=" + urllib.parse.quote(TAG))
    return [r for r in rows if TAG in r.get("tags", []) and (run_tag is None or run_tag in r.get("tags", []))]


def destroy(api, node_id, *, attempts=15):
    try:
        api.request("DELETE", f"/droplets/{int(node_id)}")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    for _ in range(attempts):
        try:
            api.request("GET", f"/droplets/{int(node_id)}")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return True
            raise
        time.sleep(2)
    return False


def reap(api, *, now=None, apply=False):
    now = now or dt.datetime.now(dt.UTC)
    rows = []
    for node in tagged(api):
        created = dt.datetime.fromisoformat(node["created_at"].replace("Z", "+00:00"))
        if (now - created).total_seconds() >= TTL_SECONDS:
            row = {"id": node["id"], "name": node["name"], "expired": True}
            try:
                row["deleted"] = destroy(api, node["id"]) if apply else False
            except Exception as exc:
                row.update(deleted=False, error=type(exc).__name__)
            rows.append(row)
    return {"dry_run": not apply, "nodes": rows,
            "cleanup_verified": not apply or all(r["deleted"] for r in rows)}


def reserve(ledger, run_id, price, now):
    month = dt.datetime.fromtimestamp(now, dt.UTC).strftime("%Y-%m")
    # Keep the full reservation for the month; estimates are not invoices.
    used = sum(max(r.get("estimated_usd", 0), r["reserved_usd"]) for r in ledger if r["month"] == month)
    if any(not r.get("cleanup_verified", False) for r in ledger):
        raise ValueError("Previous batch cleanup unresolved; reconcile before creating resources")
    if used + BATCH_USD > MONTH_USD + 1e-9:
        raise ValueError("Monthly budget exhausted")
    row = {"id": run_id, "month": month, "reserved_usd": BATCH_USD,
           "hourly_usd": price["hourly_usd"], "created_at": now, "cleanup_verified": False}
    ledger.append(row)
    return row


def reconcile(api, root):
    """Confirm externally reaped workers are absent without creating resources."""
    root = managed_root(root)
    path = root / "cloud/ledger.json"
    with FileLock(str(root / ".lock"), timeout=0):
        ledger = json.loads(path.read_text()) if path.exists() else []
        nodes = tagged(api)
        for row in ledger:
            if row.get("cleanup_verified") or any(row["run_tag"] in n["tags"] for n in nodes):
                continue
            if row.get("node_id"):
                try:
                    api.request("GET", f"/droplets/{int(row['node_id'])}")
                    continue
                except urllib.error.HTTPError as exc:
                    if exc.code != 404:
                        raise
            elif time.time() - row["created_at"] < TTL_SECONDS:
                continue  # A lost create response may still be provisioning.
            row.update(cleanup_verified=True, reconciled_at=time.time())
        if path.exists():
            write_json(path, ledger)
        return {"cleanup_verified": all(r.get("cleanup_verified") for r in ledger), "ledger": ledger}


def verify_reaper():
    """Require a recent successful, non-skipped independent cleanup job."""
    base = "https://api.github.com/repos/eren23/attocode/actions"
    def get(path):
        with urllib.request.urlopen(urllib.request.Request(base + path, headers={"User-Agent": TAG}), timeout=15) as response:
            return json.load(response)
    runs = get("/workflows/quality-cleanup.yml/runs?per_page=5")["workflow_runs"]
    now = dt.datetime.now(dt.UTC)
    for run in runs:
        updated = dt.datetime.fromisoformat(run["updated_at"].replace("Z", "+00:00"))
        if run["conclusion"] != "success" or run["head_branch"] != "main" or (now - updated).total_seconds() > 7200:
            continue
        jobs = get(f"/runs/{run['id']}/jobs")["jobs"]
        if any(step["name"] == "Reap expired quality workers" and step["conclusion"] == "success"
               for job in jobs for step in job.get("steps", [])):
            return
    raise ValueError("No successful cleanup heartbeat in two hours; enable and verify the independent reaper first")


def public_bundle(path):
    relevant = ["packages/code-intel/src", "packages/code-intel/tests", "packages/code-intel/pyproject.toml",
                "eval/quality", "eval/matrix", "pyproject.toml", "uv.lock"]
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all", "--", *relevant], cwd=REPO)
    if dirty.strip():
        raise ValueError("Remote runs require committed inputs; uncommitted code stays local")
    if subprocess.run(["git", "merge-base", "--is-ancestor", "HEAD", "refs/remotes/origin/main"],
                      cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        raise ValueError("Remote runs require a commit already published on origin/main")
    subprocess.run(["git", "archive", "--format=tar.gz", "-o", str(path), "HEAD"], cwd=REPO, check=True)
    if path.stat().st_size > 100 * 2**20:
        raise ValueError("Source bundle exceeds 100 MiB admission limit")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()


def batch(api, root, *, execute=None):
    """One controller owns the ledger; tests inject execution, never a cloud key."""
    root = managed_root(root)
    cloud = root / "cloud"
    cloud.mkdir(exist_ok=True)
    ledger_path = cloud / "ledger.json"
    with FileLock(str(root / ".lock"), timeout=0):
        if disk_bytes(root) + 100 * 2**20 >= 5 * GIB:
            raise ValueError("Managed storage has insufficient bundle headroom; inspect storage/gc first")
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else []
        if tagged(api):
            raise ValueError("Existing project worker found; reconcile/destroy it before another batch")
        price = quote(api)
        run_id = uuid.uuid4().hex[:16]
        run_tag = TAG + "-" + run_id
        directory = root / "runs" / ("cloud-" + run_id)
        directory.mkdir()
        if execute is None:
            verify_reaper()
            key = Path(os.environ.get("QUALITY_SSH_KEY", str(Path.home() / ".ssh/id_ed25519")))
            key_id = os.environ.get("QUALITY_SSH_KEY_ID")
            if not key.is_file() or not key_id:
                raise ValueError("Configure QUALITY_SSH_KEY and the registered QUALITY_SSH_KEY_ID before launch")
            commit = public_bundle(directory / "source.tar.gz")
        else:
            key, key_id, commit = Path("injected"), "injected", "injected"
        row = reserve(ledger, run_id, price, time.time())
        row.update(owner=MARKER, run_tag=run_tag, source_commit=commit)
        write_json(ledger_path, ledger)
        node_id = None
        try:
            node = api.request("POST", "/droplets", {"name": run_tag, "region": REGION, "size": SIZE,
                               "image": "ubuntu-24-04-x64", "ssh_keys": [key_id], "backups": False,
                               "tags": [TAG, run_tag]})["droplet"]
            node_id = node["id"]
            row["node_id"] = node_id
            write_json(ledger_path, ledger)
            (execute or execute_batch)(api, node_id, directory, root, key)
            row["status"] = "completed"
        except BaseException as exc:
            row.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            try:
                # A create request can time out after provisioning. Recover
                # only this unique run's IDs; never delete unrelated resources.
                nodes = {node_id} if node_id is not None else {n["id"] for n in tagged(api, run_tag)}
                outcomes = [destroy(api, identity) for identity in nodes]
                # An empty list cannot prove a timed-out create never landed.
                row["cleanup_verified"] = bool(nodes) and all(outcomes)
            except Exception as exc:
                row.update(cleanup_verified=False, cleanup_error=type(exc).__name__)
            row["finished_at"] = time.time()
            if row["cleanup_verified"]:
                row["estimated_usd"] = round(max(.01, (row["finished_at"] - row["created_at"]) / 3600 * price["hourly_usd"]), 4)
            write_json(ledger_path, ledger)
            write_json(directory / "report.json", row)
            with contextlib.suppress(FileNotFoundError):
                (directory / "source.tar.gz").unlink()
        if not row["cleanup_verified"]:
            raise RuntimeError("Worker deletion unconfirmed; further launches blocked")
        return row


def execute_batch(api, node_id, directory, root, key):
    start = time.monotonic()
    deadline = start + 90 * 60
    host = None
    while time.monotonic() < start + 300:
        node = api.request("GET", f"/droplets/{node_id}")["droplet"]
        if node["status"] == "active":
            host = next((n["ip_address"] for n in node["networks"]["v4"] if n["type"] == "public"), None)
            if host:
                ipaddress.ip_address(host)
                break
        time.sleep(2)
    if not host:
        raise TimeoutError("Droplet did not become active within five minutes")
    options = ["-F", "/dev/null", "-i", str(key), "-o", "BatchMode=yes", "-o", "ForwardAgent=no",
               "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=accept-new",
               "-o", "UserKnownHostsFile=" + str(directory / "known_hosts"), "-o", "ConnectTimeout=10"]
    ssh = ["ssh", *options, "root@" + host]
    env = environment(root)
    ready = False
    while time.monotonic() < start + 480:
        if subprocess.run([*ssh, "true"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15).returncode == 0:
            ready = True
            break
        time.sleep(2)
    if not ready:
        raise TimeoutError("SSH was not ready within setup budget")
    commands = [
        ("upload", ["scp", *options, str(directory / "source.tar.gz"), "root@" + host + ":/root/source.tar.gz"]),
        ("setup", [*ssh, "set -eu; mkdir -p /root/job; tar -xzf /root/source.tar.gz -C /root/job; rm /root/source.tar.gz; "
                   "apt-get update -qq; apt-get install -y -qq python3-venv git ripgrep; "
                   "python3 -m venv /root/bootstrap; /root/bootstrap/bin/pip -q install uv==0.10.7; "
                   "cd /root/job; mkdir -p .attocode/quality; printf %s attocode-quality-v1 > .attocode/quality/.owner; "
                   "UV_CACHE_DIR=/root/job/.attocode/quality/cache/uv /root/bootstrap/bin/uv sync "
                   "--locked --package attocode-code-intel --extra dev --extra service"]),
        ("tests", [*ssh, "cd /root/job; QUALITY_ALLOW_DOWNLOADS=1 .venv/bin/python -m eval.quality broad"]),
    ]
    rows = []
    try:
        for name, command in commands:
            limit = min(deadline, time.monotonic() + (600 if name in {"upload", "setup"} else 3660))
            result = supervise(command, cwd=REPO, env=env, root=root, log=directory / (name + ".log"),
                               deadline=limit, max_bytes=5 * GIB)
            rows.append({"name": name, **result})
            if result["status"] != "passed":
                raise RuntimeError(f"Remote {name} failed; see bounded controller log")
    finally:
        # Reports/logs only: no cloning the remote corpora or indexes to the Mac.
        collect = [*ssh, "cd /root/job; python3 - <<'PYREMOTE'\nimport pathlib,tarfile\nsize=0\n"
                   "with tarfile.open('/root/results.tar.gz','w:gz') as out:\n"
                   " for p in pathlib.Path('.attocode/quality/runs').glob('*/*'):\n"
                   "  if p.is_file() and not p.is_symlink() and p.suffix in ('.json','.log'):\n"
                   "   size += p.stat().st_size\n"
                   "   assert p.stat().st_size <= 2**21 and size <= 20*2**20, 'Report export exceeds limit'\n"
                   "   out.add(p)\n"
                   "PYREMOTE"]
        result = supervise(collect, cwd=REPO, env=env, root=root, log=directory / "collect.log",
                           deadline=min(deadline, time.monotonic() + 120), max_bytes=5 * GIB)
        rows.append({"name": "collect", **result})
        if result["status"] == "passed":
            result = supervise(["scp", *options, "root@" + host + ":/root/results.tar.gz", str(directory / "results.tar.gz")],
                               cwd=REPO, env=env, root=root, log=directory / "download.log",
                               deadline=min(deadline, time.monotonic() + 120), max_bytes=5 * GIB)
            rows.append({"name": "download", **result})
        write_json(directory / "phases.json", rows)
    if any(r["status"] != "passed" for r in rows):
        raise RuntimeError("Remote result collection incomplete")


def main(command="quote", *, root=None):
    try:
        api = API()
        if command == "quote":
            result = quote(api)
        elif command == "run":
            result = batch(api, root or REPO / ".attocode/quality")
        elif command == "reconcile":
            result = reconcile(api, root or REPO / ".attocode/quality")
        elif command in {"reap", "reap-apply"}:
            result = reap(api, apply=command == "reap-apply")
        else:
            raise ValueError("Cloud command must be quote, run, reconcile, reap, or reap-apply")
        print(json.dumps(result, indent=2))
        return 0 if result.get("cleanup_verified", True) else 1
    except (ValueError, RuntimeError, urllib.error.URLError) as exc:
        print(str(exc))
        return 1
