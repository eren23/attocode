"""Real SQL through v2 routes; SQLite locally, migrated PostgreSQL in CI.

Auth is deliberately overridden here: remote isolation has its own tests. These
tests cover persisted parser output, branch resolution and HTTP serialization.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from types import SimpleNamespace

import httpx
import pytest
from attocode_intel.api.auth import verify_auth
from attocode_intel.api.routes import analysis, lsp
from attocode_intel.db.models import (
    Branch,
    BranchFile,
    FileContent,
    Organization,
    Repository,
    Symbol,
    SymbolReference,
)
from attocode_intel.indexing.parser import extract_references, extract_symbols
from fastapi import FastAPI
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles


@compiles(JSONB, "sqlite")
def _sqlite_json(element, compiler, **kw):
    return "JSON"


@pytest.fixture
async def navigation(monkeypatch):
    engine = create_async_engine(os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:"))
    models = (Organization, Repository, Branch, FileContent, BranchFile, Symbol, SymbolReference)
    async with engine.begin() as conn:
        for model in models:
            await conn.run_sync(lambda sync, table=model.__table__: table.create(sync, checkfirst=True))
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def get_session():
        async with sessions() as session:
            yield session

    monkeypatch.setattr("attocode_intel.db.engine.get_session", get_session)
    monkeypatch.setattr("attocode_intel.api.deps.get_config", lambda: SimpleNamespace(is_service_mode=True))
    org_id, repo_id, main_id, other_id = (uuid.uuid4() for _ in range(4))
    shas = []
    async with sessions() as session:
        session.add(Organization(id=org_id, name="Navigation", slug=str(org_id), settings={}))
        await session.flush()
        session.add(Repository(id=repo_id, org_id=org_id, name="Navigation", default_branch="main", settings={}))
        await session.flush()
        session.add_all([Branch(id=main_id, repo_id=repo_id, name="main", is_default=True),
                         Branch(id=other_id, repo_id=repo_id, name="other")])
        await session.flush()
        for branch_id, caller in ((main_id, "entry"), (other_id, "other_entry")):
            content = (f"# {uuid.uuid4()}\ndef helper():\n    return 1\n"
                       f"def {caller}():\n    return helper()\nhelper()\n").encode()
            sha = hashlib.sha256(content).hexdigest()
            shas.append(sha)
            session.add(FileContent(sha256=sha, content=content, size_bytes=len(content), language="python"))
            await session.flush()
            session.add(BranchFile(branch_id=branch_id, path="module.py", content_sha=sha, status="added"))
            for symbol in extract_symbols(content, "module.py"):
                session.add(Symbol(content_sha=sha, name=symbol["name"], kind=symbol["kind"],
                                   line_start=symbol["line_start"], line_end=symbol["line_end"],
                                   signature=symbol.get("signature", ""), metadata_={}))
            for ref in extract_references(content, "module.py"):
                session.add(SymbolReference(content_sha=sha, **ref))
        await session.commit()
    app = FastAPI()
    app.dependency_overrides[verify_auth] = lambda: None
    app.include_router(analysis.router_v2)
    app.include_router(lsp.router_v2)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield SimpleNamespace(client=client, base=f"/api/v2/projects/{repo_id}", sessions=sessions,
                                  shas=shas, main_id=main_id)
    finally:
        async with sessions() as session:
            await session.execute(delete(BranchFile).where(BranchFile.branch_id.in_([main_id, other_id])))
            await session.execute(delete(Branch).where(Branch.id.in_([main_id, other_id])))
            for model in (SymbolReference, Symbol):
                await session.execute(delete(model).where(model.content_sha.in_(shas)))
            await session.execute(delete(FileContent).where(FileContent.sha256.in_(shas)))
            await session.execute(delete(Repository).where(Repository.id == repo_id))
            await session.execute(delete(Organization).where(Organization.id == org_id))
            await session.commit()
        await engine.dispose()


@pytest.mark.parametrize("branch,caller", [("", "entry"), ("other", "other_entry")])
async def test_persisted_caller_names_survive_http_serialization(navigation, branch, caller):
    response = await navigation.client.get(navigation.base + "/cross-refs", params={"symbol": "helper", "branch": branch})
    assert response.status_code == 200, response.text
    refs = response.json()["references"]
    assert {(r["line"], r["caller_qualified_name"]) for r in refs} == {(5, caller), (6, "")}
    assert all(r["file_path"] == "module.py" and r["symbol"] == "helper" for r in refs)


@pytest.mark.parametrize("endpoint", ["definition", "references", "hover"])
async def test_db_navigation_obeys_http_schema(navigation, endpoint):
    response = await navigation.client.post(navigation.base + "/lsp/" + endpoint,
                                            json={"file": "module.py", "line": 2, "col": 0})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["source"] == "symbol_index"
    if endpoint == "definition":
        assert data["location"] == {"file": "module.py", "line": 2, "col": 0}
    elif endpoint == "references":
        assert {(r["file"], r["line"]) for r in data["locations"]} == {("module.py", 2), ("module.py", 5), ("module.py", 6)}
        assert data["total"] == 3
    else:
        assert "helper" in data["content"] and data["file"] == "module.py"


async def test_declaration_flag_and_missing_branch(navigation):
    response = await navigation.client.post(navigation.base + "/lsp/references", params={"branch": "other"},
                                            json={"file": "module.py", "line": 2, "include_declaration": False})
    assert response.status_code == 200, response.text
    assert [r["line"] for r in response.json()["locations"]] == [5, 6]
    assert response.json()["total"] == 2
    response = await navigation.client.post(navigation.base + "/lsp/definition", params={"branch": "missing"},
                                            json={"file": "module.py", "line": 2})
    assert response.status_code == 404


@pytest.mark.parametrize("endpoint", ["definition", "references", "hover"])
@pytest.mark.parametrize("file,line", [("missing.py", 2), ("module.py", 5)])
async def test_missing_or_call_site_position_is_not_an_enclosing_definition(navigation, endpoint, file, line):
    response = await navigation.client.post(navigation.base + "/lsp/" + endpoint, json={"file": file, "line": line})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["error"]
    assert not data.get("location") and not data.get("locations") and not data.get("content")


async def test_no_language_server_diagnostics_are_explicitly_unsupported(navigation):
    response = await navigation.client.get(navigation.base + "/lsp/diagnostics", params={"file": "module.py"})
    assert response.status_code == 200, response.text
    assert response.json()["file"] == "module.py"
    assert response.json()["diagnostics"] == [] and response.json()["total"] == 0
    assert "language server" in response.json()["error"]


async def test_ambiguous_name_does_not_select_an_arbitrary_reference_target(navigation):
    async with navigation.sessions() as session:
        session.add(Symbol(content_sha=navigation.shas[0], name="helper", kind="function",
                           line_start=20, line_end=21, metadata_={}))
        await session.commit()
    response = await navigation.client.post(navigation.base + "/lsp/references",
                                            json={"file": "module.py", "line": 2})
    assert response.status_code == 200
    assert response.json()["locations"] == []
    assert "Ambiguous" in response.json()["error"]
    # A definition request on its declaration still identifies the selected file/line.
    response = await navigation.client.post(navigation.base + "/lsp/definition",
                                            json={"file": "module.py", "line": 20})
    assert response.json()["location"]["line"] == 20


async def test_reference_candidates_are_bounded_and_marked_partial(navigation):
    async with navigation.sessions() as session:
        session.add_all([SymbolReference(content_sha=navigation.shas[0], symbol_name="helper",
                                         ref_kind="call", line=100 + i) for i in range(501)])
        await session.commit()
    response = await navigation.client.post(navigation.base + "/lsp/references",
                                            json={"file": "module.py", "line": 2})
    data = response.json()
    assert response.status_code == 200
    assert data["total"] == len(data["locations"]) == 500
    assert data["error"] and "candidates" in data["note"]
    assert {r["col"] for r in data["locations"]} == {0}


@pytest.mark.parametrize("endpoint", ["definition", "references", "hover"])
async def test_column_precision_is_not_invented(navigation, endpoint):
    response = await navigation.client.post(navigation.base + "/lsp/" + endpoint,
                                            json={"file": "module.py", "line": 2, "col": 8})
    assert response.status_code == 200
    assert "no columns" in response.json()["error"]


async def test_identical_caller_content_retains_each_branch_path(navigation):
    content = f"# {uuid.uuid4()}\nhelper()\n".encode()
    sha = hashlib.sha256(content).hexdigest()
    navigation.shas.append(sha)
    async with navigation.sessions() as session:
        session.add(FileContent(sha256=sha, content=content, size_bytes=len(content)))
        await session.flush()
        session.add(SymbolReference(content_sha=sha, symbol_name="helper", ref_kind="call", line=2))
        for name in ("first.py", "second.py"):
            session.add(BranchFile(branch_id=navigation.main_id, path=name, content_sha=sha, status="added"))
        await session.commit()
    response = await navigation.client.post(navigation.base + "/lsp/references",
                                            json={"file": "module.py", "line": 2, "include_declaration": False})
    assert response.status_code == 200
    assert {(r["file"], r["line"]) for r in response.json()["locations"]} == {
        ("module.py", 5), ("module.py", 6), ("first.py", 2), ("second.py", 2),
    }


async def test_local_http_preserves_parser_caller_identity(tmp_path, monkeypatch):
    from attocode_intel._internal.integrations.context.ast_service import ASTService
    from attocode_intel.api.providers.local_provider import LocalAnalysisProvider
    from attocode_intel.service import CodeIntelService

    (tmp_path / "module.py").write_text("def helper(): return 1\ndef entry(): return helper()\nhelper()\n")
    ast = ASTService(str(tmp_path))
    try:
        ast.initialize_skeleton(indexing_depth="eager")
        service = CodeIntelService(str(tmp_path))
        service._ast_service = ast

        async def provider(project_id):
            return LocalAnalysisProvider(service)

        monkeypatch.setattr(analysis, "get_analysis_provider", provider)
        app = FastAPI()
        app.dependency_overrides[verify_auth] = lambda: None
        app.include_router(analysis.router_v2)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v2/projects/default/cross-refs", params={"symbol": "helper"})
        assert response.status_code == 200
        assert {(r["line"], r["caller_qualified_name"]) for r in response.json()["references"]} == {(2, "entry"), (3, "")}
    finally:
        ast.stop_hydration()
        if ast._store:
            ast._store.close()
