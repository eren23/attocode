"""State and event polling store for attoswarm TUI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from attoswarm.protocol.io import read_json


class StateStore:
    def __init__(self, run_dir: str) -> None:
        self.run_dir = Path(run_dir)
        self.state_path = self.run_dir / "swarm.state.json"
        self.events_path = self.run_dir / "swarm.events.jsonl"

    def read_state(self) -> dict[str, Any]:
        return read_json(self.state_path, default={})

    def read_events(self, limit: int = 200) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        out: list[dict[str, Any]] = []
        lines = self.events_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[-max(limit, 1):]:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                out.append(item)
        return out

    def read_agent_box(self, agent_id: str, box: str) -> dict[str, Any]:
        path = self.run_dir / "agents" / f"agent-{agent_id}.{box}.json"
        return read_json(path, default={})

    def read_task(self, task_id: str) -> dict[str, Any]:
        path = self.run_dir / "tasks" / f"task-{task_id}.json"
        return read_json(path, default={})
