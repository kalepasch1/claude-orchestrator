"""Department SLA scorecards with transparent component scores."""
from __future__ import annotations
from typing import Any


class DepartmentPerformanceScorecard:
    def score(self, department: str, *, approval_response_hours: list[float], action_completion: list[bool],
              thread_resolution_hours: list[float], approval_sla_hours: float = 24,
              resolution_sla_hours: float = 48) -> dict[str, Any]:
        avg = lambda values: sum(values) / len(values) if values else 0.0
        approval = min(100, 100 * approval_sla_hours / max(approval_sla_hours, avg(approval_response_hours)))
        resolution = min(100, 100 * resolution_sla_hours / max(resolution_sla_hours, avg(thread_resolution_hours)))
        completion = 100 * sum(bool(x) for x in action_completion) / max(1, len(action_completion))
        score = round(approval * .35 + completion * .4 + resolution * .25, 1)
        return {"department": department, "score": score, "sla_breached": approval < 100 or resolution < 100,
                "components": {"approval_response": round(approval, 1), "action_completion": round(completion, 1),
                               "thread_resolution": round(resolution, 1)}}
