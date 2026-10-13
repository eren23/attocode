"""Isolated SWE-bench preparation/grading worker; no model or agent imports."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import time
import tomllib
import uuid
from pathlib import Path

from repair_grading import (
    DATASET_SHA256,
    EVALUATOR_REVISION,
    TEST_EXIT_MARKER,
    cached_grade,
    digest,
    file_hash,
    source_digest,
    strict_script,
    test_list,
    verdict,
    write_json,
)

LOGGER = logging.getLogger("repair")
TIMEOUT = 1800


def evaluator_identity():
    import importlib.metadata

    dist = importlib.metadata.distribution("swebench")
    direct = json.loads(dist.read_text("direct_url.json") or "{}")
    revision = direct.get("vcs_info", {}).get("commit_id")
    if revision != EVALUATOR_REVISION:
        raise ValueError("The evaluator must be installed from the pinned SWE-bench commit")
    return {"revision": revision, "version": dist.version,
            "packages": sorted([d.metadata.get("Name", ""), d.version]
                               for d in importlib.metadata.distributions())}


def docker_client():
    import docker

    return docker.from_env(timeout=TIMEOUT)


def spec_for(task):
    from swebench.harness.test_spec.test_spec import make_test_spec

    return make_test_spec(task, arch="x86_64")


def put_file(container, path, content):
    data = content.encode() if isinstance(content, str) else content
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        entry = tarfile.TarInfo(Path(path).name)
        entry.size, entry.mode = len(data), 0o600
        archive.addfile(entry, io.BytesIO(data))
    container.put_archive(str(Path(path).parent), buffer.getvalue())


def checked(container, argv, *, workdir="/testbed"):
    result = container.exec_run(argv, workdir=workdir)
    if result.exit_code:
        raise RuntimeError(f"Command failed ({result.exit_code}): {argv!r}\n{result.output.decode(errors='replace')[-3000:]}")
    return result.output


def container_for(client, image, *, mount=None, preparation=False):
    kwargs = {"image": image, "command": ["sleep", "infinity"],
              "name": "attocode-r7-" + uuid.uuid4().hex[:12], "detach": True,
              "platform": "linux/amd64", "network_mode": "bridge" if preparation else "none", "nano_cpus": 2_000_000_000,
              "mem_limit": "4g", "pids_limit": 512, "working_dir": "/testbed"}
    if mount is not None:
        kwargs["volumes"] = {str(Path(mount).resolve()): {"bind": "/testbed", "mode": "rw"}}
    return client.containers.run(**kwargs)


def apply_patch(container, text, label):
    if not text:
        return
    path = "/tmp/attocode-" + label + ".patch"
    put_file(container, path, text)
    checked(container, ["git", "apply", "--check", path])
    checked(container, ["git", "apply", path])


def evaluate(task, image, patch, destination, *, source=None):
    """Fresh verifier; an optional disposable source copy verifies the agent runtime."""
    from swebench.harness.constants import END_TEST_OUTPUT, START_TEST_OUTPUT
    from swebench.harness.docker_utils import exec_run_with_timeout
    from swebench.harness.grading import get_logs_eval
    from swebench.harness.utils import get_modified_files

    identity = {"task": digest(task), "image": image, "patch": hashlib.sha256(patch.encode()).hexdigest(),
                "evaluator": evaluator_identity(), "worker": file_hash(__file__),
                "grading": file_hash(Path(__file__).with_name("repair_grading.py")),
                "source": source_digest(source) if source else None}
    destination = Path(destination)
    result_path = destination / "acceptance.json"
    cached = cached_grade(result_path, identity)
    if cached is not None:
        return cached
    destination.mkdir(parents=True, exist_ok=True)
    spec = spec_for(task)
    script = strict_script(spec.eval_script_list, START_TEST_OUTPUT, END_TEST_OUTPUT,
                           snapshot_base=task["base_commit"] if source else None)
    (destination / "eval.sh").write_text(script)
    (destination / "patch.diff").write_text(patch)
    client, container, temporary = docker_client(), None, None
    started = time.monotonic()
    result = {"identity": identity, "resolved": False, "status": "infrastructure_error"}
    try:
        reset_base = task["base_commit"]
        mount = None
        if source:
            temporary = tempfile.TemporaryDirectory(prefix="source-control-", dir=destination)
            mount = Path(temporary.name) / "repository"
            shutil.copytree(source, mount, symlinks=True, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".pytest_cache"))
            initialize_source(mount)
            reset_base = "HEAD"
        container = container_for(client, image, mount=mount)
        checked(container, ["git", "config", "--global", "--add", "safe.directory", "/testbed"])
        # Candidate edits to official tests are discarded before the trusted patch.
        try:
            apply_patch(container, patch, "submission")
            for name in get_modified_files(task["test_patch"]):
                if Path(name).is_absolute() or ".." in Path(name).parts:
                    raise ValueError("Invalid official test path")
                exists = container.exec_run(["git", "cat-file", "-e", reset_base + ":" + name],
                                            workdir="/testbed").exit_code == 0
                if exists:
                    checked(container, ["git", "checkout", reset_base, "--", name])
                else:
                    checked(container, ["rm", "-f", "--", name])
            apply_patch(container, task["test_patch"], "tests")
        except (RuntimeError, ValueError) as exc:
            result.update(status="invalid_patch", error=str(exc))
            return result
        put_file(container, "/tmp/attocode-eval.sh", script)
        # Upstream's executor decodes UTF-8 strictly; preserve arbitrary test output first.
        _, timed_out, seconds = exec_run_with_timeout(
            container, "bash -c 'bash /tmp/attocode-eval.sh > /tmp/attocode-test-output 2>&1'", TIMEOUT)
        raw_output = checked(container, ["cat", "/tmp/attocode-test-output"])
        (destination / "test_output.raw").write_bytes(raw_output)
        output = raw_output.decode(errors="replace")
        log = destination / "test_output.txt"
        log.write_text(output)
        statuses, found = get_logs_eval(spec, str(log))
        matches = re.findall(r"^" + TEST_EXIT_MARKER + r"=(-?\d+)$", output, re.M)
        code = int(matches[0]) if len(matches) == 1 else None
        result.update(verdict(task["FAIL_TO_PASS"], task["PASS_TO_PASS"], statuses,
                              exit_code=code, timed_out=timed_out, executed=bool(found and code is not None)))
        result.update(status="graded", seconds=seconds, script_sha256=file_hash(destination / "eval.sh"))
        return result
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    finally:
        if container:
            container.remove(force=True)
        if temporary:
            temporary.cleanup()
        client.close()
        result["elapsed_seconds"] = time.monotonic() - started
        write_json(result_path, result)


def ensure_image(client, task):
    from swebench.harness.docker_build import build_instance_image
    from swebench.harness.test_spec.test_spec import make_test_spec

    import docker

    remote = make_test_spec(task, namespace="swebench", arch="x86_64")
    try:
        image = client.images.get(remote.instance_image_key)
    except docker.errors.ImageNotFound:
        try:
            print(json.dumps({"pulling": remote.instance_image_key}), flush=True)
            image = client.images.pull(remote.instance_image_key, platform="linux/amd64")
        except docker.errors.NotFound:
            spec = spec_for(task)
            print(json.dumps({"building": spec.instance_image_key}), flush=True)
            build_instance_image(spec, client, LOGGER, nocache=False)
            image = client.images.get(spec.instance_image_key)
    if image.attrs.get("Architecture") != "amd64":
        raise ValueError("Expected a Linux amd64 image")
    return prepare_offline_image(client, image)


def prepare_offline_image(client, image):
    """Cache PEP-517 build wheels before timed/offline execution, without changing source."""
    recipe = digest({"base": image.id, "build_wheels": 1})
    cached = client.images.list(filters={"label": "attocode.r7.recipe=" + recipe})
    if cached:
        return cached[0].id
    container = container_for(client, image.id, preparation=True)
    try:
        read = container.exec_run(["cat", "/testbed/pyproject.toml"])
        config = tomllib.loads(read.output.decode()) if read.exit_code == 0 else {}
        requirements = config.get("build-system", {}).get("requires", ["setuptools", "wheel"])
        from packaging.requirements import Requirement
        pinned = []
        prelude = "source /opt/miniconda3/bin/activate && conda activate testbed && "
        for value in requirements:
            requirement = Requirement(value)
            info = container.exec_run(["bash", "-c", prelude + "python -m pip show " + shlex.quote(requirement.name)])
            match = re.search(rb"^Version: (.+)$", info.output, re.M)
            if match and match[1].decode() in requirement.specifier and not requirement.extras:
                pinned.append(requirement.name + "==" + match[1].decode())
            else:
                pinned.append(value)
        print(json.dumps({"preparing_offline_wheels": image.id, "requirements": pinned}), flush=True)
        checked(container, ["bash", "-c", prelude + "python -m pip download --dest /opt/attocode-wheelhouse " + shlex.join(pinned)])
        env = [e for e in image.attrs.get("Config", {}).get("Env", [])
               if not e.startswith(("PIP_NO_INDEX=", "PIP_FIND_LINKS="))]
        labels = {**(image.attrs.get("Config", {}).get("Labels", {}) or {}),
                  "attocode.r7.recipe": recipe, "attocode.r7.base": image.id}
        prepared = container.commit(conf={"Env": [*env, "PIP_NO_INDEX=1", "PIP_FIND_LINKS=/opt/attocode-wheelhouse"],
                                          "Labels": labels})
        return prepared.id
    finally:
        container.remove(force=True)


def snapshot(client, image, task, target):
    if target.exists():
        raise ValueError("Never overwrite a source snapshot")
    container = container_for(client, image)
    try:
        # Bind-mounting git archive alone hides compiled extensions installed in /testbed.
        # Preserve the prepared working tree, but never its upstream Git history.
        archive = checked(container, ["tar", "--exclude=.git", "--exclude=__pycache__", "--exclude=*.pyc",
                                      "--exclude=.pytest_cache", "-cf", "-", "."])
        target.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
            stream.extractall(target, filter="data")
        patterns = (".claude", "AGENTS*.md", "CLAUDE*.md", ".mcp.json", ".codex/config.toml")
        for pattern in patterns:
            if next(target.rglob(pattern), None):
                raise ValueError("Snapshot contains competing agent guidance: " + pattern)
        initialize_source(target)
    finally:
        container.remove(force=True)


def initialize_source(target):
    for argv in (["git", "init", "-q"], ["git", "add", "-A"],
                 ["git", "-c", "user.name=Benchmark", "-c", "user.email=benchmark@localhost",
                  "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                  "commit", "-qm", "Frozen repair input"]):
        subprocess.run(argv, cwd=target, check=True, capture_output=True)


def finalize_pack(input_pack, pack):
    """Retain the deterministic selection, refresh snapshots and check mounted execution."""
    input_pack, pack = Path(input_pack).resolve(), Path(pack).resolve()
    if pack.exists() or pack.is_relative_to(Path(__file__).resolve().parents[3]):
        raise ValueError("Use a new external pack")
    manifest = json.loads((input_pack / "pack.json").read_text())
    if manifest["evaluator"] != evaluator_identity():
        raise ValueError("Evaluator drift")
    shutil.copytree(input_pack, pack, ignore=shutil.ignore_patterns("sources"))
    (pack / "pack.json").unlink()
    client = docker_client()
    try:
        for task in manifest["tasks"]:
            raw = json.loads((pack / task["task_file"]).read_text())
            source = pack / "sources" / task["id"]
            snapshot(client, task["image"], raw, source)
            controls = pack / "mounted-controls" / task["id"]
            base = evaluate(raw, task["image"], "", controls / "base", source=source)
            gold = evaluate(raw, task["image"], raw["patch"], controls / "gold", source=source)
            if not preparation_control(base, gold, raw):
                raise ValueError("Mounted runtime controls failed: " + task["id"])
            task["source_sha256"] = source_digest(source)
            print(json.dumps({"mounted_control": task["id"], "passed": True}), flush=True)
    finally:
        client.close()
    manifest["snapshot"] = "Prepared working tree including build artifacts, without Git history"
    write_json(pack / "pack.json", manifest)


def preparation_control(base, gold, task):
    f2p, p2p = test_list(task["FAIL_TO_PASS"]), test_list(task["PASS_TO_PASS"])
    failed = {"FAILED", "ERROR"}
    return (base.get("status") == gold.get("status") == "graded"
            and base.get("executed") and not base.get("timed_out")
            and all(base["statuses"].get(t) in failed for t in f2p)
            and all(base["statuses"].get(t) == "PASSED" for t in p2p)
            and gold.get("resolved") is True)


def prepare_pack(dataset, pack):
    import pyarrow.parquet as pq

    dataset, pack = Path(dataset).resolve(), Path(pack).resolve()
    if pack.is_relative_to(Path(__file__).resolve().parents[3]):
        raise ValueError("Private benchmark inputs must be outside the repository")
    if file_hash(dataset) != DATASET_SHA256:
        raise ValueError("Pinned raw dataset checksum mismatch")
    evaluator = evaluator_identity()
    preparation = {"version": 2, "worker_sha256": file_hash(__file__),
                   "grading_sha256": file_hash(Path(__file__).with_name("repair_grading.py"))}
    pack.mkdir(parents=True, exist_ok=True)
    manifest_path = pack / "pack.json"
    state_path = pack / "preparation.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        "dataset_sha256": DATASET_SHA256, "evaluator": evaluator, "preparation": preparation,
        "candidates": {}, "selected": []}
    if (state["evaluator"] != evaluator or state["dataset_sha256"] != DATASET_SHA256
            or state.get("preparation") != preparation):
        raise ValueError("Preparation environment drift; use a new pack")
    write_json(state_path, state)
    for name in ("repair_worker.py", "repair_grading.py"):
        tooling = pack / "tooling" / name
        tooling.parent.mkdir(exist_ok=True)
        if not tooling.exists():
            shutil.copy2(Path(__file__).with_name(name), tooling)
        if file_hash(tooling) != preparation["worker_sha256" if name == "repair_worker.py" else "grading_sha256"]:
            raise ValueError("Preparation tooling changed")
    if manifest_path.exists():
        print(json.dumps({"pack": str(pack), "ready": True}), flush=True)
        return
    rows = pq.read_table(dataset).to_pylist()
    required = {"instance_id", "repo", "base_commit", "problem_statement", "patch", "test_patch",
                "FAIL_TO_PASS", "PASS_TO_PASS", "version"}
    if not rows or not required <= rows[0].keys():
        raise ValueError("Raw dataset lacks repair metadata")
    repos = sorted({r["repo"] for r in rows}, key=lambda r: hashlib.sha256(r.encode()).hexdigest())
    client = docker_client()
    try:
        for repo in repos:
            if len(state["selected"]) == 8:
                break
            if any(t["repo"] == repo for t in state["selected"]):
                continue
            candidates = sorted((r for r in rows if r["repo"] == repo),
                                key=lambda r: hashlib.sha256(r["instance_id"].encode()).hexdigest())
            for task in candidates:
                if shutil.disk_usage(pack).free < 30 * 1024**3:
                    raise RuntimeError("Preparation stopped to retain 30 GiB free disk; no task was excluded for this")
                name = task["instance_id"]
                if name in state["candidates"]:
                    continue
                if not re.fullmatch(r"[\w.-]+", name):
                    raise ValueError("Invalid instance ID")
                print(json.dumps({"preparing": name, "selected": len(state["selected"])}), flush=True)
                candidate = {"repo": repo, "status": "excluded"}
                directory = pack / "candidates" / name
                write_json(directory / "task.json", task)
                try:
                    test_list(task["FAIL_TO_PASS"])
                    test_list(task["PASS_TO_PASS"])
                    if not task["patch"] or not task["test_patch"]:
                        raise ValueError("Both code and test patches are required")
                    image = ensure_image(client, task)
                    source = pack / "sources" / name
                    if not source.exists():
                        snapshot(client, image, task, source)
                    base = evaluate(task, image, "", directory / "base")
                    gold = evaluate(task, image, task["patch"], directory / "gold")
                    if not preparation_control(base, gold, task):
                        raise ValueError("Base/gold execution controls failed")
                    mounted_base = evaluate(task, image, "", directory / "mounted-base", source=source)
                    mounted_gold = evaluate(task, image, task["patch"], directory / "mounted-gold", source=source)
                    if not preparation_control(mounted_base, mounted_gold, task):
                        raise ValueError("Mounted base/gold execution controls failed")
                    corrupted = dict(gold["statuses"])
                    corrupted[test_list(task["PASS_TO_PASS"])[0]] = "FAILED"
                    regression = verdict(task["FAIL_TO_PASS"], task["PASS_TO_PASS"], corrupted, exit_code=0)
                    if regression["resolved"]:
                        raise ValueError("Regression control incorrectly passed")
                    write_json(directory / "regression-control.json", regression)
                    chosen = {"id": name, "repo": repo, "image": image, "platform": "linux/amd64",
                              "workdir": "/testbed", "runtime_prelude": "source /opt/miniconda3/bin/activate && conda activate testbed && ",
                              "prompt": task["problem_statement"], "task_file": f"candidates/{name}/task.json",
                              "source_sha256": source_digest(source),
                              "task_sha256": file_hash(directory / "task.json"), "timeout": 600}
                    state["selected"].append(chosen)
                    candidate.update(status="ready", image=image)
                except Exception as exc:
                    candidate["reason"] = f"{type(exc).__name__}: {exc}"
                state["candidates"][name] = candidate
                write_json(state_path, state)
                print(json.dumps({"task": name, **candidate}), flush=True)
                if candidate["status"] == "ready":
                    break
    finally:
        client.close()
    if len(state["selected"]) != 8:
        raise ValueError("Fewer than eight repositories qualified; do not start model runs")
    write_json(manifest_path, {"version": 1, "kind": "repair", "dataset_sha256": DATASET_SHA256,
                               "dataset_rows": len(rows), "evaluator": evaluator, "preparation": preparation,
                               "tasks": state["selected"],
                               "limits": {"cpus": 2, "memory": "4g", "grading_timeout": TIMEOUT},
                               "selection": "SHA-256(repo), then SHA-256(instance_id); preparation controls only"})
    print(json.dumps({"pack": str(pack), "ready": True, "tasks": 8}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare-pack")
    prep.add_argument("--dataset", required=True, type=Path)
    prep.add_argument("--pack", required=True, type=Path)
    final = commands.add_parser("finalize-pack")
    final.add_argument("--input-pack", required=True, type=Path)
    final.add_argument("--pack", required=True, type=Path)
    commands.add_parser("identity")
    grade = commands.add_parser("evaluate")
    grade.add_argument("--task", required=True, type=Path)
    grade.add_argument("--image", required=True)
    grade.add_argument("--patch", required=True, type=Path)
    grade.add_argument("--output", required=True, type=Path)
    grade.add_argument("--source", type=Path)
    args = parser.parse_args()
    if args.command == "identity":
        print(json.dumps(evaluator_identity()), flush=True)
    elif args.command == "prepare-pack":
        prepare_pack(args.dataset, args.pack)
    elif args.command == "finalize-pack":
        finalize_pack(args.input_pack, args.pack)
    else:
        result = evaluate(json.loads(args.task.read_text()), args.image, args.patch.read_text(), args.output, source=args.source)
        print(json.dumps({k: result.get(k) for k in ("resolved", "status", "error")}), flush=True)


if __name__ == "__main__":
    main()
