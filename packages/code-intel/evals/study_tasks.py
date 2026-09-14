"""Fixed real-repository tasks and independent acceptance checks for client studies."""
from __future__ import annotations

import re
import subprocess

from workflows import SCENARIOS

FAMILIES = ("lookup", "change", "returning")
TASKS = [{**spec, "family": family, "id": spec["repo"] + ":" + family}
         for spec in SCENARIOS for family in FAMILIES]
FAULTS = {
    "fastapi": ("fastapi/routing.py", "response_model_by_alias=self.response_model_by_alias,", "response_model_by_alias=True,"),
    "express": ("lib/response.js", "var spaces = app.get('json spaces');", "var spaces = undefined;"),
    "frontend": ("src/lib/cn.ts", "return twMerge(clsx(inputs));", "return clsx(inputs);"),
    "ripgrep": ("crates/ignore/src/walk.rs", "self.ig_builder.hidden(yes);", "self.ig_builder.hidden(!yes);"),
}
SYMPTOMS = {
    "fastapi": "Response models configured with response_model_by_alias=False still emit alias keys. Restore the documented behavior for model and dictionary responses.",
    "express": "Setting json spaces no longer indents res.json output. Restore indentation while preserving replacer, escaping and JSONP behavior.",
    "frontend": "UI class composition keeps conflicting Tailwind classes instead of letting the last class win. Restore conflict resolution while preserving conditional and nested input support.",
    "ripgrep": "WalkBuilder.hidden(false) hides dotfiles, and hidden(true) includes them. Restore the documented behavior without changing ignore-file filtering.",
}
DEFINITIONS = {
    "fastapi": r"(?:async )?def serialize_response\(", "express": r"res\.json = function json\(",
    "frontend": r"export function cn\(", "ripgrep": r"pub struct WalkBuilder\b",
}
USES = {"fastapi": r"serialize_response\(", "express": r"\.json\(",
        "frontend": r"\bcn\(", "ripgrep": r"WalkBuilder::new\("}
SCHEMA = {"type": "object", "properties": {
    "definition": {"type": "object", "properties": {"path": {"type": "string"}, "line": {"type": "integer"}, "quote": {"type": "string"}},
                   "required": ["path", "line", "quote"], "additionalProperties": False},
    "usage": {"type": "object", "properties": {"path": {"type": "string"}, "line": {"type": "integer"}, "quote": {"type": "string"}},
              "required": ["path", "line", "quote"], "additionalProperties": False},
    "tests": {"type": "array", "items": {"type": "string"}},
    "summary": {"type": "string"},
}, "required": ["definition", "usage", "tests", "summary"], "additionalProperties": False}


def prompt(task, stage=0):
    target = {"fastapi": "request-handler response serialization", "express": "Express res.json",
              "frontend": "the cn class-composition utility", "ripgrep": "the ignore crate's WalkBuilder"}[task["repo"]]
    text = f"Work in this repository on {target}. "
    if task["family"] == "lookup" or (task["family"] == "returning" and stage == 0):
        text += "Locate its definition and one actual usage. Read source evidence; do not change production code. "
    else:
        text += SYMPTOMS[task["repo"]] + " Find the cause, repair it and run relevant verification. "
    if task["family"] == "returning":
        text += ("Leave useful repository-local notes in BENCH_NOTES.md or connected repository memory for a fresh session. "
                 if stage == 0 else "A separate editor changed source since the previous session. Consult available notes, verify current source and repair the regression. ")
    text += ("Use available native and connected intelligence tools when useful. Do not delegate, install packages, "
             "change client settings, use the network, or modify files outside this repository. "
             "Return JSON with definition and usage (repository-relative path, 1-based line, exact source-line quote), "
             "tests (relevant repository paths, or [] if none found), and a brief summary. Do not guess evidence.")
    return text


def inject(root, task):
    path, old, new = FAULTS[task["repo"]]
    source = root / path
    text = source.read_text()
    if old not in text:
        raise ValueError(f"Fixture does not match pinned source: {task['id']}")
    source.write_text(text.replace(old, new, 1))


def evidence(root, task, output):
    checks = {}
    for key, pattern in (("definition", DEFINITIONS[task["repo"]]), ("usage", USES[task["repo"]])):
        row = output.get(key, {})
        try:
            path = (root / row["path"]).resolve()
            assert path.is_relative_to(root.resolve())
            assert isinstance(row["line"], int) and row["line"] > 0
            line = path.read_text().splitlines()[row["line"] - 1]
            checks[key] = bool(row["quote"].strip() and row["quote"].strip() == line.strip() and re.search(pattern, line))
            if key == "definition":
                checks[key] &= row["path"] == task["file"]
            else:
                checks[key] &= not bool(re.search(DEFINITIONS[task["repo"]], line))
        except (KeyError, IndexError, OSError, TypeError, AssertionError):
            checks[key] = False
    tests = output.get("tests", [])
    checks["test_paths"] = isinstance(tests, list) and all(
        isinstance(p, str) and (root / p).resolve().is_relative_to(root.resolve()) and (root / p).is_file() for p in tests)
    return checks


PYTHON_CHECK = '''
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
class Item(BaseModel):
    name: str = Field(alias="alias")
app = FastAPI()
@app.get("/dict", response_model=Item, response_model_by_alias=False)
def dictionary(): return {"alias":"ok"}
@app.get("/model", response_model=Item, response_model_by_alias=False)
def model(): return Item(alias="ok")
@app.get("/default", response_model=Item)
def default(): return {"alias":"ok"}
client = TestClient(app)
assert client.get("/dict").json() == {"name":"ok"}
assert client.get("/model").json() == {"name":"ok"}
assert client.get("/default").json() == {"alias":"ok"}
'''
EXPRESS_CHECK = '''
const assert = require('node:assert/strict');
const express = require('./');
const request = require('supertest');
(async () => {
  const app = express();
  app.set('json spaces', 2);
  app.get('/', (req,res) => res.json({a:1}));
  app.get('/jsonp', (req,res) => res.jsonp({a:1}));
  const response = await request(app).get('/');
  assert.equal(response.status, 200);
  assert.equal(response.text, JSON.stringify({a:1}, null, 2));
  assert.match((await request(app).get('/jsonp?callback=fn')).text, /fn\\(/);
  app.set('json replacer', (key,value) => key === 'a' ? 9 : value);
  assert.equal((await request(app).get('/')).body.a, 9);
})().catch(e => { console.error(e); process.exit(1); });
'''
FRONTEND_CHECK = '''
const fs = require('node:fs'), ts = require('typescript'), assert = require('node:assert/strict');
const source = fs.readFileSync('src/lib/cn.ts','utf8');
const code = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
const mod = {exports:{}};
new Function('require','module','exports', code)(require,mod,mod.exports);
const cn = mod.exports.cn;
assert.equal(cn('p-2','p-4'), 'p-4');
assert.equal(cn(['text-sm',false,['text-lg']], {'font-bold':true}), 'text-lg font-bold');
assert.equal(cn(null,undefined,false), '');
'''
RUST_CHECK = '''
#[test]
fn hidden_switch_preserves_ignore_rules() {
    use std::{fs, time::{SystemTime, UNIX_EPOCH}};
    let path = std::env::temp_dir().join(format!("intel-check-{}-{}", std::process::id(), SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()));
    fs::create_dir(&path).unwrap();
    fs::write(path.join(".hidden"), "x").unwrap();
    fs::write(path.join("visible"), "x").unwrap();
    fs::write(path.join("ignored"), "x").unwrap();
    fs::write(path.join(".ignore"), "ignored\\n").unwrap();
    let names = |hidden| ignore::WalkBuilder::new(&path).hidden(hidden).build()
        .filter_map(Result::ok).map(|e| e.file_name().to_string_lossy().into_owned()).collect::<Vec<_>>();
    let shown = names(false); let hidden = names(true);
    fs::remove_dir_all(&path).unwrap();
    assert!(shown.contains(&".hidden".into()));
    assert!(!hidden.contains(&".hidden".into()));
    assert!(shown.contains(&"visible".into()) && hidden.contains(&"visible".into()));
    assert!(!shown.contains(&"ignored".into()) && !hidden.contains(&"ignored".into()));
}
'''


def acceptance(root, task, python, env):
    """Checks are injected only after the agent exits; modified tests cannot satisfy them."""
    if task["repo"] == "fastapi":
        command = [python, "-c", PYTHON_CHECK]
        env = {**env, "PYTHONPATH": str(root)}
    elif task["repo"] in {"express", "frontend"}:
        command = ["node", "-e", EXPRESS_CHECK if task["repo"] == "express" else FRONTEND_CHECK]
    else:
        path = root / "crates/ignore/tests/intelligence_acceptance.rs"
        path.parent.mkdir(exist_ok=True)
        path.write_text(RUST_CHECK)
        command = ["cargo", "test", "--offline", "--manifest-path", "crates/ignore/Cargo.toml", "--test", "intelligence_acceptance", "--quiet"]
    try:
        result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=300)
        return {"passed": result.returncode == 0, "exit_code": result.returncode, "output": (result.stdout + result.stderr)[-6000:]}
    except subprocess.TimeoutExpired:
        return {"passed": False, "timeout": True}
