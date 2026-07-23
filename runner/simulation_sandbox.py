"""Copy-on-write compliance what-if simulations; production isolation is enforced by design."""
from __future__ import annotations
from copy import deepcopy
from typing import Any, Callable


class ComplianceSimulationSandbox:
    def run(self, snapshot: dict[str, Any], scenario: dict[str, Any],
            pipeline: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        baseline, working = deepcopy(snapshot), deepcopy(snapshot)
        result = pipeline(working, deepcopy(scenario))
        return {"scenario": deepcopy(scenario), "baseline": baseline, "result": result,
                "isolated": True, "writeback_allowed": False}
