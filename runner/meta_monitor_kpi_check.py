#!/usr/bin/env python3
"""meta_monitor_kpi_check.py — is any meta-monitor KPI on fire?

The hourly orch-operator meta-monitor writes a `orch_kpi_baseline` row into
`controls` holding the KPIs it measured, the baseline it compared against, and
the resulting ratios. A KPI is "on fire" at >= 2x its baseline; that threshold
is what gates whether the P1-queue-clearance playbook may act.

Until now that comparison existed only inside the operator prompt and was
re-derived by hand every run, which is why "check the meta-monitor KPIs" keeps
being decomposed into a task. This module is that check, written down: pure
functions over the row, so the verdict is reproducible and testable without a
database.

Pure and dependency-free on purpose. `evaluate()` takes the control row and
returns a verdict; only `load_baseline_row()` touches the DB, and it is
injectable so the decision logic is never gated on one being reachable.

Env vars:
    ORCH_KPI_ON_FIRE_RATIO   on-fire threshold as a multiple of baseline
                             (default 2.0)

Usage:
    python3 runner/meta_monitor_kpi_check.py            # human-readable
    python3 runner/meta_monitor_kpi_check.py --json     # machine-readable
Exit status: 0 nothing on fire, 1 at least one KPI on fire, 2 undeterminable.
"""

import json
import os
import sys

#: A KPI at or above this multiple of its baseline is on fire. Named rather
#: than inlined so it is fleet-pushable via fleet_control.py (ORCH_ prefix).
ON_FIRE_RATIO = float(os.environ.get("ORCH_KPI_ON_FIRE_RATIO", "2.0"))

#: The control row the meta-monitor writes each run.
BASELINE_KEY = "orch_kpi_baseline"

#: KPIs where a LARGER number is worse. Only these can be "on fire" — a ratio
#: of 3x on `merged_24h` is three times the throughput, not an emergency, and
#: alerting on it would train the operator to ignore the check.
HIGHER_IS_WORSE = frozenset({
    "queued",
    "queued_4d",
    "p90_h",
    "alerts",
    "quar_24h",
    "phantom",
    "undecided",
})


def _as_float(value):
    """Coerce to float, or None. Never raises — a KPI can arrive as anything."""
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_ratios(measured, baseline):
    """Ratio of each measured KPI to its baseline, for comparable KPIs only.

    A KPI is skipped when either side is missing or non-numeric, and when the
    baseline is 0 — 0 -> anything has no finite ratio, and reporting `inf`
    would fire the alarm on the first measurement of a brand-new KPI.
    """
    ratios = {}
    for name, raw in (measured or {}).items():
        now = _as_float(raw)
        was = _as_float((baseline or {}).get(name))
        if now is None or was is None or was == 0:
            continue
        ratios[name] = now / was
    return ratios


def on_fire(ratios, threshold=None):
    """KPIs at or above `threshold`, worst first. Only HIGHER_IS_WORSE ones."""
    limit = ON_FIRE_RATIO if threshold is None else threshold
    hot = [
        {"kpi": name, "ratio": ratio, "threshold": limit}
        for name, ratio in (ratios or {}).items()
        if name in HIGHER_IS_WORSE and ratio >= limit
    ]
    return sorted(hot, key=lambda item: (-item["ratio"], item["kpi"]))


def evaluate(row, threshold=None):
    """Verdict for one `orch_kpi_baseline` control row.

    Returns a dict with:
      ok            — True when nothing is on fire AND the row was readable
      determinable  — False when the row is missing/unparseable, which is NOT
                      the same as healthy and must not be reported as such
      on_fire       — list of {kpi, ratio, threshold}, worst first
      ratios        — every comparable ratio, recomputed here rather than
                      trusting the row's own `ratios_vs_baseline`
      worst         — the worst HIGHER_IS_WORSE ratio, or None
      measured_at   — as recorded by the meta-monitor
    """
    limit = ON_FIRE_RATIO if threshold is None else threshold
    blank = {
        "ok": False,
        "determinable": False,
        "on_fire": [],
        "ratios": {},
        "worst": None,
        "measured_at": None,
        "threshold": limit,
        "reason": "no readable orch_kpi_baseline row",
    }

    value = row.get("value") if isinstance(row, dict) else None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return blank
    if not isinstance(value, dict):
        return blank

    baseline = value.get("baseline_used")
    if not isinstance(baseline, dict):
        return dict(blank, reason="row carries no baseline_used to compare against")

    # Recomputed from the raw numbers, not read from `ratios_vs_baseline`: the
    # point of the check is to verify the meta-monitor's arithmetic, and a
    # check that trusts the number it is verifying verifies nothing.
    ratios = compute_ratios(value, baseline)
    hot = on_fire(ratios, limit)
    comparable = {k: v for k, v in ratios.items() if k in HIGHER_IS_WORSE}

    return {
        "ok": not hot,
        "determinable": True,
        "on_fire": hot,
        "ratios": ratios,
        "worst": max(comparable.items(), key=lambda kv: kv[1]) if comparable else None,
        "measured_at": value.get("measured_at"),
        "threshold": limit,
        "reason": "on fire" if hot else "all tracked KPIs below threshold",
    }


def load_baseline_row(fetch=None):
    """Read the control row. Returns None rather than raising if unreachable."""
    if fetch is not None:
        try:
            return fetch(BASELINE_KEY)
        except Exception:
            return None
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import db  # noqa: PLC0415 — optional dependency, import kept local

        rows = db.query(
            "SELECT key, value FROM controls WHERE key = %s", (BASELINE_KEY,)
        )
        return rows[0] if rows else None
    except Exception:
        return None


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    verdict = evaluate(load_baseline_row())

    if "--json" in argv:
        print(json.dumps(verdict, indent=2, sort_keys=True, default=str))
    elif not verdict["determinable"]:
        print(f"UNDETERMINABLE: {verdict['reason']}")
    elif verdict["ok"]:
        worst = verdict["worst"]
        detail = f"worst {worst[0]} {worst[1]:.4f}x" if worst else "no comparable KPI"
        print(
            f"OK: nothing at or above {verdict['threshold']}x baseline "
            f"({detail}, measured_at {verdict['measured_at']})"
        )
    else:
        for item in verdict["on_fire"]:
            print(f"ON FIRE: {item['kpi']} {item['ratio']:.4f}x >= {item['threshold']}x")

    if not verdict["determinable"]:
        return 2
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
