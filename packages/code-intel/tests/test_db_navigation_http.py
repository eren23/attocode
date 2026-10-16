"""Real SQL through v2 routes; SQLite locally, migrated PostgreSQL in CI.

Auth is deliberately overridden here: remote isolation has its own tests. These
tests cover persisted parser output, branch resolution and HTTP serialization.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from types import SimpleNamespace

import httpx
import pytest
from attocode_intel.api.auth import verify_auth
from attocode_intel.api.routes import analysis, lsp
from attocode_intel.db.models import (
    Branch,
    BranchFile,
    Dependency,
    FileContent,
    Organization,
    Repository,
    Symbol,
    SymbolReference,
)
from attocode_intel.indexing.parser import extract_references, extract_symbols
from fastapi import FastAPI
from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles


@compiles(JSONB, "sqlite")
def _sqlite_json(element, compiler, **kw):
    return "JSON"


@pytest.fixture
async def navigation(monkeypatch, tmp_path):
    engine = create_async_engine(os.environ.get("TEST_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'navigation.sqlite'}"))
    models = (Organization, Repository, Branch, FileContent, BranchFile, Symbol, SymbolReference, Dependency)
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
                                  shas=shas, main_id=main_id, other_id=other_id, repo_id=repo_id, engine=engine)
    finally:
        async with sessions() as session:
            await session.execute(delete(BranchFile).where(BranchFile.branch_id.in_([main_id, other_id])))
            await session.execute(delete(Branch).where(Branch.id.in_([main_id, other_id])))
            await session.execute(delete(Dependency).where(or_(
                Dependency.source_sha.in_(shas), Dependency.target_sha.in_(shas))))
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


async def indexed_git(navigation, tmp_path, copies=1):
    """Only tiny committed fixtures; no clone, fetch, or model acquisition."""
    pytest.importorskip("pygit2")
    from attocode_intel.git.manager import GitRepoManager

    async with navigation.sessions() as session:
        source = await session.get(FileContent, navigation.shas[0])
        content = source.content
    repo = tmp_path / "source"
    repo.mkdir()
    (repo / "module.py").write_bytes(content)
    if copies == 2:
        (repo / "copy.py").write_bytes(content)
    for args in (("init", "-b", "main"), ("add", "."),
                 ("-c", "user.name=Test", "-c", "user.email=test@example.com",
                  "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgSign=false", "commit", "-m", "fixture")):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    manager = GitRepoManager(str(tmp_path / "unused-clones"))
    manager.register_path(str(navigation.repo_id), repo)
    return manager


async def persisted_refs(navigation, sha):
    async with navigation.sessions() as session:
        result = await session.execute(select(SymbolReference).where(SymbolReference.content_sha == sha))
        return sorted((r.symbol_name, r.ref_kind, r.line, r.caller_qualified_name) for r in result.scalars())


@pytest.mark.parametrize("copies", [1, 2])
async def test_full_reindex_replaces_shared_content_references(navigation, tmp_path, copies):
    from attocode_intel.indexing.full_indexer import FullIndexer

    manager = await indexed_git(navigation, tmp_path, copies)
    expected = await persisted_refs(navigation, navigation.shas[0])
    other = await persisted_refs(navigation, navigation.shas[1])
    assert len(expected) == 2
    # Repair duplicates left by older runs, not just prevent future accumulation.
    async with navigation.sessions() as session:
        session.add_all([SymbolReference(content_sha=navigation.shas[0], symbol_name=name,
                                         ref_kind=kind, line=line, caller_qualified_name=caller)
                         for name, kind, line, caller in expected])
        await session.commit()
    assert len(await persisted_refs(navigation, navigation.shas[0])) == 4
    for branch in (navigation.main_id, navigation.main_id, navigation.other_id):
        async with navigation.sessions() as session:
            stats = await FullIndexer(session, manager).index(str(navigation.repo_id), branch, ref="main")
        assert stats["errors"] == 0
        assert stats["files_indexed"] == copies
        assert stats["references_found"] == 2
        assert await persisted_refs(navigation, navigation.shas[0]) == expected
        assert await persisted_refs(navigation, navigation.shas[1]) == other
    response = await navigation.client.get(navigation.base + "/cross-refs", params={"symbol": "helper"})
    assert response.status_code == 200
    assert response.json()["total_references"] == 2 * copies


@pytest.mark.parametrize("failure", ["parse", "insert"])
async def test_failed_reference_refresh_preserves_old_rows_and_reports_error(navigation, tmp_path, monkeypatch, failure):
    from attocode_intel.indexing.full_indexer import FullIndexer

    manager = await indexed_git(navigation, tmp_path)
    before = await persisted_refs(navigation, navigation.shas[0])

    def broken_extract(*args):
        if failure == "parse":
            raise RuntimeError("injected parser failure")
        return [{"symbol_name": "new", "ref_kind": "call", "line": 10},
                {"symbol_name": "broken", "ref_kind": "call", "line": None}]

    monkeypatch.setattr("attocode_intel.indexing.full_indexer.extract_references", broken_extract)
    async with navigation.sessions() as session:
        stats = await FullIndexer(session, manager).index(str(navigation.repo_id), navigation.main_id)
    assert stats["errors"] == 1
    assert stats["references_found"] == 0
    assert await persisted_refs(navigation, navigation.shas[0]) == before


async def graph_fixture(navigation, edges, *, outside=False, duplicate=False):
    """Equal source sizes make the expected connectivity contribution explicit."""
    names = ("a", "b", "c", "isolated")
    mapping = {}
    async with navigation.sessions() as session:
        # Replace the test's main manifest; unrelated branch content remains present.
        await session.execute(delete(BranchFile).where(BranchFile.branch_id == navigation.main_id))
        for name in names:
            content = f"# {uuid.uuid4()}\n".encode()
            sha = hashlib.sha256(content).hexdigest()
            navigation.shas.append(sha)
            mapping[name] = sha
            session.add(FileContent(sha256=sha, content=content, size_bytes=len(content), language="python"))
            await session.flush()
            session.add(BranchFile(branch_id=navigation.main_id, path=name + ".py", content_sha=sha, status="added"))
        if duplicate:
            session.add(BranchFile(branch_id=navigation.main_id, path="a-copy.py", content_sha=mapping["a"], status="added"))
        mapping["outside"] = navigation.shas[1]
        for source, target in edges:
            session.add(Dependency(source_sha=mapping[source], target_sha=mapping[target], dep_type="import", metadata_={}))
        if outside:
            session.add_all([Dependency(source_sha=mapping["outside"], target_sha=mapping["a"], dep_type="import", metadata_={}),
                             Dependency(source_sha=mapping["a"], target_sha=mapping["outside"], dep_type="import", metadata_={})])
        await session.commit()


@pytest.mark.parametrize("edges,counts", [
    ([("a", "b"), ("b", "c")], {"a": (0, 1), "b": (1, 1), "c": (1, 0), "isolated": (0, 0)}),
    ([("a", "b"), ("a", "c")], {"a": (0, 2), "b": (1, 0), "c": (1, 0), "isolated": (0, 0)}),
    ([], {"a": (0, 0), "b": (0, 0), "c": (0, 0), "isolated": (0, 0)}),
])
async def test_hotspots_normalize_connections_by_file_identity(navigation, edges, counts):
    await graph_fixture(navigation, edges)
    response = await navigation.client.get(navigation.base + "/hotspots")
    assert response.status_code == 200, response.text
    rows = response.json()["file_hotspots"]
    assert len(rows) == 4
    maximum = max((sum(pair) for pair in counts.values()), default=1) or 1
    for row in rows:
        fan_in, fan_out = counts[row["path"].removesuffix(".py")]
        assert (row["fan_in"], row["fan_out"]) == (fan_in, fan_out)
        assert row["composite"] == pytest.approx(round(.4 + .3 * (fan_in + fan_out) / maximum, 4))
    top = await navigation.client.get(navigation.base + "/hotspots", params={"top_n": 1})
    assert top.json()["file_hotspots"] == rows[:1]
    # Tied scores retain a stable path order when a page truncates the list.
    assert [r["path"] for r in rows] == [r["path"] for r in sorted(rows, key=lambda r: (-r["composite"], r["path"]))]


@pytest.mark.parametrize("duplicate", [False, True])
async def test_hotspots_exclude_other_branch_edges_and_preserve_identical_files(navigation, duplicate):
    await graph_fixture(navigation, [("a", "b"), ("b", "c")], outside=True, duplicate=duplicate)
    response = await navigation.client.get(navigation.base + "/hotspots")
    assert response.status_code == 200
    rows = {r["path"]: r for r in response.json()["file_hotspots"]}
    assert set(rows) == {"a.py", "b.py", "c.py", "isolated.py"} | ({"a-copy.py"} if duplicate else set())
    assert rows["a.py"]["fan_in"] == 0
    assert rows["a.py"]["fan_out"] == 1
    assert rows["a.py"]["composite"] == .55
    if duplicate:
        assert {k: v for k, v in rows["a-copy.py"].items() if k != "path"} == {
            k: v for k, v in rows["a.py"].items() if k != "path"}
    assert rows["b.py"]["composite"] == .7


async def test_successful_empty_reference_refresh_removes_stale_rows(navigation, tmp_path, monkeypatch):
    from attocode_intel.indexing.full_indexer import FullIndexer

    manager = await indexed_git(navigation, tmp_path)
    other = await persisted_refs(navigation, navigation.shas[1])
    monkeypatch.setattr("attocode_intel.indexing.full_indexer.extract_references", lambda *args: [])
    async with navigation.sessions() as session:
        stats = await FullIndexer(session, manager).index(str(navigation.repo_id), navigation.main_id)
    assert stats["errors"] == stats["references_found"] == 0
    assert await persisted_refs(navigation, navigation.shas[0]) == []
    assert await persisted_refs(navigation, navigation.shas[1]) == other


async def test_reference_replacement_requires_existing_content(navigation):
    from attocode_intel.storage.symbol_store import SymbolStore

    async with navigation.sessions() as session:
        with pytest.raises(ValueError, match="Store file content"):
            await SymbolStore(session).replace_references("absent", [])
        # The caller still owns a usable transaction after the failed savepoint.
        assert await session.get(FileContent, navigation.shas[0]) is not None


async def test_postgres_reference_writers_serialize_and_readers_keep_committed_rows(navigation):
    from attocode_intel.storage.symbol_store import SymbolStore
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    sha = navigation.shas[0]
    before = await persisted_refs(navigation, sha)
    first = [{"symbol_name": "first", "ref_kind": "call", "line": 10}]
    second = [{"symbol_name": "second", "ref_kind": "call", "line": 20}]
    async with (navigation.sessions() as key_reader,
                navigation.sessions() as writer, navigation.sessions() as contender):
        if writer.get_bind().dialect.name != "postgresql":
            pytest.skip("PostgreSQL row-lock/MVCC control; exercised by product CI")
        # An unrelated symbol/reference insert can hold this FK parent lock.
        # Refreshing references must not need to upgrade it to FOR UPDATE.
        await key_reader.execute(select(FileContent.sha256).where(FileContent.sha256 == sha)
                                 .with_for_update(read=True, key_share=True))
        await writer.execute(text("SET LOCAL lock_timeout = '250ms'"))
        await SymbolStore(writer).replace_references(sha, first)
        # Independent readers retain the old committed set while a writer replaces it.
        assert await persisted_refs(navigation, sha) == before
        await contender.execute(text("SET LOCAL lock_timeout = '250ms'"))
        with pytest.raises(DBAPIError) as blocked:
            await SymbolStore(contender).replace_references(sha, second)
        assert getattr(blocked.value.orig, "sqlstate", None) == "55P03"
        await writer.commit()
        # The failed contender's savepoint recovered; retry after the lock owner commits.
        assert await SymbolStore(contender).replace_references(sha, second) == 1
        await contender.commit()
    assert await persisted_refs(navigation, sha) == [("second", "call", 20, "")]


async def apply_changes(navigation, changes, *, branch=None, base_dir=None):
    from attocode_intel.indexing.incremental import IncrementalPipeline

    for content in changes.values():
        if content is not None:
            navigation.shas.append(hashlib.sha256(content).hexdigest())
    async with navigation.sessions() as session:
        stats = await IncrementalPipeline(session).process_file_changes(
            branch or navigation.main_id, list(changes), base_dir=base_dir,
            file_contents={p: c for p, c in changes.items() if c is not None})
        await session.commit()
    return stats


@pytest.fixture
async def incremental(navigation):
    return navigation


def workflow_sources(extension, nonce, caller="entry", target="target_workflow"):
    if extension == "py":
        return {"api.py": f"# {nonce}\ndef target_workflow():\n    return 1\n".encode(),
                "caller.py": (f"# {nonce}\nfrom api import {target}\ndef {caller}():\n"
                              f"    return {target}()\n").encode()}
    return {f"api.{extension}": f"// {nonce}\nexport function target_workflow() {{\n  return 1;\n}}\n".encode(),
            f"caller.{extension}": (f"// {nonce}\nimport {{ {target} }} from './api';\n"
                                    f"function {caller}() {{\n  return {target}();\n}}\n").encode()}


async def seed_workflow(navigation, tmp_path, extension):
    from attocode_intel.git.manager import GitRepoManager
    from attocode_intel.indexing.full_indexer import FullIndexer

    sources = workflow_sources(extension, uuid.uuid4())
    repo = tmp_path / "workflow"
    repo.mkdir()
    for path, content in sources.items():
        (repo / path).write_bytes(content)
        navigation.shas.append(hashlib.sha256(content).hexdigest())
    for args in (("init", "-b", "main"), ("add", "."),
                 ("-c", "user.name=Test", "-c", "user.email=test@example.com",
                  "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgSign=false", "commit", "-m", "fixture")):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    manager = GitRepoManager(str(tmp_path / "unused"))
    manager.register_path(str(navigation.repo_id), repo)
    for branch in (navigation.main_id, navigation.other_id):
        async with navigation.sessions() as session:
            stats = await FullIndexer(session, manager).index(str(navigation.repo_id), branch)
            assert stats["errors"] == 0
    return sources


async def caller_locations(navigation, branch="", symbol="target_workflow"):
    response = await navigation.client.get(navigation.base + "/cross-refs", params={"symbol": symbol, "branch": branch})
    assert response.status_code == 200, response.text
    rows = response.json()["references"]
    return sorted((r["file_path"], r["line"], r["caller_qualified_name"]) for r in rows)


async def impacted(navigation, path, branch=""):
    response = await navigation.client.get(navigation.base + "/impact", params={"files": path, "branch": branch})
    assert response.status_code == 200, response.text
    return response.json()["impacted_files"]


@pytest.mark.parametrize("extension", ["py", "js", "ts"])
async def test_incremental_caller_edit_rename_delete_branch_and_reconnect(incremental, tmp_path, extension):
    n = incremental
    sources = await seed_workflow(n, tmp_path, extension)
    caller, api, moved, copy = (f"{name}.{extension}" for name in ("caller", "api", "renamed", "copy"))
    assert await caller_locations(n) == [(caller, 4, "entry")]
    assert await impacted(n, api) == [caller]
    edited = workflow_sources(extension, uuid.uuid4(), caller="updated")[caller]
    stats = await apply_changes(n, {caller: edited})
    assert stats["errors"] == 0 and stats["processed"] == 1
    assert await caller_locations(n) == [(caller, 4, "updated")]
    assert await caller_locations(n, "other") == [(caller, 4, "entry")]
    assert await impacted(n, api) == [caller]
    stats = await apply_changes(n, {caller: edited})
    assert stats["skipped_unchanged"] == 1
    assert await caller_locations(n) == [(caller, 4, "updated")]
    # Rename with unchanged content, and a second path sharing the same content.
    assert (await apply_changes(n, {caller: None, moved: edited, copy: edited}))["errors"] == 0
    assert await caller_locations(n) == [(copy, 4, "updated"), (moved, 4, "updated")]
    assert await impacted(n, api) == [copy, moved]
    # Independent interpreter/provider and a new DB pool, not an in-memory cache.
    await n.engine.dispose()
    restarted = subprocess.run([sys.executable, "-c", RESTART_QUERY], input=json.dumps({
        "url": n.engine.url.render_as_string(hide_password=False),
        "project": str(n.repo_id), "api": api,
    }), text=True, capture_output=True, timeout=20)
    assert restarted.returncode == 0, restarted.stderr
    recovered = json.loads(restarted.stdout)
    assert recovered["callers"] == [[copy, 4, "updated"], [moved, 4, "updated"]]
    assert recovered["impact"] == [copy, moved]
    assert await caller_locations(n) == [(copy, 4, "updated"), (moved, 4, "updated")]
    assert (await apply_changes(n, {copy: None, moved: None}))["processed"] == 2
    assert await caller_locations(n) == [] and await impacted(n, api) == []
    assert await caller_locations(n, "other") == [(caller, 4, "entry")]
    assert await impacted(n, api, "other") == [caller]
    # Recover an earlier version from the content store without multiplying refs.
    assert (await apply_changes(n, {caller: sources[caller]}))["errors"] == 0
    assert await caller_locations(n) == [(caller, 4, "entry")]


@pytest.mark.parametrize("extension", ["py", "js", "ts"])
async def test_impact_follows_target_edit_and_removed_import(incremental, tmp_path, extension):
    n = incremental
    sources = await seed_workflow(n, tmp_path, extension)
    caller, api = f"caller.{extension}", f"api.{extension}"
    new_api = sources[api].replace(b"return 1", b"return 2")
    assert (await apply_changes(n, {api: new_api}))["errors"] == 0
    assert await impacted(n, api) == [caller]
    assert await impacted(n, api, "other") == [caller]
    no_call = (f"# {uuid.uuid4()}\ndef empty():\n    return 1\n" if extension == "py"
               else f"// {uuid.uuid4()}\nfunction empty() {{ return 1; }}\n").encode()
    assert (await apply_changes(n, {caller: no_call}))["errors"] == 0
    assert await caller_locations(n) == [] and await impacted(n, api) == []
    assert await caller_locations(n, "other") == [(caller, 4, "entry")]


@pytest.mark.parametrize("failure", ["parse", "insert"])
async def test_failed_incremental_refresh_preserves_manifest_and_allows_retry(incremental, monkeypatch, failure):
    n = incremental
    from attocode_intel.indexing import incremental as module
    from attocode_intel.storage.branch_overlay import BranchOverlay

    updated = f"# {uuid.uuid4()}\ndef changed():\n    return helper()\n".encode()
    healthy = f"# {uuid.uuid4()}\ndef healthy():\n    return helper()\n".encode()
    real = extract_references

    def broken(content, path):
        if path == "module.py":
            if failure == "parse":
                raise RuntimeError("injected extraction failure")
            return [{"symbol_name": "helper", "ref_kind": "call", "line": None}]
        return real(content, path)

    # raising=False makes the pre-fix regression fail on its actual behavior.
    monkeypatch.setattr(module, "extract_references", broken, raising=False)
    stats = await apply_changes(n, {"module.py": updated, "healthy.py": healthy})
    assert stats["errors"] == 1 and stats["processed"] == 1
    async with n.sessions() as session:
        manifest = await BranchOverlay(session).resolve_manifest(n.main_id)
    assert manifest["module.py"] == n.shas[0]
    assert "healthy.py" in manifest
    assert len(await persisted_refs(n, n.shas[0])) == 2
    monkeypatch.setattr(module, "extract_references", real)
    stats = await apply_changes(n, {"module.py": updated})
    assert stats["errors"] == 0 and stats["processed"] == 1
    rows = await caller_locations(n, symbol="helper")
    assert ("module.py", 3, "changed") in rows
    assert ("healthy.py", 3, "healthy") in rows


async def test_unreadable_existing_file_is_not_deleted(incremental, tmp_path, monkeypatch):
    from pathlib import Path

    from attocode_intel.storage.branch_overlay import BranchOverlay

    path = tmp_path / "module.py"
    path.write_text("unreadable")
    original = Path.read_bytes

    def unreadable(self):
        if self == path:
            raise PermissionError("injected read failure")
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", unreadable)
    stats = await apply_changes(incremental, {"module.py": None}, base_dir=str(tmp_path))
    assert stats["errors"] == 1 and stats["processed"] == 0
    async with incremental.sessions() as session:
        manifest = await BranchOverlay(session).resolve_manifest(incremental.main_id)
    assert manifest["module.py"] == incremental.shas[0]


@pytest.mark.parametrize("extension", ["py", "js", "ts"])
async def test_nested_import_transitive_impact_survives_target_change(incremental, extension):
    n = incremental
    nonce = uuid.uuid4()
    if extension == "py":
        sources = {"api.py": f"# {nonce}\ndef target_workflow():\n    return 1\n".encode(),
                   "pkg/caller.py": b"from api import target_workflow\ndef entry():\n    return target_workflow()\n",
                   "top.py": b"from pkg.caller import entry\nentry()\n"}
    else:
        sources = {f"api.{extension}": f"// {nonce}\nexport function target_workflow() {{ return 1; }}\n".encode(),
                   f"pkg/caller.{extension}": b"import { target_workflow } from '../api';\nfunction entry() {\n return target_workflow();\n}\n",
                   f"top.{extension}": b"import { entry } from './pkg/caller';\nentry();\n"}
    # Reverse dependency order in the input, exercising complete-manifest resolution.
    assert (await apply_changes(n, dict(reversed(list(sources.items())))))["errors"] == 0
    api = f"api.{extension}"
    assert await impacted(n, api) == [f"pkg/caller.{extension}", f"top.{extension}"]
    assert (await apply_changes(n, {api: sources[api].replace(b"return 1", b"return 2")}))["errors"] == 0
    assert await impacted(n, api) == [f"pkg/caller.{extension}", f"top.{extension}"]
    assert (await apply_changes(n, {f"pkg/caller.{extension}": None}))["errors"] == 0
    assert await impacted(n, api) == []


async def test_impact_includes_importers_beyond_500_contents(incremental):
    n = incremental
    # Persist 513 distinct, tiny callers without a large checkout/download.
    async with n.sessions() as session:
        for i in range(513):
            content = f"# {uuid.uuid4()}\nfrom module import helper\n".encode()
            sha = hashlib.sha256(content).hexdigest()
            n.shas.append(sha)
            session.add(FileContent(sha256=sha, content=content, size_bytes=len(content), language="python"))
            await session.flush()
            session.add(BranchFile(branch_id=n.main_id, path=f"caller{i:03}.py", content_sha=sha, status="added"))
        await session.commit()
    assert await impacted(n, "module.py") == [f"caller{i:03}.py" for i in range(513)]


async def test_impact_resolves_current_typescript_aliases(incremental):
    n = incremental
    nonce = uuid.uuid4()
    sources = {"src/api.ts": f"// {nonce}\nexport function helper() {{ return 1; }}\n".encode(),
               "caller.ts": b"import { helper } from '@/api';\nhelper();\n",
               "tsconfig.json": b'{"compilerOptions":{"paths":{"@/*":["src/*"]}}}'}
    assert (await apply_changes(n, sources))["errors"] == 0
    assert await impacted(n, "src/api.ts") == ["caller.ts"]
    assert (await apply_changes(n, {"src/api.ts": sources["src/api.ts"].replace(b"return 1", b"return 2")}))["errors"] == 0
    assert await impacted(n, "src/api.ts") == ["caller.ts"]
    assert (await apply_changes(n, {"tsconfig.json": b'{"compilerOptions":{"paths":{"@/*":["missing/*"]}}}'}))["errors"] == 0
    assert await impacted(n, "src/api.ts") == []


@pytest.mark.parametrize("prefix", ["export ", "export default ", "export async ", "export default async "])
def test_exported_declaration_is_not_its_own_caller(prefix):
    source = f"{prefix}function helper() {{\n  return 1;\n}}\nhelper();\n".encode()
    refs = extract_references(source, "api.ts")
    assert [(r["symbol_name"], r["line"]) for r in refs] == [("helper", 4)]


async def test_git_missing_path_is_deletion_but_invalid_ref_is_an_error(incremental, tmp_path):
    from attocode_intel.indexing.incremental import IncrementalPipeline
    from attocode_intel.storage.branch_overlay import BranchOverlay

    manager = await indexed_git(incremental, tmp_path)
    with pytest.raises(FileNotFoundError):
        manager.read_file(str(incremental.repo_id), "main", "missing.py")
    async with incremental.sessions() as session:
        stats = await IncrementalPipeline(session).process_file_changes(
            incremental.main_id, ["module.py"], git_reader=manager,
            repo_id=str(incremental.repo_id), ref="nonexistent-ref")
        await session.commit()
        manifest = await BranchOverlay(session).resolve_manifest(incremental.main_id)
    assert stats["errors"] == 1 and stats["processed"] == 0
    assert manifest["module.py"] == incremental.shas[0]


RESTART_QUERY = """
import asyncio, json, sys
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from attocode_intel.api.providers.db_provider import DbAnalysisProvider
import attocode_intel.db.engine as db
request = json.load(sys.stdin)
async def main():
    engine = create_async_engine(request["url"])
    sessions = async_sessionmaker(engine)
    async def get_session():
        async with sessions() as session:
            yield session
    db.get_session = get_session
    try:
        provider = DbAnalysisProvider(request["project"])
        refs = await provider.cross_references("target_workflow", "")
        impact = await provider.impact_analysis([request["api"]], "")
        print(json.dumps({"callers": sorted((r.file_path, r.line, r.caller_qualified_name)
                                           for r in refs.references),
                          "impact": impact.impacted_files}))
    finally:
        await engine.dispose()
asyncio.run(main())
"""
