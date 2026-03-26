from __future__ import annotations

import asyncio
import re
import shlex
import subprocess
import sys
import textwrap
from types import SimpleNamespace
from typing import TYPE_CHECKING

import yaml

from attoswarm.research.experiment_db import ExperimentDB

if TYPE_CHECKING:
    from pathlib import Path


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def init_repo(repo: Path, files: dict[str, str]) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init")
    for relative_path, content in files.items():
        target = repo / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "init",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return git(repo, "rev-parse", "HEAD")


def commit_all(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            message,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return git(repo, "rev-parse", "HEAD")


def clone_repo(source: Path, target: Path) -> None:
    subprocess.run(
        ["git", "clone", str(source), str(target)],
        check=True,
        capture_output=True,
        text=True,
    )


def write_fake_worker(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            """
            import sys
            from pathlib import Path


            def _append_once(path: Path, line: str) -> bool:
                if not path.exists():
                    return False
                text = path.read_text(encoding="utf-8")
                if line in text:
                    return False
                path.write_text(text + line, encoding="utf-8")
                return True


            def main() -> int:
                prompt = sys.stdin.read()
                lower = prompt.lower()
                cwd = Path.cwd()
                notes: list[str] = []

                target = cwd / "target.txt"
                compose = cwd / "compose.txt"

                if "workspace preparation" in lower and compose.exists():
                    compose_text = compose.read_text(encoding="utf-8")
                    if "imported\\n" not in compose_text:
                        print("compose missing imported patch", flush=True)
                        return 2
                    if "composed\\n" not in compose_text:
                        compose.write_text(compose_text + "composed\\n", encoding="utf-8")
                    notes.append("compose-ready")

                if target.exists():
                    text = target.read_text(encoding="utf-8")
                    if "remove or simplify" in lower or "ablate" in lower:
                        updated = text.replace("feature\\n", "")
                        updated = updated.replace("better\\n", "")
                        if updated != text:
                            target.write_text(updated, encoding="utf-8")
                            notes.append("ablate-applied")
                    elif "better\\n" not in text:
                        target.write_text(text + "better\\n", encoding="utf-8")
                        notes.append("improvement-applied")

                if not notes:
                    notes.append("noop")
                print("\\n".join(notes), flush=True)
                return 0


            raise SystemExit(main())
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def write_metric_evaluator(
    path: Path,
    *,
    target_file: str = "target.txt",
    token: str = "better",
    fail_on_token: str = "",
    artifact_name: str = "artifact.txt",
) -> None:
    path.write_text(
        textwrap.dedent(
            f"""
            import json
            from pathlib import Path

            target = Path({target_file!r})
            text = target.read_text(encoding="utf-8") if target.exists() else ""
            artifact = Path({artifact_name!r})
            artifact.write_text("artifact\\n", encoding="utf-8")
            score = text.count({token!r})
            fail_on_token = {fail_on_token!r}
            constraints = {{
                "artifact_ok": {{"passed": artifact.exists()}},
                "content_ok": {{"passed": not fail_on_token or fail_on_token not in text}},
            }}
            print(json.dumps({{
                "primary_metric": float(score),
                "secondary_metrics": {{"length": len(text.splitlines())}},
                "constraint_checks": constraints,
                "artifacts": [artifact.name],
                "success": True,
            }}))
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def build_eval_command(script_path: Path) -> str:
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(script_path))}"


def write_swarm_config(path: Path, *, working_dir: Path, run_dir: Path, worker_script: Path) -> None:
    config = {
        "version": 1,
        "run": {
            "working_dir": str(working_dir),
            "run_dir": str(run_dir / "swarm"),
            "poll_interval_ms": 50,
            "max_runtime_seconds": 30,
        },
        "roles": [
            {
                "role_id": "researcher",
                "role_type": "worker",
                "backend": "attocode",
                "model": "fake",
                "count": 1,
                "write_access": True,
                "workspace_mode": "shared_ro",
                "task_kinds": ["implement"],
                "command": [sys.executable, str(worker_script)],
            },
        ],
        "budget": {
            "max_tokens": 100_000,
            "max_cost_usd": 10.0,
            "reserve_ratio": 0.1,
            "chars_per_token_fallback": 4.0,
        },
        "merge": {"authority_role": "researcher", "judge_roles": [], "quality_threshold": 0.5},
        "watchdog": {"heartbeat_timeout_seconds": 10},
        "retries": {"max_task_attempts": 1},
    }
    path.write_text(yaml.safe_dump(config), encoding="utf-8")


def run_attoswarm(args: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    merged_env = dict(env or {})
    return subprocess.run(
        [sys.executable, "-m", "attoswarm", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=merged_env or None,
    )


def parse_run_id(output: str) -> str:
    match = re.search(r"Research Run:\s+([a-z0-9-]+)", output)
    if not match:
        raise AssertionError(f"Unable to find run id in output:\n{output}")
    return match.group(1)


def open_store(db_path: Path) -> ExperimentDB:
    return ExperimentDB(db_path)


def make_patch(source_repo: Path, *, relative_path: str, new_content: str, patch_path: Path) -> str:
    patch_repo = patch_path.parent / f"{patch_path.stem}_repo"
    clone_repo(source_repo, patch_repo)
    target = patch_repo / relative_path
    target.write_text(new_content, encoding="utf-8")
    patch_text = git(patch_repo, "diff", "--stat", "--patch")
    patch_path.write_text(patch_text, encoding="utf-8")
    return patch_text


async def spawn_fake_worker(worker_script: Path, task: dict) -> SimpleNamespace:
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(worker_script),
        cwd=task["working_dir"],
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate((task["description"] or "").encode("utf-8"))
    output = (stdout or b"").decode("utf-8", errors="replace").strip()
    error = (stderr or b"").decode("utf-8", errors="replace").strip()
    return SimpleNamespace(
        result_summary=output,
        error=error,
        tokens_used=7,
        cost_usd=0.01,
        success=proc.returncode == 0,
    )
