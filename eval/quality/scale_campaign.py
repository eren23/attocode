"""GHA-only controller for three pre-reserved, immutable-product DO batches."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import ipaddress
import json
import os
import shlex
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from eval.quality.cloud import (
    API,
    TAG,
    WORKER_DNS_PREFLIGHT,
    destroy,
    public_bundle,
    quote,
    tagged,
    verify_reaper,
    wait_for_bootstrap,
    worker_command,
)
from eval.quality.scale_evidence import (
    PRODUCT,
    export_evidence,
    require,
    unique_dispatch,
    validate_reservation,
    write,
)


def preflight(data, output, api):
    require(
        os.environ.get("GITHUB_REF") == "refs/heads/main", "paid controller requires published main"
    )
    require(
        os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "manual paid dispatch required"
    )
    require(
        os.environ.get("INPUT_RESERVATION") == data["reservation_id"],
        "dispatch reservation differs from secret",
    )
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    require(head == os.environ["GITHUB_SHA"], "checkout differs from dispatch")
    require(
        subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip()
        == data["qualified_tree"],
        "qualified harness tree changed",
    )
    subprocess.run(["git", "fetch", "--no-tags", "--depth", "1", "origin", PRODUCT], check=True)
    subprocess.run(
        [
            "git",
            "diff",
            "--exit-code",
            PRODUCT,
            "HEAD",
            "--",
            "packages/code-intel/src",
            "packages/code-intel/pyproject.toml",
            "pyproject.toml",
            "uv.lock",
        ],
        check=True,
    )
    title = f"Scale {data['batch']} {data['reservation_id']}"
    with urllib.request.urlopen(
        "https://api.github.com/repos/eren23/attocode/actions/workflows/quality-scale.yml/runs?per_page=100",
        timeout=30,
    ) as stream:
        runs = json.load(stream)["workflow_runs"]
    unique_dispatch(
        runs, int(os.environ["GITHUB_RUN_ID"]), title, int(os.environ["GITHUB_RUN_ATTEMPT"])
    )
    verify_reaper()
    require(not tagged(api), "another quality worker exists")
    price = quote(api)
    require(
        price["size"] == "s-8vcpu-16gb-amd"
        and price["region"] == "ams3"
        and price["hourly_usd"] <= 0.16667,
        "live quote differs from authority",
    )
    public_bundle(output / "source.tar.gz")
    write(
        output / "admission.json",
        {
            "head": head,
            "product": PRODUCT,
            "quote": price,
            "run_id": os.environ["GITHUB_RUN_ID"],
            "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
            "source_archive_sha256": hashlib.sha256(
                (output / "source.tar.gz").read_bytes()
            ).hexdigest(),
            "reservation_id": data["reservation_id"],
            "baseline_sha256": data["baseline_sha256"],
            "ledger_sha256": hashlib.sha256(
                json.dumps(data["ledger"], sort_keys=True).encode()
            ).hexdigest(),
        },
    )
    return price


def make_key(path):
    subprocess.run(
        [
            "ssh-keygen",
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-C",
            "attocode-scale-ephemeral",
            "-f",
            str(path),
        ],
        check=True,
    )
    return Path(str(path) + ".pub").read_text().strip()


def keys(api):
    result = []
    for page in range(1, 101):
        data = api.request("GET", f"/account/keys?per_page=200&page={page}")
        result.extend(data["ssh_keys"])
        if not data.get("links", {}).get("pages", {}).get("next"):
            return result
    raise ValueError("SSH key pagination limit")


def run(data, output, *, api=None, execute=None, month=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    require(not (output / "receipt.json").exists(), "controller receipt already exists")
    row = validate_reservation(
        data, data["batch"], month=month or dt.datetime.now(dt.UTC).strftime("%Y-%m")
    )
    api = api or API()
    result = {
        "reservation_id": row["id"],
        "batch": data["batch"],
        "run_tag": row["run_tag"],
        "complete": False,
        "cleanup_verified": False,
        "key_cleanup_verified": False,
        "started_unix": time.time(),
        "product_commit": PRODUCT,
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "head": os.environ.get("GITHUB_SHA"),
    }
    key = output.parent / ("scale-private-" + row["id"])
    name = "attocode-scale-" + row["id"]
    started_create = False
    try:
        price = preflight(data, output, api)
        result["hourly_usd"] = price["hourly_usd"]
        public = make_key(key)
        api.request("POST", "/account/keys", {"name": name, "public_key": public})
        matches = [k for k in keys(api) if k["name"] == name]
        require(len(matches) == 1, "ephemeral key identity ambiguous")
        result["key_id"] = matches[0]["id"]
        started_create = True
        created = api.request(
            "POST",
            "/droplets",
            {
                "name": name,
                "region": "ams3",
                "size": "s-8vcpu-16gb-amd",
                "image": "ubuntu-24-04-x64",
                "backups": False,
                "ssh_keys": [result["key_id"]],
                "tags": [TAG, row["run_tag"]],
            },
        )
        result["node_id"] = created["droplet"]["id"]
        write(
            output / "resource.json",
            {k: result[k] for k in ("reservation_id", "run_tag", "node_id", "key_id")},
        )
        result["execution"] = (execute or execute_remote)(api, result, output, key)
        result["complete"] = result["execution"].get("complete") is True
    except BaseException as error:
        result["error"] = {"type": type(error).__name__, "message": str(error)[:4000]}
    finally:
        cleanup_errors = []
        try:
            nodes = tagged(api, row["run_tag"])
            ids = {n["id"] for n in nodes}
            if result.get("node_id"):
                ids.add(result["node_id"])
            for node_id in ids:
                require(destroy(api, node_id), "worker deletion unverified")
            # An uncertain create response requires the independent TTL reconciliation;
            # do not claim absence from one empty eventually-consistent listing.
            result["cleanup_verified"] = not tagged(api, row["run_tag"]) and (
                not started_create or bool(ids)
            )
        except BaseException as error:
            cleanup_errors.append("worker:" + type(error).__name__)
        try:
            for item in [k for k in keys(api) if k["name"] == name]:
                api.request("DELETE", "/account/keys/" + str(item["id"]))
            result["key_cleanup_verified"] = not any(k["name"] == name for k in keys(api))
        except BaseException as error:
            cleanup_errors.append("key:" + type(error).__name__)
        for path in (key, Path(str(key) + ".pub")):
            path.unlink(missing_ok=True)
        result.update(finished_unix=time.time(), cleanup_errors=cleanup_errors)
        result["estimated_usd"] = round(
            max(
                0.01,
                (result["finished_unix"] - result["started_unix"])
                / 3600
                * result.get("hourly_usd", 0.16667),
            ),
            4,
        )
        result["complete"] = (
            result["complete"]
            and result["cleanup_verified"]
            and result["key_cleanup_verified"]
            and not cleanup_errors
        )
        write(output / "receipt.json", result)
    return result


SETUP = (
    r"""set -eu
"""
    + WORKER_DNS_PREFLIGHT
    + r"""
mkdir -p /root/job
tar -xzf /root/source.tar.gz -C /root/job
rm /root/source.tar.gz
apt-get update -qq
apt-get -o DPkg::Lock::Timeout=120 install -y -qq python3-venv python3-dev git ripgrep build-essential
python3 -m venv /root/bootstrap
/root/bootstrap/bin/pip -q install uv==0.10.7
cd /root/job
/root/bootstrap/bin/uv sync --locked --package attocode-code-intel --extra dev --extra tree-sitter-all
python3 - <<'PYWHEEL'
import hashlib,json,urllib.request
from pathlib import Path
with urllib.request.urlopen('https://pypi.org/pypi/attocode-code-intel/0.1.20/json',timeout=30) as s: data=json.load(s)
wheel=next(x for x in data['urls'] if x['filename']=='attocode_code_intel-0.1.20-py3-none-any.whl')
assert wheel['digests']['sha256']=='caadfebdeb3f25090878e78ea64f1034fc01a6b0edcf48e227bd402647fdc9dd'
with urllib.request.urlopen(wheel['url'],timeout=30) as s: raw=s.read(8*2**20+1)
assert len(raw)<=8*2**20 and hashlib.sha256(raw).hexdigest()==wheel['digests']['sha256']
Path('/root/attocode_code_intel-0.1.20-py3-none-any.whl').write_bytes(raw)
Path('/root/published.whl').write_bytes(raw)
PYWHEEL
/root/bootstrap/bin/uv pip install --python .venv/bin/python --no-deps --reinstall /root/attocode_code_intel-0.1.20-py3-none-any.whl
/root/bootstrap/bin/uv pip install --python .venv/bin/python --no-deps 'tree-sitter-crystal @ git+https://github.com/crystal-lang-tools/tree-sitter-crystal@50ca9e6fcfb16a2cbcad59203cfd8ad650e25c49'
mkdir -p /root/scale/cache/grammars
QUALITY_GRAMMAR_CACHE=/root/scale/cache/grammars .venv/bin/python - <<'PYGRAMMAR'
import os
import tree_sitter_language_pack as pack
pack.configure(cache_dir=os.environ['QUALITY_GRAMMAR_CACHE'])
pack.download(['ocaml','perl'])
assert {'ocaml','perl'}<=set(pack.downloaded_languages())
from attocode_intel._internal.integrations.context.ts_parser import is_available
assert all(is_available(x) for x in ['rust','ocaml','perl','crystal'])
PYGRAMMAR
"""
)


def execute_remote(api, result, output, key):
    from eval.quality.runner import supervise

    start = time.monotonic()
    deadline = start + 4800
    wall_deadline = time.time() + 4800
    host = None
    while time.monotonic() - start < 300:
        node = api.request("GET", "/droplets/" + str(result["node_id"]))["droplet"]
        if node["status"] == "active":
            host = next(
                (n["ip_address"] for n in node["networks"]["v4"] if n["type"] == "public"), None
            )
            if host:
                ipaddress.ip_address(host)
                break
        time.sleep(2)
    require(host is not None, "worker activation deadline")
    options = [
        "-F",
        "/dev/null",
        "-i",
        str(key),
        "-o",
        "BatchMode=yes",
        "-o",
        "ForwardAgent=no",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "UserKnownHostsFile=" + str(output / "known_hosts"),
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=3",
    ]
    ssh = ["ssh", *options, "root@" + host]
    wait_for_bootstrap(
        ssh,
        os.environ.copy(),
        output,
        deadline=min(deadline, start + 480),
        wall_deadline=wall_deadline,
    )
    rows = []

    def command(name, args, seconds):
        seconds = min(seconds, int(deadline - time.monotonic()))
        require(seconds > 0, "controller deadline")
        row = supervise(
            args,
            cwd=Path.cwd(),
            env=os.environ.copy(),
            root=output,
            log=output / (name + ".log"),
            deadline=time.monotonic() + seconds,
            wall_deadline=wall_deadline,
            max_bytes=2**30,
        )
        rows.append({"phase": name, **row})
        write(output / "phases.json", rows)
        require(
            row["status"] == "passed" and row["cleanup_verified"] and not row["log_truncated"],
            "controller phase failed: " + name,
        )

    def bounded(script, seconds, payload=False):
        args = shlex.split(worker_command(script, seconds))
        if payload:
            index = args.index("/bin/sh")
            args[index:index] = [
                "--property=MemoryMax=12G",
                "--property=MemorySwapMax=0",
                "--property=TasksMax=512",
            ]
        return [*ssh, shlex.join(args)]

    try:
        command(
            "upload",
            [
                "scp",
                *options,
                str(output / "source.tar.gz"),
                "root@" + host + ":/root/source.tar.gz",
            ],
            180,
        )
        command("setup", bounded(SETUP, 600), 620)
        environment = "ATTOCODE_LOCAL_ONLY=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 QUALITY_ALLOW_DOWNLOADS=1 QUALITY_GRAMMAR_CACHE=/root/scale/cache/grammars PYTHONPATH=/root/job"
        payload = (
            "cd /root/job; "
            + environment
            + " .venv/bin/python -m eval.quality.scale_workload --batch "
            + result["batch"]
            + " --root /root/scale"
        )
        command("payload", bounded(payload, 3600, True), 3620)
    finally:
        remaining = int(deadline - time.monotonic())
        if remaining > 150:
            script = "cd /root/job; PYTHONPATH=/root/job .venv/bin/python -m eval.quality.scale_campaign --export /root/scale/evidence --out /root/results.tar.gz"
            try:
                command("export", bounded(script, 90), 110)
                command(
                    "download",
                    [
                        "scp",
                        *options,
                        "root@" + host + ":/root/results.tar.gz",
                        str(output / "results.tar.gz"),
                    ],
                    120,
                )
                with tarfile.open(output / "results.tar.gz") as archive:
                    require(
                        sum(m.size for m in archive.getmembers()) <= 20 * 2**20,
                        "downloaded evidence overflow",
                    )
                    require(
                        all(
                            m.isfile()
                            and not Path(m.name).is_absolute()
                            and ".." not in Path(m.name).parts
                            for m in archive.getmembers()
                        ),
                        "unsafe evidence archive",
                    )
                    archive.extractall(output / "evidence", filter="data")
            except BaseException as error:
                write(
                    output / "collection-error.json",
                    {"type": type(error).__name__, "message": str(error)[:2000]},
                )
    path = output / "evidence/batch-result.json"
    require(path.exists(), "batch result missing")
    report = json.loads(path.read_text())
    return {
        "complete": report.get("complete") is True and all(r["status"] == "passed" for r in rows),
        "batch": report,
        "phases": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--export", type=Path)
    args = parser.parse_args()
    if args.export:
        receipt = export_evidence(args.export, args.out)
        print(json.dumps(receipt))
        return 0
    data = json.loads(os.environ.pop("QUALITY_SCALE_RESERVATION"))
    result = run(data, args.out)
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "reservation_id",
                    "batch",
                    "complete",
                    "cleanup_verified",
                    "key_cleanup_verified",
                )
            }
        )
    )
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
