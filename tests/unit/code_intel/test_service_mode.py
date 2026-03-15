"""Tests for service mode infrastructure (config, auth, models, middleware)."""

from __future__ import annotations

import hashlib
import os
import time
import uuid

import pytest

from attocode.code_intel.api import deps
from attocode.code_intel.config import CodeIntelConfig

# Skip tests requiring service deps if not installed
try:
    import jose  # noqa: F401
    import bcrypt  # noqa: F401
    HAS_SERVICE_DEPS = True
except ImportError:
    HAS_SERVICE_DEPS = False

try:
    import sqlalchemy  # noqa: F401
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False

requires_service_deps = pytest.mark.skipif(
    not HAS_SERVICE_DEPS, reason="Service dependencies (python-jose, bcrypt) not installed"
)
requires_sqlalchemy = pytest.mark.skipif(
    not HAS_SQLALCHEMY, reason="SQLAlchemy not installed"
)


@pytest.fixture(autouse=True)
def _reset():
    deps.reset()
    yield
    deps.reset()


# --- Config ---


class TestServiceModeConfig:
    def test_defaults_not_service_mode(self):
        cfg = CodeIntelConfig()
        assert not cfg.is_service_mode
        assert cfg.database_url == ""
        assert cfg.secret_key == ""
        assert cfg.redis_url == ""

    def test_service_mode_with_database_url(self):
        cfg = CodeIntelConfig(database_url="postgresql+asyncpg://localhost/test")
        assert cfg.is_service_mode

    def test_from_env_service_fields(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost/test")
        monkeypatch.setenv("SECRET_KEY", "mysecret")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("GIT_CLONE_DIR", "/tmp/clones")
        monkeypatch.setenv("GIT_CLONE_MAX_GB", "25")
        monkeypatch.setenv("JWT_EXPIRY_MINUTES", "120")
        monkeypatch.setenv("REFRESH_EXPIRY_DAYS", "7")

        cfg = CodeIntelConfig.from_env()
        assert cfg.is_service_mode
        assert cfg.database_url == "postgresql+asyncpg://localhost/test"
        assert cfg.secret_key == "mysecret"
        assert cfg.redis_url == "redis://localhost:6379/0"
        assert cfg.git_clone_dir == "/tmp/clones"
        assert cfg.git_clone_max_gb == 25.0
        assert cfg.jwt_expiry_minutes == 120
        assert cfg.refresh_expiry_days == 7

    def test_from_env_defaults_no_service(self, monkeypatch):
        for var in ("DATABASE_URL", "SECRET_KEY", "REDIS_URL"):
            monkeypatch.delenv(var, raising=False)
        cfg = CodeIntelConfig.from_env()
        assert not cfg.is_service_mode
        assert cfg.git_clone_dir == "/var/lib/code-intel/repos"
        assert cfg.git_clone_max_gb == 50.0

    def test_backward_compat_fields(self):
        """Original Phase 1 fields still work."""
        cfg = CodeIntelConfig(
            project_dir="/tmp", host="0.0.0.0", port=9090,
            api_key="secret", cors_origins=["http://a.com"], log_level="debug",
        )
        assert cfg.project_dir == "/tmp"
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 9090


# --- Auth Context ---


class TestAuthContext:
    def test_legacy_context(self):
        from attocode.code_intel.api.auth.context import AuthContext

        ctx = AuthContext()
        assert ctx.auth_method == "legacy"
        assert ctx.user_id is None
        assert ctx.has_scope("anything")  # Empty scopes = full access

    def test_scoped_context(self):
        from attocode.code_intel.api.auth.context import AuthContext

        ctx = AuthContext(scopes=["read:symbols", "read:analysis"])
        assert ctx.has_scope("read:symbols")
        assert not ctx.has_scope("admin:org")

    def test_require_scope_raises(self):
        from fastapi import HTTPException

        from attocode.code_intel.api.auth.context import AuthContext

        ctx = AuthContext(scopes=["read:symbols"])
        with pytest.raises(HTTPException) as exc_info:
            ctx.require_scope("admin:org")
        assert exc_info.value.status_code == 403


# --- JWT ---


@requires_service_deps
class TestJWT:
    def test_create_and_decode_access_token(self):
        from attocode.code_intel.api.auth.jwt import create_access_token, decode_token

        deps.configure(CodeIntelConfig(secret_key="test-secret"))
        user_id = uuid.uuid4()
        org_id = uuid.uuid4()

        token = create_access_token(
            user_id=user_id, org_id=org_id,
            scopes=["read:symbols"], plan="team",
        )
        payload = decode_token(token)

        assert payload is not None
        assert payload["sub"] == str(user_id)
        assert payload["org"] == str(org_id)
        assert payload["scopes"] == ["read:symbols"]
        assert payload["plan"] == "team"
        assert payload["type"] == "access"

    def test_create_and_decode_refresh_token(self):
        from attocode.code_intel.api.auth.jwt import create_refresh_token, decode_token

        deps.configure(CodeIntelConfig(secret_key="test-secret"))
        user_id = uuid.uuid4()

        token = create_refresh_token(user_id)
        payload = decode_token(token)

        assert payload is not None
        assert payload["sub"] == str(user_id)
        assert payload["type"] == "refresh"

    def test_decode_invalid_token(self):
        from attocode.code_intel.api.auth.jwt import decode_token

        deps.configure(CodeIntelConfig(secret_key="test-secret"))
        assert decode_token("garbage.token.here") is None

    def test_decode_wrong_secret(self):
        from attocode.code_intel.api.auth.jwt import create_access_token, decode_token

        deps.configure(CodeIntelConfig(secret_key="secret-a"))
        token = create_access_token(uuid.uuid4())

        deps.configure(CodeIntelConfig(secret_key="secret-b"))
        assert decode_token(token) is None


# --- Passwords ---


@requires_service_deps
class TestPasswords:
    def test_hash_and_verify(self):
        from attocode.code_intel.api.auth.passwords import hash_password, verify_password

        hashed = hash_password("mypassword")
        assert hashed != "mypassword"
        assert verify_password("mypassword", hashed)
        assert not verify_password("wrong", hashed)

    def test_different_hashes(self):
        from attocode.code_intel.api.auth.passwords import hash_password

        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # bcrypt salts differ


# --- API Key Generation ---


@requires_service_deps
class TestApiKeyGen:
    def test_generate_api_key_format(self):
        from attocode.code_intel.api.auth.api_keys import generate_api_key

        plaintext, key_hash, key_prefix = generate_api_key()
        assert plaintext.startswith("aci_")
        assert len(key_prefix) == 12
        assert key_prefix == plaintext[:12]
        assert key_hash == hashlib.sha256(plaintext.encode()).hexdigest()

    def test_generate_unique(self):
        from attocode.code_intel.api.auth.api_keys import generate_api_key

        keys = {generate_api_key()[0] for _ in range(10)}
        assert len(keys) == 10  # All unique


# --- Rate Limiter ---


class TestRateLimiter:
    def test_allows_within_limit(self):
        from attocode.code_intel.api.middleware import RateLimitMiddleware

        mw = RateLimitMiddleware(app=None, requests_per_minute=5)
        now = time.monotonic()
        for _ in range(5):
            allowed, remaining, _ = mw._check_and_record("test", now)
            assert allowed

    def test_blocks_over_limit(self):
        from attocode.code_intel.api.middleware import RateLimitMiddleware

        mw = RateLimitMiddleware(app=None, requests_per_minute=3)
        now = time.monotonic()
        for _ in range(3):
            mw._check_and_record("test", now)

        allowed, remaining, _ = mw._check_and_record("test", now)
        assert not allowed
        assert remaining == 0

    def test_window_expires(self):
        from attocode.code_intel.api.middleware import RateLimitMiddleware

        mw = RateLimitMiddleware(app=None, requests_per_minute=2)
        now = time.monotonic()
        mw._check_and_record("test", now)
        mw._check_and_record("test", now)

        # 61 seconds later, window should have expired
        allowed, _, _ = mw._check_and_record("test", now + 61)
        assert allowed

    def test_separate_keys(self):
        from attocode.code_intel.api.middleware import RateLimitMiddleware

        mw = RateLimitMiddleware(app=None, requests_per_minute=1)
        now = time.monotonic()
        mw._check_and_record("user-a", now)
        allowed, _, _ = mw._check_and_record("user-b", now)
        assert allowed  # Different key, not rate limited


# --- Resolve Auth ---


@requires_service_deps
class TestResolveAuth:
    @pytest.mark.asyncio
    async def test_legacy_mode_no_key(self):
        from attocode.code_intel.api.auth import resolve_auth

        deps.configure(CodeIntelConfig(api_key=""))
        ctx = await resolve_auth(authorization=None)
        assert ctx.auth_method == "legacy"

    @pytest.mark.asyncio
    async def test_legacy_mode_with_key(self):
        from attocode.code_intel.api.auth import resolve_auth

        deps.configure(CodeIntelConfig(api_key="secret"))
        ctx = await resolve_auth(authorization="Bearer secret")
        assert ctx.auth_method == "legacy"

    @pytest.mark.asyncio
    async def test_legacy_mode_wrong_key_401(self):
        from fastapi import HTTPException

        from attocode.code_intel.api.auth import resolve_auth

        deps.configure(CodeIntelConfig(api_key="secret"))
        with pytest.raises(HTTPException) as exc_info:
            await resolve_auth(authorization="Bearer wrong")
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_service_mode_jwt(self):
        from attocode.code_intel.api.auth import resolve_auth
        from attocode.code_intel.api.auth.jwt import create_access_token

        deps.configure(CodeIntelConfig(
            database_url="postgresql+asyncpg://localhost/test",
            secret_key="test-secret",
        ))
        user_id = uuid.uuid4()
        org_id = uuid.uuid4()
        token = create_access_token(user_id, org_id, scopes=["read:symbols"])

        ctx = await resolve_auth(authorization=f"Bearer {token}")
        assert ctx.auth_method == "jwt"
        assert ctx.user_id == user_id
        assert ctx.org_id == org_id

    @pytest.mark.asyncio
    async def test_service_mode_no_header_401(self):
        from fastapi import HTTPException

        from attocode.code_intel.api.auth import resolve_auth

        deps.configure(CodeIntelConfig(
            database_url="postgresql+asyncpg://localhost/test",
            secret_key="test-secret",
        ))
        with pytest.raises(HTTPException) as exc_info:
            await resolve_auth(authorization=None)
        assert exc_info.value.status_code == 401


# --- Content Store (unit, no DB) ---


@requires_sqlalchemy
class TestContentStoreHash:
    def test_hash_content(self):
        from attocode.code_intel.storage.content_store import ContentStore

        content = b"hello world"
        sha = ContentStore.hash_content(content)
        assert sha == hashlib.sha256(content).hexdigest()

    def test_hash_deterministic(self):
        from attocode.code_intel.storage.content_store import ContentStore

        assert ContentStore.hash_content(b"abc") == ContentStore.hash_content(b"abc")


# --- Git Models ---


class TestGitModels:
    def test_branch_info(self):
        from attocode.code_intel.git.models import BranchInfo

        b = BranchInfo(name="main", commit="abc123", is_default=True)
        assert b.name == "main"
        assert b.is_default

    def test_diff_entry(self):
        from attocode.code_intel.git.models import DiffEntry

        d = DiffEntry(path="src/a.py", status="modified", additions=10, deletions=5)
        assert d.status == "modified"
        assert d.old_path is None

    def test_tree_entry(self):
        from attocode.code_intel.git.models import TreeEntry

        t = TreeEntry(name="file.py", path="src/file.py", type="blob", size=100)
        assert t.type == "blob"


# --- Clone Storage Manager ---


class TestCloneStorageManager:
    def test_init_creates_dir(self, tmp_path):
        from attocode.code_intel.git.storage import CloneStorageManager

        mgr = CloneStorageManager(str(tmp_path / "clones"), max_gb=1.0)
        assert (tmp_path / "clones").exists()

    def test_total_usage_empty(self, tmp_path):
        from attocode.code_intel.git.storage import CloneStorageManager

        mgr = CloneStorageManager(str(tmp_path / "clones"))
        assert mgr.total_usage() == 0

    def test_has_space(self, tmp_path):
        from attocode.code_intel.git.storage import CloneStorageManager

        mgr = CloneStorageManager(str(tmp_path / "clones"), max_gb=1.0)
        assert mgr.has_space()
        assert mgr.has_space(1024)

    def test_stats(self, tmp_path):
        from attocode.code_intel.git.storage import CloneStorageManager

        mgr = CloneStorageManager(str(tmp_path / "clones"), max_gb=10.0)
        stats = mgr.stats()
        assert stats["total_bytes"] == 0
        assert stats["clone_count"] == 0
        assert stats["usage_pct"] == 0.0


# --- Parser ---


class TestParser:
    def test_detect_language(self):
        from attocode.code_intel.indexing.parser import detect_language

        assert detect_language("foo.py") == "python"
        assert detect_language("bar.js") == "javascript"
        assert detect_language("baz.ts") == "typescript"
        assert detect_language("qux.go") == "go"
        assert detect_language("unknown.xyz") is None

    def test_extract_symbols_python(self):
        from attocode.code_intel.indexing.parser import extract_symbols

        code = b"def hello():\n    pass\n\nclass Foo:\n    pass\n"
        symbols = extract_symbols(code, "test.py")
        names = {s["name"] for s in symbols}
        assert "hello" in names
        assert "Foo" in names

    def test_extract_symbols_unknown_ext(self):
        from attocode.code_intel.indexing.parser import extract_symbols

        symbols = extract_symbols(b"some content", "file.xyz")
        assert symbols == []


# --- DB Session Dependency ---


@requires_sqlalchemy
class TestDbSessionDep:
    @pytest.mark.asyncio
    async def test_raises_503_when_not_service_mode(self):
        from fastapi import HTTPException

        deps.configure(CodeIntelConfig())  # No DATABASE_URL
        with pytest.raises(HTTPException) as exc_info:
            async for _ in deps.get_db_session():
                pass
        assert exc_info.value.status_code == 503


# --- Content-Hash Gating ---


class TestContentHashGating:
    """Test that content-hash comparison correctly detects changes."""

    def test_unchanged_file_same_hash(self):
        from attocode.code_intel.storage.content_store import ContentStore

        content = b"print('hello')"
        sha = ContentStore.hash_content(content)
        manifest = {"test.py": sha}
        assert ContentStore.hash_content(content) == manifest.get("test.py")

    def test_changed_file_different_hash(self):
        from attocode.code_intel.storage.content_store import ContentStore

        old_sha = ContentStore.hash_content(b"print('hello')")
        new_sha = ContentStore.hash_content(b"print('world')")
        manifest = {"test.py": old_sha}
        assert new_sha != manifest.get("test.py")

    def test_new_file_not_in_manifest(self):
        manifest: dict[str, str] = {}
        assert manifest.get("new.py") is None


# --- Parse Content Bridge ---


class TestParseContentBridge:
    """Test the parse_content bridge function for the incremental pipeline."""

    def test_returns_structured_result(self):
        from attocode.code_intel.indexing.parser import parse_content

        code = b"def foo(): pass"
        result = parse_content("abc123", code, "test.py")
        assert result["content_sha"] == "abc123"
        assert result["language"] == "python"
        assert len(result["symbols"]) >= 1
        assert result["symbols"][0]["name"] == "foo"

    def test_extracts_python_imports(self):
        from attocode.code_intel.indexing.parser import parse_content

        code = b"import os\nfrom pathlib import Path\nimport sys"
        result = parse_content("sha", code, "test.py")
        assert "os" in result["imports"]
        assert "pathlib" in result["imports"]
        assert "sys" in result["imports"]

    def test_extracts_js_imports(self):
        from attocode.code_intel.indexing.parser import parse_content

        code = b"import React from 'react';\nconst fs = require('fs');"
        result = parse_content("sha", code, "test.js")
        assert "react" in result["imports"]
        assert "fs" in result["imports"]

    def test_unknown_language_empty(self):
        from attocode.code_intel.indexing.parser import parse_content

        result = parse_content("sha", b"data", "file.xyz")
        assert result["language"] is None
        assert result["symbols"] == []
        assert result["imports"] == []


# --- Debouncer ---


import asyncio


class TestDebouncer:
    """Test the per-project file change debouncer."""

    @pytest.mark.asyncio
    async def test_batches_multiple_notifications(self):
        from attocode.code_intel.indexing.debouncer import FileChangeDebouncer

        received = []

        async def handler(project_id, branch, paths, files=None):
            received.append((project_id, branch, sorted(paths)))

        debouncer = FileChangeDebouncer(handler=handler, delay_seconds=0.1)

        await debouncer.notify("proj1", "main", ["a.py"])
        await debouncer.notify("proj1", "main", ["b.py"])
        await debouncer.notify("proj1", "main", ["c.py"])

        await asyncio.sleep(0.2)
        assert len(received) == 1
        assert received[0] == ("proj1", "main", ["a.py", "b.py", "c.py"])
        await debouncer.shutdown()

    @pytest.mark.asyncio
    async def test_separate_branches_separate_batches(self):
        from attocode.code_intel.indexing.debouncer import FileChangeDebouncer

        received = []

        async def handler(project_id, branch, paths, files=None):
            received.append((project_id, branch))

        debouncer = FileChangeDebouncer(handler=handler, delay_seconds=0.1)

        await debouncer.notify("proj1", "main", ["a.py"])
        await debouncer.notify("proj1", "feat/x", ["b.py"])

        await asyncio.sleep(0.2)
        assert len(received) == 2
        branches = {r[1] for r in received}
        assert branches == {"main", "feat/x"}
        await debouncer.shutdown()

    @pytest.mark.asyncio
    async def test_dedup_paths_within_batch(self):
        from attocode.code_intel.indexing.debouncer import FileChangeDebouncer

        received = []

        async def handler(project_id, branch, paths, files=None):
            received.append(paths)

        debouncer = FileChangeDebouncer(handler=handler, delay_seconds=0.1)

        await debouncer.notify("proj1", "main", ["a.py", "b.py"])
        await debouncer.notify("proj1", "main", ["a.py"])  # duplicate

        await asyncio.sleep(0.2)
        assert len(received) == 1
        assert len(received[0]) == 2  # a.py and b.py, not 3
        await debouncer.shutdown()

    @pytest.mark.asyncio
    async def test_flush_fires_immediately(self):
        from attocode.code_intel.indexing.debouncer import FileChangeDebouncer

        received = []

        async def handler(project_id, branch, paths, files=None):
            received.append(paths)

        debouncer = FileChangeDebouncer(handler=handler, delay_seconds=10.0)

        await debouncer.notify("proj1", "main", ["a.py"])
        await debouncer.flush("proj1", "main")

        assert len(received) == 1
        await debouncer.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_cancels_pending(self):
        from attocode.code_intel.indexing.debouncer import FileChangeDebouncer

        received = []

        async def handler(project_id, branch, paths, files=None):
            received.append(paths)

        debouncer = FileChangeDebouncer(handler=handler, delay_seconds=10.0)

        await debouncer.notify("proj1", "main", ["a.py"])
        await debouncer.shutdown()

        await asyncio.sleep(0.1)
        assert len(received) == 0
        assert debouncer.pending_count == 0


# --- Notify Route Models ---


class TestNotifyModels:
    def test_file_changed_request(self):
        from attocode.code_intel.api.routes.notify import FileChangedRequest

        req = FileChangedRequest(paths=["a.py", "b.py"], project="proj1", branch="main")
        assert len(req.paths) == 2
        assert req.branch == "main"

    def test_file_changed_request_defaults(self):
        from attocode.code_intel.api.routes.notify import FileChangedRequest

        req = FileChangedRequest(paths=["a.py"])
        assert req.project == ""
        assert req.branch == ""

    def test_file_changed_response(self):
        from attocode.code_intel.api.routes.notify import FileChangedResponse

        resp = FileChangedResponse(accepted=3)
        assert resp.accepted == 3
        assert resp.message == "Accepted"


# --- Branch Context ---


class TestBranchContext:
    def test_branch_context_properties(self):
        from attocode.code_intel.api.deps import BranchContext

        ctx = BranchContext(
            branch_id=uuid.uuid4(),
            branch_name="feat/x",
            manifest={"a.py": "sha1", "b.py": "sha2"},
            version=5,
        )
        assert ctx.branch_name == "feat/x"
        assert ctx.version == 5
        assert ctx.content_shas == {"sha1", "sha2"}
        assert ctx.sha_to_path == {"sha1": "a.py", "sha2": "b.py"}

    def test_branch_context_empty_manifest(self):
        from attocode.code_intel.api.deps import BranchContext

        ctx = BranchContext(
            branch_id=uuid.uuid4(),
            branch_name="main",
            manifest={},
        )
        assert ctx.content_shas == set()
        assert ctx.sha_to_path == {}


# --- C1: Path Traversal Prevention ---


class TestPathTraversalPrevention:
    """C1: Verify _read_file blocks directory traversal."""

    @pytest.mark.asyncio
    async def test_rejects_path_traversal(self, tmp_path):
        from attocode.code_intel.indexing.incremental import IncrementalPipeline

        # Create a mock session (not used for local mode reads)
        class FakeSession:
            pass

        pipeline = IncrementalPipeline.__new__(IncrementalPipeline)
        with pytest.raises(ValueError, match="Path traversal detected"):
            await pipeline._read_file(
                "../../etc/passwd", str(tmp_path), None, None, None
            )

    @pytest.mark.asyncio
    async def test_allows_normal_paths(self, tmp_path):
        from attocode.code_intel.indexing.incremental import IncrementalPipeline

        # Create a file inside base_dir
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "test.py").write_bytes(b"print('hello')")

        pipeline = IncrementalPipeline.__new__(IncrementalPipeline)
        content = await pipeline._read_file(
            "src/test.py", str(tmp_path), None, None, None
        )
        assert content == b"print('hello')"

    @pytest.mark.asyncio
    async def test_missing_file_returns_none(self, tmp_path):
        from attocode.code_intel.indexing.incremental import IncrementalPipeline

        pipeline = IncrementalPipeline.__new__(IncrementalPipeline)
        content = await pipeline._read_file(
            "nonexistent.py", str(tmp_path), None, None, None
        )
        assert content is None


# --- M3: Go Import Regex ---


class TestGoImportRegex:
    """M3: Verify Go import extraction only matches import blocks."""

    def test_go_import_block(self):
        from attocode.code_intel.indexing.parser import parse_content

        code = b'''package main

import (
    "fmt"
    "os"
)

func main() {
    x := "not-an-import"
    fmt.Println(x)
}
'''
        result = parse_content("sha", code, "main.go")
        assert "fmt" in result["imports"]
        assert "os" in result["imports"]
        # M3: "not-an-import" should NOT be captured
        assert "not-an-import" not in result["imports"]

    def test_go_single_import(self):
        from attocode.code_intel.indexing.parser import parse_content

        code = b'''package main

import "fmt"

func main() {}
'''
        result = parse_content("sha", code, "main.go")
        assert "fmt" in result["imports"]


# --- N7: Better Content Hash Gating Tests ---


class TestContentHashEdgeCases:
    """N7: Replace tautological tests with meaningful edge cases."""

    def test_empty_content_has_consistent_hash(self):
        from attocode.code_intel.storage.content_store import ContentStore

        sha1 = ContentStore.hash_content(b"")
        sha2 = ContentStore.hash_content(b"")
        assert sha1 == sha2
        assert len(sha1) == 64  # SHA-256 hex length

    def test_whitespace_only_differs_from_empty(self):
        from attocode.code_intel.storage.content_store import ContentStore

        assert ContentStore.hash_content(b"") != ContentStore.hash_content(b" ")
        assert ContentStore.hash_content(b"\n") != ContentStore.hash_content(b"\r\n")

    def test_binary_content_hashes(self):
        from attocode.code_intel.storage.content_store import ContentStore

        binary = bytes(range(256))
        sha = ContentStore.hash_content(binary)
        assert ContentStore.hash_content(binary) == sha

    def test_large_content_hashes_consistently(self):
        from attocode.code_intel.storage.content_store import ContentStore

        large = b"x" * 1_000_000
        sha1 = ContentStore.hash_content(large)
        sha2 = ContentStore.hash_content(large)
        assert sha1 == sha2


# --- Debouncer Max Pending ---


class TestDebouncerMaxPending:
    """M9: Verify debouncer caps pending paths."""

    @pytest.mark.asyncio
    async def test_caps_pending_paths(self):
        from attocode.code_intel.indexing.debouncer import FileChangeDebouncer

        received = []

        async def handler(project_id, branch, paths, files=None):
            received.append(paths)

        debouncer = FileChangeDebouncer(
            handler=handler, delay_seconds=10.0, max_pending_per_key=5
        )

        # Add more paths than the cap
        await debouncer.notify("proj1", "main", [f"file{i}.py" for i in range(10)])
        # Pending should be capped
        key = ("proj1", "main")
        assert len(debouncer._pending[key]) <= 5

        await debouncer.shutdown()


# --- BranchParam shared import ---


class TestSharedBranchParam:
    """N2: Verify BranchParam is importable from deps."""

    def test_branch_param_importable(self):
        from attocode.code_intel.api.deps import BranchParam

        assert BranchParam is not None
