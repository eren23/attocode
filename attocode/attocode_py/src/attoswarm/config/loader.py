"""YAML config loader for attoswarm."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from attoswarm.config.schema import (
    BudgetConfig,
    MergeConfig,
    OrchestrationConfig,
    RetryConfig,
    RoleConfig,
    RunConfig,
    SwarmYamlConfig,
    UIConfig,
    WatchdogConfig,
    WorkspaceConfig,
)


def load_swarm_yaml(path: str | Path) -> SwarmYamlConfig:
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    if not isinstance(raw, dict):
        raw = {}

    run_raw = raw.get("run", {}) if isinstance(raw.get("run"), dict) else {}
    budget_raw = raw.get("budget", {}) if isinstance(raw.get("budget"), dict) else {}
    merge_raw = raw.get("merge", {}) if isinstance(raw.get("merge"), dict) else {}
    watchdog_raw = raw.get("watchdog", {}) if isinstance(raw.get("watchdog"), dict) else {}
    retries_raw = raw.get("retries", {}) if isinstance(raw.get("retries"), dict) else {}
    orchestration_raw = (
        raw.get("orchestration", {}) if isinstance(raw.get("orchestration"), dict) else {}
    )
    ui_raw = raw.get("ui", {}) if isinstance(raw.get("ui"), dict) else {}
    workspace_raw = raw.get("workspace", {}) if isinstance(raw.get("workspace"), dict) else {}

    run = RunConfig(**_pick(run_raw, RunConfig))
    budget = BudgetConfig(**_pick(budget_raw, BudgetConfig))
    merge = MergeConfig(**_pick(merge_raw, MergeConfig))
    watchdog = WatchdogConfig(**_pick(watchdog_raw, WatchdogConfig))
    retries = RetryConfig(**_pick(retries_raw, RetryConfig))
    orchestration = OrchestrationConfig(**_pick(orchestration_raw, OrchestrationConfig))
    ui = UIConfig(**_pick(ui_raw, UIConfig))
    workspace = WorkspaceConfig(**_pick(workspace_raw, WorkspaceConfig))

    roles: list[RoleConfig] = []
    raw_roles = raw.get("roles", [])
    if isinstance(raw_roles, list):
        for item in raw_roles:
            if isinstance(item, dict) and "role_id" in item and "backend" in item and "model" in item:
                defaults = {"role_type": "worker"}
                roles.append(RoleConfig(**(defaults | _pick(item, RoleConfig))))

    return SwarmYamlConfig(
        version=int(raw.get("version", 1)),
        run=run,
        roles=roles,
        budget=budget,
        merge=merge,
        watchdog=watchdog,
        retries=retries,
        orchestration=orchestration,
        ui=ui,
        workspace=workspace,
    )


def _pick(raw: dict[str, Any], model_type: type[Any]) -> dict[str, Any]:
    allowed = set(model_type.__dataclass_fields__.keys())
    return {k: v for k, v in raw.items() if k in allowed}
