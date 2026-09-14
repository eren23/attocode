"""Development answer-quality cases with independently authored, source-bound rubrics.

These are finite claim and retrieval judgments, not exhaustive repository truth.
Rubrics are frozen outside the agent's repository. No engine output creates labels.
"""
from __future__ import annotations

import copy
import hashlib
import json
import random
import subprocess


def anchor(path, quote, after=None, span=45):
    if after == "res.json = function json(obj) {":
        span = 25
    return {"path": path, "quote": quote, "after": after, "span": span}


def claim(identity, text, verdict, *anchors):
    # Every group must be covered; alternatives can be added to a group explicitly.
    return {"id": identity, "text": text, "verdict": verdict, "evidence_groups": [[a] for a in anchors]}


E = "lib/response.js"
F = "fastapi/routing.py"
JSON = "res.json = function json(obj) {"
JSONP = "res.jsonp = function jsonp(obj) {"
SERIALIZE = "async def serialize_response("
EPATHS = [E, "lib/application.js", "test/res.json.js", "test/res.jsonp.js", "test/res.send.js", "test/req.get.js"]
FPATHS = [F, "fastapi/encoders.py", "fastapi/exceptions.py", "tests/test_response_by_alias.py",
          "tests/test_validate_response.py", "tests/test_path.py"]


def case(repo, name, question, claims, relevant, *, mutation=None):
    return {"id": f"{repo}:quality_{name}", "repo": repo, "family": "quality", "split": "development",
            "question": question, "claims": claims, "candidate_files": EPATHS if repo == "express" else FPATHS,
            "relevant_files": relevant, "mutation": mutation}


TASKS = [
    case("express", "flow", "Explain the res.json serialization path and content-type behavior. Rank the implementation file and dedicated res.json tests; exclude generic send and JSONP tests.", [
        claim("serialize_then_send", "res.json passes its object through stringify and sends the resulting body.", "supported",
              anchor(E, "var body = stringify(obj, replacer, spaces, escape)", JSON), anchor(E, "return this.send(body);", JSON)),
        claim("always_overwrites_type", "res.json always overwrites an existing Content-Type with application/json.", "contradicted",
              anchor(E, "if (!this.get('Content-Type')) {", JSON)),
        claim("native_stringify", "The helper delegates JSON serialization to JSON.stringify.", "supported",
              anchor(E, "? JSON.stringify(value, replacer, spaces)", "function stringify (value, replacer, spaces, escape) {")),
        claim("deployment_indent", "The unprovided production application's json spaces setting is exactly 2.", "insufficient",
              anchor(E, "var spaces = app.get('json spaces');", JSON)),
    ], [E, "test/res.json.js"]),
    case("express", "impact", "Assess a change to the shared stringify helper's handling of replacer/spaces. Rank the candidate implementation and direct regression-test files for JSON and JSONP serialization.", [
        claim("json_calls_helper", "The res.json path calls the shared stringify helper with replacer and spaces.", "supported",
              anchor(E, "var body = stringify(obj, replacer, spaces, escape)", JSON)),
        claim("jsonp_unaffected", "res.jsonp does not call that helper, so changing it cannot affect JSONP serialization.", "contradicted",
              anchor(E, "var body = stringify(obj, replacer, spaces, escape)", JSONP)),
        claim("both_tested", "Both JSON and JSONP have dedicated tests that configure json spaces.", "supported",
              anchor("test/res.json.js", "app.set('json spaces', 2);"), anchor("test/res.jsonp.js", "app.set('json spaces', 2);")),
        claim("production_traffic", "More than half of the unprovided deployment's requests use JSONP.", "insufficient",
              anchor(E, "var callback = this.req.query[app.get('jsonp callback name')];", JSONP)),
    ], [E, "test/res.json.js", "test/res.jsonp.js"]),
    case("express", "stale", "BENCH_NOTES.md predates a source edit. Reassess JSON indentation and whether JSONP changed too. Rank the implementation and dedicated JSON/JSONP tests needed to distinguish these behaviors.", [
        claim("json_reads_spaces", "The current res.json implementation still reads json spaces from the app.", "contradicted",
              anchor(E, "var spaces = undefined;", JSON)),
        claim("jsonp_reads_spaces", "The current res.jsonp implementation still reads json spaces from the app.", "supported",
              anchor(E, "var spaces = app.get('json spaces');", JSONP)),
        claim("notes_current", "The saved note accurately describes current res.json indentation behavior.", "contradicted",
              anchor(E, "var spaces = undefined;", JSON)),
        claim("who_changed_it", "The unrecorded source edit was made by the production on-call engineer.", "insufficient",
              anchor("BENCH_NOTES.md", "Editor identity and deployment configuration were not recorded.")),
    ], [E, "test/res.json.js", "test/res.jsonp.js"], mutation="json_spaces_only"),
    case("fastapi", "flow", "Explain how get_request_handler handles an endpoint's returned value. Rank candidate implementation and tests specifically for response validation errors and the no-response-field encoding path; exclude alias-configuration tests.", [
        claim("endpoint_first", "The request handler awaits run_endpoint_function to obtain raw_response.", "supported",
              anchor(F, "raw_response = await run_endpoint_function(")),
        claim("response_always_serialized", "Every returned Response instance is passed through serialize_response.", "contradicted",
              anchor(F, "if isinstance(raw_response, Response):"), anchor(F, "response = raw_response")),
        claim("no_field_encoder", "serialize_response uses jsonable_encoder when no response field is supplied.", "supported",
              anchor(F, "return jsonable_encoder(response_content)", SERIALIZE)),
        claim("deployment_latency", "The unprovided deployment's serialization p95 is below one millisecond.", "insufficient",
              anchor(F, "async def serialize_response(")),
    ], [F, "fastapi/encoders.py", "fastapi/exceptions.py", "tests/test_validate_response.py"]),
    case("fastapi", "alias", "Explain response_model_by_alias=False and identify candidate implementation and direct tests for model and dictionary responses.", [
        claim("flag_forwarded", "The handler forwards response_model_by_alias into serialize_response's by_alias argument.", "supported",
              anchor(F, "by_alias=response_model_by_alias,", "content = await serialize_response(")),
        claim("serializer_ignores_flag", "serialize_response ignores its by_alias argument when invoking the field serializer.", "contradicted",
              anchor(F, "by_alias=by_alias,", SERIALIZE)),
        claim("dict_and_model_tests", "The alias test module configures both dictionary and model routes with response_model_by_alias=False.", "supported",
              anchor("tests/test_response_by_alias.py", '@app.get("/dict", response_model=Model, response_model_by_alias=False)'),
              anchor("tests/test_response_by_alias.py", '@app.get("/model", response_model=Model, response_model_by_alias=False)')),
        claim("deployment_preference", "All routes in the unprovided production application disable alias serialization.", "insufficient",
              anchor(F, "by_alias=response_model_by_alias,", "content = await serialize_response(")),
    ], [F, "tests/test_response_by_alias.py"]),
    case("fastapi", "validation", "Explain response-field validation failure and synchronous endpoint execution. Rank candidate files directly implementing or testing response validation errors.", [
        claim("response_error", "Response-field validation errors cause serialize_response to raise ResponseValidationError.", "supported",
              anchor(F, "if errors:", SERIALIZE), anchor(F, "raise ResponseValidationError(", SERIALIZE)),
        claim("request_error", "Those errors instead raise RequestValidationError from serialize_response.", "contradicted",
              anchor(F, "raise ResponseValidationError(", SERIALIZE)),
        claim("sync_threadpool", "run_endpoint_function runs a synchronous endpoint through run_in_threadpool.", "supported",
              anchor(F, "return await run_in_threadpool(dependant.call, **values)", "async def run_endpoint_function(")),
        claim("deployed_handler", "An unprovided deployment has installed a custom handler for ResponseValidationError.", "insufficient",
              anchor(F, "raise ResponseValidationError(", SERIALIZE)),
    ], [F, "fastapi/exceptions.py", "tests/test_validate_response.py"]),
]

# Discovery cases omit source paths and private relevance candidates from prompts.
# Public API vocabulary describes the behavior; implementation symbol names stay private.
D = "fastapi/dependencies/utils.py"
M = "fastapi/dependencies/models.py"
C = "tests/test_dependency_cache.py"
DISCOVERY = case("fastapi", "dependency_discovery", (
    "Investigate why a counter used by nested dependencies may run once or more than once during a request, "
    "and why security scopes can change reuse. Trace the public caching option through dependency construction "
    "and execution, explain cache reads versus writes and request boundaries, and locate dedicated regression tests. "
    "Rank the Python implementation and dedicated test files directly establishing these behaviors."
), [
    claim("option_flow", "The public dependency caching option reaches the dependency graph and controls reuse during execution.", "supported",
          anchor("fastapi/param_functions.py", "return params.Depends(dependency=dependency, use_cache=use_cache, scope=scope)"),
          anchor("fastapi/params.py", "use_cache: bool = True", "class Depends:"),
          anchor(D, "use_cache=param_details.depends.use_cache,"),
          anchor(D, "if sub_dependant.use_cache and sub_dependant.cache_key in dependency_cache:")),
    claim("read_and_write_disabled", "Disabling caching on a dependency prevents both reading an existing cached value and storing its newly computed value.", "contradicted",
          anchor(D, "if sub_dependant.use_cache and sub_dependant.cache_key in dependency_cache:"),
          anchor(D, "if sub_dependant.cache_key not in dependency_cache:"),
          anchor(D, "dependency_cache[sub_dependant.cache_key] = solved")),
    claim("scope_independent", "Two security dependencies using the same callable necessarily share a cached value even when their declared scopes differ.", "contradicted",
          anchor(M, "tuple(sorted(set(self.oauth_scopes or []))) if self._uses_scopes else ()"),
          anchor(M, "scopes_for_cache,", "def cache_key(self) -> DependencyCacheKey:"),
          anchor(C, 'assert response.json() == {"counter": 1, "scope_counter_1": 2, "scope_counter_2": 2}')),
    claim("request_boundary", "The dedicated counter tests demonstrate reuse within a request and recomputation on the next request, consistent with a new cache for a top-level resolution.", "supported",
          anchor(D, "if dependency_cache is None:"), anchor(D, "dependency_cache = {}"),
          anchor(C, 'assert response.json() == {"counter": 1, "subcounter": 1}'),
          anchor(C, 'assert response.json() == {"counter": 2, "subcounter": 2}')),
], ["fastapi/param_functions.py", "fastapi/params.py", D, M, C])
DISCOVERY.update(discovery=True, candidate_files=[
    "fastapi/param_functions.py", "fastapi/params.py", D, M, C,
    "fastapi/encoders.py", "fastapi/exceptions.py", "fastapi/openapi/utils.py",
    "tests/test_response_by_alias.py", "tests/test_validate_response.py", "tests/test_path.py",
])
TASKS.append(DISCOVERY)


def source_files(root, task):
    """Pin source independently of relevance so discovery can cite unjudged Python files."""
    files = set(task["candidate_files"])
    if task.get("discovery"):
        files.update(p.relative_to(root).as_posix() for directory in ("fastapi", "tests")
                     for p in (root / directory).rglob("*.py"))
    return sorted(files)


def materialize(root, task):
    """Apply a specified counterfactual to an isolated copy, never the original clone."""
    if task.get("mutation") == "json_spaces_only":
        path = root / E
        text = path.read_text()
        old = "var spaces = app.get('json spaces');"
        if text.count(old) != 2:
            raise ValueError("Expected separate JSON and JSONP settings before mutation")
        path.write_text(text.replace(old, "var spaces = undefined;", 1))
        (root / "BENCH_NOTES.md").write_text(
            "Old observation: res.json reads json spaces from the app and honors indentation.\n"
            "Editor identity and deployment configuration were not recorded.\n")
    elif task.get("mutation") is not None:
        raise ValueError("Unknown quality mutation")


def compile_task(root, task):
    """Reject drifting or ambiguous evidence, and pin all judged candidate files."""
    result = copy.deepcopy(task)
    if (not task["claims"] or len({c["id"] for c in task["claims"]}) != len(task["claims"])
            or not task["relevant_files"] or len(set(task["candidate_files"])) != len(task["candidate_files"])
            or any(c["verdict"] not in {"supported", "contradicted", "insufficient"}
                   or not c["evidence_groups"] or not all(c["evidence_groups"]) for c in task["claims"])):
        raise ValueError("Incomplete or duplicate quality judgments")
    result["file_hashes"] = {}
    for path in [*source_files(root, task), *(a["path"] for c in task["claims"] for g in c["evidence_groups"] for a in g)]:
        resolved = (root / path).resolve()
        if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
            raise ValueError(f"Missing or escaping rubric source: {path}")
        result["file_hashes"][path] = hashlib.sha256(resolved.read_bytes()).hexdigest()
    for c in result["claims"]:
        for group in c["evidence_groups"]:
            for a in group:
                lines = (root / a["path"]).read_text().splitlines()
                start, stop = 0, len(lines)
                if a["after"]:
                    starts = [i for i, line in enumerate(lines) if line.strip() == a["after"]]
                    if len(starts) != 1:
                        raise ValueError(f"Ambiguous rubric scope: {a}")
                    start, stop = starts[0], starts[0] + a["span"]
                matches = [i + 1 for i, line in enumerate(lines) if start <= i < stop and line.strip() == a["quote"]]
                if len(matches) != 1:
                    raise ValueError(f"Missing or ambiguous rubric anchor: {a}")
                a["line"] = matches[0]
    if not set(task["relevant_files"]).issubset(task["candidate_files"]):
        raise ValueError("Every ranked relevance judgment must be inside the candidate pool")
    return result


def prompt(task):
    from quality_scoring import ANSWER_SCHEMA
    public = {"question": task["question"], "claims": [{"id": c["id"], "text": c["text"]} for c in task["claims"]],
              "answer_schema": ANSWER_SCHEMA}
    if task.get("discovery"):
        ranking = ("Discover the relevant files yourself. Cite Python implementation and test source. "
                   "Rank the files directly supporting the requested behavior, best first; omit general background files. ")
    else:
        public["candidate_files"] = sorted(task["candidate_files"])
        ranking = "Rank only the relevant files from the candidate pool, best first; omit unrelated candidates. "
    random.Random(task["id"]).shuffle(public["claims"])
    return ("Analyze this repository using available native and connected tools when useful. "
            "For each supplied claim, return supported, contradicted, or insufficient. Insufficient means the supplied "
            "repository does not determine the claim, not that you chose not to investigate. Cite exact source excerpts "
            "(repository-relative path, 1-based starting line, quote of at most 12 contiguous lines) establishing the conclusion or the information boundary. "
            "Use multiple citations when a claim spans steps or files. Confidence is your probability (0 to 1) that your selected verdict is correct. "
            + ranking + "Explain the reasoning briefly for each claim and in a summary. "
            "Deployment configuration, traffic, identity, and latency data are not supplied. "
            "Do not edit files, delegate, install packages, use the network, read outside this repository, or change client settings. "
            "Do not name your model or tool provider in the answer. Return the requested JSON schema.\n" + json.dumps(public))


def verify_counterfactual(root):
    """Execute actual response methods on clean and edited Express, then restore source."""
    script = r'''
const response = require('./lib/response');
function invoke(name) {
  const headers = {'Content-Type': 'application/custom'};
  const res = {
    app: {get: key => ({'json spaces': 2, 'jsonp callback name': 'callback'})[key]},
    req: {query: {}}, get: key => headers[key], set: (key,value) => {headers[key]=value},
    send: body => body
  };
  return {body: response[name].call(res, {a:1}), type: headers['Content-Type']};
}
console.log(JSON.stringify({json:invoke('json'), jsonp:invoke('jsonp')}));
'''
    path = root / E
    original = path.read_bytes()
    old = "var spaces = app.get('json spaces');"
    if original.decode().count(old) != 2:
        raise ValueError("Counterfactual probe requires the pinned clean Express source")
    def execute():
        return json.loads(subprocess.check_output(["node", "-e", script], cwd=root, text=True, timeout=30))
    try:
        clean = execute()
        path.write_text(original.decode().replace(old, "var spaces = undefined;", 1))
        edited = execute()
    finally:
        path.write_bytes(original)
    pretty = '{\n  "a": 1\n}'
    passed = (clean["json"]["body"] == clean["jsonp"]["body"] == edited["jsonp"]["body"] == pretty
              and edited["json"]["body"] == '{"a":1}'
              and all(r["type"] == "application/custom" for v in (clean, edited) for r in v.values()))
    return {"passed": passed, "clean": clean, "edited": edited, "scope": "JSON-only mutation, JSONP negative control, existing content type"}


def verify_discovery(root, python, env):
    """Execute dependency behavior and reject separate cache-write and scope-key faults."""
    script = r'''
import json, runpy
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
suite = runpy.run_path('tests/test_dependency_cache.py')
checks = {}
for name in ('test_normal_counter', 'test_sub_counter', 'test_sub_counter_no_cache', 'test_security_cache'):
    try:
        suite[name]()
        checks[name] = True
    except AssertionError:
        checks[name] = False
app = FastAPI()
counter = [0]
def count():
    counter[0] += 1
    return counter[0]
@app.get('/probe')
def probe(first: int = Depends(count, use_cache=False), second: int = Depends(count)):
    return {'first': first, 'second': second}
with TestClient(app) as client:
    checks['uncached_first_can_populate_cache'] = client.get('/probe').json() == {'first': 1, 'second': 1}
print(json.dumps(checks))
'''
    files = {name: (root / name).read_bytes() for name in (D, M)}
    # New subprocesses must load edited source instead of reusing timestamp-based bytecode.
    import shutil
    def execute():
        for cache in (root / "fastapi").rglob("__pycache__"):
            shutil.rmtree(cache)
        return json.loads(subprocess.check_output([python, "-B", "-c", script], cwd=root, text=True,
                                                 env={**env, "PYTHONPATH": str(root)}, timeout=60))
    try:
        clean = execute()
        old = "if sub_dependant.cache_key not in dependency_cache:"
        if files[D].decode().count(old) != 1:
            raise ValueError("Cache-write fault requires a unique pinned condition")
        (root / D).write_text(files[D].decode().replace(old, "if sub_dependant.use_cache and sub_dependant.cache_key not in dependency_cache:"))
        write_fault = execute()
        (root / D).write_bytes(files[D])
        old = "            scopes_for_cache,"
        if files[M].decode().count(old) != 1:
            raise ValueError("Scope-key fault requires a unique pinned tuple member")
        (root / M).write_text(files[M].decode().replace(old, "            (),"))
        scope_fault = execute()
    finally:
        for name, original in files.items():
            (root / name).write_bytes(original)
        for cache in (root / "fastapi").rglob("__pycache__"):
            shutil.rmtree(cache)
    passed = (all(clean.values()) and not write_fault["uncached_first_can_populate_cache"]
              and all(write_fault[name] for name in clean if name != "uncached_first_can_populate_cache")
              and not scope_fault["test_security_cache"]
              and all(scope_fault[name] for name in clean if name != "test_security_cache"))
    return {"passed": passed, "clean": clean, "write_fault": write_fault, "scope_fault": scope_fault,
            "scope": "Actual dependency requests; isolated cache-write and scope-key faults with unchanged-behavior controls"}
