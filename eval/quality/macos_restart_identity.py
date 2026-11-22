"""Bind the macOS diagnostic to the actual published wheel; runner only."""
from __future__ import annotations
import hashlib
import importlib.metadata
import io
import json
import os
import platform
import subprocess
import sys
import tarfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path

VERSION = "0.1.39"
RELEASE = "ed74f9a6f2190186e2e59a4435860ed7a4a9fd7d"
WHEEL = "attocode_code_intel-0.1.39-py3-none-any.whl"
DIGEST = "0deaaa567853cbc48964ea69dc79b4996a60e37aa1c245b68580861f1cb58f53"
TESTS = [
    "packages/code-intel/tests/test_trigram_restart_freshness.py",
    *[f"packages/code-intel/tests/test_trigram_freshness{x}.py" for x in ("", "_scope", "_edges", "_modes")],
    "packages/code-intel/tests/test_trigram_workspace.py",
    "packages/code-intel/tests/unit/integrations/context/test_trigram_index.py",
    "packages/code-intel/tests/unit/code_intel/test_search_tools.py",
    "packages/code-intel/tests/test_keyword_prefilter_soundness.py",
]
sha = lambda b: hashlib.sha256(b).hexdigest()
git = lambda *a: subprocess.check_output(["git", *a])
def save(out, name, data):
    (out / name).write_text(json.dumps(data, indent=2) + "\n")
def source_files():
    prefix = "packages/code-intel/src/"
    with tarfile.open(fileobj=io.BytesIO(git("archive", RELEASE, prefix + "attocode_intel"))) as z:
        return {m.name.removeprefix(prefix): z.extractfile(m).read()
                for m in z.getmembers() if m.isfile() and m.name.endswith(".py")}
def main(mode, out):
    out.mkdir(parents=True, exist_ok=True)
    assert sys.platform == "darwin"
    assert sys.version_info[:2] == (3, 12)
    assert git("rev-parse", "HEAD^").decode().strip() == RELEASE
    assert not git("diff", "HEAD", "--")
    backend = {"platform": sys.platform, "macos": platform.mac_ver()[0],
               "machine": platform.machine(), "python": platform.python_version(),
               "runner_os": os.environ.get("RUNNER_OS"), "image_os": os.environ.get("ImageOS"),
               "image_version": os.environ.get("ImageVersion"),
               "diagnostic_head": git("rev-parse", "HEAD").decode().strip(),
               "diagnostic_tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
               "released_commit": RELEASE, "release_tree": git("rev-parse", RELEASE + "^{tree}").decode().strip()}
    save(out, "backend.json", backend)
    expected = source_files()
    assert len(expected) == 274
    if mode == "download":
        req = urllib.request.Request("https://pypi.org/pypi/attocode-code-intel/0.1.39/json",
                                     headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read()
            save(out, "pypi-response.json", {"status": r.status, "headers": dict(r.headers), "sha256": sha(raw)})
        (out / "pypi.json").write_bytes(raw)
        meta = json.loads(raw)
        assert meta["info"]["version"] == VERSION
        choices = [v for v in meta["urls"] if v["filename"] == WHEEL]
        assert len(choices) == 1
        a = choices[0]
        assert not a["yanked"] and a["digests"]["sha256"] == DIGEST and a["size"] == 977309
        assert a["url"].startswith("https://files.pythonhosted.org/")
        with urllib.request.urlopen(a["url"], timeout=45) as r:
            body = r.read()
        (out / WHEEL).write_bytes(body)
        assert len(body) == a["size"] and sha(body) == DIGEST
    else:
        body = (out / WHEEL).read_bytes()
        assert sha(body) == DIGEST and len(body) == 977309
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        assert z.testzip() is None
        wheel = {n: z.read(n) for n in z.namelist() if n.startswith("attocode_intel/") and n.endswith(".py")}
    assert wheel == expected
    if mode == "download":
        save(out, "wheel-input.json", {"version": VERSION, "sha256": sha(body), "bytes": len(body),
                                      "python_files_exact_release": len(wheel)})
        return
    import attocode_intel
    d = importlib.metadata.distribution("attocode-code-intel")
    module = Path(attocode_intel.__file__).resolve()
    assert attocode_intel.__version__ == d.version == VERSION
    assert module.is_relative_to(Path(sys.prefix).resolve()) and "site-packages" in module.parts
    actual = {str(f): Path(d.locate_file(f)).read_bytes() for f in d.files
              if str(f).startswith("attocode_intel/") and str(f).endswith(".py")}
    assert actual == expected == wheel
    lock = tomllib.loads(Path("uv.lock").read_text())
    testdeps = {p["name"]: p["version"] for p in lock["package"]
                if p["name"] in {"pytest", "pytest-asyncio", "pytest-mock", "pytest-cov", "coverage"}}
    assert all(importlib.metadata.version(n) == v for n, v in testdeps.items())
    tests = {p: sha(Path(p).read_bytes()) for p in TESTS}
    assert all(Path(p).read_bytes() == git("show", RELEASE + ":" + p) for p in TESTS)
    save(out, "installed-" + mode + ".json",
         {"version": d.version, "module": str(module), "prefix": sys.prefix,
          "python_hashes": {n: sha(b) for n, b in actual.items()}, "test_files": tests,
          "test_dependencies": testdeps, "tracked_source_unchanged": True})
    print(json.dumps({"mode": mode, "installed_version": d.version, "python_files": len(actual),
                      "installed_from_public_wheel": True}), flush=True)
if __name__ == "__main__":
    assert sys.argv[1] in {"download", "before", "after"}
    main(sys.argv[1], Path(sys.argv[2]))
