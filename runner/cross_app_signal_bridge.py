#!/usr/bin/env python3
"""
cross_app_signal_bridge.py — subscribes to all app signal sources.

Consumes:
  1. Smarter's IntelligenceBus signals (via shared Supabase table)
  2. Apparently's coordination_events (already in Supabase)
  3. Apparently's hivemind_consultations (consensus results)
  4. Beethoven's own improvement_proposals and stage_metrics

Publishes an aggregated cross-app signal summary to:
  - improvement_miner (targeted mining based on actual signals)
  - meta_loop (cadence tuning based on cross-app health)

Loop type: 'signal_bridge' (cadence 300s — every 5 min).
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

POLL_WINDOW_MIN = int(os.environ.get("SIGNAL_BRIDGE_WINDOW_MIN", "60"))
RUNTIME_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           ".runtime")


def _iso_minutes_ago(minutes):
    t = time.time() - (minutes * 60)
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _safe_select(table, params):
    """Select with fail-soft — table may not exist yet in every environment."""
    try:
        return db.select(table, params) or []
    except Exception:
        return []


def consume_intelligence_bus_signals(since_minutes=None):
    """Read Smarter's IntelligenceBus signals from shared table."""
    since_minutes = since_minutes or POLL_WINDOW_MIN
    return _safe_select("intelligence_signals", {
        "select": "id,category,severity,source,payload,created_at",
        "created_at": f"gte.{_iso_minutes_ago(since_minutes)}",
        "order": "created_at.desc",
        "limit": "100",
    })


def consume_coordination_events(since_minutes=None):
    """Read Apparently's coordination_events."""
    since_minutes = since_minutes or POLL_WINDOW_MIN
    return _safe_select("coordination_events", {
        "select": "id,event_type,payload,created_at",
        "created_at": f"gte.{_iso_minutes_ago(since_minutes)}",
        "order": "created_at.desc",
        "limit": "100",
    })


def consume_hivemind_consensus(since_minutes=None):
    """Read Apparently's hivemind consultation results."""
    since_minutes = since_minutes or (POLL_WINDOW_MIN * 24)   # default 24h window
    return _safe_select("hivemind_consultations", {
        "select": "id,consensus_type,result,created_at",
        "created_at": f"gte.{_iso_minutes_ago(since_minutes)}",
        "order": "created_at.desc",
        "limit": "50",
    })


def aggregate_signals():
    """Build a cross-app signal summary."""
    intel     = consume_intelligence_bus_signals()
    coord     = consume_coordination_events()
    consensus = consume_hivemind_consensus()

    summary = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "intelligence_signals": {
            "count": len(intel),
            "by_category": {},
            "by_severity": {},
            "critical": [],
        },
        "coordination_events": {
            "count": len(coord),
            "by_type": {},
        },
        "hivemind_consensus": {
            "count": len(consensus),
            "consensus_types": {},
            "escalations": [],
        },
    }

    for s in intel:
        cat = s.get("category", "unknown")
        sev = s.get("severity", "info")
        summary["intelligence_signals"]["by_category"][cat] = \
            summary["intelligence_signals"]["by_category"].get(cat, 0) + 1
        summary["intelligence_signals"]["by_severity"][sev] = \
            summary["intelligence_signals"]["by_severity"].get(sev, 0) + 1
        if sev == "critical":
            summary["intelligence_signals"]["critical"].append(
                {"id": s.get("id"), "category": cat, "source": s.get("source")})

    for e in coord:
        t = e.get("event_type", "unknown")
        summary["coordination_events"]["by_type"][t] = \
            summary["coordination_events"]["by_type"].get(t, 0) + 1

    for c in consensus:
        ct = c.get("consensus_type", "unknown")
        summary["hivemind_consensus"]["consensus_types"][ct] = \
            summary["hivemind_consensus"]["consensus_types"].get(ct, 0) + 1
        if ct == "escalated":
            summary["hivemind_consensus"]["escalations"].append(
                {"id": c.get("id"), "result": str(c.get("result", ""))[:200]})

    # Persist the latest summary for other modules to read
    try:
        os.makedirs(RUNTIME_DIR, exist_ok=True)
        with open(os.path.join(RUNTIME_DIR, "signal_bridge_summary.json"), "w") as f:
            json.dump(summary, f, indent=2)
    except Exception:
        pass

    return summary


def get_signal_context_for_miner():
    """Compact string for improvement_miner's _context()."""
    # Try local file first (written by the last bridge tick), fall back to live
    summary = None
    path = os.path.join(RUNTIME_DIR, "signal_bridge_summary.json")
    try:
        with open(path) as f:
            summary = json.load(f)
    except Exception:
        pass
    if not summary:
        try:
            summary = aggregate_signals()
        except Exception:
            return ""

    lines = ["CROSS-APP SIGNALS (last hour):"]

    intel = summary.get("intelligence_signals", {})
    if intel.get("count"):
        lines.append(f"  IntelligenceBus: {intel['count']} signals")
        if intel.get("by_severity"):
            lines.append(f"    By severity: {intel['by_severity']}")
        if intel.get("by_category"):
            lines.append(f"    By category: {intel['by_category']}")
        if intel.get("critical"):
            lines.append(f"    CRITICAL: {len(intel['critical'])} signals requiring attention")

    coord = summary.get("coordination_events", {})
    if coord.get("count"):
        lines.append(f"  Coordination: {coord['count']} events")
        if coord.get("by_type"):
            lines.append(f"    By type: {coord['by_type']}")

    cons = summary.get("hivemind_consensus", {})
    if cons.get("count"):
        lines.append(f"  Hivemind Consensus: {cons['count']} consultations")
        if cons.get("consensus_types"):
            lines.append(f"    Types: {cons['consensus_types']}")
        if cons.get("escalations"):
            lines.append(f"    ESCALATIONS: {len(cons['escalations'])} (needs human review)")

    return "\n".join(lines) if len(lines) > 1 else ""


def run():
    """Entry point called by loops.py for the 'signal_bridge' loop type."""
    summary = aggregate_signals()
    total = (summary.get("intelligence_signals", {}).get("count", 0)
             + summary.get("coordination_events", {}).get("count", 0)
             + summary.get("hivemind_consensus", {}).get("count", 0))
    print(f"cross_app_signal_bridge: aggregated {total} cross-app signals")
    return summary


if __name__ == "__main__":
    import pprint
    pprint.pprint(run())
