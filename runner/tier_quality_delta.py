"""
tier_quality_delta.py - Measure quality delta between model tiers per task shape.
Only pay for expensive models where the quality improvement is real.
"""
from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class TaskOutcome:
    task_id: str
    slug: str
    model: str
    task_shape: str
    verify_passed: bool
    merged: bool
    cost_usd: float
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class TierStats:
    model: str
    task_shape: str
    total: int = 0
    verify_pass: int = 0
    merge_success: int = 0
    total_cost: float = 0.0
    @property
    def verify_rate(self):
        return self.verify_pass / max(1, self.total)
    @property
    def merge_rate(self):
        return self.merge_success / max(1, self.total)
    @property
    def avg_cost(self):
        return self.total_cost / max(1, self.total)


@dataclass
class QualityDelta:
    task_shape: str
    high_model: str
    low_model: str
    verify_delta: float
    merge_delta: float
    cost_ratio: float
    recommendation: str


MODEL_TIER = {"opus": 3, "sonnet": 2, "haiku": 1}
QUALITY_THRESHOLD = 0.10


def compute_tier_stats(outcomes):
    groups = defaultdict(lambda: {"total": 0, "verify": 0, "merge": 0, "cost": 0.0})
    for o in outcomes:
        key = (o.model, o.task_shape)
        groups[key]["total"] += 1
        groups[key]["verify"] += int(o.verify_passed)
        groups[key]["merge"] += int(o.merged)
        groups[key]["cost"] += o.cost_usd
    stats = []
    for (model, shape), g in groups.items():
        stats.append(TierStats(model=model, task_shape=shape, total=g["total"],
            verify_pass=g["verify"], merge_success=g["merge"], total_cost=g["cost"]))
    return stats


def compute_quality_deltas(stats, threshold=QUALITY_THRESHOLD):
    by_shape = defaultdict(list)
    for s in stats:
        by_shape[s.task_shape].append(s)
    deltas = []
    for shape, shape_stats in by_shape.items():
        if len(shape_stats) < 2:
            continue
        shape_stats.sort(key=lambda s: MODEL_TIER.get(s.model, 0))
        low, high = shape_stats[0], shape_stats[-1]
        vd = high.verify_rate - low.verify_rate
        md = high.merge_rate - low.merge_rate
        cr = high.avg_cost / max(0.001, low.avg_cost)
        rec = "use_high" if md >= threshold else "use_low"
        deltas.append(QualityDelta(task_shape=shape, high_model=high.model,
            low_model=low.model, verify_delta=vd, merge_delta=md,
            cost_ratio=cr, recommendation=rec))
    return deltas


def recommend_model(deltas, task_shape):
    for d in deltas:
        if d.task_shape == task_shape:
            return d.high_model if d.recommendation == "use_high" else d.low_model
    return "haiku"
