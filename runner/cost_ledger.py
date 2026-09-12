#!/usr/bin/env python3
"""
cost_ledger.py - keep API spend minimized AND visible across all projects.

record()  - after each task, parse token usage from the claude -p log (if present)
            and append a costed row to ~/.claude-orchestrator/cost.jsonl
report()  - roll up spend by project / model / day so you can see where money goes
            and confirm the model router is doing its job.

Prices are editable (USD per 1M tokens). Update if Anthropic's pricing changes.
This module never blocks a build; it's pure accounting.
"""
import os, sys, json, re, time, glob

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
LEDGER = os.path.join(HOME, "cost.jsonl")

# USD per 1M tokens (input, output). Edit to match current pricing.
PRICES = {
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-opus-4-8": (15.0, 75.0),
    "claude-fable-5": (3.0, 15.0),
}
_IN = re.compile(r"(input|prompt)[ _]tokens[\"':\s]+([0-9,]+)", re.I)
_OUT = re.compile(r"(output|completion)[ _]tokens[\"':\s]+([0-9,]+)", re.I)


def _n(s):
    """Parse a numeric string that may contain commas (e.g. '1,234') into an int. Returns 0 on error."""
    try:
        return int(str(s or "").replace(",", ""))
    except (ValueError, TypeError):
        return 0


def record(project, slug, model, logpath):
    """Extract token counts from a task log and append a costed row to the ledger.

    Parses input/output token counts from the log file at *logpath*, computes USD
    cost using PRICES, and appends a JSON line to LEDGER. Returns the row dict.
    Fail-soft: continues even if log parsing or write fails.
    """
    itok = otok = 0
    try:
        txt = open(logpath, errors="replace").read()
        mi = _IN.findall(txt); mo = _OUT.findall(txt)
        itok = sum(_n(x[1]) for x in mi); otok = sum(_n(x[1]) for x in mo)
    except Exception:
        pass
    pin, pout = PRICES.get(model, (3.0, 15.0))
    cost = itok / 1e6 * pin + otok / 1e6 * pout
    row = {"ts": time.time(), "project": project, "slug": slug, "model": model,
           "input_tokens": itok, "output_tokens": otok, "usd": round(cost, 4)}
    try:
        os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
        with open(LEDGER, "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as exc:  # noqa: BLE001 - cost accounting must not wedge a run
        # A broad catch is the fail-soft convention here; a SILENT one is the
        # defect. Losing a cost row unannounced is how the ledger quietly stops
        # matching reality, so say so and keep going.
        print("cost_ledger: could not append row (%s); continuing" % exc,
              file=sys.stderr)
    return row


def report():
    """Print aggregate cost report. Fail-soft: prints diagnostic on error instead of crashing."""
    if not os.path.exists(LEDGER):
        print("no cost data yet"); return
    rows = []
    try:
        with open(LEDGER, errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except (json.JSONDecodeError, ValueError):
                    pass
    except (OSError, IOError) as e:
        print(f"error reading ledger: {e}"); return
    if not rows:
        print("no valid cost records found"); return
    by_proj, by_model = {}, {}
    total = 0.0
    for r in rows:
        try:
            proj = r.get("project") or "unknown"
            model = r.get("model") or "unknown"
            cost = float(r.get("usd") or 0)
            by_proj[proj] = by_proj.get(proj, 0) + cost
            by_model[model] = by_model.get(model, 0) + cost
            total += cost
        except (ValueError, TypeError):
            pass
    print(f"TOTAL ${total:.2f} over {len(rows)} tasks")
    print("by project:", {k: round(v, 2) for k, v in sorted(by_proj.items(), key=lambda x: -x[1])})
    print("by model:  ", {k: round(v, 2) for k, v in sorted(by_model.items(), key=lambda x: -x[1])})


if __name__ == "__main__":
    report()
