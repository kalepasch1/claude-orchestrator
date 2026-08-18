"""canary_triage — swarm remediation bot #3 (canary-unblocker).

Classifies a self-deploy canary failure and files the right tier-1 remediation task,
so a stuck self-deploy self-triages instead of waiting for a human. Pure + injectable.

Failure classes (ordered most-specific first):
  conflict-marker   : <<<<<<< markers in tracked code (route to conflict_marker_sentinel/PR#34)
  missing-module    : ModuleNotFoundError — an import target that does not exist
  import-error      : other ImportError at collection
  collection-error  : pytest collection interrupted (non-import)
  stale-test        : AssertionError comparing shapes/values (code evolved, test did not)
  real-regression   : a behavioural test failed in a way that looks like a genuine break
  unknown           : none matched — escalate to a human
"""

def classify(log_text):
    t = log_text or ""
    low = t.lower()
    if "leftover conflict marker" in low or "<<<<<<< " in t:
        return "conflict-marker"
    if "modulenotfounderror" in low:
        return "missing-module"
    if "importerror" in low:
        return "import-error"
    if "assertionerror" in low:
        # a dict/shape comparison that changed = stale test; a value/behaviour break = regression
        if ("left contains" in low or "right contains" in low or "omitting" in low
                or "== {" in t or "!= {" in t):
            return "stale-test"
        return "real-regression"
    if "error during collection" in low or "interrupted:" in low:
        return "collection-error"
    if "syntaxerror" in low:
        return "conflict-marker" if "<<<<<<< " in t else "collection-error"
    return "unknown"

_ROUTE = {
    "conflict-marker": ("Conflict markers in tracked code failed the canary. Resolve them "
                        "(see conflict_marker_sentinel / auto_conflict_resolver guard)."),
    "missing-module":  ("A canary test imports a module that does not exist. Create the module "
                        "or guard the import with pytest.importorskip."),
    "import-error":    "A canary test failed to import its target. Fix the import or the target.",
    "collection-error":"pytest collection was interrupted. Fix the offending test file so the gate collects.",
    "stale-test":      ("A canary test asserts an outdated shape/value; the code evolved. Align the "
                        "test with the current return (adversarially verify it is not a real regression)."),
    "real-regression": ("A behavioural canary test failed in a way that looks like a genuine regression. "
                        "Investigate the code change, not the test."),
}

def triage(log_text, enqueue_fn=None, project_id=None, head=None):
    cls = classify(log_text)
    if cls == "unknown" or enqueue_fn is None:
        return {"class": cls, "filed": False}
    rec = {
        "project_id": project_id,
        "slug": f"remediation-canary-{cls}" + (f"-{head[:8]}" if head else ""),
        "kind": "remediation",
        "priority": 1,
        "prompt": _ROUTE[cls] + (f" (head {head[:12]})" if head else ""),
        "note": f"filed by canary_triage (swarm bot #3); class={cls}",
    }
    try:
        enqueue_fn(rec); return {"class": cls, "filed": True}
    except Exception:
        return {"class": cls, "filed": False}
