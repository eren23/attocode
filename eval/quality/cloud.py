"""Opt-in DigitalOcean CPU batches with a persistent budget ledger and TTL reaper.

The controller retains credentials; disposable workers receive public committed
source only. 'quote' is free. 'run' creates a billed resource. No model calls.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import ipaddress
import json
import os
import shlex
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
SIZE = "s-8vcpu-16gb-amd"
REGION = "ams3"
BATCH_USD = 1.0
MONTH_USD = 21.0
TTL_SECONDS = 7200
CONTROLLER_SECONDS = 90 * 60
WORKER_APT_INSTALL = (
    "apt-get", "-o", "DPkg::Lock::Timeout=120", "install", "-y", "-qq",
    "python3-venv", "git", "ripgrep",
)
# This applies only to the disposable Ubuntu worker, never the account's VPC
# or the controller. Keep DNS failure bounded before apt's long retry cycle.
WORKER_DNS_PREFLIGHT = (
    "timeout 15 getent ahostsv4 archive.ubuntu.com >/dev/null || { "
    "echo 'Worker DNS unavailable; applying temporary eth0 public DNS fallback'; "
    "resolvectl dns eth0 1.1.1.1 8.8.8.8; resolvectl domain eth0 '~.'; "
    "resolvectl flush-caches; "
    "timeout 15 getent ahostsv4 archive.ubuntu.com >/dev/null; }; "
)


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
                "packages/code-intel/scripts", "eval/quality", "eval/matrix", "pyproject.toml", "uv.lock"]
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


def workflow_arguments(packs=(), shard=None, suite="all", *, resume=False):
    import yaml

    from eval.quality.corpus import PACK
    from eval.quality.evidence import select_packs
    if suite not in {"all", "workflows", "ranking"} or (suite == "ranking" and (packs or shard or resume)):
        raise ValueError("Invalid workflow selection; ranking requires the complete gate")
    select_packs(yaml.safe_load(PACK.read_text())["repositories"], packs, shard)
    arguments = ["--suite", suite]
    for pack in packs:
        arguments.extend(["--pack", pack])
    if shard:
        arguments.extend(["--shard", shard])
    if resume:
        arguments.extend(["--resume", "/root/job/.attocode/quality/resume.json"])
    return arguments


def probe_arguments(packs=(), shard=None, suite="all", resume=None):
    """A diagnostic selects exactly one pinned corpus and is never a release gate."""
    if len(packs) != 1 or shard or resume or suite != "all":
        raise ValueError("Index probe requires exactly one pack, no shard/resume/suite override")
    workflow_arguments(packs, None, "all")
    return ["--pack", packs[0], "--seconds", "600"]


def validated_resume(path):
    """Reject wrong source inputs before spending; the worker checks its environment."""
    if path is None:
        return None
    from eval.quality.corpus import evidence_identity
    from eval.quality.evidence import reusable_rows
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2**21:
        raise ValueError("Resume report must be a regular file of at most 2 MiB")
    data = json.loads(path.read_text())
    identity = evidence_identity()
    for key in ('source_sha256', 'harness_sha256', 'fixture_sha256', 'pack_sha256'):
        if data.get('identity', {}).get(key) != identity[key]:
            raise ValueError("Resume report has different candidate inputs")
    reusable_rows(data, data['identity'], data.get('manifest_packs', []))
    return data


def batch(api, root, *, execute=None, packs=(), shard=None, suite="all", resume=None, diagnostic=False):
    """One controller owns the ledger; tests inject execution, never a cloud key."""
    probe_arguments(packs, shard, suite, resume) if diagnostic else workflow_arguments(packs, shard, suite, resume=bool(resume))
    resume_data = validated_resume(resume)  # Validate before provisioning or reservation.
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
        if resume_data is not None:
            write_json(directory / "resume.json", resume_data)
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
        row.update(owner=MARKER, run_tag=run_tag, source_commit=commit,
                   selection={"packs": list(packs), "shard": shard, "suite": "index-probe" if diagnostic else suite})
        if resume_data is not None:
            row['selection']['resume_sha256'] = hashlib.sha256((directory / 'resume.json').read_bytes()).hexdigest()
        write_json(ledger_path, ledger)
        node_id = None
        try:
            node = api.request("POST", "/droplets", {"name": run_tag, "region": REGION, "size": SIZE,
                               "image": "ubuntu-24-04-x64", "ssh_keys": [key_id], "backups": False,
                               "tags": [TAG, run_tag]})["droplet"]
            node_id = node["id"]
            row["node_id"] = node_id
            write_json(ledger_path, ledger)
            if execute:
                execute(api, node_id, directory, root, key)
            else:
                execute_batch(api, node_id, directory, root, key, packs=packs, shard=shard, suite=suite,
                              resume=resume_data is not None, diagnostic=diagnostic,
                              wall_deadline=row["created_at"] + CONTROLLER_SECONDS)
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


def worker_command(command, seconds):
    """Bound the worker cgroup, including children that create new sessions."""
    seconds = int(seconds)
    if not 0 < seconds <= CONTROLLER_SECONDS:
        raise ValueError("Worker timeout must be positive and within the controller budget")
    unit = "attocode-quality-" + uuid.uuid4().hex
    return shlex.join([
        "systemd-run", "--quiet", "--wait", "--pipe", "--collect",
        "--service-type=exec", "--expand-environment=no",
        "--unit=" + unit,
        # Package maintenance may explicitly restart even Restart=no units.
        # A second activation must fail instead of rerunning work/resetting its clock.
        "--property=ExecStartPre=/usr/bin/mkdir /run/" + unit + ".started",
        f"--property=RuntimeMaxSec={seconds}s", "--property=TimeoutStopSec=10s",
        "--property=KillMode=control-group", "--property=SendSIGKILL=yes",
        "/bin/sh", "-c", command,
    ])


def wait_for_bootstrap(ssh, env, directory, *, deadline, wall_deadline):
    """SSH readiness precedes cloud-init completion and is not safe test admission."""
    while (remaining := min(deadline - time.monotonic(), wall_deadline - time.time())) > 0:
        result = subprocess.run([*ssh, "cloud-init status --format=json"], env=env,
                                capture_output=True, text=True, timeout=min(15, remaining))
        if result.returncode == 255:  # SSH is not ready yet.
            time.sleep(min(2, remaining))
            continue
        try:
            if len(result.stdout) > 65536:
                raise ValueError("Oversized bootstrap status")
            status = json.loads(result.stdout)
            if not isinstance(status, dict):
                raise ValueError("Expected bootstrap status object")
        except ValueError as exc:
            raise RuntimeError("Invalid cloud-init status; refusing worker setup") from exc
        write_json(directory / "bootstrap.json", {"exit_code": result.returncode, **status})
        if result.returncode == 0 and status.get("extended_status") == "done" and not status.get("errors"):
            return
        if result.returncode != 0 or status.get("status") not in {"running", "not started"}:
            raise RuntimeError("Cloud-init did not finish cleanly; see bootstrap.json")
        time.sleep(min(2, remaining))
    raise TimeoutError("Cloud-init did not complete within the worker setup budget")


def execute_batch(api, node_id, directory, root, key, *, packs=(), shard=None, suite="all", resume=False,
                  wall_deadline=None, diagnostic=False):
    arguments = shlex.join(probe_arguments(packs, shard, suite, resume) if diagnostic
                           else workflow_arguments(packs, shard, suite, resume=resume))
    test_module = "eval.quality.index_probe" if diagnostic else "eval.quality broad"
    start = time.monotonic()
    deadline = start + CONTROLLER_SECONDS
    if wall_deadline is None:
        wall_deadline = time.time() + CONTROLLER_SECONDS

    def remaining():
        return min(deadline - time.monotonic(), wall_deadline - time.time())
    host = None
    while time.monotonic() < start + 300 and remaining() > 0:
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
               "-o", "UserKnownHostsFile=" + str(directory / "known_hosts"), "-o", "ConnectTimeout=10",
               "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3"]
    ssh = ["ssh", *options, "root@" + host]
    env = environment(root)
    wait_for_bootstrap(ssh, env, directory, deadline=min(deadline, start + 480),
                       wall_deadline=wall_deadline)
    commands = [
        ("upload", ["scp", *options, str(directory / "source.tar.gz"), "root@" + host + ":/root/source.tar.gz"]),
        ("setup", [*ssh, "set -eu; " + WORKER_DNS_PREFLIGHT +
                   "mkdir -p /root/job; tar -xzf /root/source.tar.gz -C /root/job; rm /root/source.tar.gz; "
                   "apt-get update -qq; " + shlex.join(WORKER_APT_INSTALL) + "; "
                   "python3 -m venv /root/bootstrap; /root/bootstrap/bin/pip -q install uv==0.10.7; "
                   "cd /root/job; mkdir -p .attocode/quality; printf %s attocode-quality-v1 > .attocode/quality/.owner; "
                   "UV_CACHE_DIR=/root/job/.attocode/quality/cache/uv /root/bootstrap/bin/uv sync "
                   "--locked --package attocode-code-intel --extra dev --extra service"]),
        ("tests", [*ssh, "cd /root/job; QUALITY_ALLOW_DOWNLOADS=1 .venv/bin/python -m " + test_module + " " + arguments]),
    ]
    if resume:
        commands.insert(2, ('resume', ['scp', *options, str(directory / 'resume.json'),
                                      'root@' + host + ':/root/job/.attocode/quality/resume.json']))
    rows = []
    try:
        for name, command in commands:
            if remaining() <= 0:
                raise TimeoutError("Controller wall or monotonic deadline expired")
            if name in {"setup", "tests"}:
                # Leave ten seconds for systemd's SIGKILL escalation.
                seconds = min(600 if name == "setup" else 660 if diagnostic else 3600, int(remaining()) - 10)
                if seconds <= 0:
                    raise TimeoutError("Insufficient controller time for remote work")
                command = [*command[:-1], worker_command(command[-1], seconds)]
            limit = min(deadline, time.monotonic() + (600 if name in {"upload", "setup"} else 3660))
            result = supervise(command, cwd=REPO, env=env, root=root, log=directory / (name + ".log"),
                               deadline=limit, wall_deadline=wall_deadline, max_bytes=5 * GIB)
            rows.append({"name": name, **result})
            if result["status"] != "passed":
                raise RuntimeError(f"Remote {name} failed; see bounded controller log")
    finally:
        # Reports/logs only: no cloning the remote corpora or indexes to the Mac.
        collect_seconds = min(110, int(remaining()) - 10)
        if collect_seconds <= 0:
            result = {"status": "incomplete", "reason": "admission_budget", "seconds": 0}
        else:
            collect = [*ssh, worker_command("cd /root/job; python3 -m eval.quality.export", collect_seconds)]
            result = supervise(collect, cwd=REPO, env=env, root=root, log=directory / "collect.log",
                               deadline=min(deadline, time.monotonic() + 120),
                               wall_deadline=wall_deadline, max_bytes=5 * GIB)
        rows.append({"name": "collect", **result})
        if result["status"] == "passed":
            result = supervise(["scp", *options, "root@" + host + ":/root/results.tar.gz", str(directory / "results.tar.gz")],
                               cwd=REPO, env=env, root=root, log=directory / "download.log",
                               deadline=min(deadline, time.monotonic() + 120),
                               wall_deadline=wall_deadline, max_bytes=5 * GIB)
            rows.append({"name": "download", **result})
        write_json(directory / "phases.json", rows)
    if any(r["status"] != "passed" for r in rows):
        raise RuntimeError("Remote result collection incomplete")


def main(command="quote", *, root=None, packs=(), shard=None, suite="all", resume=None):
    try:
        api = API()
        if command == "quote":
            result = quote(api)
        elif command in {"run", "probe"}:
            result = batch(api, root or REPO / ".attocode/quality", packs=packs, shard=shard, suite=suite, resume=resume,
                           diagnostic=command == "probe")
        elif command == "reconcile":
            result = reconcile(api, root or REPO / ".attocode/quality")
        elif command in {"reap", "reap-apply"}:
            result = reap(api, apply=command == "reap-apply")
        else:
            raise ValueError("Cloud command must be quote, run, probe, reconcile, reap, or reap-apply")
        print(json.dumps(result, indent=2))
        return 0 if result.get("cleanup_verified", True) else 1
    except (ValueError, RuntimeError, urllib.error.URLError) as exc:
        print(str(exc))
        return 1
