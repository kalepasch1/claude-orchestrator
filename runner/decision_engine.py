#!/usr/bin/env python3
"""
decision_engine.py - turns each legal/strategic decision from a yes/no card into a full decision-support
session, drawing on the same analytical firepower as Smarter (negotiation) and Tomorrow (war room):

  brief(approval)   -> a STRUCTURED brief: the real decision, the OPTIONS (never just yes/no), each with
                       upside / downside / reversibility / precedent, leverage & BATNA for negotiations,
                       scenario outcomes, a recommendation + confidence, and "what would change this".
  ask(id, question) -> threaded Q&A: you ask anything, it answers with analysis + your app data.
  decide(id, type, text) -> records a NON-BINARY decision (approve | deny | conditions | negotiate |
                       directive | more_info) with free text, and if the decision implies a PROCESS,
                       spawns tasks INSTANTLY into the right project.

High-stakes -> uses the strongest available model (Opus) for briefs; Q&A uses a strong-but-cheaper tier.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

BRIEF_MODEL = os.environ.get("DECISION_MODEL", "claude-opus-4-8")
QA_MODEL = os.environ.get("DECISION_QA_MODEL", "claude-sonnet-4-6")

BRIEF_PROMPT = """You are the chief-of-staff / general-counsel / lead negotiator for a solo founder.
Analyze this decision the way a war room + a top negotiator would. Return ONE JSON object:
{
 "decision": "<the real question in one sentence>",
 "stakes": "<what's actually at risk / to gain>",
 "options": [ {"label":"...","upside":"...","downside":"...","reversibility":"high|med|low","precedent":"what others do"} ],
 "negotiation": {"leverage":"our leverage","batna":"best alt if this fails","counter":"a smart counter-move or ''"},
 "scenarios": [ {"if":"...","then":"...","likelihood":"high|med|low"} ],
 "recommendation": "<clear rec>",
 "confidence": 0-100,
 "what_would_change_this": "<the key fact that would flip the recommendation>",
 "counsel_needed": true|false
}
Be concrete and specific to THIS decision; no boilerplate. DECISION: {title}
CONTEXT: {why}"""


def _complete(model_pref, prompt, task_class="hard"):
    try:
        import model_policy, model_gateway
        # prefer the requested strong model but respect availability/cost policy
        prov, model, _ = model_policy.choose(task_class, agentic=False, need=9)
        # decisions are worth the strongest model when available (subscription = $0)
        if "claude" in prov:
            model = model_pref
        r = model_gateway.complete(prov, model, prompt)
        return r.get("text") or ""
    except Exception as e:
        return ""


def brief(approval):
    db.update("approvals", {"id": approval["id"]}, {"brief_status": "generating"})
    prompt = BRIEF_PROMPT.replace("{title}", (approval.get("title") or "")[:400]).replace(
        "{why}", (approval.get("why") or "")[:1200])
    txt = _complete(BRIEF_MODEL, prompt, "hard")
    import re
    m = re.search(r"\{.*\}", txt, re.S)
    data = {}
    if m:
        try:
            data = json.loads(m.group(0))
        except Exception:
            data = {}
    if data:
        # human-readable summary for surfaces that don't render JSON
        rec = data.get("recommendation", "")
        conf = data.get("confidence", "")
        summary = f"{data.get('decision','')} — Rec: {rec} (confidence {conf}%). " \
                  f"{'⚖️ counsel advised.' if data.get('counsel_needed') else ''}"
        db.update("approvals", {"id": approval["id"]},
                  {"brief_json": data, "prebrief": summary[:1500], "brief_status": "ready"})
    else:
        db.update("approvals", {"id": approval["id"]}, {"brief_status": "ready", "prebrief": (txt or "")[:1500]})
    return data


def ask(approval_id, question, record_question=True):
    """Threaded follow-up. Answers using the card + brief + prior messages (+ app data if wired).
    record_question=False when the question is already in the thread (cockpit-posted)."""
    a = (db.select("approvals", {"select": "*", "id": f"eq.{approval_id}"}) or [{}])[0]
    msgs = db.select("decision_messages", {"select": "role,body", "approval_id": f"eq.{approval_id}",
                                           "order": "created_at.asc", "limit": "20"}) or []
    if record_question:
        db.insert("decision_messages", {"approval_id": approval_id, "role": "owner", "body": question[:2000]})
    history = "\n".join(f"{m['role']}: {m['body']}" for m in msgs)
    prompt = (f"You are advising the founder on this decision. Be direct, specific, and analytical "
              f"(negotiation leverage, downside, precedent, next steps). Decision: {a.get('title')}\n"
              f"Context: {a.get('why')}\nBrief: {json.dumps(a.get('brief_json') or {})[:2000]}\n"
              f"Conversation so far:\n{history}\nFounder asks: {question}\nAnswer concisely.")
    ans = _complete(QA_MODEL, prompt, "plan") or "I couldn't generate an answer right now."
    db.insert("decision_messages", {"approval_id": approval_id, "role": "assistant", "body": ans[:3000]})
    return ans


def decide(approval_id, decision_type, text=""):
    """Record a non-binary decision. If it implies a PROCESS, spawn it instantly."""
    a = (db.select("approvals", {"select": "*", "id": f"eq.{approval_id}"}) or [{}])[0]
    status = {"approve": "approved", "deny": "denied"}.get(decision_type, "pending")
    upd = {"decision_type": decision_type, "decision_text": text[:2000]}
    if status in ("approved", "denied"):
        upd.update({"status": status, "decided_by": "owner", "decided_at": "now()"})
    db.update("approvals", {"id": approval_id}, upd)
    db.insert("decision_messages", {"approval_id": approval_id, "role": "owner",
              "body": f"[decision: {decision_type}] {text}"[:2000]})
    # a directive / conditional approve / negotiate that implies ACTION -> spawn a process now
    if decision_type in ("directive", "conditions", "negotiate") or (decision_type == "approve" and text.strip()):
        _spawn_process(a, text or decision_type)
    return {"ok": True, "decision": decision_type, "status": status}


def _spawn_process(approval, directive):
    """Turn a decision directive into real tasks in the relevant project, instantly."""
    project = approval.get("project") or "PORTFOLIO"
    proc = db.insert("decision_processes", {"approval_id": approval["id"], "project": project,
                     "directive": directive[:1000], "status": "planning"})
    proj = (db.select("projects", {"select": "id", "name": f"eq.{project}"}) or [{}])
    task_ids = []
    if proj and proj[0].get("id"):
        import re
        slug = "decision-" + re.sub(r"[^a-z0-9]+", "-", (approval.get("title") or "act")[:40].lower()).strip("-")
        t = db.insert("tasks", {"project_id": proj[0]["id"], "slug": slug, "state": "QUEUED", "kind": "build",
              "prompt": f"OWNER DECISION -> EXECUTE: {directive}\nContext: {approval.get('why')}\n"
                        f"Implement/act on this decision with a well-tested change; if it's a document or "
                        f"filing, draft it; if it's a negotiation, prepare the materials.",
              "deps": [], "base_branch": "main", "material": True})
        if t:
            task_ids = [t[0]["id"] if isinstance(t, list) else t["id"]]
    db.update("decision_processes", {"approval_id": approval["id"]},
              {"status": "running" if task_ids else "queued", "spawned_task_ids": task_ids})
    db.update("approvals", {"id": approval["id"]}, {"process_spawned": True})
    return task_ids


def answer_pending():
    """Answer owner questions posted from the cockpit (an owner message with no assistant reply after)."""
    threads = {}
    for m in db.select("decision_messages", {"select": "approval_id,role,body,created_at",
                                             "order": "created_at.asc", "limit": "400"}) or []:
        threads.setdefault(m["approval_id"], []).append(m)
    answered = 0
    for aid, msgs in threads.items():
        last = msgs[-1]
        # a trailing owner message that isn't a recorded [decision:...] => needs an answer
        if last["role"] == "owner" and not (last.get("body") or "").startswith("[decision:"):
            try:
                ask(aid, last["body"], record_question=False)   # already in the thread
                answered += 1
            except Exception:
                pass
    if answered:
        print(f"decision_engine: answered {answered} owner question(s)")
    return answered


def run():
    """Auto-generate briefs for new legal/strategic cards without one, and answer pending questions."""
    answer_pending()
    cards = db.select("approvals", {"select": "id,title,why,kind,brief_status", "status": "eq.pending",
                                    "kind": "in.(legal,material)", "limit": "15"}) or []
    n = 0
    for a in cards:
        if a.get("brief_status") in ("ready", "generating"):
            continue
        brief(a); n += 1
    print(f"decision_engine: briefed {n} decision(s)")
    return n


if __name__ == "__main__":
    run()
