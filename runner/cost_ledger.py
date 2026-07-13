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
    "claude-opus-4-8": (15.0, 75.0),
}
_IN = re.compile(r"(input|prompt)[ _]tokens[\"':\s]+([0-9,]+)", re.I)
_OUT = re.compile(r"(output|completion)[ _]tokens[\"':\s]+([0-9,]+)", re.I)


def _n(s): return int(s.replace(",", ""))


def record(project, slug, model, logpath):
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
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a") as f:
        f.write(json.dumps(row) + "\n")
    return row


def report():
    if not os.path.exists(LEDGER):
        print("no cost data yet"); return
    rows = [json.loads(l) for l in open(LEDGER) if l.strip()]
    by_proj, by_model = {}, {}
    total = 0.0
    for r in rows:
        by_proj[r["project"]] = by_proj.get(r["project"], 0) + r["usd"]
        by_model[r["model"]] = by_model.get(r["model"], 0) + r["usd"]
        total += r["usd"]
    print(f"TOTAL ${total:.2f} over {len(rows)} tasks")
    print("by project:", {k: round(v, 2) for k, v in sorted(by_proj.items(), key=lambda x: -x[1])})
    print("by model:  ", {k: round(v, 2) for k, v in sorted(by_model.items(), key=lambda x: -x[1])})


if __name__ == "__main__":
    report()
