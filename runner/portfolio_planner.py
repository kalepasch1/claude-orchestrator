#!/usr/bin/env python3
"""Rolling-horizon constrained portfolio planner.

The existing economic/thermal schedulers provide signals. This module performs
the missing joint selection step: it chooses a feasible batch across projects,
repository file scopes, material-risk limits, and lane capacity using the control
plane's shared delivery-value + information-gain score.
"""
from __future__ import annotations

import os
import re
from typing import Iterable

import control_plane

_PATH = re.compile(r"(?<![\w.-])((?:[\w.-]+/)+[\w.-]+\.[a-zA-Z0-9]{1,8})")


def file_scope(task: dict) -> set[str]:
    text = " ".join(str(task.get(k) or "") for k in ("prompt", "note", "diff_plan"))
    return {p for p in _PATH.findall(text) if not p.startswith(("http/", "https/"))}


def _conflicts(scope: set[str], selected_scopes: list[set[str]]) -> bool:
    return bool(scope and any(scope & other for other in selected_scopes))


def plan(tasks: Iterable[dict], capacity: int, lane: str = "general") -> dict:
    candidates = control_plane.rank_tasks(list(tasks))
    max_per_project = max(1, int(os.environ.get("ORCH_PLAN_PER_PROJECT", "2")))
    selected, deferred, reasons = [], [], {}
    project_count: dict[str, int] = {}
    scopes: list[set[str]] = []

    for task in candidates:
        tid = str(task.get("id") or task.get("slug"))
        pid = str(task.get("project_id") or "")
        scope = file_scope(task)
        reason = ""
        if len(selected) >= max(0, int(capacity)):
            reason = "capacity"
        elif project_count.get(pid, 0) >= max_per_project:
            reason = "project-lane-limit"
        elif _conflicts(scope, scopes):
            reason = "predicted-file-conflict"
        elif lane == "api" and (task.get("material") or str(task.get("kind") or "").lower() in {"security", "legal"}):
            reason = "requires-policy-rich-lane"

        if reason:
            deferred.append(task)
            reasons[tid] = reason
            continue
        selected.append(task)
        scopes.append(scope)
        project_count[pid] = project_count.get(pid, 0) + 1
        reasons[tid] = "selected"

    return {
        "selected": selected,
        "deferred": deferred,
        "reasons": reasons,
        "objective_score": round(sum(control_plane.global_task_score(t) for t in selected), 6),
        "information_gain": round(sum(control_plane.information_gain(t) for t in selected), 6),
    }


if __name__ == "__main__":
    print("portfolio_planner is a library; call plan(tasks, capacity, lane)")
