"""Policy decision interface for deterministic routing and resource allocation."""

from typing import Dict, Any, Optional


class DecisionContext:
    """Input context for a policy decision."""

    def __init__(self, task_id: str, task_data: Dict[str, Any], available_routes: list):
        self.task_id = task_id
        self.task_data = task_data
        self.available_routes = available_routes


class PolicyDecision:
    """Output of a policy decision with deterministic comparison."""

    def __init__(self, chosen_route: str, policy_name: str, confidence: float = 1.0):
        self.chosen_route = chosen_route
        self.policy_name = policy_name
        self.confidence = confidence

    def __eq__(self, other):
        if not isinstance(other, PolicyDecision):
            return False
        return (self.chosen_route == other.chosen_route and
                self.policy_name == other.policy_name)

    def __repr__(self):
        return f"PolicyDecision(route={self.chosen_route}, policy={self.policy_name}, conf={self.confidence})"


class BasePolicy:
    """Base class for deterministic policy evaluation."""

    def __init__(self, name: str):
        self.name = name

    def evaluate(self, context: DecisionContext) -> PolicyDecision:
        """Evaluate the policy deterministically given a context.

        Must return the same decision for identical inputs.
        """
        raise NotImplementedError

    def __call__(self, context: DecisionContext) -> PolicyDecision:
        return self.evaluate(context)


class DefaultPolicy(BasePolicy):
    """Default round-robin policy for routing."""

    def __init__(self):
        super().__init__("default_roundrobin")
        self._counter = 0

    def evaluate(self, context: DecisionContext) -> PolicyDecision:
        if not context.available_routes:
            raise ValueError(f"No routes available for task {context.task_id}")
        # Deterministic selection: use task_id hash for consistency
        idx = hash(context.task_id) % len(context.available_routes)
        chosen = context.available_routes[idx]
        return PolicyDecision(chosen, self.name, confidence=1.0)


class AffinityPolicy(BasePolicy):
    """Route based on project/model affinity when available."""

    def __init__(self):
        super().__init__("affinity_based")

    def evaluate(self, context: DecisionContext) -> PolicyDecision:
        if not context.available_routes:
            raise ValueError(f"No routes available for task {context.task_id}")

        task_data = context.task_data
        project = task_data.get("project_id")
        model = task_data.get("model_id")

        # Try to match affinity; fall back to first route
        for route in context.available_routes:
            if (route.get("project") == project or
                route.get("model") == model):
                return PolicyDecision(route.get("id", route), self.name, confidence=0.9)

        # Fallback: deterministic based on task_id
        idx = hash(context.task_id) % len(context.available_routes)
        chosen = context.available_routes[idx]
        return PolicyDecision(
            chosen.get("id", chosen) if isinstance(chosen, dict) else chosen,
            self.name,
            confidence=0.5
        )
