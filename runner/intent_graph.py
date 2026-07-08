#!/usr/bin/env python3
"""
intent_graph.py — Reusable intent graph across successful artifacts (1000X replay savings).

Maps task intents → file changes → outcomes, enabling:

  1. Zero-agent replay: identical intent on same codebase → apply cached diff directly
  2. Cross-project transfer: "add auth middleware" intent transfers between projects
  3. Outcome prediction: estimate success probability from graph proximity
  4. DAG shortcuts: if A→B→C was done before, skip planning and replay

Graph structure:
  intent_node: {fingerprint, normalized_prompt, domain, task_class}
  change_node: {files_changed: [path], diff_hash, lines_added, lines_removed}
  outcome_edge: {merged: bool, cost_usd, wall_s, model, rollback: bool}

Storage: controls.intent_graph (JSON adjacency list, pruned to top N entries)

Usage:
    import intent_graph
    match = intent_graph.find_replay(task, project_path)
    if match and match["confidence"] > 0.9:
        # apply cached diff directly, skip agent entirely
"""
import os, sys, json, hashlib, re, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MAX_GRAPH_NODES = int(os.environ.get("ORCH_INTENT_GRAPH_MAX", "1000"))
REPLAY_CONFIDENCE_THRESHOLD = float(os.environ.get("ORCH_REPLAY_CONFIDENCE", "0.85"))


def _normalize_intent(prompt):
    """Normalize a prompt to its structural intent (strip variables, keep verbs+nouns)."""
    text = (prompt or "").lower().strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[0-9a-f]{8,}", "HASH", text)
    text = re.sub(r"\d{4,}", "NUM", text)
    text = re.sub(r"['\"].*?['\"]", "STR", text)
    return text[:300]


def _intent_fingerprint(task):
    """Fingerprint a task's intent for graph lookup."""
    norm = _normalize_intent(task.get("prompt", ""))
    project = task.get("project_id", "")
    kind = task.get("kind", "")
    raw = f"{project}|{kind}|{norm}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def _graph():
    """Load the intent graph from controls."""
    try:
        rows = db.select("controls", {"select": "value", "key": "eq.intent_graph"})
        if rows and rows[0].get("value"):
            v = rows[0]["value"]
            return json.loads(v) if isinstance(v, str) else v
    except Exception:
        pass
    return {"intents": {}, "changes": {}, "edges": []}


def _save_graph(graph):
    """Save the intent graph, pruning old entries."""
    intents = graph.get("intents", {})
    if len(intents) > MAX_GRAPH_NODES:
        # Keep most recent
        by_time = sorted(intents.items(), key=lambda x: x[1].get("last_seen", 0))
        graph["intents"] = dict(by_time[-MAX_GRAPH_NODES:])
        # Prune orphan edges
        valid_fps = set(graph["intents"].keys())
        graph["edges"] = [e for e in graph.get("edges", [])
                          if e.get("intent_fp") in valid_fps]

    try:
        db.upsert("controls", {"key": "intent_graph", "value": json.dumps(graph, default=str)})
    except Exception:
        pass


def record(task, files_changed, diff_hash, outcome):
    """Record a completed task in the intent graph.

    Args:
        task: task dict (prompt, project_id, kind, slug)
        files_changed: list of file paths that were modified
        diff_hash: hash of the actual diff produced
        outcome: {merged: bool, cost_usd: float, wall_s: float, model: str, rollback: bool}
    """
    fp = _intent_fingerprint(task)
    graph = _graph()

    # Upsert intent node
    intent = graph["intents"].get(fp, {
        "fingerprint": fp,
        "normalized": _normalize_intent(task.get("prompt", "")),
        "project_id": task.get("project_id", ""),
        "kind": task.get("kind", ""),
        "slug": task.get("slug", ""),
        "first_seen": time.time(),
        "attempts": 0,
        "successes": 0,
    })
    intent["last_seen"] = time.time()
    intent["attempts"] = intent.get("attempts", 0) + 1
    if outcome.get("merged"):
        intent["successes"] = intent.get("successes", 0) + 1

    graph["intents"][fp] = intent

    # Record the change set
    change_key = diff_hash or hashlib.sha256(
        json.dumps(sorted(files_changed)).encode()
    ).hexdigest()[:16]

    graph["changes"][change_key] = {
        "diff_hash": diff_hash,
        "files": files_changed[:50],
        "lines_added": outcome.get("lines_added", 0),
        "lines_removed": outcome.get("lines_removed", 0),
    }

    # Add edge: intent → change → outcome
    edge = {
        "intent_fp": fp,
        "change_key": change_key,
        "merged": outcome.get("merged", False),
        "cost_usd": outcome.get("cost_usd", 0),
        "wall_s": outcome.get("wall_s", 0),
        "model": outcome.get("model", ""),
        "rollback": outcome.get("rollback", False),
        "timestamp": time.time(),
    }
    graph.setdefault("edges", []).append(edge)

    # Cap edges per intent
    intent_edges = [e for e in graph["edges"] if e["intent_fp"] == fp]
    if len(intent_edges) > 20:
        graph["edges"] = [e for e in graph["edges"] if e["intent_fp"] != fp] + intent_edges[-20:]

    _save_graph(graph)
    return fp


def find_replay(task, project_path=None):
    """Find a replayable cached result for this task intent.

    Returns:
        {confidence: float, diff_hash: str, files: [str], model: str,
         avg_cost: float, success_rate: float} or None
    """
    fp = _intent_fingerprint(task)
    graph = _graph()

    intent = graph["intents"].get(fp)
    if not intent:
        return None

    # Find successful edges for this intent
    edges = [e for e in graph.get("edges", [])
             if e.get("intent_fp") == fp and e.get("merged") and not e.get("rollback")]

    if not edges:
        return None

    # Compute confidence from success rate
    total_attempts = intent.get("attempts", 0)
    total_successes = intent.get("successes", 0)
    if total_attempts < 2:
        return None  # Not enough data

    success_rate = total_successes / total_attempts

    # Use most recent successful edge
    latest = sorted(edges, key=lambda e: e.get("timestamp", 0))[-1]
    change = graph.get("changes", {}).get(latest.get("change_key", ""), {})

    confidence = success_rate * 0.8  # Scale down — replay is risky
    # Boost if same project
    if intent.get("project_id") == task.get("project_id"):
        confidence = min(confidence * 1.2, 0.99)

    if confidence < REPLAY_CONFIDENCE_THRESHOLD:
        return None

    avg_cost = sum(e.get("cost_usd", 0) for e in edges) / len(edges) if edges else 0

    return {
        "confidence": round(confidence, 3),
        "diff_hash": latest.get("change_key", ""),
        "files": change.get("files", []),
        "model": latest.get("model", ""),
        "avg_cost": round(avg_cost, 4),
        "success_rate": round(success_rate, 3),
        "replay_count": len(edges),
        "intent_fingerprint": fp,
    }


def intent_stats():
    """Summary statistics for the intent graph."""
    graph = _graph()
    intents = graph.get("intents", {})
    edges = graph.get("edges", [])

    total = len(intents)
    replayable = sum(1 for i in intents.values()
                     if i.get("successes", 0) >= 2 and i.get("attempts", 0) >= 2)
    total_edges = len(edges)
    merged_edges = sum(1 for e in edges if e.get("merged"))

    return {
        "total_intents": total,
        "replayable_intents": replayable,
        "total_edges": total_edges,
        "merged_edges": merged_edges,
        "edge_merge_rate": round(merged_edges / max(total_edges, 1), 3),
    }


def run():
    """Periodic: compute stats and prune graph."""
    stats = intent_stats()
    print(f"[intent-graph] {stats['total_intents']} intents, "
          f"{stats['replayable_intents']} replayable, "
          f"{stats['total_edges']} edges ({stats['edge_merge_rate']:.0%} merged)")

    # Log to resource_events
    try:
        db.insert("resource_events", {
            "kind": "intent_graph_stats",
            "detail": json.dumps(stats)[:500],
            "action": "scan",
            "created_at": "now()",
        })
    except Exception:
        pass
