"""Real import/body controls for maintained experiment bindings; no trial runs."""
from __future__ import annotations

import importlib
import json
import sys
import uuid
import warnings

import pytest
import yaml

from eval.quality import experiments


@pytest.fixture
def operator_case(tmp_path, monkeypatch):
    """Place real isolated Python operators on the existing package search path."""
    import eval.quality

    repo = tmp_path / "repo"
    package = repo / "eval/quality"
    package.mkdir(parents=True)
    root = tmp_path / "attempt"
    (root / "evidence").mkdir(parents=True)
    monkeypatch.setenv("ATTOCODE_EXPERIMENT_ENGINE", str(experiments.ENGINE))
    monkeypatch.setattr(experiments, "REPO", repo)
    monkeypatch.setattr(eval.quality, "__path__", [str(package), *eval.quality.__path__])
    modules = []

    def make(source, *, alias=False, registered=True, shadow=False):
        name = "dispatch_test_" + uuid.uuid4().hex
        stem = name + ("_bound" if alias else "_experiment")
        module = "eval.quality." + stem
        path = package / (stem + ".py")
        if shadow:
            other = tmp_path / "shadow"
            other.mkdir()
            monkeypatch.setattr(eval.quality, "__path__", [str(other), str(package), *eval.quality.__path__])
            path.write_text("def run(root):\n    raise AssertionError('declared source must not execute')\n")
            path = other / path.name
        if source is not None:
            path.write_text(source)
        bindings = dict(getattr(experiments, "OPERATORS", {}))
        if registered:
            bindings[name] = module
        monkeypatch.setattr(experiments, "OPERATORS", bindings, raising=False)
        modules.append(module)
        importlib.invalidate_caches()
        return name, root, path

    yield make
    for module in modules:
        sys.modules.pop(module, None)
    importlib.invalidate_caches()


GOOD = "def run(root):\n    (root / 'body-ran').write_text(str(root))\n"


def rejection(name, root):
    error = None
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="coroutine .* was never awaited", category=RuntimeWarning)
        try:
            experiments.payload(name, root)
        except Exception as caught:
            error = caught
    assert isinstance(error, ValueError), "dispatcher binding guard: invalid handler not explicitly rejected"
    assert not (root / "body-ran").exists()
    assert not (root / "evidence/controller-complete.json").exists()
    return error


def test_explicit_alias_uses_registered_module(operator_case):
    name, root, _ = operator_case(GOOD, alias=True)
    error = None
    try:
        experiments.payload(name, root)
    except Exception as caught:
        error = caught
    assert error is None, "dispatcher binding guard: registered alias was guessed from its name"
    assert (root / "body-ran").read_text() == str(root)
    assert json.loads((root / "evidence/controller-complete.json").read_text())["complete"] is True


def test_unregistered_conventional_module_never_runs(operator_case):
    name, root, _ = operator_case(GOOD, registered=False)
    rejection(name, root)


@pytest.mark.parametrize("source", [
    "answer = 42\n",
    "run = 42\n",
    "def run():\n    raise AssertionError('body')\n",
    "def run(root, required):\n    (root / 'body-ran').touch()\n",
    "def run(root, *, required):\n    (root / 'body-ran').touch()\n",
    "async def run(root):\n    (root / 'body-ran').touch()\n",
    "class Runner:\n    async def __call__(self, root):\n        (root / 'body-ran').touch()\nrun = Runner()\n",
], ids=["missing", "noncallable", "no-root", "extra-required", "keyword-required", "async", "async-callable"])
def test_invalid_entrypoint_rejected_before_body(operator_case, source):
    name, root, _ = operator_case(source)
    rejection(name, root)


def test_missing_module_is_explicit_binding_error(operator_case):
    name, root, _ = operator_case(None)
    error = rejection(name, root)
    assert isinstance(error.__cause__, ModuleNotFoundError)


def test_import_error_keeps_original_cause(operator_case):
    name, root, _ = operator_case("raise RuntimeError('retained import trigger')\n")
    error = rejection(name, root)
    assert isinstance(error.__cause__, RuntimeError)
    assert str(error.__cause__) == "retained import trigger"


def test_shadow_module_cannot_execute_body(operator_case):
    name, root, _ = operator_case(GOOD, shadow=True)
    rejection(name, root)


@pytest.mark.parametrize("source", [
    GOOD,
    "def run(root, /):\n    (root / 'body-ran').write_text(str(root))\n",
    "def run(root, option=42):\n    assert option == 42\n    (root / 'body-ran').write_text(str(root))\n",
], ids=["ordinary", "positional-only", "optional"])
def test_compatible_root_entrypoint_runs(operator_case, source):
    name, root, _ = operator_case(source)
    experiments.payload(name, root)
    assert (root / "body-ran").read_text() == str(root)


@pytest.mark.parametrize("name", ["native", "preview", "restart"])
def test_maintained_operator_qualifies_without_running(name):
    loader = getattr(experiments, "load_operator", None)
    assert callable(loader), "dispatcher binding guard: maintained qualification is missing"
    operator = loader(name)
    assert callable(operator)
    assert operator.__module__ == "eval.quality." + name + "_experiment"


@pytest.mark.parametrize("name", ["preflight", "broad"])
def test_inline_handler_qualification_needs_no_operator(name):
    loader = getattr(experiments, "load_operator", None)
    assert callable(loader), "dispatcher binding guard: maintained qualification is missing"
    assert loader(name) is None


def test_workflow_choices_and_registered_targets_qualify():
    registry = getattr(experiments, "OPERATORS", None)
    assert registry is not None, "dispatcher binding guard: explicit bindings are missing"
    workflow = yaml.safe_load((experiments.REPO / ".github/workflows/intelligence-experiments.yml").read_text())
    trigger = workflow.get("on", workflow.get(True))
    choices = trigger["workflow_dispatch"]["inputs"]["experiment"]["options"]
    assert len(choices) == len(set(choices))
    assert set(choices) == set(experiments.SECONDS) == {"preflight", "broad", *registry}
    for name in registry:
        assert callable(experiments.load_operator(name))


def test_engine_guard_precedes_operator_import(operator_case, monkeypatch):
    name, root, path = operator_case(GOOD)
    marker = root / "import-ran"
    path.write_text("from pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\n" + GOOD)
    monkeypatch.setenv("ATTOCODE_EXPERIMENT_ENGINE", str(root / "wrong-engine"))
    with pytest.raises(ValueError, match="engine_origin"):
        experiments.payload(name, root)
    assert not marker.exists()
    assert not (root / "body-ran").exists()
