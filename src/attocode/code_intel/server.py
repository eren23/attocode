"""MCP server exposing Attocode's code intelligence capabilities.

Provides 48 tools for deep codebase understanding:
- bootstrap: All-in-one orientation (summary + map + conventions + search)
- relevant_context: Subgraph capsule for file(s) with neighbors and symbols
- repo_map: Token-budgeted file tree with symbols
- symbols: List symbols in a file
- search_symbols: Fuzzy symbol search across codebase
- dependencies: File import/importer relationships
- impact_analysis: Transitive impact of file changes (BFS)
- cross_references: Symbol definitions + usage sites
- file_analysis: Detailed single-file analysis
- dependency_graph: Dependency graph from a starting file
- project_summary: High-level project overview (CLAUDE.md bootstrap)
- hotspots: Risk/complexity analysis with ranked hotspots
- conventions: Code style and convention detection (with optional directory scoping)
- lsp_definition: Type-resolved go-to-definition
- lsp_references: All references with type awareness
- lsp_hover: Type signature + docs for symbol
- lsp_diagnostics: Errors/warnings from language server
- graph_query: Raw graph traversal query
- graph_dsl: Graph query language for dependency traversal
- explore_codebase: Hierarchical drill-down navigation
- find_related: Find files related to a given file
- community_detection: Detect module communities in the dependency graph
- security_scan: Secret/anti-pattern/dependency scanning
- semantic_search: Natural language code search
- semantic_search_status: Check embedding index progress
- analyze: Rule-based analysis with language packs (Go, Python, TS, Rust, Java)
- list_rules: Browse available analysis rules by language/category/severity
- list_packs: List installed language analysis packs
- install_pack: Install a language analysis pack (go, python, ts, rust, java)
- register_rule: Register a custom YAML rule at runtime
- notify_file_changed: Notify server of external file modifications
- recall: Retrieve relevant project learnings
- record_learning: Record patterns/conventions/gotchas
- learning_feedback: Mark learnings as helpful/unhelpful
- list_learnings: Browse stored learnings
- record_adr: Record an architecture decision
- list_adrs: Browse architecture decision records
- get_adr: Get full details of an ADR
- update_adr_status: Update ADR lifecycle status
- dead_code: Detect unreachable/unused code
- distill: Distill code into compressed representations
- code_evolution: Trace how code has changed over time
- recent_changes: Show recent file modifications
- review_change: Unified change review (security + conventions)
- explain_impact: Blast radius explanation with risk assessment
- suggest_tests: Test file recommendations for changed files

Usage::

    attocode-code-intel --project /path/to/repo

Remote mode (proxy through a remote code-intel HTTP server)::

    attocode-code-intel --project . --remote https://code.example.com --remote-token <jwt> --remote-repo <uuid>

Remote connection can also be auto-loaded from ``.attocode/config.toml``
(created by ``attocode code-intel connect``).
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path

import attocode.code_intel._shared as _shared  # noqa: F401

# ---------------------------------------------------------------------------
# Shared deps (mcp instance, lazy singletons, getters) live in _shared.py
# to break the circular import: server.py → tool modules → server.py.
# Re-exported here for backward compatibility.
# ---------------------------------------------------------------------------
from attocode.code_intel._shared import (  # noqa: F401
    _get_ast_service,
    _get_code_analyzer,
    _get_context_mgr,
    _get_explorer,
    _get_project_dir,
    _walk_up,
    clear_remote_service,
    configure_remote_service,
    mcp,
)

logger = logging.getLogger(__name__)

# Backward-compat: tests and internal code set server._ast_service = mock.
# The getters (in _shared) read _shared._ast_service, so we must ensure
# that setting server._ast_service also sets _shared._ast_service.
# We do this by NOT declaring local variables here and using __getattr__
# to proxy reads, plus __setattr__ to proxy writes via setattr().
_SINGLETON_VARS = frozenset({
    "_ast_service", "_context_mgr", "_code_analyzer",
    "_semantic_search", "_memory_store", "_explorer",
    "_service", "_remote_service",
})

def __getattr__(name: str):
    if name in _SINGLETON_VARS:
        return getattr(_shared, name, None)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# ---------------------------------------------------------------------------
# MCP Resource: Agent Guidelines
# ---------------------------------------------------------------------------

_GUIDELINES_PATH = Path(__file__).parent / "GUIDELINES.md"


@mcp.resource("attocode://guidelines")
def guidelines_resource() -> str:
    """Agent guidelines for using code intelligence tools effectively."""
    try:
        return _GUIDELINES_PATH.read_text(encoding="utf-8")
    except OSError:
        return "Guidelines file not found."


# ---------------------------------------------------------------------------
# MCP Resources: Project files and symbol lookup
# ---------------------------------------------------------------------------


@mcp.resource("attocode://project/{path}")
def project_file_resource(path: str) -> str:
    """File content with line numbers. Path-traversal protected.

    Args:
        path: Relative file path within the project.
    """
    project_dir = _get_project_dir()
    root = Path(os.path.realpath(project_dir))
    full = Path(os.path.realpath(os.path.join(project_dir, path)))
    if not full.is_relative_to(root):
        return "Error: path traversal not allowed."
    if not full.is_file():
        return f"Error: file not found: {path}"
    try:
        content = full.read_text(encoding="utf-8", errors="replace")
        lines = content.split("\n")
        numbered = [f"{i + 1:>5} | {line}" for i, line in enumerate(lines)]
        return "\n".join(numbered)
    except Exception as e:
        return f"Error reading file: {e}"


@mcp.resource("attocode://symbols/{name}")
def symbol_resource(name: str) -> str:
    """Symbol definition lookup with source snippets.

    Args:
        name: Symbol name to look up.
    """
    svc = _get_ast_service()
    defs = svc.find_symbol(name)
    if not defs:
        return f"No definitions found for '{name}'."

    project_dir = _get_project_dir()
    root = Path(os.path.realpath(project_dir))

    lines = [f"Definitions for '{name}':"]
    for d in defs[:10]:
        lines.append(f"\n  {d.file_path}:{d.start_line}")
        lines.append(f"    Qualified: {d.qualified_name}")
        # Try to read source snippet (path-traversal protected)
        try:
            full = Path(os.path.realpath(os.path.join(project_dir, d.file_path)))
            if not full.is_relative_to(root):
                continue
            src_lines = full.read_text(encoding="utf-8", errors="replace").split("\n")
            start = max(0, d.start_line - 1)
            end = min(len(src_lines), d.end_line + 1)
            for i in range(start, end):
                lines.append(f"    {i + 1:>5} | {src_lines[i]}")
        except Exception:
            pass
    return "\n".join(lines)


@mcp.resource("attocode://learnings")
def learnings_resource() -> str:
    """All active project learnings. Read this for full project knowledge base."""
    from attocode.code_intel.tools.learning_tools import _get_memory_store

    store = _get_memory_store()
    results = store.list_all(status="active")
    if not results:
        return "No project learnings recorded yet."

    lines = ["# Project Learnings\n"]
    by_type: dict[str, list[dict]] = {}
    for r in results:
        by_type.setdefault(r["type"], []).append(r)

    for type_name, entries in sorted(by_type.items()):
        lines.append(f"\n## {type_name.title()} ({len(entries)})\n")
        for r in entries:
            scope_tag = f" [{r['scope']}]" if r["scope"] else ""
            conf = f"{r['confidence']:.0%}"
            lines.append(f"- **{r['description']}**{scope_tag} (id: {r['id']}, confidence: {conf})")
            if r["details"]:
                lines.append(f"  {r['details']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Notification tool (explicit index update)
# ---------------------------------------------------------------------------


@mcp.tool()
def notify_file_changed(files: list[str]) -> str:
    """Notify the server that files have been modified externally.

    Call this after editing files to immediately update the AST index
    and invalidate stale semantic search embeddings. Useful when the
    file watcher is unavailable or for batch updates.

    Args:
        files: List of file paths (relative or absolute) that changed.
    """
    if not files:
        return "No files specified."

    project_dir = _get_project_dir()
    svc = _get_ast_service()
    updated = 0

    for f in files:
        try:
            p = Path(f)
            rel = os.path.relpath(str(p), project_dir) if p.is_absolute() else str(p)
            # Guard against path traversal
            rel = os.path.normpath(rel)
            if rel.startswith(".."):
                continue
            svc.notify_file_changed(rel)
            # Also invalidate semantic search embeddings
            try:
                smgr = _semantic_search
                if smgr is None:
                    from attocode.code_intel.tools.search_tools import _get_semantic_search
                    smgr = _get_semantic_search()
                abs_path = os.path.join(project_dir, rel)
                smgr.invalidate_file(abs_path)
                smgr.queue_reindex(abs_path)
            except Exception:
                pass
            # Also invalidate trigram index
            try:
                from attocode.code_intel.tools.search_tools import _get_trigram_index
                tri_idx = _get_trigram_index()
                if tri_idx is not None:
                    abs_path = os.path.join(project_dir, rel)
                    tri_idx.update_file(rel, b"")
            except Exception:
                pass
            updated += 1
        except Exception as exc:
            logger.debug("notify_file_changed: error for %s: %s", f, exc)

    # Also drain the notification queue (CLI-written)
    queued = _process_notification_queue()

    total = updated + queued
    return f"Updated {total} file(s). AST index refreshed."


# ---------------------------------------------------------------------------
# Notification queue (CLI -> server communication)
# ---------------------------------------------------------------------------


def _get_queue_path() -> Path:
    """Return the path to the notification queue file."""
    return Path(_get_project_dir()) / ".attocode" / "cache" / "file_changes"


_queue_lock = threading.Lock()


def _process_notification_queue() -> int:
    """Check the notification queue file and process pending changes.

    Returns number of files processed.
    """
    with _queue_lock:
        return _process_notification_queue_locked()


def _process_notification_queue_locked() -> int:
    """Inner implementation -- must be called under ``_queue_lock``."""
    try:
        queue_path = _get_queue_path()
    except RuntimeError:
        return 0

    if not queue_path.exists():
        return 0

    try:
        # Atomic read-and-truncate under exclusive lock to avoid TOCTOU
        try:
            import fcntl
            with open(queue_path, "r+", encoding="utf-8") as fh:
                fcntl.flock(fh, fcntl.LOCK_EX)
                content = fh.read()
                fh.seek(0)
                fh.truncate()
        except ImportError:
            # Windows: fall back to non-locked read+truncate
            content = queue_path.read_text(encoding="utf-8")
            queue_path.write_text("", encoding="utf-8")
    except OSError:
        return 0

    paths = [line.strip() for line in content.splitlines() if line.strip()]
    if not paths:
        return 0

    project_dir = _get_project_dir()
    svc = _get_ast_service()
    count = 0

    for rel in paths:
        # Guard against path traversal (e.g. ../../etc/passwd)
        norm = os.path.normpath(rel)
        if norm.startswith(".."):
            continue
        try:
            svc.notify_file_changed(norm)
            try:
                smgr = _semantic_search
                if smgr is None:
                    from attocode.code_intel.tools.search_tools import _get_semantic_search
                    smgr = _get_semantic_search()
                abs_path = os.path.join(project_dir, norm)
                smgr.invalidate_file(abs_path)
                smgr.queue_reindex(abs_path)
            except Exception:
                pass
            try:
                from attocode.code_intel.tools.search_tools import _get_trigram_index
                tri_idx = _get_trigram_index()
                if tri_idx is not None:
                    tri_idx.update_file(norm, b"")
            except Exception:
                pass
            count += 1
        except Exception:
            pass

    if count:
        logger.debug("Processed %d queued file notification(s)", count)
    return count


_queue_thread: threading.Thread | None = None


def _start_queue_poller(project_dir: str) -> None:
    """Start a background thread that polls the notification queue every 2s."""
    global _queue_thread

    if _queue_thread is not None:
        return

    def _poll_loop() -> None:
        while not _watcher_stop.is_set():
            try:
                _process_notification_queue()
            except Exception:
                pass
            _watcher_stop.wait(2.0)

    _queue_thread = threading.Thread(
        target=_poll_loop, daemon=True, name="code-intel-queue-poller"
    )
    _queue_thread.start()
    logger.debug("Notification queue poller started")


# ---------------------------------------------------------------------------
# File watcher (background thread)
# ---------------------------------------------------------------------------

_CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java",
    ".rb", ".c", ".cpp", ".h", ".hpp", ".cs", ".swift", ".kt",
    ".scala", ".sc", ".ex", ".exs", ".zig", ".hs", ".tf", ".tfvars",
    ".hcl", ".lua", ".sh", ".bash", ".php",
}

_watcher_thread: threading.Thread | None = None
_watcher_stop = threading.Event()


def _start_file_watcher(project_dir: str, *, debounce_ms: int = 500) -> None:
    """Start a background file watcher that updates the AST index on changes.

    Uses watchfiles (Rust-backed) if available, otherwise skips silently.
    Calls ASTService.notify_file_changed() and queues background reindex for
    modified code files. Second call is a no-op (idempotent).

    Args:
        project_dir: Absolute path to the project root.
        debounce_ms: Debounce interval in milliseconds (default 500ms).
    """
    global _watcher_thread

    if _watcher_thread is not None:
        return  # Already running

    try:
        from watchfiles import Change, watch
    except ImportError:
        logger.debug("watchfiles not installed — file watcher disabled")
        return

    def _watcher_loop() -> None:
        try:
            for changes in watch(
                project_dir,
                stop_event=_watcher_stop,
                recursive=True,
                debounce=debounce_ms,
                # Ignore hidden dirs, node_modules, __pycache__, .git
                watch_filter=lambda _, path: (
                    not any(
                        part.startswith(".") or part in ("node_modules", "__pycache__", ".git")
                        for part in Path(path).parts
                    )
                    and Path(path).suffix.lower() in _CODE_EXTENSIONS
                ),
            ):
                if _watcher_stop.is_set():
                    break

                svc = _get_ast_service()
                for change_type, path_str in changes:
                    if change_type in (Change.modified, Change.added, Change.deleted):
                        try:
                            rel = os.path.relpath(path_str, project_dir)
                            svc.notify_file_changed(rel)
                            # Also invalidate semantic search embeddings
                            try:
                                from attocode.code_intel.tools.search_tools import (
                                    _get_semantic_search,
                                )

                                smgr = _get_semantic_search()
                                smgr.invalidate_file(path_str)
                                smgr.queue_reindex(path_str)
                            except Exception:
                                pass
                            try:
                                from attocode.code_intel.tools.search_tools import (
                                    _get_trigram_index,
                                )

                                tri_idx = _get_trigram_index()
                                if tri_idx is not None:
                                    tri_idx.update_file(rel, b"")
                            except Exception:
                                pass
                            logger.debug("File watcher: updated %s", rel)
                        except Exception:
                            pass  # Best-effort -- don't crash the watcher
        except Exception:
            logger.debug("File watcher stopped", exc_info=True)

    _watcher_thread = threading.Thread(
        target=_watcher_loop, daemon=True, name="code-intel-watcher"
    )
    _watcher_thread.start()
    logger.info("File watcher started for %s (debounce=%dms)", project_dir, debounce_ms)


def _stop_file_watcher() -> None:
    """Stop the background file watcher and queue poller."""
    global _watcher_thread, _queue_thread
    _watcher_stop.set()
    for t in (_watcher_thread, _queue_thread):
        if t is not None:
            t.join(timeout=2.0)
    _watcher_thread = None
    _queue_thread = None


# ---------------------------------------------------------------------------
# Tool instrumentation — wraps MCP tool functions with metrics recording
# ---------------------------------------------------------------------------


def _instrument_tool(tool_fn, tool_name: str):
    """Wrap an MCP tool function to record call metrics.

    Records duration and success/failure for each invocation via the
    module-level ``metrics_collector`` singleton.

    Args:
        tool_fn: The original tool function (sync).
        tool_name: Human-readable tool name for metric labels.

    Returns:
        Wrapped function that records metrics then delegates to *tool_fn*.
    """
    import functools
    import time as _time

    @functools.wraps(tool_fn)
    def _wrapper(*args, **kwargs):
        from attocode.code_intel.api.middleware import metrics_collector

        start = _time.monotonic()
        success = True
        try:
            result = tool_fn(*args, **kwargs)
            return result
        except Exception:
            success = False
            raise
        finally:
            duration_ms = (_time.monotonic() - start) * 1000
            metrics_collector.record_tool_call(tool_name, duration_ms, success)

    return _wrapper


def _instrument_all_tools() -> None:
    """Wrap all registered MCP tools with metrics instrumentation.

    Must be called after all tool modules have been imported (so that
    ``@mcp.tool()`` decorators have fired). Patches the internal tool
    registry in-place.
    """
    try:
        # FastMCP stores tools in mcp._tool_manager._tools (dict[str, Tool])
        tool_manager = getattr(mcp, "_tool_manager", None)
        if tool_manager is None:
            return
        tools_dict = getattr(tool_manager, "_tools", None)
        if tools_dict is None:
            return

        for name, tool_obj in tools_dict.items():
            original_fn = getattr(tool_obj, "fn", None)
            if original_fn is None:
                continue
            tool_obj.fn = _instrument_tool(original_fn, name)
        logger.info("Instrumented %d MCP tools with metrics recording", len(tools_dict))
    except Exception:
        logger.debug("Failed to instrument MCP tools", exc_info=True)


# ---------------------------------------------------------------------------
# Register all tool modules (decorators fire on import)
# ---------------------------------------------------------------------------

import attocode.code_intel.tools.adr_tools as _adr_tools  # noqa: E402, F401
import attocode.code_intel.tools.analysis_tools as _analysis_tools  # noqa: E402, F401
import attocode.code_intel.tools.cross_mode_tools as _cross_mode_tools  # noqa: E402, F401
import attocode.code_intel.tools.dead_code_tools as _dead_code_tools  # noqa: E402, F401
import attocode.code_intel.tools.distill_tools as _distill_tools  # noqa: E402, F401
import attocode.code_intel.tools.frecency_tools as _frecency_tools  # noqa: E402, F401
import attocode.code_intel.tools.fuzzy_tools as _fuzzy_tools  # noqa: E402, F401
import attocode.code_intel.tools.history_tools as _history_tools  # noqa: E402, F401
import attocode.code_intel.tools.learning_tools as _learning_tools  # noqa: E402, F401
import attocode.code_intel.tools.lsp_tools as _lsp_tools  # noqa: E402, F401
import attocode.code_intel.tools.navigation_tools as _navigation_tools  # noqa: E402, F401
import attocode.code_intel.tools.query_constraints_tools as _query_constraints_tools  # noqa: E402, F401
import attocode.code_intel.tools.query_history_tools as _query_history_tools  # noqa: E402, F401
import attocode.code_intel.tools.readiness_tools as _readiness_tools  # noqa: E402, F401
import attocode.code_intel.tools.composite_tools as _composite_tools  # noqa: E402, F401
import attocode.code_intel.tools.search_tools as _search_tools  # noqa: E402, F401
# pin_tools must come first because maintenance_tools imports
# _stamp_pin / _STORE_DEFS from it.
import attocode.code_intel.tools.pin_tools as _pin_tools  # noqa: E402, F401
import attocode.code_intel.tools.maintenance_tools as _maintenance_tools  # noqa: E402, F401
import attocode.code_intel.tools.snapshot_tools as _snapshot_tools  # noqa: E402, F401
import attocode.code_intel.tools.overlay_tools as _overlay_tools  # noqa: E402, F401
# Rule-based analysis engine (PerfInsights-inspired)
import attocode.code_intel.tools.rule_tools as _rule_tools  # noqa: E402, F401
from attocode.code_intel.helpers import (  # noqa: E402, F401
    _compute_file_metrics,
    _percentile_ranks,
)

# Backward-compatible re-exports via attribute alias (avoids circular import)
file_analysis = _analysis_tools.file_analysis  # noqa: E402
impact_analysis = _analysis_tools.impact_analysis  # noqa: E402
dependency_graph = _analysis_tools.dependency_graph  # noqa: E402
hotspots = _analysis_tools.hotspots  # noqa: E402
cross_references = _analysis_tools.cross_references  # noqa: E402
dependencies = _analysis_tools.dependencies  # noqa: E402
explore_codebase = _navigation_tools.explore_codebase  # noqa: E402
find_related = _analysis_tools.find_related  # noqa: E402
community_detection = _analysis_tools.community_detection  # noqa: E402
graph_dsl = _analysis_tools.graph_dsl  # noqa: E402

semantic_search = _search_tools.semantic_search  # noqa: E402
semantic_search_status = _search_tools.semantic_search_status  # noqa: E402
security_scan = _search_tools.security_scan  # noqa: E402
fast_search = _search_tools.fast_search  # noqa: E402

recall = _learning_tools.recall  # noqa: E402
record_learning = _learning_tools.record_learning  # noqa: E402
learning_feedback = _learning_tools.learning_feedback  # noqa: E402
list_learnings = _learning_tools.list_learnings  # noqa: E402

record_adr = _adr_tools.record_adr  # noqa: E402
list_adrs = _adr_tools.list_adrs  # noqa: E402
get_adr = _adr_tools.get_adr  # noqa: E402
update_adr_status = _adr_tools.update_adr_status  # noqa: E402

dead_code = _dead_code_tools.dead_code  # noqa: E402
distill = _distill_tools.distill  # noqa: E402
readiness_report = _readiness_tools.readiness_report  # noqa: E402

code_evolution = _history_tools.code_evolution  # noqa: E402
recent_changes = _history_tools.recent_changes  # noqa: E402

review_change = _composite_tools.review_change  # noqa: E402
explain_impact = _composite_tools.explain_impact  # noqa: E402
suggest_tests = _composite_tools.suggest_tests  # noqa: E402
architecture_drift = _composite_tools.architecture_drift  # noqa: E402

bootstrap = _navigation_tools.bootstrap  # noqa: E402
conventions = _navigation_tools.conventions  # noqa: E402
project_summary = _navigation_tools.project_summary  # noqa: E402
relevant_context = _navigation_tools.relevant_context  # noqa: E402
repo_map = _navigation_tools.repo_map  # noqa: E402
search_symbols = _navigation_tools.search_symbols  # noqa: E402
symbols = _navigation_tools.symbols  # noqa: E402

# Instrument all registered tools with metrics recording
_instrument_all_tools()

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

# Subcommands that should be dispatched to the CLI handler instead of
# starting the MCP server.
_CLI_SUBCOMMANDS = {
    "install", "uninstall", "serve", "status", "probe-install", "notify",
    "connect", "test-connection", "watch", "help", "--help", "-h",
    "query", "symbols", "impact", "hotspots", "deps", "dead-code",
    "gc", "verify", "reindex", "bundle",
}


def main() -> None:
    """CLI entry point for the MCP server.

    If the first positional argument is a known subcommand (install, uninstall,
    notify, status, serve, help), delegates to ``cli.dispatch_code_intel``.
    Otherwise starts the MCP server on stdio.
    """
    args = sys.argv[1:]

    # Detect subcommands -- delegate to CLI dispatcher
    if args and args[0] in _CLI_SUBCOMMANDS:
        from attocode.code_intel.cli import dispatch_code_intel

        dispatch_code_intel(args)
        return

    # No subcommand -- start MCP server
    # Walk up from CWD to find project root (marker = .git or .attocode)
    _cwd = os.path.abspath(".")
    _project_root = _cwd
    for _candidate in [_cwd] + list(_walk_up(_cwd)):
        if os.path.isdir(os.path.join(_candidate, ".git")) or os.path.isdir(
            os.path.join(_candidate, ".attocode")
        ):
            _project_root = _candidate
            break
    project_dir = _project_root

    transport = "stdio"
    host = "127.0.0.1"
    port = 8080
    remote_url = ""
    remote_token = ""
    remote_repo_id = ""
    local_only = os.environ.get("ATTOCODE_LOCAL_ONLY") == "1"
    for i, arg in enumerate(args):
        if arg == "--project" and i + 1 < len(args):
            project_dir = args[i + 1]
        elif arg.startswith("--project="):
            project_dir = arg.split("=", 1)[1]
        elif arg == "--transport" and i + 1 < len(args):
            transport = args[i + 1]
        elif arg.startswith("--transport="):
            transport = arg.split("=", 1)[1]
        elif arg == "--host" and i + 1 < len(args):
            host = args[i + 1]
        elif arg.startswith("--host="):
            host = arg.split("=", 1)[1]
        elif arg == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
        elif arg.startswith("--port="):
            port = int(arg.split("=", 1)[1])
        elif arg == "--remote" and i + 1 < len(args):
            remote_url = args[i + 1]
        elif arg.startswith("--remote="):
            remote_url = arg.split("=", 1)[1]
        elif arg == "--remote-token" and i + 1 < len(args):
            remote_token = args[i + 1]
        elif arg.startswith("--remote-token="):
            remote_token = arg.split("=", 1)[1]
        elif arg == "--remote-repo" and i + 1 < len(args):
            remote_repo_id = args[i + 1]
        elif arg.startswith("--remote-repo="):
            remote_repo_id = arg.split("=", 1)[1]
        elif arg == "--local-only":
            local_only = True

    project_dir = os.path.abspath(project_dir)
    os.environ["ATTOCODE_PROJECT_DIR"] = project_dir
    if local_only:
        os.environ["ATTOCODE_LOCAL_ONLY"] = "1"

    # Load remote config from .attocode/config.toml if not explicitly provided
    clear_remote_service()
    if not remote_url and not local_only:
        from attocode.code_intel.config import load_remote_config
        rc = load_remote_config(project_dir)
        if rc.is_configured:
            remote_url = rc.server
            remote_token = rc.token
            remote_repo_id = rc.repo_id

    if remote_url:
        configure_remote_service(remote_url, remote_token, remote_repo_id)
        logger.info("Remote mode: proxying through %s (repo: %s)", remote_url, remote_repo_id)

    # Start file watcher and notification queue poller in background
    _start_file_watcher(project_dir)
    _start_queue_poller(project_dir)

    logger.info("Starting attocode-code-intel for %s (transport=%s)", project_dir, transport)
    try:
        if transport == "http":
            from attocode.code_intel.cli import _serve_http

            _serve_http(project_dir, host=host, port=port, debug=False)
        elif transport == "sse":
            mcp.run(transport="sse", host=host, port=port)
        else:
            mcp.run(transport="stdio")
    finally:
        _stop_file_watcher()


if __name__ == "__main__":
    main()
