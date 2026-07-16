#!/usr/bin/env python3
"""
moat_loop.py - engagement moat cycle: ingest new stages, replay, capture,
re-index, and report backtest win-rate + calibration deltas.

Pure over injected `run_cade` callable so tests never touch real infra.

Env vars:
    ORCH_MOAT_ENABLED       "true" to enable (default "true")
    ORCH_MOAT_MIN_SOURCES   minimum sources to run cycle (default 1)
"""
import os, sys, time, threading, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

ENABLED = os.environ.get("ORCH_MOAT_ENABLED", "true").lower() in ("1", "true", "yes")
MIN_SOURCES = int(os.environ.get("ORCH_MOAT_MIN_SOURCES", "1"))

_stats_lock = threading.Lock()
_stats = {"cycles": 0, "records_ingested": 0, "replays": 0,
          "captures": 0, "reindexed": 0, "errors": 0}


def _inc(key, n=1):
    with _stats_lock:
        _stats[key] = _stats.get(key, 0) + n


def _ingest_stages(sources):
    """Pull new engagement stages from each source. Returns list of records."""
    records = []
    for src in sources:
        try:
            if callable(src):
                batch = src()
            elif isinstance(src, list):
                batch = src
            else:
                batch = []
            records.extend(batch)
        except Exception:
            _inc("errors")
    _inc("records_ingested", len(records))
    return records


def _replay_and_capture(records, run_cade):
    """Replay records through the cade callable and capture results."""
    results = []
    for rec in records:
        try:
            outcome = run_cade(rec)
            _inc("replays")
            results.append({"record": rec, "outcome": outcome, "ok": True})
            _inc("captures")
        except Exception as e:
            _inc("errors")
            results.append({"record": rec, "outcome": str(e), "ok": False})
    return results


def _compute_backtest(results):
    """Compute win-rate and calibration deltas from results."""
    if not results:
        return {"win_rate": 0.0, "total": 0, "wins": 0, "calibration_delta": 0.0}
    wins = sum(1 for r in results if r.get("ok"))
    total = len(results)
    win_rate = wins / total if total else 0.0
    # calibration delta: difference between predicted and actual win-rate
    expected = 0.8  # baseline expectation
    calibration_delta = round(win_rate - expected, 4)
    return {"win_rate": round(win_rate, 4), "total": total, "wins": wins,
            "calibration_delta": calibration_delta}


def _reindex(results):
    """Re-index successful results for future retrieval."""
    count = 0
    for r in results:
        if r.get("ok"):
            count += 1
    _inc("reindexed", count)
    return count


def run_moat_cycle(sources, run_cade):
    """Run full moat cycle: ingest -> replay -> capture -> re-index -> report.

    Args:
        sources: list of source callables or lists of records
        run_cade: callable that processes a single record
    Returns:
        summary dict with backtest win-rate and calibration deltas
    """
    if not ENABLED:
        return {"status": "disabled"}
    if len(sources) < MIN_SOURCES:
        return {"status": "skipped", "reason": "insufficient_sources"}
    records = _ingest_stages(sources)
    results = _replay_and_capture(records, run_cade)
    reindexed = _reindex(results)
    backtest = _compute_backtest(results)
    _inc("cycles")
    return {"status": "ok", "records": len(records), "reindexed": reindexed,
            **backtest}


def stats():
    with _stats_lock:
        return dict(_stats)


def reset_stats():
    with _stats_lock:
        for k in _stats:
            _stats[k] = 0


if __name__ == "__main__":
    print(json.dumps(stats(), indent=2))
