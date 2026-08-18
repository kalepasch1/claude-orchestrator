"""self_deploy_watchdog — swarm remediation bot #5.

Reads the self-deploy log and, on a `canary_failed` verdict, drives canary_triage (bot #3)
to file the right tier-1 remediation task — so a stuck self-deploy triages itself instead of
waiting for a human. Pure + injectable (takes log text + an enqueue callable).
"""
import re, json

def parse_last_verdict(log_text):
    """Return the most recent {reason, running, head} verdict block, or None."""
    t = log_text or ""
    idxs = [m.start() for m in re.finditer(r'"reason"\s*:', t)]
    if not idxs:
        return None
    seg = t[idxs[-1] - 1:]  # step back to catch the opening brace region
    def _find(key):
        m = re.search(r'"%s"\s*:\s*"([^"]*)"' % key, seg)
        return m.group(1) if m else None
    reason = _find("reason")
    if reason is None:
        return None
    return {"reason": reason, "running": _find("running_commit"), "head": _find("head_commit")}

def watch(log_text, enqueue_fn=None, project_id=None):
    """On canary_failed: triage + file remediation. Returns an action dict."""
    v = parse_last_verdict(log_text)
    if not v:
        return {"action": "none"}
    if v["reason"] == "canary_failed":
        import canary_triage
        res = canary_triage.triage(log_text, enqueue_fn=enqueue_fn,
                                   project_id=project_id, head=v.get("head"))
        return {"action": "triaged", "class": res.get("class"), "filed": res.get("filed"),
                "head": v.get("head")}
    return {"action": "none", "reason": v["reason"]}
