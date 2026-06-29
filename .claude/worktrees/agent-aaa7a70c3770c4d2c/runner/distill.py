#!/usr/bin/env python3
"""
distill.py - clean-room learning. Takes a GENERALIZED process description (public know-how,
NOT raw customer data), scrubs anything that slips through, and produces a reusable
capability draft with SYNTHETIC test exemplars - so you learn the workflow without any
client's data ever crossing the boundary. Output is published to the capability registry.

distill(process_text, name, slug, domain, source_project, regulated=False)
"""
import os, sys, json, subprocess, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import privacy, capability, db

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
MODEL = os.environ.get("DISTILL_MODEL", "claude-sonnet-4-6")

PROMPT = """Generalize the PROCESS below into a reusable, productizable capability. Output ONE
JSON object: {"summary":"1-2 sentences","steps":["..."],"contract":{"inputs":[...],
"outputs":[...],"depends_on":[]},"synthetic_examples":[{"input":{...},"expected":"..."}]}.
Use ONLY generalized/public knowledge and FICTIONAL synthetic data - never real names,
clients, or identifiers. PROCESS:
"""


def distill(process_text, name, slug, domain, source_project, consent=True,
            residency=None, regulated=False):
    clean_in, findings = privacy.scrub(process_text)
    if findings:
        print(f"distill: scrubbed {findings} from input before processing")
    try:
        out = subprocess.check_output([CLAUDE_BIN, "-p", PROMPT + clean_in, "--model", MODEL,
                                       "--output-format", "text"], text=True, timeout=200)
        d = json.loads(re.search(r"\{.*\}", out, re.S).group(0))
    except Exception as e:
        return {"ok": False, "error": f"distillation failed: {e}"}
    spec = json.dumps({"steps": d.get("steps", []), "examples": d.get("synthetic_examples", [])}, indent=2)
    # double-scrub the model output before it enters the registry
    if not privacy.is_clean(spec):
        spec, _ = privacy.scrub(spec)
    res = capability.publish(name, slug, domain, d.get("summary", ""), d.get("contract", {}),
                             spec, source_project, consent=consent, residency=residency,
                             regulated=regulated)
    # store synthetic evals
    cap = capability.get(slug)
    for ex in d.get("synthetic_examples", [])[:10]:
        ce, _ = privacy.scrub(json.dumps(ex.get("input", {})))
        db.insert("capability_evals", {"capability_id": cap["id"], "name": "synthetic",
                                       "input": json.loads(ce) if ce.strip().startswith("{") else {},
                                       "expected": str(ex.get("expected", ""))[:500]})
    return {"ok": True, "capability": slug, "scrubbed": res.get("scrubbed")}


if __name__ == "__main__":
    print("distill.py: call distill(process_text, name, slug, domain, source_project)")
