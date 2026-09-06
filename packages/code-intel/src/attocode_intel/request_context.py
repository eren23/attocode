"""Identity and workspace selection for one intelligence operation."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RequestContext:
    project_dir: str
    workspace: str
    revision: str = "working-tree"
    source: str = "local"
    identity: Any = None
    stores: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def service(self):
        from attocode_intel.service import CodeIntelService

        if "service" not in self.stores:
            self.stores["service"] = CodeIntelService(self.project_dir)
        return self.stores["service"]


current_request: ContextVar[RequestContext | None] = ContextVar(
    "intelligence_request", default=None
)


@contextmanager
def bind_request(context: RequestContext):
    token = current_request.set(context)
    try:
        yield context
    finally:
        current_request.reset(token)


def scoped_store(name, factory):
    context = current_request.get()
    if context is None:
        return None
    if name not in context.stores:
        context.stores[name] = factory(context.project_dir)
    return context.stores[name]


def resolve_workspace(workspace: str = "", default: str = "") -> str:
    """Explicit roots win; discovery recognizes .git files in worktrees."""
    if workspace or default:
        path = Path(workspace or default).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"Workspace directory does not exist: {path}")
        return str(path)
    cwd = Path.cwd().resolve()
    for path in (cwd, *cwd.parents):
        if any(
            (path / marker).exists()
            for marker in (
                ".git",
                ".attocode",
                "pyproject.toml",
                "package.json",
                "Cargo.toml",
                "go.mod",
            )
        ):
            return str(path)
    raise ValueError(
        "No repository selected. Supply workspace or start with --project /path/to/repo."
    )
