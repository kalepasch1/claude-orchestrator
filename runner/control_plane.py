#!/usr/bin/env python3
"""Authoritative orchestration control plane.

This module deliberately contains no autonomous idea generator.  It is the common,
deterministic boundary used by task admission, task claiming, and the periodic
scheduler so the many specialist modules cannot fight each other.

The control plane provides eight closely-related capabilities:

* semantic objective admission and clock-integrity checks;
* automatic finish-first (liquidation) mode when the queue is deep;
* a compact, machine-readable outcome contract on every task;
* one global task score combining delivery value and information gain;
* declarative schedule de-duplication;
* controller arbitration and evidence-based subsystem slashing;
* content-addressed objective identities shared by every execution lane; and
* audit summaries that can be published without creating more tasks.

All functions are fail-soft.  If the control plane cannot establish that a
mutation is unsafe it preserves the old behavior; safety and release work never
depends on this module being available.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import os
import re
import threading
import time
from typing import Any, Callable, Iterable


TRUE = {"1", "true", "yes", "on", "enabled"}
LIVE_STATES = "in.(QUEUED,RUNNING,RETRY,DONE,MERGED,BLOCKED,DECOMPOSED)"
GENERATOR_PREFIXES = (
    "improve-", "idea-", "roadmap-", "spec-", "reconsider-", "predictive-",
)
DELIVERY_PREFIXES = (
    "qafix-", "relfix-", "buildfix-", "deployfix-", "recover-missing-branch-",
    "rework-", "toolchain-repair-",
)
EVIDENCE_PREFIXES = ("canary-", "eval-", "probe-")
GENERATOR_JOBS = {
    "improve", "meta_loop.py", "scout", "spec", "bizradar", "roadmap",
    "newapp", "committees", "committeeboard", "agentmarket", "commonbrain",
    "demand_mining.py", "capability_radar.py", "feedback_review.py",
    "experiment_portfolio.py", "predictive_scheduler.py", "promptfactory",
}

_STOP = set(
    "the a an to of and or for in on with from into this that these those build add "
    "fix update create make implement task change feature improve improvement orchestrator "
    "system using ensure new more across current existing".split()
)
_VOLATILE = re.compile(
    r"\b(?:[0-9a-f]{8}-[0-9a-f-]{20,}|[0-9a-f]{12,}|20\d\d[-_/]\d\d[-_/]\d\d|\d{4,})\b",
    re.I,
)
_TOKEN = re.compile(r"[a-z][a-z0-9_-]{2,}", re.I)
_cache_lock = threading.Lock()
_queue_cache = {"at": 0.0, "depth": 0}


def _truthy(name: str, default: str = "true") -> bool:
    return os.environ.get(name, default).strip().lower() in TRUE


def _tokens(text: str) -> tuple[str, ...]:
    cleaned = _VOLATILE.sub(" ", (text or "").lower())
    return tuple(sorted({t for t in _TOKEN.findall(cleaned) if t not in _STOP}))


def objective_fingerprint(row_or_text: Any) -> str:
    """Stable identity for the requested outcome, ignoring dates/run ids/boilerplate."""
    if isinstance(row_or_text, dict):
        # Slugs frequently contain generator/run ids; the requested outcome lives in
        # kind+prompt. Evidence lanes additionally key by model/coder so independent
        # vendor samples are not collapsed.
        text = " ".join(str(row_or_text.get(k) or "") for k in ("kind", "prompt"))
        if str(row_or_text.get("slug") or "").startswith(EVIDENCE_PREFIXES):
            text += " " + str(row_or_text.get("force_coder") or row_or_text.get("model") or "")
        project = str(row_or_text.get("project_id") or row_or_text.get("project") or "")
    else:
        text, project = str(row_or_text or ""), ""
    canonical = project + "|" + " ".join(_tokens(text))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


def semantic_similarity(a: Any, b: Any) -> float:
    aa, bb = set(_tokens(str(a or ""))), set(_tokens(str(b or "")))
    return len(aa & bb) / len(aa | bb) if aa and bb else 0.0


def _parse_time(value: Any) -> _dt.datetime | None:
    if not value or str(value).lower() == "now()":
        return None
    try:
        parsed = _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=_dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def normalize_clock(row: dict) -> dict:
    """Remove impossible client timestamps so Postgres remains the time authority."""
    out = dict(row)
    now = _dt.datetime.now(_dt.timezone.utc)
    for field in ("created_at", "updated_at", "queued_at"):
        parsed = _parse_time(out.get(field))
        if parsed and parsed > now + _dt.timedelta(minutes=5):
            out.pop(field, None)
            out["note"] = _append_note(out.get("note"), f"clock-normalized:{field}")
    return out


def outcome_contract(row: dict) -> dict:
    """Infer the minimum measurable contract when a producer supplied none."""
    prompt = str(row.get("prompt") or "").lower()
    kind = str(row.get("kind") or "build").lower()
    material = bool(row.get("material"))
    primary = "deployed_and_verified" if material else "integrated_change"
    if kind in {"test", "canary", "eval", "research"}:
        primary = "decision_changing_evidence"
    elif any(w in prompt for w in ("latency", "performance", "throughput")):
        primary = "measured_performance_delta"
    elif any(w in prompt for w in ("revenue", "conversion", "retention", "activation")):
        primary = "measured_product_delta"
    return {
        "v": 1,
        "primary": primary,
        "baseline": "pre_change",
        "guardrails": ["tests_green", "no_regression", "rollback_ready"],
        "window": "post_deploy" if material else "integration",
        "stop": "retire_after_2_noninformative_attempts",
    }


def _append_note(note: Any, addition: str, max_len: int = 1800) -> str:
    base = str(note or "").strip()
    if addition in base:
        return base[:max_len]
    if len(base) >= max_len:
        return base[:max_len]
    prefix = (base + " | ") if base else ""
    return prefix + addition[: max(0, max_len - len(prefix))]


def _queue_depth(select_fn: Callable | None) -> int:
    if not select_fn:
        return 0
    now = time.time()
    with _cache_lock:
        if now - _queue_cache["at"] < 30:
            return int(_queue_cache["depth"])
    ceiling = max(1, int(os.environ.get("ORCH_LIQUIDATION_QUEUE_FLOOR", "500")))
    try:
        depth = len(select_fn("tasks", {
            "select": "id", "state": "eq.QUEUED", "limit": str(ceiling + 1)
        }) or [])
    except Exception:
        depth = 0
    with _cache_lock:
        _queue_cache.update({"at": now, "depth": depth})
    return depth


def liquidation_active(select_fn: Callable | None = None, queue_depth: int | None = None) -> bool:
    mode = os.environ.get("ORCH_LIQUIDATION_MODE", "auto").strip().lower()
    if mode in TRUE:
        return True
    if mode in {"0", "false", "off", "disabled"}:
        return False
    floor = max(1, int(os.environ.get("ORCH_LIQUIDATION_QUEUE_FLOOR", "500")))
    depth = _queue_depth(select_fn) if queue_depth is None else queue_depth
    return depth >= floor


def is_delivery_work(row: dict) -> bool:
    slug = str(row.get("slug") or "").lower()
    kind = str(row.get("kind") or "").lower()
    note = str(row.get("note") or "").lower()
    return (
        slug.startswith(DELIVERY_PREFIXES)
        or kind in {"bugfix", "security", "deploy", "release"}
        or any(x in note for x in ("release_train", "integration_sweeper", "vercel"))
    )


def is_generator_work(row: dict) -> bool:
    return str(row.get("slug") or "").lower().startswith(GENERATOR_PREFIXES)


def prepare_task(row: dict, select_fn: Callable | None = None) -> dict:
    """Prepare or reject a task at the single DB insertion boundary.

    Returns ``{"accept": bool, "row": row, "existing": rows, "reason": str}``.
    Exact slug de-dup remains in db.py; this layer adds semantic objective identity.
    """
    if not _truthy("ORCH_OBJECTIVE_ADMISSION", "true"):
        return {"accept": True, "row": dict(row), "reason": "disabled"}
    out = normalize_clock(row)
    fp = objective_fingerprint(out)
    contract = outcome_contract(out)
    out["note"] = _append_note(
        out.get("note"),
        "objective:%s outcome:%s" % (fp, json.dumps(contract, separators=(",", ":"))),
    )

    # In liquidation mode, speculative generators may update an existing objective but
    # cannot increase queue cardinality. Delivery, security and evidence lanes remain open.
    if (liquidation_active(select_fn)
            and is_generator_work(out)
            and not is_delivery_work(out)):
        return {"accept": False, "row": out, "existing": [], "reason": "liquidation-mode"}

    if not select_fn or not out.get("project_id"):
        return {"accept": True, "row": out, "reason": "prepared"}
    try:
        candidates = select_fn("tasks", {
            "select": "id,slug,prompt,note,state,project_id",
            "project_id": f"eq.{out['project_id']}",
            "state": LIVE_STATES,
            "order": "created_at.desc",
            "limit": os.environ.get("ORCH_ADMISSION_SCAN_LIMIT", "250"),
        }) or []
    except Exception:
        return {"accept": True, "row": out, "reason": "lookup-unavailable"}

    marker = f"objective:{fp}"
    exact = [c for c in candidates if marker in str(c.get("note") or "")]
    if exact:
        return {"accept": False, "row": out, "existing": exact[:1], "reason": "same-objective"}

    threshold = float(os.environ.get("ORCH_ADMISSION_SIMILARITY", "0.88"))
    prompt = str(out.get("prompt") or "")
    for candidate in candidates:
        # Recovery and evidence tasks intentionally repeat an experiment with different
        # identities; exact fingerprinting still catches accidental copies.
        if str(out.get("slug") or "").startswith(EVIDENCE_PREFIXES):
            break
        sim = semantic_similarity(prompt, candidate.get("prompt"))
        if sim >= threshold:
            return {
                "accept": False, "row": out, "existing": [candidate],
                "reason": f"semantic-duplicate:{sim:.3f}",
            }
    return {"accept": True, "row": out, "reason": "novel-objective"}


def information_gain(task: dict) -> float:
    """Cheap expected information gain used when outcome evidence is sparse."""
    prompt = str(task.get("prompt") or "").lower()
    kind = str(task.get("kind") or "").lower()
    score = 0.15
    if kind in {"test", "canary", "eval", "research"}:
        score += 0.45
    if any(w in prompt for w in ("measure", "hypothesis", "baseline", "counterfactual", "profile")):
        score += 0.25
    if any(w in prompt for w in ("redesign", "rewrite everything", "all capabilities")):
        score -= 0.15
    attempts = int(task.get("attempt") or task.get("attempts") or 0)
    score *= 1.0 / (1.0 + attempts)
    return max(0.0, min(1.0, score))


def global_task_score(task: dict) -> float:
    """One comparable score for all lanes; larger is better."""
    slug = str(task.get("slug") or "").lower()
    confidence = float(task.get("confidence") or 0.5)
    priority = float(task.get("priority") or 1000)
    delivery = 4.0 if is_delivery_work(task) else 1.0
    evidence = information_gain(task)
    churn = 0.15 if slug.startswith(("cont-", "batch-mech")) else 1.0
    speculative = 0.2 if is_generator_work(task) else 1.0
    return (delivery * (0.5 + confidence) * (1.0 + evidence) * churn * speculative
            / max(1.0, math.log10(10.0 + priority)))


def rank_tasks(tasks: Iterable[dict]) -> list[dict]:
    return sorted(tasks, key=lambda t: (-global_task_score(t), str(t.get("created_at") or "")))


def normalize_schedule(schedule: Iterable[tuple]) -> list[tuple]:
    """Compile one authoritative trigger per job.

    For duplicate interval triggers the shortest cadence wins.  An interval trigger
    supersedes daily/weekly duplicates because it already covers those executions.
    """
    chosen: dict[str, tuple] = {}
    order: list[str] = []
    for item in schedule:
        key, job, stype, args = item
        if job not in chosen:
            chosen[job] = item
            order.append(job)
            continue
        prev = chosen[job]
        if stype == "interval" and (prev[2] != "interval" or float(args) < float(prev[3])):
            chosen[job] = item
    return [chosen[j] for j in order]


def controller_allowed(job: str, queue_depth: int = 0) -> tuple[bool, str]:
    """Single arbitration decision for scheduled controllers."""
    if liquidation_active(queue_depth=queue_depth) and job in GENERATOR_JOBS:
        return False, "liquidation-mode"
    state = _load_controller_state().get(job, {})
    failures = int(state.get("consecutive_failures") or 0)
    retired_until = float(state.get("retired_until") or 0)
    if retired_until > time.time():
        return False, f"subsystem-slashed:{failures}-failures"
    return True, "allowed"


def _state_path() -> str:
    home = os.environ.get(
        "CLAUDE_ORCH_HOME",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".runtime"),
    )
    return os.path.join(home, "controller_health.json")


def _load_controller_state() -> dict:
    try:
        with open(_state_path()) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def record_controller_outcome(job: str, ok: bool, runtime_s: float, effect: float = 0.0) -> dict:
    """Evidence-based subsystem slashing with automatic probation expiry."""
    data = _load_controller_state()
    row = dict(data.get(job) or {})
    row["runs"] = int(row.get("runs") or 0) + 1
    row["successes"] = int(row.get("successes") or 0) + int(bool(ok))
    row["consecutive_failures"] = 0 if ok else int(row.get("consecutive_failures") or 0) + 1
    row["runtime_s_ema"] = round(
        0.8 * float(row.get("runtime_s_ema") or runtime_s) + 0.2 * runtime_s, 3
    )
    row["effect_ema"] = round(0.8 * float(row.get("effect_ema") or 0) + 0.2 * effect, 4)
    row["updated_at"] = time.time()
    threshold = max(2, int(os.environ.get("ORCH_CONTROLLER_SLASH_FAILURES", "3")))
    if row["consecutive_failures"] >= threshold:
        row["retired_until"] = time.time() + float(os.environ.get("ORCH_CONTROLLER_PROBATION_S", "3600"))
    elif ok:
        row["retired_until"] = 0
    data[job] = row
    path = _state_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + f".{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, sort_keys=True, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass
    return row


def audit(tasks: Iterable[dict]) -> dict:
    rows = list(tasks)
    fps: dict[str, int] = {}
    future = generators = delivery = 0
    now = _dt.datetime.now(_dt.timezone.utc)
    for row in rows:
        fp = objective_fingerprint(row)
        fps[fp] = fps.get(fp, 0) + 1
        generators += int(is_generator_work(row))
        delivery += int(is_delivery_work(row))
        ts = _parse_time(row.get("created_at"))
        future += int(bool(ts and ts > now + _dt.timedelta(minutes=5)))
    return {
        "tasks": len(rows),
        "unique_objectives": len(fps),
        "duplicate_rows": sum(v - 1 for v in fps.values() if v > 1),
        "generator_rows": generators,
        "delivery_rows": delivery,
        "future_dated_rows": future,
        "liquidation_recommended": len(rows) >= int(os.environ.get("ORCH_LIQUIDATION_QUEUE_FLOOR", "500")),
    }


if __name__ == "__main__":
    print(json.dumps({"controller_health": _load_controller_state()}, indent=2))
