"""Exercise real SQL queries and Git snapshots, including cached cross-tenant requests."""

from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from attocode_intel.api.auth.context import AuthContext
from attocode_intel.db.models import Organization, OrgMembership, Repository, User
from attocode_intel.gateway import OperationGateway
from attocode_intel.knowledge import KnowledgeEntry
from attocode_intel.remote import RemoteResolver, authorized_repo, remote_identity
from fastapi import HTTPException
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles


@compiles(JSONB, "sqlite")
def _sqlite_json(element, compiler, **kw):
    return "JSON"


@pytest.fixture
async def team(tmp_path, monkeypatch):
    engine = create_async_engine(
        os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    )
    tables = [
        Organization.__table__,
        User.__table__,
        OrgMembership.__table__,
        Repository.__table__,
        KnowledgeEntry.__table__,
    ]
    async with engine.begin() as conn:
        for table in tables:
            await conn.run_sync(lambda sync, table=table: table.create(sync, checkfirst=True))
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def get_session():
        async with sessions() as session:
            yield session

    monkeypatch.setattr("attocode_intel.db.engine.get_session", get_session)
    identities, repos = [], []
    async with sessions() as session:
        for name in ("alpha", "beta"):
            root = tmp_path / name
            root.mkdir()
            (root / "helper.py").write_text(f"def {name}_only(): return 1\n")

            def git(*args, root=root):
                return subprocess.run(
                    ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
                ).stdout.strip()

            git("init", "-b", "main")
            git("add", "helper.py")
            git(
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.com",
                "-c",
                "core.hooksPath=/dev/null",
                "commit",
                "-m",
                "fixture",
            )
            org = Organization(
                id=uuid.uuid4(), name=name, slug=f"{name}-{uuid.uuid4()}", settings={}
            )
            user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@example.com")
            session.add_all([org, user])
            await session.flush()
            session.add(
                OrgMembership(org_id=org.id, user_id=user.id, accepted_at=datetime.now(UTC))
            )
            repo = Repository(
                id=uuid.uuid4(),
                org_id=org.id,
                name=name,
                clone_path=str(root),
                default_branch="main",
                settings={},
            )
            session.add(repo)
            identities.append(
                AuthContext(user.id, org.id, ["intelligence:read", "intelligence:write"], "api_key")
            )
            repos.append(repo)
        await session.commit()
    gateway = OperationGateway(
        profile="full",
        resolver=RemoteResolver(SimpleNamespace(git_clone_dir=str(tmp_path / "snapshots"))),
    )

    async def call(identity, repo, name, **args):
        token = remote_identity.set(identity)
        try:
            return await gateway.execute(name, {"workspace": str(repo.id), **args})
        finally:
            remote_identity.reset(token)

    yield SimpleNamespace(
        identities=identities, repos=repos, call=call, gateway=gateway, sessions=sessions
    )
    await gateway.close()
    async with sessions() as session:
        for repo in repos:
            from sqlalchemy import delete

            await session.execute(delete(KnowledgeEntry).where(KnowledgeEntry.repo_id == repo.id))
            await session.execute(delete(Repository).where(Repository.id == repo.id))
            await session.execute(delete(OrgMembership).where(OrgMembership.org_id == repo.org_id))
            await session.execute(delete(Organization).where(Organization.id == repo.org_id))
        for identity in identities:
            await session.execute(delete(User).where(User.id == identity.user_id))
        await session.commit()
    await engine.dispose()


async def test_remote_isolation_commits_and_revoked_membership(team):
    a, b = team.identities
    ra, rb = team.repos
    first, second = await asyncio.gather(
        team.call(a, ra, "symbols", path="helper.py"), team.call(b, rb, "symbols", path="helper.py")
    )
    assert "alpha_only" in first.content[0].text and "beta_only" not in first.content[0].text
    assert "beta_only" in second.content[0].text
    assert first.structuredContent["metadata"]["revision"] != "working-tree"
    # Uncommitted edits in the server checkout never enter the committed snapshot.
    from pathlib import Path

    Path(ra.clone_path, "helper.py").write_text("def secret_uncommitted(): pass\n")
    again = await team.call(a, ra, "symbols", path="helper.py")
    assert "secret_uncommitted" not in again.content[0].text
    with pytest.raises(HTTPException) as denied:
        await team.call(a, rb, "symbols", path="helper.py")
    assert denied.value.status_code == 404
    with pytest.raises(ValueError, match="inside"):
        await team.call(a, ra, "symbols", path="../../private.py")
    from sqlalchemy import delete

    async with team.sessions() as session:
        await session.execute(delete(OrgMembership).where(OrgMembership.user_id == a.user_id))
        await session.commit()
    with pytest.raises(HTTPException):
        await team.call(a, ra, "symbols", path="helper.py")


async def test_shared_knowledge_permissions_crud_and_staleness(team):
    a, b = team.identities
    ra, rb = team.repos
    created = await team.call(
        a,
        ra,
        "record_learning",
        type="convention",
        description="Keep helpers pure",
        scope="helper.py",
    )
    row = created.structuredContent["data"]
    assert row["author_id"] == str(a.user_id) and not row["stale"]
    found = await team.call(a, ra, "recall", query="helpers")
    assert found.structuredContent["data"][0]["id"] == row["id"]
    read_only = AuthContext(a.user_id, a.org_id, ["intelligence:read"], "api_key")
    with pytest.raises(HTTPException) as denied:
        await team.call(
            read_only, ra, "update_learning", learning_id=row["id"], description="changed"
        )
    assert denied.value.status_code == 403
    with pytest.raises(ValueError, match="not found"):
        await team.call(b, rb, "update_learning", learning_id=row["id"], description="cross tenant")
    updated = await team.call(
        a, ra, "update_learning", learning_id=row["id"], description="Helpers are deterministic"
    )
    assert updated.structuredContent["data"]["description"] == "Helpers are deterministic"
    from pathlib import Path

    Path(ra.clone_path, "helper.py").write_text("def alpha_only(): return 2\n")
    subprocess.run(
        [
            "git",
            "-C",
            ra.clone_path,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-am",
            "change",
        ],
        check=True,
        capture_output=True,
    )
    stale = await team.call(a, ra, "list_learnings")
    assert stale.structuredContent["data"][0]["stale"]
    await team.call(a, ra, "update_learning", learning_id=row["id"], status="archived")
    active = await team.call(a, ra, "list_learnings")
    assert active.structuredContent["data"] == []


async def test_empty_key_scopes_and_invitation_are_not_access(team):
    a = team.identities[0]
    repo = team.repos[0]
    with pytest.raises(HTTPException) as denied:
        await authorized_repo(str(repo.id), AuthContext(a.user_id, a.org_id, [], "api_key"))
    assert denied.value.status_code == 403
    from sqlalchemy import update

    async with team.sessions() as session:
        await session.execute(
            update(OrgMembership).where(OrgMembership.user_id == a.user_id).values(accepted_at=None)
        )
        await session.commit()
    with pytest.raises(HTTPException) as denied:
        await authorized_repo(str(repo.id), a)
    assert denied.value.status_code == 404


async def test_remote_catalog_reports_only_supported_operations(team):
    names = {tool.name for tool in team.gateway.catalog()}
    assert {"record_learning", "security_scan", "snapshot_list", "pin_resolve"} <= names
    assert not {"snapshot_restore", "notify_file_changed", "clear_all"} & names


def test_team_repository_sources_cannot_select_server_files(monkeypatch):
    from attocode_intel.api.repository_source import validate_remote_source
    monkeypatch.setattr("attocode_intel.api.deps.get_config", lambda: SimpleNamespace(is_service_mode=True))
    for source in ("/private/repository", "file:///private/repository", "../another-org/repo"):
        with pytest.raises(HTTPException):
            validate_remote_source(clone_url=source)
    with pytest.raises(HTTPException):
        validate_remote_source(local_path="/private/repository")
    validate_remote_source(clone_url="https://github.com/example/repo.git")
    validate_remote_source(clone_url="git@example.com:team/repo.git")


async def test_native_http_auth_profiles_resources_and_legacy_knowledge(
    team, monkeypatch, tmp_path
):
    import httpx
    from attocode_intel.api.app import create_app
    from attocode_intel.api.auth.jwt import create_access_token
    from attocode_intel.config import CodeIntelConfig

    config = CodeIntelConfig(
        database_url="postgresql+asyncpg://unused",
        secret_key="test-signing-key-for-native-http",
        git_clone_dir=str(tmp_path / "http-snapshots"),
    )
    app = create_app(config)
    a, b = team.identities
    ra, rb = team.repos
    # JWT verification is real; repository/membership SQL uses the fixture database.
    headers = {
        "Authorization": "Bearer " + create_access_token(a.user_id, a.org_id),
        "X-Attocode-Workspace": str(ra.id),
        "X-Attocode-Profile": "daily",
        "Accept": "application/json, text/event-stream",
    }

    # Token revocation queries use a separate table already covered by auth tests.
    async def not_revoked(*args):
        return False

    monkeypatch.setattr("attocode_intel.api.auth._is_token_revoked", not_revoked)
    transport = app.state.mcp_transport
    try:
        async with (
            transport.manager.run(),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            body = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            }
            assert (await client.post("/mcp/", json=body)).status_code == 401
            assert (await client.post("/mcp/", json=body, headers=headers)).status_code == 200
            body.update(method="tools/list", params={})
            tools = (await client.post("/mcp/", json=body, headers=headers)).json()["result"][
                "tools"
            ]
            assert "analyze" not in {tool["name"] for tool in tools}
            body.update(
                method="tools/call", params={"name": "symbols", "arguments": {"path": "helper.py"}}
            )
            result = (await client.post("/mcp/", json=body, headers=headers)).json()["result"]
            assert not result.get("isError"), result
            assert "alpha_only" in result["content"][0]["text"]
            body.update(
                method="resources/read",
                params={"uri": f"attocode://project/helper.py?workspace={rb.id}"},
            )
            denied = (await client.post("/mcp/", json=body, headers=headers)).json()
            assert "error" in denied, denied
            # Old HTTP writers and the new operation readers share PostgreSQL knowledge.
            response = await client.post(
                f"/api/v1/projects/{ra.id}/learnings",
                headers=headers,
                json={"type": "convention", "description": "Shared across transports"},
            )
            assert response.status_code == 200, response.text
            response = await client.post(
                "/api/v2/operations/list_learnings", headers=headers, json={"workspace": str(ra.id)}
            )
            assert response.status_code == 200, response.text
            assert response.json()["data"][0]["description"] == "Shared across transports"
            response = await client.post(
                "/api/v2/operations/symbols",
                headers=headers,
                json={"workspace": str(ra.id), "path": 123},
            )
            assert response.status_code == 422
    finally:
        await transport.gateway.close()
