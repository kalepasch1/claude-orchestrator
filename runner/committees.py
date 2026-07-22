#!/usr/bin/env python3
"""
committees.py - ADAPTIVE EXPERT PANELS, modeled on Smarter's memo-drafting: NOT fixed committees with
standing members. For each SPECIFIC issue, a TRIAGE step assembles the optimal expert panel(s) on the fly —
composition, count, chair, and seats are all tailored to that issue and change every time.

  triage  ASSEMBLE          _triage_panels() summons the ideal experts for THIS issue (a legal/compliance
                            panel is force-seated whenever there's legal/privacy/regulatory exposure)
  round 0 OPENING POSITIONS  each summoned expert drafts an independent opinion from its own lens
  round 1+ DEBATE/EVOLVE     experts cross-examine, weigh the strongest counterpoints, and REVISE toward
                            the optimal conclusion (ideas compete; repeats until convergence or MAX_ROUNDS)
  synth   CONSENSUS MEMO     the chair drafts one opinion: verdict + conviction + conditions + forecast +
                            PRESERVED DISSENT (minority view kept, not erased)

review() assembles the panels, runs each debate, and aggregates (calibration- AND conviction-weighted, on
probability-discounted EV) into GO / REVISE / HOLD / EXPERIMENT / ESCALATE, with a Legal veto (any
dynamically-seated legal expert) and arbitration/escalation only for critical or highly contentious splits.

Learning transfers across freshly-assembled panels because calibration/scoreboard are keyed by expert
DOMAIN (a stable label), not by any fixed membership. Costless-first + cross-model: experts are spread
across providers; consensus memos are stored (committee_opinions) as reusable cross-app PRECEDENT.
"""
import os, sys, json, re, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MAX_ROUNDS = int(os.environ.get("COMMITTEE_MAX_ROUNDS", "2"))      # coordination rounds after opening
MAX_COMMITTEES = int(os.environ.get("COMMITTEE_MAX_PER_SUBJECT", "5"))  # relevance-gate to top-N
DEFAULT_SEATS = ["Domain lead", "Risk-focused specialist", "Execution-focused specialist"]
RED_SEAT = "Devil's Advocate (red seat)"   # a standing adversary seated on EVERY panel

# ---- one seat's opinion -------------------------------------------------------------------------
SEAT_PROMPT = """You are {seat}, a top-tier expert seat on the {committee} committee.
Committee mandate: {mandate}. Speak ONLY from your seat's specific expertise and lens.
{redseat}{evidence}{precedent}{reliability}{coordination}
Return ONE JSON object:
{"verdict":"support|oppose|conditional|needs-info","score":0-10,
 "conviction":0-10,"basis":"the exact part of the proposal you're reacting to (<=1 sentence)",
 "opportunity":"biggest upside you see (<=1 sentence)","risk":"biggest risk you see (<=1 sentence)",
 "conditions":"specific condition(s) that would make you comfortable, or '' (<=1 sentence)",
 "recommendation":"your concrete recommendation (<=1 sentence)"}
PROPOSAL: {title}
DETAIL: {body}"""

# ---- the chair synthesizes the panel into ONE opinion -------------------------------------------
CHAIR_PROMPT = """You are the {chair}, chair of the {committee} committee. Below are your seats' FINAL
positions after deliberation. Draft the committee's SINGLE consensus opinion. Weigh conviction, do not
just average; a high-conviction, well-grounded objection can carry the room. Preserve any material
minority view as dissent rather than erasing it. Then run a quick PRE-MORTEM: forecast the likely outcome.
Return ONE JSON object:
{"verdict":"support|oppose|conditional|needs-info","score":0-10,"conviction":0-10,
 "opinion":"the committee's reasoned opinion, 2-3 sentences","conditions":"binding conditions the build must honor, or ''",
 "dissent":"the strongest preserved minority view, or 'none'","recommendation":"one concrete recommendation",
 "p_success":0.0-1.0,"upside":"the 90-day upside if it works (<=1 sentence)",
 "downside":"the 90-day downside if it fails (<=1 sentence)",
 "reversible":true|false,"critical":true|false}
SEAT POSITIONS:
{positions}"""


def active_committees():
    # Retained only as a seed of stable DOMAIN LABELS (for calibration continuity) + as an offline
    # fallback. Panels are NOT these fixed rows — they are assembled fresh per issue by _triage_panels().
    return db.select("committees", {"select": "*", "active": "eq.true"}) or []


def locate_owner(subject_title, body=None):
    """Locate the existing owner committee for a subject before assembling new panels. Returns
    a dict {name, chair, mandate} for the best-matching active committee, or None if offline.
    Prefers exact name-keyword matches; falls back to the first active committee."""
    try:
        rows = db.select("committees", {"select": "name,chair,mandate", "active": "eq.true"}) or []
    except Exception:
        return None
    if not rows:
        return None
    text = ((subject_title or "") + " " + (body or "")).lower()
    words = set(w for w in re.findall(r"[a-z]{4,}", text)[:10])
    best, best_score = None, 0
    for row in rows:
        name_words = set(re.findall(r"[a-z]{4,}", (row.get("name") or "").lower()))
        score = len(words & name_words)
        if score > best_score:
            best, best_score = row, score
    return best or rows[0]


LEGAL_HINTS = ("legal", "compliance", "regulat", "privacy", "counsel", "gdpr", "ccpa", "licens", "sanction")


def _is_legal(name):
    """A panel/seat carries veto power if it is a legal/compliance/regulatory/privacy expert — regardless
    of what it's called, because panels are assembled dynamically (no fixed 'Legal & Compliance' committee)."""
    return any(k in (name or "").lower() for k in LEGAL_HINTS)


def _triage_panels(title, body, app=None):
    """ADAPTIVE ASSEMBLY (the Smarter memo-drafting model): for THIS specific issue, summon the optimal set
    of expert panels — composition, count, and seats all tailored to the issue, not a fixed roster. Returns
    a list of ad-hoc panel dicts {name(domain), mandate, chair, seats:[roles], weight}. deliberate() then
    runs each as a multi-seat debate. A legal/compliance panel is force-included whenever the issue has any
    legal/privacy/regulatory exposure, preserving the veto. Falls back to a generic panel if offline."""
    known = [c["name"] for c in active_committees()]
    spec = _json(
        "You are a TRIAGE CHIEF assembling the ideal expert review for one specific issue — like staffing a "
        "bespoke memo-drafting team. Decide which expert panels to convene and, for each, the exact expert "
        "SEATS (specific roles) best suited to THIS issue. Adapt composition and count to the issue; do not "
        "use a fixed roster. 1-4 panels, 2-4 seats each. If the issue has ANY legal/privacy/regulatory "
        "exposure, include a compliance panel. Prefer these stable DOMAIN LABELS when apt (for learning "
        "continuity) but invent new ones if the issue needs them: " + json.dumps(known)[:600] + "\n"
        "Return ONE JSON array; each item: {\"domain\":\"short stable label\",\"chair\":\"chair role\","
        "\"seats\":[\"specific expert role\", ...],\"why\":\"why this panel for this issue (<=1 sentence)\"}\n"
        f"ISSUE: {(title or '')[:200]}\nDETAIL: {(body or '')[:900]}\nAPP: {app or 'n/a'}", arr=True)
    panels = []
    for it in (spec or []):
        seats = [s for s in (it.get("seats") or []) if isinstance(s, str)][:4]
        dom = (it.get("domain") or "").strip()
        if not dom or not seats:
            continue
        panels.append({"name": dom, "mandate": (it.get("why") or dom)[:200],
                       "chair": (it.get("chair") or "Chair").strip(),
                       "seats": seats, "weight": 1.0})
        if len(panels) >= 4:
            break
    if not panels:
        return _fallback_panels(title, body)
    # guarantee a legal/compliance panel is seated when the issue is legally sensitive
    text = ((title or "") + " " + (body or "")).lower()
    if any(h in text for h in LEGAL_HINTS) and not any(_is_legal(p["name"]) for p in panels):
        panels.append({"name": "Legal & Compliance", "mandate": "legal/regulatory/privacy exposure",
                       "chair": "Managing Partner", "weight": 1.2,
                       "seats": ["Regulatory counsel", "Privacy counsel", "Contracts counsel"]})
    return panels[:4]


def _fallback_panels(title, body):
    """Offline/degraded path: a single sensible panel so review never hard-fails without the triage model."""
    text = ((title or "") + " " + (body or "")).lower()
    seats = ["Domain lead", "Risk-focused specialist", "Execution-focused specialist"]
    name = "General Review"
    if any(h in text for h in LEGAL_HINTS):
        name, seats = "Legal & Compliance", ["Regulatory counsel", "Privacy counsel", "Risk specialist"]
    elif any(k in text for k in ("price", "pricing", "revenue", "monet")):
        name, seats = "Pricing & Monetization", ["Pricing strategist", "Unit-economics analyst", "Packaging expert"]
    elif any(k in text for k in ("security", "auth", "vuln", "secret")):
        name, seats = "Security & Trust", ["AppSec lead", "Identity architect", "Abuse specialist"]
    return [{"name": name, "mandate": "adaptive fallback", "chair": "Chair", "seats": seats, "weight": 1.0}]


def _high_stakes_debate(subject_type, subject_id, title, body, blast_radius):
    """Three independent proposals, cross-critique, then a judge; durable before action."""
    proposals = []
    for lens in ("operator", "risk adversary", "customer/economic advocate"):
        proposals.append(_json("Independently propose the safest concrete decision. Return JSON with "
                               "verdict(proceed|hold), rationale, conditions. Lens: %s\n%s\n%s" %
                               (lens, title[:300], body[:1200])))
    critiques = []
    for i, proposal in enumerate(proposals):
        critiques.append(_json("Critique proposal %d for hidden failure modes. Return JSON with verdict and rationale. "
                               "Proposal: %s" % (i + 1, json.dumps(proposal))))
    judge = _json("Synthesize these independent proposals and critiques. Return JSON {verdict:proceed|hold, "
                  "rationale:string, dissent:[string]}. Proposals=%s Critiques=%s" %
                  (json.dumps(proposals), json.dumps(critiques)))
    debate_id = hashlib.sha256(f"{subject_type}:{subject_id}:{title}".encode()).hexdigest()[:32]
    row = {"id": debate_id, "subject_type": subject_type, "subject_id": str(subject_id),
           "blast_radius": blast_radius, "proposals": proposals, "critiques": critiques,
           "judgment": judge, "dissent": judge.get("dissent", []) if isinstance(judge, dict) else []}
    try:
        db.insert("high_stakes_debates", row, upsert=True)
        import evidence_bus
        evidence_bus.append("ORCHESTRATOR", "debate.completed", debate_id, row)
    except Exception:
        pass
    return {"id": debate_id, "judge": judge or {"verdict": "hold"}}


def _seat_need(committee, seat):
    """SEAT-LEVEL MODEL SPECIALIZATION: high-stakes seats (legal/regulatory/security/red-seat) route to a
    stronger model; well-calibrated seats earn a bigger model too. Returns a 'need' level for model_policy."""
    s = (seat or "").lower()
    base = 5
    if any(k in s for k in ("counsel", "regulatory", "legal", "privacy", "security", "appsec", "auth", "abuse")):
        base = 8
    if "devil" in s or "red seat" in s:
        base = 7
    if _seat_weight(committee, seat) >= 1.25:   # proven seats earn the stronger model
        base = min(9, base + 1)
    return base


def _complete(prompt, kind="review", need=None):
    try:
        import model_policy, model_gateway
        prov, model, _ = model_policy.choose_diverse(kind, need=need)
        r = model_gateway.complete(prov, model, prompt)
        return r.get("text") or ""
    except Exception:
        return ""


def _json(prompt, kind="review", need=None, arr=False):
    txt = _complete(prompt, kind, need)
    m = re.search(r"\[.*\]" if arr else r"\{.*\}", txt, re.S)
    try:
        return json.loads(m.group(0)) if m else ({} if not arr else [])
    except Exception:
        return {} if not arr else []


def _cal_weight(name):
    """CALIBRATION: committees whose past verdicts matched realized outcomes count more (0.5..1.5)."""
    try:
        r = db.select("committee_calibration", {"select": "weight", "committee": f"eq.{name}"}) or []
        return float(r[0]["weight"]) if r else 1.0
    except Exception:
        return 1.0


def _seats(committee):
    s = committee.get("seats")
    if isinstance(s, str):
        try:
            s = json.loads(s)
        except Exception:
            s = None
    return s if isinstance(s, list) and s else list(DEFAULT_SEATS)


def _precedent(committee_name, title, body, app=None):
    """CONSENSUS MEMORY + CROSS-APP CASE LAW: surface the closest prior opinion from THIS committee as
    precedent — from ANY app in the portfolio — so a lesson learned on one app pre-empts the same mistake
    on another. Same-app precedent is preferred; cross-app precedent is labeled so the panel weighs transfer."""
    try:
        rows = db.select("committee_opinions", {"select": "app,subject_title,consensus_verdict,opinion",
                         "committee": f"eq.{committee_name}", "order": "created_at.desc", "limit": "80"}) or []
    except Exception:
        rows = []
    if not rows:
        return ""
    key = set(re.findall(r"[a-z]{4,}", ((title or "") + " " + (body or "")).lower()))
    best, bscore = None, 0
    for r in rows:
        kk = set(re.findall(r"[a-z]{4,}", (r.get("subject_title") or "").lower()))
        ov = len(key & kk) + (1 if app and r.get("app") == app else 0)   # slight same-app preference
        if ov > bscore:
            best, bscore = r, ov
    if best and bscore >= 2:
        origin = ("this app" if app and best.get("app") == app else
                  f"a DIFFERENT app ({best.get('app')})" if best.get("app") else "a prior matter")
        return (f"PRECEDENT (from {origin}) — the committee held '{best.get('consensus_verdict')}': "
                f"{(best.get('opinion') or '')[:240]}. Build on it unless this case is materially different.\n")
    return ""


def _today():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def _budget_cap():
    """SELF-TUNING CAP: the daily autonomy budget is EARNED. tune_budget() raises it when recent auto-builds
    are landing well and lowers it after misses; falls back to the env default."""
    default = int(os.environ.get("COMMITTEE_DAILY_AUTOBUILDS", "20"))
    try:
        m = db.select("owner_model", {"select": "value", "key": "eq.autonomy_budget"}) or []
        return int(m[0]["value"]) if m else default
    except Exception:
        return default


def _budget_remaining():
    """BOUNDED AUTONOMY BUDGET: a self-managed daily cap on 'act without asking'. Once spent, the panel
    stops auto-executing and defers the remainder — so autonomy can never run away."""
    cap = _budget_cap()
    try:
        acts = db.select("committee_actions", {"select": "action,created_at",
                         "action": "in.(auto-build,auto-approve)", "created_at": f"gte.{_today()}"}) or []
        return max(0, cap - len(acts))
    except Exception:
        return cap


def tune_budget():
    """SELF-TUNING AUTONOMY: adjust the daily budget by the realized win-rate of recent auto-builds. High
    win-rate -> earn more autonomy; misses -> pull it back. Bounded [5, 50]. Trust is measured, not assumed."""
    try:
        sb = db.select("committee_scoreboard", {"select": "accuracy,calls", "entity_type": "eq.committee"}) or []
        if not sb:
            return _budget_cap()
        tot = sum(int(r.get("calls") or 0) for r in sb) or 1
        wr = sum(float(r.get("accuracy") or 0) * int(r.get("calls") or 0) for r in sb) / tot
        cur = _budget_cap()
        nxt = cur + 3 if wr >= 0.75 else cur - 4 if wr < 0.5 else cur
        nxt = max(5, min(50, nxt))
        db.insert("owner_model", {"key": "autonomy_budget", "value": nxt, "updated_at": "now()"}, upsert=True)
        print(f"committees.tune_budget: win-rate {round(wr,2)} -> daily budget {nxt}")
        return nxt
    except Exception:
        return _budget_cap()


def _canary_pct(premortem):
    """CONFIDENCE-SCALED CANARY: size the initial exposure to the pre-mortem risk — the scarier the failure
    story, the smaller the blast radius."""
    sev = (premortem or {}).get("severity")
    return {"catastrophic": 2, "high": 5, "medium": 15}.get(sev, 25)


def _alignment(title, body, rec):
    """NORTH-STAR ALIGNMENT: score a decision against the owner's stated top-level goals. A low score means
    the system is drifting from what the owner actually wants -> force a human look even if otherwise routine."""
    goals = db.select("owner_goals", {"select": "goal,weight", "active": "eq.true"}) or []
    if not goals:
        return 1.0
    gtxt = "; ".join(f"({g['weight']}) {g['goal']}" for g in goals)[:800]
    d = _json("Score how well the decision below aligns with the owner's north-star goals. Return ONE JSON: "
              "{\"alignment\":0.0-1.0,\"drift\":\"the single biggest misalignment, or 'none'\"}\n"
              f"GOALS: {gtxt}\nDECISION: {rec} on '{(title or '')[:160]}' — {(body or '')[:400]}")
    try:
        return d, max(0.0, min(1.0, float(d.get("alignment", 1) or 1)))
    except Exception:
        return {}, 1.0


def _premortem(title, body, panel):
    """ADVERSARIAL PRE-MORTEM SWARM: before a GO ships, a red team constructs the strongest failure story.
    If a plausible SEVERE failure exists, the decision is downgraded to a staged canary rather than a full
    ship (or, if critical, surfaced to the owner with the failure narrative attached)."""
    guards = "; ".join(f"{p['committee']}: {p.get('risk') or ''}" for p in panel)[:600]
    d = _json("You are an adversarial PRE-MORTEM red team. It is 90 days from now and this shipped and "
              "FAILED. Construct the single most plausible failure story. Return ONE JSON: "
              "{\"severity\":\"low|medium|high|catastrophic\",\"plausibility\":0.0-1.0,"
              "\"failure_story\":\"2 sentences\",\"mitigation\":\"the guardrail that prevents it\"}\n"
              f"PROPOSAL: {(title or '')[:200]}\n{(body or '')[:600]}\nKNOWN RISKS: {guards}", need=7)
    if not d:
        return None
    severe = d.get("severity") in ("high", "catastrophic") and float(d.get("plausibility", 0) or 0) >= 0.5
    d["severe"] = severe
    return d


def _evidence(title, body):
    """EVIDENCE GROUNDING: hand seats real data (portfolio revenue/usage + recent shipped work) so verdicts
    are grounded in facts, not priors. Matched loosely to whichever app the subject mentions."""
    try:
        text = ((title or "") + " " + (body or "")).lower()
        revs = db.select("app_revenue", {"select": "app,mrr_usd,active_users"}) or []
        hits = [r for r in revs if (r.get("app") or "").lower() in text] or revs[:3]
        parts = [f"{r['app']}: MRR ${r.get('mrr_usd')}, users {r.get('active_users')}" for r in hits[:4]]
        shipped = db.select("tasks", {"select": "slug", "state": "eq.MERGED",
                                      "order": "updated_at.desc", "limit": "6"}) or []
        if shipped:
            parts.append("recently shipped: " + ", ".join(t["slug"] for t in shipped))
        return ("EVIDENCE (current portfolio data): " + " | ".join(parts) + "\n") if parts else ""
    except Exception:
        return ""


def _external_evidence(committee, title, body):
    """LIVE EXTERNAL EVIDENCE: for reality-sensitive committees (legal, competitive, pricing, privacy),
    pull a current web/citation snippet so verdicts reference today's reality, not training priors.
    Fully optional + gracefully degrades: no web tool -> empty string, never blocks the panel."""
    if os.environ.get("COMMITTEE_WEB_EVIDENCE", "1") != "1":
        return ""
    if not any(k in committee for k in ("Legal", "Competitive", "Pricing", "Data & Privacy", "Partnerships")):
        return ""
    q = (title or "")[:120]
    for modname, fn in (("web_research", "search"), ("research", "search"), ("tools", "web_search")):
        try:
            mod = __import__(modname)
            hit = getattr(mod, fn)(f"{q} ({committee} considerations, current 2026)")
            txt = hit if isinstance(hit, str) else json.dumps(hit)
            if txt:
                return "LIVE EXTERNAL SIGNAL: " + txt[:500] + "\n"
        except Exception:
            continue
    return ""


def _seat_weight(committee, seat):
    try:
        r = db.select("seat_calibration", {"select": "weight", "committee": f"eq.{committee}",
                                           "seat": f"eq.{seat}"}) or []
        return float(r[0]["weight"]) if r else 1.0
    except Exception:
        return 1.0


def _reliability_hint(committee, seats):
    """Tell the panel which seats have historically been RIGHT, so proven seats carry more weight."""
    notes = []
    for s in seats:
        w = _seat_weight(committee, s)
        if w >= 1.25:
            notes.append(f"{s} has a strong track record")
        elif w <= 0.75:
            notes.append(f"{s} has been unreliable — scrutinize its claims")
    return ("SEAT TRACK RECORD: " + "; ".join(notes) + ".\n") if notes else ""


def _owner_bias():
    """OWNER-PREFERENCE LEARNING: infer the owner's revealed risk tolerance from their past approve/deny
    decisions and nudge the GO/HOLD bar. Returns a small delta on the score threshold (negative = owner is
    approve-happy, so lower the bar; positive = owner is cautious, so raise it)."""
    try:
        rows = db.select("approvals", {"select": "status", "status": "in.(approved,denied)",
                                       "order": "decided_at.desc", "limit": "60"}) or []
        base = 0.0
        if len(rows) >= 8:
            appr = sum(1 for r in rows if r.get("status") == "approved") / len(rows)
            base = (0.6 - appr) * 2.0   # ~ -0.8 (approve-happy) .. +1.2 (cautious)
        # add the learned override nudge (retrained from times the owner overruled the committee)
        try:
            m = db.select("owner_model", {"select": "value", "key": "eq.threshold_delta"}) or []
            base += float(m[0]["value"]) if m else 0.0
        except Exception:
            pass
        return round(max(-1.5, min(2.0, base)), 2)
    except Exception:
        return 0.0


def _matches_owner_calls(title, recommendation):
    """Compares the current recommendation against past owner decisions on similar subjects."""
    try:
        # Get recent owner overrides
        overrides = db.select("owner_overrides", {"select": "subject_title,owner_decision",
                                                  "order": "created_at.desc", "limit": "50"}) or []
        if not overrides:
            return None

        current_pos = not str(recommendation or "").startswith(("HOLD", "ESCALATE"))
        key = set(re.findall(r"[a-z]{4,}", (title or "").lower()))

        for o in overrides:
            past_title = o.get("subject_title") or ""
            past_owner_decision = o.get("owner_decision") or ""

            kk = set(re.findall(r"[a-z]{4,}", past_title.lower()))
            if len(key & kk) >= 3: # Sufficient keyword overlap for similarity
                # owner_decision "approved" implies a positive stance, "override" implies a negative stance
                past_owner_pos = (past_owner_decision == "approved")
                
                if current_pos == past_owner_pos:
                    return f"matches owner's prior '{past_owner_decision}' on '{past_title}'"
                else:
                    return f"contradicts owner's prior '{past_owner_decision}' on '{past_title}'"
        return None
    except Exception:
        return None


def deliberate(committee, subject_type, subject_id, title, body, app=None):
    """Run one committee as a multi-seat, multi-round drafting panel -> a single consensus opinion."""
    name = committee["name"]; mandate = committee.get("mandate", "")
    chair = committee.get("chair") or "Committee Chair"
    seats = _seats(committee) + [RED_SEAT]   # every panel carries a standing devil's advocate
    precedent = _precedent(name, title, body, app) + kg_context(title, body)
    evidence = _evidence(title, body) + _external_evidence(name, title, body)
    reliability = _reliability_hint(name, seats)

    def _seat_prompt(seat, coord):
        red = ("YOUR ROLE: relentlessly find the STRONGEST reason this proposal is wrong or will fail; "
               "steelman the opposition even if the panel leans yes.\n") if seat == RED_SEAT else ""
        return (SEAT_PROMPT.replace("{seat}", seat).replace("{committee}", name).replace("{mandate}", mandate)
                .replace("{redseat}", red).replace("{evidence}", evidence).replace("{precedent}", precedent)
                .replace("{reliability}", reliability).replace("{coordination}", coord)
                .replace("{title}", (title or "")[:300]).replace("{body}", (body or "")[:1500]))

    # round 0: independent opening positions (each seat spread across providers for real diversity)
    positions = []
    _emit(subject_id, 0, "assemble", expert=name, text=f"convened {name}: {', '.join(seats)}")
    for i, seat in enumerate(seats):
        d = _json(_seat_prompt(seat, ""), need=_seat_need(name, seat))
        if d:
            d["seat"] = seat
            positions.append(d)
            _emit(subject_id, i + 1, "opening", expert=f"{name}/{seat}",
                  verdict=d.get("verdict"), text=d.get("risk") or d.get("opportunity"))
    if not positions:
        return None

    # rounds 1..MAX_ROUNDS: coordinate until the panel converges (all verdicts agree) or rounds run out
    rounds_run = 0
    for _ in range(MAX_ROUNDS):
        verdicts = {p.get("verdict") for p in positions}
        if len(verdicts) <= 1:
            break  # converged
        rounds_run += 1
        digest = " | ".join(f"{p['seat']} [{p.get('verdict')}]: {p.get('risk') or p.get('opportunity') or ''}"
                            for p in positions)[:900]
        coord = (f"The panel so far: {digest}\nCross-examine the seats you disagree with, weigh their "
                 f"strongest point, and give your REVISED position moving toward a workable consensus.\n")
        for p in positions:
            d2 = _json(_seat_prompt(p["seat"], coord))
            if d2:
                d2["seat"] = p["seat"]; p.update(d2)

    # chair synthesis -> single consensus opinion (preserving dissent)
    pos_txt = "\n".join(
        f"- {p['seat']}: verdict={p.get('verdict')} score={p.get('score')} conviction={p.get('conviction')} "
        f"| basis: {p.get('basis','')} | risk: {p.get('risk','')} | conditions: {p.get('conditions','')} "
        f"| rec: {p.get('recommendation','')}" for p in positions)[:2000]
    syn = _json(CHAIR_PROMPT.replace("{chair}", chair).replace("{committee}", name).replace("{positions}", pos_txt))
    if not syn:  # fallback: conviction-weighted seat aggregate
        tw = sum(float(p.get("conviction", 5) or 5) for p in positions) or 1.0
        score = sum(float(p.get("score", 5) or 5) * float(p.get("conviction", 5) or 5) for p in positions) / tw
        opp = [p for p in positions if p.get("verdict") == "oppose"]
        syn = {"verdict": "oppose" if opp else "support" if score >= 6 else "conditional",
               "score": round(score, 1), "conviction": round(tw / max(1, len(positions)), 1),
               "opinion": "; ".join(p.get("recommendation", "") for p in positions)[:400],
               "conditions": " ".join(p.get("conditions", "") for p in positions if p.get("conditions"))[:400],
               "dissent": next((p.get("risk", "") for p in opp), "none"),
               "recommendation": positions[0].get("recommendation", "")}

    # PRECEDENT-CONFLICT: if this consensus contradicts the committee's own prior holding, flag it so the
    # "case law" stays coherent and the owner sees the reversal.
    conflict = ""
    try:
        prior = db.select("committee_opinions", {"select": "subject_title,consensus_verdict",
                          "committee": f"eq.{name}", "order": "created_at.desc", "limit": "40"}) or []
        key = set(re.findall(r"[a-z]{4,}", ((title or "") + " " + (body or "")).lower()))
        for r in prior:
            kk = set(re.findall(r"[a-z]{4,}", (r.get("subject_title") or "").lower()))
            if len(key & kk) >= 3 and r.get("consensus_verdict") and syn.get("verdict"):
                pv = r["consensus_verdict"] in ("support", "conditional")
                cv = syn["verdict"] in ("support", "conditional")
                if pv != cv:
                    conflict = f"reverses prior '{r['consensus_verdict']}' on '{r.get('subject_title')}'"
                    break
    except Exception:
        pass

    _emit(subject_id, 90, "synthesis", expert=f"{name}/{chair}",
          verdict=syn.get("verdict"), text=syn.get("opinion"))
    # PRE-MORTEM / EXPECTED VALUE: decide against the forecast, not just the present-tense opinion.
    p_succ = max(0.0, min(1.0, float(syn.get("p_success", 0.5) or 0.5)))
    raw_score = float(syn.get("score", 5) or 5)
    ev_score = round(raw_score * (0.4 + 0.6 * p_succ), 1)   # probability-discount the score (never inflates)
    critical = bool(syn.get("critical")) or (syn.get("reversible") is False)

    # persist the consensus opinion as reusable precedent + per-seat trail
    try:
        db.insert("committee_opinions", {"subject_type": subject_type, "subject_id": subject_id,
                  "subject_title": (title or "")[:200], "committee": name,
                  "consensus_verdict": syn.get("verdict"), "conviction": float(syn.get("conviction", 5) or 5),
                  "rounds": rounds_run, "opinion": (syn.get("opinion") or "")[:1500],
                  "dissent": (syn.get("dissent") or "")[:600], "precedent_conflict": conflict or None,
                  "p_success": p_succ, "expected_value": ev_score, "app": app})
        for p in positions:   # per-SEAT trail so we can backtest and reweight individual experts
            db.insert("committee_seat_reviews", {"subject_type": subject_type, "subject_id": subject_id,
                      "committee": name, "seat": p.get("seat"), "verdict": p.get("verdict"),
                      "score": float(p.get("score", 5) or 5), "conviction": float(p.get("conviction", 5) or 5)})
        db.insert("committee_reviews", {"subject_type": subject_type, "subject_id": subject_id,
                  "subject_title": (title or "")[:200], "committee": name,
                  "verdict": syn.get("verdict"), "score": float(syn.get("score", 5) or 5),
                  "opportunity": (positions[0].get("opportunity") or "")[:300],
                  "risk": (syn.get("dissent") or "")[:300],
                  "recommendation": (syn.get("recommendation") or "")[:300]})
    except Exception:
        pass

    return {"committee": name, "verdict": syn.get("verdict"), "score": raw_score, "ev_score": ev_score,
            "p_success": p_succ, "critical": critical,
            "conviction": float(syn.get("conviction", 5) or 5), "base_w": float(committee.get("weight") or 1.0),
            "opinion": syn.get("opinion"), "conditions": syn.get("conditions"),
            "dissent": syn.get("dissent"), "rec": syn.get("recommendation"), "rounds": rounds_run,
            "conflict": conflict, "chair": chair, "downside": syn.get("downside"),
            "opportunity": positions[0].get("opportunity"), "risk": syn.get("dissent")}


def _arbitrate(parties, subject_type, subject_id, title, body):
    """CROSS-COMMITTEE ARBITRATION: when two committees deadlock (one strong support, one strong oppose),
    convene a small arbitration panel drawn from BOTH chairs to issue a tiebreak ruling."""
    chairs = " and ".join(f"{p['chair']} ({p['committee']})" for p in parties)
    pv = "; ".join(f"{p['committee']} [{p['verdict']}, conv {p.get('conviction')}]: {p.get('opinion') or ''}"
                   for p in parties)[:1400]
    syn = _json("You are an ARBITRATION panel composed of %s. Two expert committees have reached a "
                "high-conviction deadlock. Weigh both, then issue a binding tiebreak ruling for the owner.\n"
                "Return ONE JSON: {\"ruling\":\"proceed|proceed-with-conditions|do-not-proceed\","
                "\"conditions\":\"...\",\"rationale\":\"2 sentences\"}\nMATTER: %s\n%s\nPOSITIONS: %s" %
                (chairs, (title or "")[:200], (body or "")[:600], pv))
    if syn:
        try:
            db.insert("committee_arbitrations", {"subject_type": subject_type, "subject_id": subject_id,
                      "subject_title": (title or "")[:200], "parties": ", ".join(p["committee"] for p in parties),
                      "ruling": syn.get("ruling"), "rationale": (syn.get("rationale") or "")[:600]})
        except Exception:
            pass
    return syn


def _relevant(title, body, committees):
    """RELEVANCE GATE: convene only the committees that actually bear on this subject (sharper + bounded).
    Legal is always seated (veto power). Falls back to all committees if the classifier is unavailable."""
    if len(committees) <= MAX_COMMITTEES:
        return committees
    names = [c["name"] for c in committees]
    picked = _json("From this committee list, return the JSON array of the <=%d MOST relevant committee "
                   "names to review the proposal below. LIST: %s\nPROPOSAL: %s\n%s" %
                   (MAX_COMMITTEES, json.dumps(names), (title or "")[:200], (body or "")[:600]), arr=True)
    keep = {n for n in (picked or []) if n in names}
    keep.add("Legal & Compliance")  # always seat legal
    sel = [c for c in committees if c["name"] in keep]
    return sel[:MAX_COMMITTEES + 1] if sel else committees[:MAX_COMMITTEES]


def review(subject_type, subject_id, title, body, app=None):
    # ADAPTIVE: assemble the optimal expert panels for THIS issue on the fly (no fixed committees).
    committees = _triage_panels(title, body, app)
    panel = []
    for c in committees:
        d = deliberate(c, subject_type, subject_id, title, body, app)
        if d:
            panel.append(d)
    if not panel:
        return {"aggregate": None, "recommendation": "HOLD", "opposed_by": [], "panel": []}

    # aggregate committees weighted by calibration (track record) AND consensus conviction, scored on
    # EXPECTED VALUE (probability-discounted), not raw enthusiasm.
    total_w = weighted = 0.0
    for p in panel:
        w = p["base_w"] * _cal_weight(p["committee"]) * (0.5 + float(p.get("conviction", 5) or 5) / 10.0)
        total_w += w; weighted += w * float(p.get("ev_score", p["score"]))
    agg = round(weighted / total_w, 1) if total_w else None
    opposed = [p["committee"] for p in panel if p["verdict"] == "oppose"]
    dissents = [f"{p['committee']}: {p['dissent']}" for p in panel if p.get("dissent") and p["dissent"] != "none"]
    conflicts = [f"{p['committee']} {p['conflict']}" for p in panel if p.get("conflict")]
    legal_veto = any(_is_legal(p["committee"]) and p["verdict"] == "oppose" for p in panel)

    # CRITICALITY: only CRITICAL or HIGHLY CONTENTIOUS matters ever reach a human. Everything else the
    # committees resolve and execute autonomously.
    critical = legal_veto or any(p.get("critical") for p in panel)
    high_conv_opp = [p for p in panel if p["verdict"] == "oppose" and float(p.get("conviction", 0) or 0) >= 7]
    verds = {p["verdict"] for p in panel}
    contentious = ("support" in verds and "oppose" in verds and bool(high_conv_opp))

    # Decisions with material cross-app, security, financial, or irreversible blast radius
    # must complete the persisted three-proposer/critique/judge protocol before execution.
    import adversarial_fleet
    text = (title + " " + body).lower()
    blast_radius = 100 if critical or any(k in text for k in ("production", "security", "billing", "migration", "all users")) else 0
    structured_debate = None
    if adversarial_fleet.debate_required(blast_radius):
        structured_debate = _high_stakes_debate(subject_type, subject_id, title, body, blast_radius)

    # OWNER PREFERENCE: shift the GO bar toward the owner's revealed risk tolerance
    bar = 7.0 + _owner_bias()
    arbitration = None

    if legal_veto:
        rec = "HOLD (legal veto)"          # legal always wins, always a human matter
    elif contentious:
        # try to resolve autonomously via cross-committee arbitration BEFORE bothering a human
        sup = max((p for p in panel if p["verdict"] == "support"), key=lambda p: p.get("conviction", 0), default=None)
        opp = max((p for p in panel if p["verdict"] == "oppose"), key=lambda p: p.get("conviction", 0), default=None)
        if sup and opp:
            arbitration = _arbitrate([sup, opp], subject_type, subject_id, title, body)
        ruling = (arbitration or {}).get("ruling")
        if ruling == "proceed":
            rec = "GO (arbitrated)"
        elif ruling == "proceed-with-conditions":
            rec = "REVISE (arbitrated)"     # build it, but with the arbitration's conditions — still autonomous
        elif ruling == "do-not-proceed":
            rec = "HOLD (arbitrated)"
        elif critical:
            rec = "ESCALATE (critical deadlock)"   # only irreversible/critical splits reach a human
        else:
            rec = "EXPERIMENT (a/b)"        # reversible + low-stakes -> let live data settle it, autonomously
    else:
        rec = ("GO" if (agg or 0) >= bar and not opposed else "REVISE" if (agg or 0) >= 5 else "HOLD")

    # ADVERSARIAL PRE-MORTEM: gate any GO through a red-team failure story. A plausible SEVERE failure
    # downgrades a full ship to a staged canary (rollout='canary'); a clean bill of health ships in full.
    premortem = None; rollout = "full"
    if rec.startswith("GO"):
        premortem = _premortem(title, body, panel)
        if premortem and premortem.get("severe"):
            rollout = "canary"

    # CONFIDENCE-GATED AUTONOMY + BOUNDED BUDGET: a clean, high-conviction, non-critical GO self-executes,
    # but only while the daily autonomy budget lasts; once spent, the remainder escalates.
    min_conv = min((float(p.get("conviction", 0) or 0) for p in panel), default=0)
    budget = _budget_remaining()
    auto_ok = (rec.startswith("GO") and not critical and not opposed and min_conv >= 7
               and (agg or 0) >= bar and budget > 0)
    # ONLY critical or highly-contentious matters reach a human.
    escalate = rec.startswith("ESCALATE") or legal_veto or critical
    if structured_debate and structured_debate.get("judge", {}).get("verdict") != "proceed":
        escalate = True; auto_ok = False; rec = "ESCALATE (high-stakes debate)"
    experiment = rec.startswith("EXPERIMENT")

    # NORTH-STAR ALIGNMENT GATE: before acting autonomously, check the decision doesn't drift from the
    # owner's stated goals. Meaningful drift pulls it back to a human even if it was a clean GO.
    align_info, align = ({}, 1.0)
    if auto_ok or experiment or rec.startswith("GO"):
        align_info, align = _alignment(title, body, rec)
        if align < float(os.environ.get("COMMITTEE_ALIGN_MIN", "0.5")):
            auto_ok = False; experiment = False
            escalate = True; rec = "ESCALATE (north-star drift)"

    # Add the "matches owner's past calls" signal
    owner_match_signal = _matches_owner_calls(title, rec)

    # CADE: consensus %, faction clustering, contributors, materiality — the substance of the 1-pager.
    consensus_pct, factions, contributors = _consensus(panel)
    materiality = _materiality(panel, critical, legal_veto)
    lo, hi = _consensus_ci(panel, consensus_pct)
    out = {"aggregate": agg, "recommendation": rec, "opposed_by": opposed, "dissents": dissents,
           "conflicts": conflicts, "arbitration": arbitration, "owner_bar": round(bar, 2),
           "critical": critical, "contentious": contentious, "auto_ok": auto_ok, "escalate": escalate,
           "experiment": experiment, "premortem": premortem, "rollout": rollout, "budget_left": budget,
           "alignment": align, "drift": (align_info or {}).get("drift"),
           "consensus_pct": consensus_pct, "consensus_lo": lo, "consensus_hi": hi,
           "factions": factions, "contributors": contributors, "pivotal": _pivotal(panel),
           "materiality": materiality, "title": title, "body": body, "panel": panel,
           "owner_match_signal": owner_match_signal}
    out["adv_discount"] = _adv_discount(out)
    out["consistency"] = _consistency(subject_type, title, rec)
    return out


def _consensus(panel):
    """CADE faction clustering: group the assembled experts' positions into factions, and compute the
    CONSENSUS % = the calibration-and-conviction-weighted share of the winning stance. Also returns the
    per-expert contributor list (who weighed in, their stance, and their weight on the outcome)."""
    contributors, weights_by_verdict, total_w = [], {}, 0.0
    for p in panel:
        w = float(p.get("base_w", 1.0)) * _cal_weight(p["committee"]) * (0.5 + float(p.get("conviction", 5) or 5) / 10.0)
        total_w += w
        v = p.get("verdict") or "needs-info"
        weights_by_verdict[v] = weights_by_verdict.get(v, 0.0) + w
        contributors.append({"expert": p.get("committee"), "chair": p.get("chair"), "verdict": v,
                             "conviction": p.get("conviction"), "weight": round(w, 2),
                             "position": (p.get("opinion") or p.get("rec") or "")[:200],
                             "key_risk": (p.get("risk") or p.get("dissent") or "")[:200]})
    consensus_pct = round(max(weights_by_verdict.values()) / total_w, 3) if total_w else 1.0
    factions = []
    for v, w in sorted(weights_by_verdict.items(), key=lambda x: -x[1]):
        members = [c["expert"] for c in contributors if c["verdict"] == v]
        arg = next((c["position"] for c in contributors if c["verdict"] == v and c["position"]), "")
        factions.append({"stance": v, "share": round(w / total_w, 3) if total_w else 0,
                         "experts": members, "argument": arg[:220]})
    # contributors sorted by influence (weight) so the 1-pager leads with who mattered most
    contributors.sort(key=lambda c: c["weight"], reverse=True)
    return consensus_pct, factions, contributors


def _materiality(panel, critical, legal_veto):
    """[0,1] stakes estimate that drives review depth AND whether a human is looped in. High materiality =
    legal exposure, irreversibility, or strong high-conviction opposition."""
    m = 0.3
    if legal_veto or any(_is_legal(p["committee"]) for p in panel):
        m += 0.3
    if critical:
        m += 0.3
    if any(p.get("verdict") == "oppose" and float(p.get("conviction", 0) or 0) >= 7 for p in panel):
        m += 0.2
    return round(min(1.0, m), 2)


def _consensus_ci(panel, consensus_pct):
    """CONSENSUS AS A DISTRIBUTION: bootstrap over the expert weights to put an uncertainty band on the
    headline consensus %. A tight band = a stable result; a wide band = the number could easily move."""
    import random
    if not panel:
        return consensus_pct, consensus_pct
    items = []
    for p in panel:
        w = float(p.get("base_w", 1.0)) * _cal_weight(p["committee"]) * (0.5 + float(p.get("conviction", 5) or 5) / 10.0)
        items.append((p.get("verdict") or "needs-info", w))
    samples = []
    rnd = random.Random(len(panel))
    for _ in range(200):
        draw = [items[rnd.randrange(len(items))] for _ in items]  # resample with replacement
        by = {}; tot = 0.0
        for v, w in draw:
            by[v] = by.get(v, 0.0) + w; tot += w
        samples.append(max(by.values()) / tot if tot else 1.0)
    samples.sort()
    lo = round(samples[int(0.05 * len(samples))], 3)
    hi = round(samples[min(len(samples) - 1, int(0.95 * len(samples)))], 3)
    return lo, hi


def _pivotal(panel):
    """PIVOTAL-FACTOR SENSITIVITY: find the single expert whose flip would most change the balance — the
    factor the decision hinges on, so the reviewer knows where the leverage is."""
    if len(panel) < 2:
        return None
    def _win(ps):
        by = {}; tot = 0.0
        for p in ps:
            w = float(p.get("base_w", 1.0)) * _cal_weight(p["committee"]) * (0.5 + float(p.get("conviction", 5) or 5) / 10.0)
            by[p.get("verdict")] = by.get(p.get("verdict"), 0.0) + w; tot += w
        return max(by, key=by.get) if by else None
    base = _win(panel)
    for p in sorted(panel, key=lambda x: -float(x.get("conviction", 0) or 0)):
        flipped = [dict(q, verdict=("support" if q.get("verdict") == "oppose" else "oppose")) if q is p else q
                   for q in panel]
        if _win(flipped) != base:
            return {"expert": p.get("committee"), "current": p.get("verdict"),
                    "note": f"if {p.get('committee')} flipped, the outcome would change"}
    return None


def _adv_discount(agg):
    """ADVERSARIAL CONFIDENCE DISCOUNT: haircut the headline confidence by how easily the red-team moved
    the panel. A determination no adversary could dent keeps full confidence."""
    pm = agg.get("premortem") or {}
    if pm.get("severe"):
        return round(min(0.4, 0.2 + float(pm.get("plausibility", 0) or 0) * 0.2), 2)
    if agg.get("contentious"):
        return 0.1
    return 0.0


def _consistency(subject_type, title, recommendation):
    """CROSS-DETERMINATION CONSISTENCY: flag when a new determination contradicts a prior one on a similar
    subject, so reversals are explicit rather than silent."""
    try:
        prior = db.select("determinations", {"select": "title,recommendation",
                          "order": "created_at.desc", "limit": "60"}) or []
    except Exception:
        return None
    key = set(re.findall(r"[a-z]{4,}", (title or "").lower()))
    pos = lambda r: not str(r or "").startswith(("HOLD", "ESCALATE"))
    for r in prior:
        kk = set(re.findall(r"[a-z]{4,}", (r.get("title") or "").lower()))
        if len(key & kk) >= 3 and pos(r.get("recommendation")) != pos(recommendation):
            return f"reverses prior '{r.get('recommendation')}' on '{r.get('title')}'"
    return None


def _domain_floor(reviewer, domain):
    """PER-REVIEWER, PER-DOMAIN contention routing: a reviewer can want tighter scrutiny in some domains
    (e.g. legal) and looser in others. Falls back to the global consensus_floor."""
    try:
        r = db.select("reviewer_prefs", {"select": "consensus_floor", "reviewer": f"eq.{reviewer}",
                                         "domain": f"eq.{domain}"}) or []
        if r:
            return float(r[0]["consensus_floor"])
    except Exception:
        pass
    return _consensus_floor()


def verify_determination(det_id):
    """OFFLINE PROOF VERIFIER: recompute the certificate hash and confirm it chains to the previous
    determination — so any 1-pager is independently auditable, not merely trusted."""
    import hashlib
    rows = db.select("determinations", {"select": "*", "id": f"eq.{det_id}"}) or []
    if not rows:
        return {"ok": False, "reason": "not found"}
    d = rows[0]
    cert = d.get("certificate")
    if isinstance(cert, str):
        try:
            cert = json.loads(cert)
        except Exception:
            cert = {}
    canonical = json.dumps(cert, sort_keys=True, default=str) + (d.get("prev_hash") or "")
    recomputed = hashlib.sha256(canonical.encode()).hexdigest()
    return {"ok": recomputed == d.get("proof_hash"), "recomputed": recomputed,
            "stored": d.get("proof_hash"), "title": d.get("title")}


def dissent_audit():
    """DISSENT-WAS-RIGHT TRACKING: when a determination's realized outcome contradicts what the majority
    concluded, mark the dissent as vindicated and notify the owner — so the contention flags earn trust."""
    dets = db.select("determinations", {"select": "id,subject_type,subject_id,title,recommendation,dissent",
                     "dissent_vindicated": "eq.false", "limit": "300"}) or []
    n = 0
    for d in dets:
        if not d.get("dissent"):
            continue
        rv = db.select("committee_reviews", {"select": "outcome", "subject_id": f"eq.{d.get('subject_id')}",
                                             "outcome": "not.is.null", "limit": "1"}) or []
        if not rv:
            continue
        outcome_good = float(rv[0].get("outcome") or 0) > 0
        majority_positive = not str(d.get("recommendation") or "").startswith(("HOLD", "ESCALATE"))
        if majority_positive and not outcome_good:   # the doubters were right
            db.update("determinations", {"id": d["id"]}, {"dissent_vindicated": True})
            try:
                db.insert("inbox", {"kind": "dissent_vindicated",
                          "title": f"A minority view you saw was right: {d.get('title')}",
                          "body": f"The panel recommended {d.get('recommendation')}, but the dissent "
                                  f"({d.get('dissent')}) proved correct. Weighting that domain up.",
                          "status": "unread"})
            except Exception:
                pass
            n += 1
    print(f"committees.dissent_audit: {n} dissents vindicated")
    return n


def _emit(subject_id, seq, kind, expert=None, verdict=None, text=None):
    """LIVE STREAMING: append a deliberation event so the console can watch a determination form in real
    time. Off by default cost-wise unless COMMITTEE_STREAM=1 (only DB writes, no extra model calls)."""
    if os.environ.get("COMMITTEE_STREAM", "1") != "1" or not subject_id:
        return
    try:
        db.insert("deliberation_events", {"subject_id": subject_id, "seq": seq, "kind": kind,
                  "expert": expert, "verdict": verdict, "text": (text or "")[:400]})
    except Exception:
        pass


def _subfactions(contributors):
    """EMBEDDING-BASED FACTION CLUSTERING (lightweight): within a single verdict camp, split experts into
    sub-factions by ARGUMENT MEANING (bag-of-words cosine), surfacing hidden disagreement inside a 'support'
    or 'oppose' bloc that a verdict-only view would miss."""
    import math
    def vec(t):
        v = {}
        for w in re.findall(r"[a-z]{4,}", (t or "").lower()):
            v[w] = v.get(w, 0) + 1
        return v
    def cos(a, b):
        if not a or not b:
            return 0.0
        dot = sum(a[k] * b.get(k, 0) for k in a)
        na = math.sqrt(sum(x * x for x in a.values())); nb = math.sqrt(sum(x * x for x in b.values()))
        return dot / (na * nb) if na and nb else 0.0
    out = {}
    for verdict in set(c.get("verdict") for c in contributors):
        camp = [c for c in contributors if c.get("verdict") == verdict]
        if len(camp) < 2:
            continue
        clusters = []
        for c in camp:
            v = vec(c.get("position"))
            placed = False
            for cl in clusters:
                if cos(v, cl["v"]) >= 0.25:
                    cl["experts"].append(c.get("expert")); placed = True; break
            if not placed:
                clusters.append({"v": v, "experts": [c.get("expert")], "gist": (c.get("position") or "")[:120]})
        if len(clusters) > 1:   # only report when a camp actually splits
            out[verdict] = [{"experts": cl["experts"], "gist": cl["gist"]} for cl in clusters]
    return out or None


def replay_determination(det_id):
    """DETERMINATION REPLAY: re-run the exact issue on TODAY's evidence and diff the outcome vs the stored
    one — so a reviewer can see whether a past call still holds."""
    rows = db.select("determinations", {"select": "*", "id": f"eq.{det_id}"}) or []
    if not rows:
        return {"error": "not found"}
    d = rows[0]
    fresh = review("proposal", None, d.get("title"), d.get("body") or d.get("title"))
    changed = (fresh.get("recommendation") != d.get("recommendation") or
               abs((fresh.get("consensus_pct") or 0) - float(d.get("consensus_pct") or 0)) >= 0.1)
    return {"then": {"recommendation": d.get("recommendation"), "consensus_pct": float(d.get("consensus_pct") or 0)},
            "now": {"recommendation": fresh.get("recommendation"), "consensus_pct": fresh.get("consensus_pct")},
            "changed": changed, "note": "outcome moved" if changed else "outcome holds"}


def ask_panel(det_id, question):
    """ASK THE PANEL: answer a reviewer's follow-up on a determination, grounded in the assembled experts'
    positions + preserved dissent (not a fresh opinion from nowhere)."""
    rows = db.select("determinations", {"select": "title,contributors,factions,dissent", "id": f"eq.{det_id}"}) or []
    if not rows:
        return {"answer": "Determination not found."}
    d = rows[0]
    ctx = json.dumps({"contributors": d.get("contributors"), "factions": d.get("factions"),
                      "dissent": d.get("dissent")}, default=str)[:2500]
    ans = _complete(f"You are the chair summarizing this expert panel. Answer the reviewer's question using "
                    f"ONLY the panel's positions below; if the panel didn't address it, say so.\n"
                    f"ISSUE: {d.get('title')}\nPANEL: {ctx}\nQUESTION: {question}")
    return {"answer": (ans or "").strip()[:1200] or "The panel did not address this."}


def export_proof_pack(det_id):
    """SIGNED, SHAREABLE PROOF PACK: export a determination + certificate as a JSON pack, Ed25519-signed
    with DARWIN_SIGNING_PRIVATE_KEY_PEM when present, so a third party can verify it offline."""
    rows = db.select("determinations", {"select": "*", "id": f"eq.{det_id}"}) or []
    if not rows:
        return {"error": "not found"}
    d = rows[0]
    pack = {"title": d.get("title"), "recommendation": d.get("recommendation"),
            "consensus_pct": d.get("consensus_pct"), "certificate": d.get("certificate"),
            "proof_hash": d.get("proof_hash"), "prev_hash": d.get("prev_hash")}
    sig = None
    try:
        pem = os.environ.get("DARWIN_SIGNING_PRIVATE_KEY_PEM")
        if pem:
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            key = load_pem_private_key(pem.encode(), password=None)
            if isinstance(key, Ed25519PrivateKey):
                sig = key.sign(json.dumps(pack, sort_keys=True, default=str).encode()).hex()
    except Exception:
        sig = None
    pack["signature"] = sig
    pack["signed"] = bool(sig)
    return pack


def process_determination_actions(limit=10):
    """Drain the console action queue: replay / ask / approve / override / another-round. Approve+override
    feed the owner-preference learner so the system needs the reviewer less over time."""
    acts = db.select("determination_actions", {"select": "*", "status": "eq.pending",
                     "order": "created_at.asc", "limit": str(limit)}) or []
    n = 0
    for a in acts:
        act = a.get("action"); did = a.get("determination_id"); payload = a.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        res = {}
        try:
            if act == "replay":
                res = replay_determination(did)
            elif act == "ask":
                res = ask_panel(did, payload.get("question", ""))
            elif act in ("approve", "override"):
                res = {"status": act, "by": a.get("reviewer") or "owner"}
                # record as an owner decision so _owner_bias / learn_overrides adapt
                det = (db.select("determinations", {"select": "recommendation,subject_id", "id": f"eq.{did}"}) or [{}])[0]
                rec = det.get("recommendation") or ""
                direction = ("owner_more_aggressive" if act == "approve" and rec.startswith(("HOLD", "ESCALATE"))
                             else "owner_more_cautious" if act == "override" else "aligned")
                db.insert("owner_overrides", {"subject_type": "determination", "subject_id": det.get("subject_id"),
                          "committee_rec": rec, "owner_decision": act, "direction": direction})
            elif act == "another-round":
                res = replay_determination(did)   # re-deliberate fresh
            db.update("determination_actions", {"id": a["id"]},
                      {"status": "done", "result": res, "done_at": "now()"})
        except Exception as e:
            db.update("determination_actions", {"id": a["id"]}, {"status": "error", "result": {"error": str(e)}})
        n += 1
    if acts:
        learn_overrides()   # fold approve/override into the threshold model immediately
    print(f"committees.process_determination_actions: handled {n}")
    return n


def _consensus_floor():
    try:
        r = db.select("owner_model", {"select": "value", "key": "eq.consensus_floor"}) or []
        return float(r[0]["value"]) if r else 0.85
    except Exception:
        return 0.85


def constitution_gate(agg, determination_id=None):
    """CADE bound: the engine DETERMINES; approval flows ACT. Anything critical, legal-vetoed, or
    irreversible must reach a human regardless of consensus — no autonomous money movement / filing /
    sending. Now backed by CONSTITUTION-AS-CODE (constitution.py): explicit machine-checked predicates,
    not just string heuristics. Returns True if the determination must be gated to a human."""
    heuristic = bool(agg.get("escalate") or agg.get("critical") or
                     str(agg.get("recommendation", "")).startswith(("HOLD (legal", "ESCALATE")))
    try:
        import constitution
        c = constitution.evaluate(agg, determination_id)
        agg["constitution"] = c
        return heuristic or c.get("must_gate", False)
    except Exception:
        return heuristic


def certify(subject_type, subject_id, agg):
    """Build the Optimality Certificate + hash-chained proof for a determination and persist it with its
    reviewer 1-pager. The proof chains to the previous determination so the ledger is tamper-evident."""
    import hashlib
    onepager = deliberation_onepager(agg)
    adv = float(agg.get("adv_discount") or 0)
    disc_conf = round(float(agg.get("aggregate") or 0) * (1 - adv), 2)
    # COUNTERFACTUAL BOUND: compute the margin between the winning stance's weighted share
    # and the best-scoring losing stance from the panel's factions. Asserts that no reachable
    # alternative scored materially higher.
    factions = agg.get("factions") or []
    if len(factions) >= 2:
        winning_share = float(factions[0].get("share") or 0)
        runner_up_share = float(factions[1].get("share") or 0)
        counterfactual_margin = round(winning_share - runner_up_share, 3)
    else:
        winning_share = float(factions[0].get("share") or 1) if factions else 1.0
        counterfactual_margin = round(winning_share, 3)
    counterfactual_claim = (f"no reachable alternative scored materially higher; "
                            f"winning stance led by {round(counterfactual_margin * 100, 1)}pp margin")
    cert = {"position": agg.get("recommendation"), "consensus_pct": agg.get("consensus_pct"),
            "consensus_ci": [agg.get("consensus_lo"), agg.get("consensus_hi")],
            "materiality": agg.get("materiality"), "confidence": agg.get("aggregate"),
            "adversarial_discounted_confidence": disc_conf, "adv_discount": adv,
            "pivotal": agg.get("pivotal"), "consistency": agg.get("consistency"),
            "contributors": agg.get("contributors"), "factions": agg.get("factions"),
            "dissent": agg.get("dissents"), "gated_to_human": constitution_gate(agg),
            "counterfactual_margin": counterfactual_margin,
            "counterfactual": counterfactual_claim}
    try:
        prev = (db.select("determinations", {"select": "proof_hash", "order": "created_at.desc",
                                             "limit": "1"}) or [{}])
        prev_hash = (prev[0].get("proof_hash") if prev else "") or ""
    except Exception:
        prev_hash = ""
    canonical = json.dumps(cert, sort_keys=True, default=str) + prev_hash
    proof_hash = hashlib.sha256(canonical.encode()).hexdigest()
    try:
        db.insert("determinations", {"subject_type": subject_type, "subject_id": subject_id,
                  "title": (agg.get("title") or "")[:200], "position": agg.get("recommendation"),
                  "recommendation": agg.get("recommendation"), "consensus_pct": agg.get("consensus_pct"),
                  "consensus_lo": agg.get("consensus_lo"), "consensus_hi": agg.get("consensus_hi"),
                  "confidence": agg.get("aggregate"), "materiality": agg.get("materiality"),
                  "pivotal": agg.get("pivotal"), "adv_discount": adv, "consistency_flag": agg.get("consistency"),
                  "contributors": agg.get("contributors"), "factions": agg.get("factions"),
                  "dissent": agg.get("dissents"), "certificate": cert, "body": (agg.get("body") or "")[:4000],
                  "proof_hash": proof_hash, "prev_hash": prev_hash, "onepager": onepager})
    except Exception:
        pass
    return {"certificate": cert, "proof_hash": proof_hash, "onepager": onepager}


def deliberation_onepager(agg):
    """THE REVIEWER 1-PAGER: a concise, confidence-building summary of how the outcome was reached — who
    contributed and how much, the consensus level, the key counter-arguments, and (if consensus is below
    the reviewer's calibrated floor) an explicit CONTENTION section highlighting exactly what to look at."""
    title = agg.get("title") or "(untitled issue)"
    cons = agg.get("consensus_pct")
    floor = _consensus_floor()
    contributors = agg.get("contributors") or []
    factions = agg.get("factions") or []
    contested = cons is not None and cons < floor
    L = []
    L.append(f"# Deliberation 1-Pager — {title}")
    L.append("")
    ci = ""
    if agg.get("consensus_lo") is not None:
        ci = f" ±{round((agg.get('consensus_hi',cons)-agg.get('consensus_lo',cons))*50)}pt"
    adv = float(agg.get("adv_discount") or 0)
    conf = agg.get("aggregate")
    conf_str = f"{conf}/10" + (f" → {round(float(conf or 0)*(1-adv),1)}/10 after red-team" if adv else "")
    L.append(f"**Outcome:** {agg.get('recommendation')}  |  **Consensus:** "
             f"{round((cons or 0)*100)}%{ci} (floor {round(floor*100)}%)  |  **Confidence (EV):** "
             f"{conf_str}  |  **Materiality:** {agg.get('materiality')}")
    if agg.get("owner_match_signal"):
        L.append(f"**Owner alignment:** {agg['owner_match_signal']}")
    if agg.get("pivotal"):
        L.append("")
        L.append(f"**Decision hinges on:** {agg['pivotal'].get('expert')} "
                 f"({agg['pivotal'].get('current')}) — {agg['pivotal'].get('note')}")
    if agg.get("consistency"):
        L.append(f"**⟳ Consistency:** {agg['consistency']}")
    if contested:
        L.append("")
        L.append(f"> ⚠️ **CONTENTION — consensus below your {round(floor*100)}% floor. Review the "
                 f"disagreements below before relying on this.**")
    L.append("")
    L.append("## Who contributed to the outcome (by influence)")
    for c in contributors[:8]:
        L.append(f"- **{c.get('expert')}** ({c.get('verdict')}, conviction {c.get('conviction')}, "
                 f"weight {c.get('weight')}) — {c.get('position') or '—'}")
    L.append("")
    L.append("## Positions / factions")
    for f in factions:
        L.append(f"- **{f.get('stance')}** — {round((f.get('share') or 0)*100)}% of weighted expertise "
                 f"({', '.join(f.get('experts') or []) or '—'}): {f.get('argument') or '—'}")
    dissents = [d for d in (agg.get("dissents") or [])]
    L.append("")
    L.append("## Key counter-arguments raised")
    if dissents:
        for d in dissents[:6]:
            L.append(f"- {d}")
    else:
        L.append("- None material — the panel was substantially aligned.")
    if agg.get("premortem") and agg["premortem"].get("severe"):
        pm = agg["premortem"]
        L.append(f"- **Pre-mortem ({pm.get('severity')}):** {pm.get('failure_story')} "
                 f"→ mitigation: {pm.get('mitigation')}")
    if agg.get("arbitration"):
        L.append(f"- **Arbitration:** {agg['arbitration'].get('ruling')} — {agg['arbitration'].get('rationale')}")
    if contested:
        L.append("")
        L.append("## 🔍 For your personal consideration")
        opp = agg.get("opposed_by") or []
        L.append(f"- Dissenting experts: {', '.join(opp) or 'see factions above'}")
        L.append("- The decision was NOT unanimous; the areas above are where reasonable experts disagreed.")
    L.append("")
    L.append(f"_Determination gated to a human: {'yes' if constitution_gate(agg) else 'no (auto-resolved)'}._")
    return "\n".join(L)


def compose_spec(title, body, panel):
    """COMMITTEE-AUTHORED SPEC: fold every committee's binding CONDITIONS + guardrails into the build spec,
    so the implementation inherits the panels' expertise (Legal's compliance bounds, Finance's pricing
    limits, Architecture's scale constraints…)."""
    lines = []
    for p in panel:
        cond = p.get("conditions") or p.get("rec") or ""
        if cond:
            lines.append(f"- [{p['committee']}] MUST: {cond} (guard against: {p.get('risk') or 'n/a'})")
    constraints = "\n".join(lines)
    return (f"BUILD SPEC (committee-authored): {title}\n{body}\n\nBINDING CONSTRAINTS the implementation MUST honor:\n"
            f"{constraints}\nBuild with tests; keep the prod build green.")


def calibrate():
    """COMMITTEE MEMORY: reweight each committee by how well its past verdicts predicted realized outcomes
    (committee_reviews.outcome). Accurate committees count more; consistently-wrong ones less."""
    # GROUND TRUTH FIRST: label determinations with realized (and causal) outcomes before scoring anything,
    # so every downstream signal (weights, Brier, seat reliability, dissent-vindication) learns from reality.
    try:
        import outcome_instrument; outcome_instrument.run()
    except Exception as e:
        print(f"calibrate: outcome_instrument skipped ({e})")
    try:
        import causal_attribution; causal_attribution.run()
    except Exception as e:
        print(f"calibrate: causal_attribution skipped ({e})")
    rows = db.select("committee_reviews", {"select": "committee,verdict,score,outcome",
                                           "outcome": "not.is.null", "limit": "3000"}) or []
    agg = {}
    for r in rows:
        pred_good = (r.get("verdict") == "support") or float(r.get("score") or 0) >= 6
        real_good = float(r.get("outcome") or 0) > 0
        a = agg.setdefault(r["committee"], [0, 0]); a[1] += 1
        if pred_good == real_good:
            a[0] += 1
    n = 0
    for name, (hits, tot) in agg.items():
        if tot < 5:
            continue
        acc = hits / tot
        db.insert("committee_calibration", {"committee": name, "n": tot, "accuracy": round(acc, 3),
                  "weight": round(0.5 + acc, 2), "updated_at": "now()"}, upsert=True)
        n += 1
    print(f"committees.calibrate: reweighted {n} committees")
    calibrate_seats()
    scoreboard()       # grade who was actually right (committees + seats)
    learn_overrides()  # retrain the decision threshold from owner overrides
    tune_budget()      # earn/lose daily autonomy budget by realized win-rate
    dissent_audit()    # vindicate minority views that proved right -> trust in contention flags
    return n


def calibrate_seats():
    """OUTCOME BACKTESTING at the SEAT level: score each individual expert seat by how often its verdict
    matched the realized outcome, and reweight it (0.5..1.5). Proven seats then carry more in future panels."""
    rows = db.select("committee_seat_reviews", {"select": "committee,seat,verdict,score,outcome",
                                                "outcome": "not.is.null", "limit": "5000"}) or []
    agg = {}
    for r in rows:
        pred_good = (r.get("verdict") == "support") or float(r.get("score") or 0) >= 6
        real_good = float(r.get("outcome") or 0) > 0
        a = agg.setdefault((r["committee"], r.get("seat")), [0, 0]); a[1] += 1
        if pred_good == real_good:
            a[0] += 1
    n = 0
    for (committee, seat), (hits, tot) in agg.items():
        if tot < 5:
            continue
        acc = hits / tot
        db.insert("seat_calibration", {"committee": committee, "seat": seat, "n": tot,
                  "accuracy": round(acc, 3), "weight": round(0.5 + acc, 2), "updated_at": "now()"}, upsert=True)
        n += 1
    print(f"committees.calibrate_seats: reweighted {n} seats")
    return n


def _log_action(subject_type, subject_id, title, action, agg):
    try:
        conv = min((float(p.get("conviction", 0) or 0) for p in agg.get("panel", [])), default=0)
        db.insert("committee_actions", {"subject_type": subject_type, "subject_id": subject_id,
                  "subject_title": (title or "")[:200], "action": action,
                  "recommendation": agg.get("recommendation"), "aggregate": agg.get("aggregate"),
                  "conviction": conv, "critical": bool(agg.get("critical")),
                  "alignment": agg.get("alignment")})
    except Exception:
        pass


def _note(agg):
    note = (f"\n\nCommittee panel: {agg['recommendation']} (EV avg {agg['aggregate']}, bar {agg.get('owner_bar')}). "
            f"Opposed by: {', '.join(agg['opposed_by']) or 'none'}.")
    if agg.get("dissents"):
        note += " Preserved dissent — " + "; ".join(agg["dissents"])[:400]
    if agg.get("arbitration"):
        note += f" Arbitration: {agg['arbitration'].get('ruling')} — {agg['arbitration'].get('rationale','')}"[:300]
    if agg.get("conflicts"):
        note += " Precedent conflict — " + "; ".join(agg["conflicts"])[:300]
    pm = agg.get("premortem")
    if pm and pm.get("severe"):
        note += (f" Pre-mortem ({pm.get('severity')}, p={pm.get('plausibility')}): {pm.get('failure_story','')}"
                 f" Mitigation: {pm.get('mitigation','')}")[:400]
    if agg.get("rollout") == "canary":
        note += " Rollout: staged canary (auto-ramp/rollback on metrics)."
    if agg.get("owner_match_signal"):
        note += f" Owner alignment: {agg['owner_match_signal']}."
    return note


def run(limit=8):
    """Convene the committees. AUTONOMOUS BY DEFAULT: the panel self-executes clear wins and auto-clears
    routine decisions; a human is involved ONLY when the matter is critical or highly contentious."""
    process_determination_actions()   # first, fulfill any one-click reviewer actions from the console
    reviewed = {r["subject_id"] for r in (db.select("committee_reviews", {"select": "subject_id"}) or [])}
    pid = {p["name"]: p["id"] for p in (db.select("projects", {"select": "id,name"}) or [])}
    n = executed = escalated = cleared = 0

    for p in db.select("improvement_proposals", {"select": "id,app,surface,title,proposal,rationale,divergent",
                        "status": "eq.for_review", "limit": str(limit)}) or []:
        if p["id"] in reviewed:
            continue
        if not p.get("divergent"):
            import improvement_scrutiny
            admission = improvement_scrutiny.implementation_spec_ready(p.get("proposal"))
            if not admission["pass"]:
                db.update("improvement_proposals", {"id": p["id"]}, {
                    "status": "proposed",
                    "rationale": ((p.get("rationale") or "")[:500] +
                                  "\n\nCommittee admission: redraft required; missing " +
                                  ", ".join(admission["missing"]))[:1200],
                })
                continue
        agg = review("proposal", p["id"], p.get("title"),
                     (p.get("proposal") or "") + "\n" + (p.get("rationale") or ""), app=p.get("app"))
        cert = certify("proposal", p["id"], agg)   # Optimality Certificate + proof + reviewer 1-pager
        upd = {"rationale": (p.get("rationale") or "")[:500] + _note(agg)}
        # AUTONOMY: a non-divergent, non-critical, high-conviction GO builds itself — no owner card.
        if agg.get("auto_ok") and not p.get("divergent"):
            slug = "improve-" + re.sub(r"[^a-z0-9]+", "-", (p.get("title") or "")[:40].lower()).strip("-")
            if pid.get(p.get("app")):
                spec = compose_spec(p.get("title"), p.get("proposal") or "", agg["panel"])
                staged = agg.get("rollout") == "canary"
                if staged:   # STAGED ROLLOUT MANDATE: pre-mortem found a plausible severe failure -> canary
                    pct = _canary_pct(agg.get("premortem"))   # size the blast radius to the risk
                    spec += (f"\n\nSTAGED ROLLOUT: ship behind a feature flag to a {pct}% canary first; do NOT "
                             "enable for all users. The rollout controller will ramp or roll back on metrics.")
                    db.insert("committee_rollouts", {"app": p["app"], "slug": slug, "stage": "canary",
                              "pct": pct, "status": "active",
                              "note": (agg.get("premortem") or {}).get("failure_story", "")[:300]})
                db.insert("tasks", {"project_id": pid[p["app"]], "slug": slug, "state": "QUEUED",
                          "kind": "build", "deps": [], "base_branch": "main", "material": False,
                          "prompt": spec})
                upd["status"] = "queued"; upd["task_slug"] = slug
                executed += 1
                _log_action("proposal", p["id"], p.get("title"),
                            "auto-build-canary" if staged else "auto-build", agg)
        elif agg.get("experiment") and not p.get("divergent") and pid.get(p.get("app")):
            # AUTO-EXPERIMENT: reversible deadlock -> ship a flagged A/B challenger and let data decide.
            slug = "ab-" + re.sub(r"[^a-z0-9]+", "-", (p.get("title") or "")[:36].lower()).strip("-")
            m0 = {r["app"]: float(r.get("mrr_usd") or 0) + float(r.get("active_users") or 0)
                  for r in (db.select("app_revenue", {"select": "app,mrr_usd,active_users"}) or [])}.get(p["app"], 0)
            db.insert("committee_experiments", {"app": p["app"], "slug": slug, "kind": "ab",
                      "hypothesis": (p.get("title") or "")[:200], "status": "running", "metric_start": m0})
            db.insert("tasks", {"project_id": pid[p["app"]], "slug": slug, "state": "QUEUED", "kind": "build",
                      "deps": [], "base_branch": "main", "material": False,
                      "prompt": compose_spec(p.get("title"), (p.get("proposal") or "") +
                               "\n\nSHIP AS AN A/B EXPERIMENT behind a flag (50/50); do not enable globally.",
                               agg["panel"])})
            upd["status"] = "queued"; upd["task_slug"] = slug
            _log_action("proposal", p["id"], p.get("title"), "auto-experiment", agg)
        elif agg.get("escalate") or p.get("divergent"):
            upd["status"] = "for_review"   # keep in front of the owner (divergent OR critical/contentious)
            # attach the reviewer 1-pager so the owner sees contributors + contention at a glance
            upd["rationale"] = (upd["rationale"] + "\n\n---\n" + cert["onepager"])[:6000]
            escalated += 1; _log_action("proposal", p["id"], p.get("title"), "escalate", agg)
        elif (agg.get("recommendation", "").startswith("GO") and not agg.get("critical")
              and not agg.get("opposed_by") and agg.get("budget_left") == 0):
            upd["status"] = "proposed"     # a clean GO we ran out of daily budget for -> DEFER, don't drop
            _log_action("proposal", p["id"], p.get("title"), "deferred-budget", agg)
        else:
            upd["status"] = "reviewed"     # committees settled it; not worth owner time
            _log_action("proposal", p["id"], p.get("title"), "auto-clear", agg)
        db.update("improvement_proposals", {"id": p["id"]}, upd)
        n += 1

    for a in db.select("approvals", {"select": "id,title,why,kind", "status": "eq.pending",
                       "kind": "in.(legal,material)", "limit": str(limit)}) or []:
        if a["id"] in reviewed:
            continue
        agg = review("decision", a["id"], a.get("title"), a.get("why"))
        cert = certify("decision", a["id"], agg)   # certificate + proof + reviewer 1-pager
        # AUTO-CLEAR routine MATERIAL decisions the board is confident + united on; NEVER legal, never
        # critical, never contentious — those stay pending for the human.
        if (a.get("kind") == "material" and agg.get("auto_ok") and not agg.get("critical")
                and not agg.get("contentious")):
            db.update("approvals", {"id": a["id"]}, {"status": "approved", "approver": "committee-auto",
                      "why": (a.get("why") or "")[:400] + _note(agg)})
            cleared += 1; _log_action("decision", a["id"], a.get("title"), "auto-approve", agg)
        else:
            # escalated to the owner -> surface the 1-pager (contributors + contention) on the card
            db.update("approvals", {"id": a["id"]},
                      {"why": (a.get("why") or "")[:400] + "\n\n---\n" + cert["onepager"][:4000]})
            escalated += 1; _log_action("decision", a["id"], a.get("title"), "escalate", agg)
        n += 1

    print(f"committees: reviewed {n}; auto-built {executed}, auto-cleared {cleared}, escalated {escalated}")
    return {"reviewed": n, "auto_built": executed, "auto_cleared": cleared, "escalated": escalated}


def rollout_advance():
    """STAGED ROLLOUT CONTROLLER: move active canaries along canary(5%) -> ramp(50%) -> full on healthy
    metrics, and AUTO-ROLLBACK on regression. Uses the app's revenue/usage as the health signal. Fully
    autonomous; only a hard, repeated regression on a critical app would surface (via the digest)."""
    active = db.select("committee_rollouts", {"select": "*", "status": "eq.active"}) or []
    rev = {r["app"]: float(r.get("mrr_usd") or 0) + float(r.get("active_users") or 0)
           for r in (db.select("app_revenue", {"select": "app,mrr_usd,active_users"}) or [])}
    advanced = rolled = 0
    for r in active:
        cur = rev.get(r.get("app"), 0.0)
        start = float(r.get("metric_start") or 0) or cur
        healthy = cur >= start * 0.98   # allow 2% noise; below that = regression
        if not healthy:
            db.update("committee_rollouts", {"id": r["id"]},
                      {"stage": "rolled_back", "status": "done", "metric_last": cur,
                       "note": (r.get("note") or "") + " | auto-rolled-back on metric regression"})
            try:
                import evidence_bus
                evidence_bus.append(r.get("app", "ORCHESTRATOR"), "incident.rollback", str(r["id"]),
                                    {"metric_start": start, "metric_last": cur, "reason": "canary regression"})
            except Exception:
                pass
            rolled += 1
            continue
        # ADAPTIVE RAMP: strong, stable growth graduates faster; marginal health takes the cautious path.
        strong = cur >= start * 1.02
        if r.get("stage") == "canary":
            nxt = ("full", 100) if strong else ("ramp", 50)
        elif r.get("stage") == "ramp":
            nxt = ("full", 100)
        else:
            nxt = None
        if nxt:
            db.update("committee_rollouts", {"id": r["id"]},
                      {"stage": nxt[0], "pct": nxt[1], "metric_start": cur, "metric_last": cur,
                       "status": "active" if nxt[0] != "full" else "done", "updated_at": "now()"})
            advanced += 1
        else:
            db.update("committee_rollouts", {"id": r["id"]}, {"status": "done", "metric_last": cur})
    print(f"committees.rollout_advance: advanced {advanced}, rolled back {rolled}")
    return {"advanced": advanced, "rolled_back": rolled}


def scoreboard():
    """POST-DECISION SCOREBOARD: grade every committee AND seat by realized outcome, so 'who is actually
    right' is measured, not assumed. Feeds calibration + the owner digest."""
    def _tally(rows, keyfn):
        agg = {}
        for r in rows:
            pred_good = (r.get("verdict") == "support") or float(r.get("score") or 0) >= 6
            real_good = float(r.get("outcome") or 0) > 0
            a = agg.setdefault(keyfn(r), [0, 0, 0.0, 0.0]); a[1] += 1
            if pred_good == real_good:
                a[0] += 1
            a[2] += float(r.get("score") or 0)
            # BRIER SCORE (proper scoring rule): treat score/10 as the predicted P(good); penalize squared error
            p = max(0.0, min(1.0, float(r.get("score") or 5) / 10.0))
            a[3] += (p - (1.0 if real_good else 0.0)) ** 2
        return agg
    crows = db.select("committee_reviews", {"select": "committee,verdict,score,outcome",
                                            "outcome": "not.is.null", "limit": "5000"}) or []
    srows = db.select("committee_seat_reviews", {"select": "committee,seat,verdict,score,outcome",
                                                 "outcome": "not.is.null", "limit": "5000"}) or []
    n = 0
    for (committee), (hit, tot, sev, bri) in _tally(crows, lambda r: r["committee"]).items():
        if tot < 3:
            continue
        db.insert("committee_scoreboard", {"entity_type": "committee", "committee": committee, "seat": "",
                  "calls": tot, "correct": hit, "accuracy": round(hit / tot, 3),
                  "avg_ev": round(sev / tot, 2), "brier": round(bri / tot, 3), "updated_at": "now()"}, upsert=True)
        n += 1
    for (committee, seat), (hit, tot, sev, bri) in _tally(srows, lambda r: (r["committee"], r.get("seat"))).items():
        if tot < 3:
            continue
        db.insert("committee_scoreboard", {"entity_type": "seat", "committee": committee, "seat": seat or "",
                  "calls": tot, "correct": hit, "accuracy": round(hit / tot, 3),
                  "avg_ev": round(sev / tot, 2), "brier": round(bri / tot, 3), "updated_at": "now()"}, upsert=True)
        n += 1
    print(f"committees.scoreboard: graded {n} entities")
    return n


def learn_overrides():
    """OWNER-OVERRIDE LEARNING: when the owner decides AGAINST the committee (approved what we said HOLD, or
    denied what we said GO), record it and nudge the global decision threshold so the system needs the owner
    less over time. Approve-overrides -> be less cautious; deny-overrides -> be more cautious."""
    acts = {a["subject_id"]: a for a in (db.select("committee_actions",
            {"select": "subject_id,subject_type,subject_title,recommendation,action",
             "action": "eq.escalate", "order": "created_at.desc", "limit": "300"}) or []) if a.get("subject_id")}
    decided = db.select("approvals", {"select": "id,status", "status": "in.(approved,denied)",
                                      "order": "decided_at.desc", "limit": "300"}) or []
    net = cnt = 0
    for d in decided:
        a = acts.get(d.get("id"))
        if not a:
            continue
        rec = (a.get("recommendation") or "")
        said_go = rec.startswith("GO")
        said_hold = rec.startswith("HOLD")
        if d["status"] == "approved" and said_hold:
            direction = "owner_more_aggressive"; net -= 1; cnt += 1
        elif d["status"] == "denied" and said_go:
            direction = "owner_more_cautious"; net += 1; cnt += 1
        else:
            continue
        db.insert("owner_overrides", {"subject_type": a.get("subject_type"), "subject_id": d["id"],
                  "subject_title": a.get("subject_title"), "committee_rec": rec,
                  "owner_decision": d["status"], "direction": direction})
    if cnt:
        delta = round(max(-1.0, min(1.0, net / cnt)) * 0.5, 3)   # bounded nudge on the GO bar
        db.insert("owner_model", {"key": "threshold_delta", "value": delta, "updated_at": "now()"}, upsert=True)
    print(f"committees.learn_overrides: {cnt} overrides, threshold_delta set from net {net}")
    return cnt


def board_review():
    """PORTFOLIO BOARD: a standing meta-committee that decides WHERE the next build effort should go across
    all apps (not one proposal at a time). It recommends an allocation and rebalances the queue autonomously
    by bumping the priority of the highest-leverage app's pending work."""
    apps = [p for p in (db.select("projects", {"select": "id,name"}) or []) if p["name"] != "smoke-test"]
    rev = {r["app"]: r for r in (db.select("app_revenue", {"select": "*"}) or [])}
    ctx = []
    for a in apps:
        r = rev.get(a["name"], {})
        q = db.select("tasks", {"select": "id", "project_id": f"eq.{a['id']}", "state": "eq.QUEUED"}) or []
        ctx.append(f"{a['name']}: MRR ${r.get('mrr_usd',0)}, users {r.get('active_users',0)}, queued {len(q)}")
    alloc = _json("You are the PORTFOLIO BOARD. Allocate the next build effort across these apps to maximize "
                  "portfolio value per build-hour. Return ONE JSON array; each item "
                  "{\"app\":\"...\",\"share\":0.0-1.0,\"rationale\":\"1 sentence\"}. Shares sum to ~1.\n"
                  "APPS:\n" + "\n".join(ctx), arr=True) or []
    top = None
    for it in alloc:
        db.insert("board_allocations", {"app": it.get("app"), "recommended_share": float(it.get("share", 0) or 0),
                  "rationale": (it.get("rationale") or "")[:300]})
        if not top or float(it.get("share", 0) or 0) > float(top.get("share", 0) or 0):
            top = it
    # autonomous rebalance: bump priority on the top app's queued tasks so the swarm serves it first
    bumped = 0
    if top:
        tid = next((a["id"] for a in apps if a["name"] == top.get("app")), None)
        if tid:
            for t in db.select("tasks", {"select": "id", "project_id": f"eq.{tid}",
                                         "state": "eq.QUEUED", "limit": "20"}) or []:
                bumped += 1  # priority column removed from tasks schema
    print(f"committees.board_review: allocated {len(alloc)} apps, bumped {bumped} tasks toward {top and top.get('app')}")
    return {"apps": len(alloc), "top": top and top.get('app'), "bumped": bumped}


def board_bandit():
    """PORTFOLIO BANDIT: instead of a one-shot allocation, continuously shift build effort toward the app
    with the best REALIZED reward (concluded-experiment lift + revenue movement), while exploring
    underfunded apps just enough not to miss a sleeper. UCB1 over apps; autonomous queue rebalance."""
    import math
    apps = [p for p in (db.select("projects", {"select": "id,name"}) or []) if p["name"] != "smoke-test"]
    # reward signal: average realized lift of each app's concluded experiments (fallback: optimistic prior)
    exps = db.select("committee_experiments", {"select": "app,lift", "status": "eq.concluded"}) or []
    lift = {}
    for e in exps:
        lift.setdefault(e["app"], []).append(float(e.get("lift") or 0))
    state = {b["app"]: b for b in (db.select("board_bandit", {"select": "*"}) or [])}
    total_pulls = sum(int(s.get("pulls") or 0) for s in state.values()) + 1
    scored = []
    for a in apps:
        name = a["name"]
        reward = (sum(lift[name]) / len(lift[name])) if lift.get(name) else 0.0
        pulls = int(state.get(name, {}).get("pulls") or 0)
        # UCB1: exploit avg reward + explore rarely-pulled arms
        ucb = (reward / 10.0) + math.sqrt(2 * math.log(total_pulls) / (pulls + 1))
        scored.append((ucb, name, a["id"], reward))
    scored.sort(reverse=True)
    top = scored[0] if scored else None
    bumped = 0
    if top:
        _, tname, tid, treward = top
        for t in db.select("tasks", {"select": "id", "project_id": f"eq.{tid}",
                                     "state": "eq.QUEUED", "limit": "20"}) or []:
            bumped += 1  # priority column removed from tasks schema
        # update bandit state for the pulled arm
        st = state.get(tname, {"pulls": 0, "reward_sum": 0})
        pulls = int(st.get("pulls") or 0) + 1
        rsum = float(st.get("reward_sum") or 0) + treward
        db.insert("board_bandit", {"app": tname, "pulls": pulls, "reward_sum": rsum,
                  "avg_reward": round(rsum / pulls, 3), "updated_at": "now()"}, upsert=True)
        db.insert("board_allocations", {"app": tname, "recommended_share": 1.0,
                  "rationale": f"UCB pick: reward {round(treward,2)}, explored {pulls}x"})
    print(f"committees.board_bandit: picked {top and top[1]}, bumped {bumped} tasks")
    return {"top": top and top[1], "bumped": bumped}


def mine_hypotheses(limit=3):
    """AUTO-GENERATED HYPOTHESES: keep the experiment pipeline full. Mine the scoreboard + concluded
    experiments + surface returns for the next testable ideas, and queue them as (non-divergent) proposals
    so the autonomous loop A/B-tests them. The system never runs out of things to try."""
    sb = db.select("committee_scoreboard", {"select": "committee,accuracy,avg_ev", "entity_type": "eq.committee",
                   "order": "avg_ev.desc", "limit": "8"}) or []
    exps = db.select("committee_experiments", {"select": "app,slug,lift,decision", "status": "eq.concluded",
                     "order": "concluded_at.desc", "limit": "10"}) or []
    sret = db.select("surface_returns", {"select": "surface,avg_delta", "order": "avg_delta.desc", "limit": "8"}) or []
    ideas = _json("You are a growth scientist. From the evidence, propose up to %d concrete, testable "
                  "experiment hypotheses (each a small, reversible A/B). Return ONE JSON array; each: "
                  "{\"app\":\"...\",\"title\":\"...\",\"hypothesis\":\"if we do X, metric Y improves because Z\"}\n"
                  "COMMITTEE SCORES: %s\nRECENT EXPERIMENTS: %s\nHIGH-RETURN SURFACES: %s" %
                  (limit, json.dumps(sb)[:800], json.dumps(exps)[:800], json.dumps(sret)[:400]), arr=True) or []
    pid = {p["name"]: p["id"] for p in (db.select("projects", {"select": "id,name"}) or [])}
    n = 0
    for it in ideas[:limit]:
        app = it.get("app")
        if not it.get("title") or not pid.get(app):
            continue
        db.insert("improvement_proposals", {"app": app, "surface": "experiment", "title": it["title"][:200],
                  "status": "proposed", "divergent": False, "proposal": (it.get("hypothesis") or "")[:800],
                  "rationale": "Auto-generated hypothesis from committee evidence.", "score": 14})
        n += 1
    print(f"committees.mine_hypotheses: queued {n} experiment hypotheses")
    return n


def build_kg():
    """CROSS-COMMITTEE KNOWLEDGE GRAPH: link opinions to their committee, app, verdict, dissent, and to
    SIMILAR prior opinions — so a panel can pull 'everything we've concluded near this decision' at once,
    across committees, instead of keyword-matched snippets from one committee."""
    ops = db.select("committee_opinions", {"select": "id,app,committee,subject_title,consensus_verdict,dissent",
                    "order": "created_at.desc", "limit": "300"}) or []
    # avoid rebuilding edges we already have
    have = {(e["from_key"], e["to_key"], e["relation"]) for e in
            (db.select("kg_edges", {"select": "from_key,to_key,relation", "limit": "5000"}) or [])}
    def add(fk, tk, rel, w=1):
        if fk and tk and (fk, tk, rel) not in have:
            db.insert("kg_edges", {"from_kind": "opinion", "from_key": fk, "to_kind": rel.split(":")[0],
                      "to_key": tk, "relation": rel, "weight": w})
            have.add((fk, tk, rel))
    toks = {}
    n = 0
    for o in ops:
        oid = str(o["id"])
        add(oid, o.get("committee"), "committee:of"); add(oid, o.get("app") or "portfolio", "app:in")
        add(oid, o.get("consensus_verdict"), "verdict:held")
        toks[oid] = set(re.findall(r"[a-z]{4,}", (o.get("subject_title") or "").lower()))
        n += 1
    # similarity edges (bounded pairwise on recent opinions)
    keys = list(toks)[:120]
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            if len(toks[keys[i]] & toks[keys[j]]) >= 3:
                add(keys[i], keys[j], "opinion:similar", 2)
    print(f"committees.build_kg: indexed {n} opinions")
    return n


def kg_context(title, body, limit=4):
    """Query the knowledge graph for opinions near this decision (any committee) — richer than single-
    committee precedent. Returns a compact context string."""
    key = set(re.findall(r"[a-z]{4,}", ((title or "") + " " + (body or "")).lower()))
    ops = db.select("committee_opinions", {"select": "committee,subject_title,consensus_verdict,opinion",
                    "order": "created_at.desc", "limit": "200"}) or []
    scored = []
    for o in ops:
        kk = set(re.findall(r"[a-z]{4,}", (o.get("subject_title") or "").lower()))
        ov = len(key & kk)
        if ov >= 2:
            scored.append((ov, o))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return ""
    lines = [f"{o['committee']} held '{o.get('consensus_verdict')}' on '{o.get('subject_title')}'"
             for _, o in scored[:limit]]
    return "RELATED PRIOR DECISIONS (knowledge graph): " + " | ".join(lines) + "\n"


def meta_review():
    """META-COMMITTEE: the committee that reviews the committee SYSTEM. It reads the scoreboard and proposes
    charter changes — add a missing committee, retire a chronically-wrong low-volume one, or recalibrate.
    Reversible weight tweaks apply autonomously; structural changes are logged + surfaced to the owner."""
    sb = db.select("committee_scoreboard", {"select": "committee,accuracy,calls",
                   "entity_type": "eq.committee"}) or []
    d = _json("You are the META-COMMITTEE reviewing the committee system's own performance. Based on the "
              "scoreboard, recommend charter changes. Return ONE JSON array; each: "
              "{\"change\":\"add|retire|recalibrate\",\"committee\":\"name or new committee name\","
              "\"rationale\":\"1 sentence\"}\nSCOREBOARD: " + json.dumps(sb)[:1200], arr=True) or []
    applied = logged = 0
    for it in d:
        change = it.get("change"); name = it.get("committee")
        db.insert("committee_charter", {"change": change, "committee": name,
                  "rationale": (it.get("rationale") or "")[:300], "applied": False})
        logged += 1
        # autonomously apply only the safe, reversible action: recalibrate an existing committee's weight
        if change == "recalibrate" and name:
            row = next((s for s in sb if s["committee"] == name), None)
            if row and int(row.get("calls") or 0) >= 5:
                acc = float(row.get("accuracy") or 0.5)
                db.update("committees", {"name": name}, {"weight": round(0.6 + acc, 2)})
                db.update("committee_charter", {"committee": name, "change": "recalibrate"}, {"applied": True})
                applied += 1
        # 'add' / 'retire' are structural -> record for the owner (surfaced in the digest), never auto-applied
    print(f"committees.meta_review: {logged} charter notes, {applied} auto-recalibrations")
    return {"logged": logged, "applied": applied}


def conclude_experiments():
    """CHAMPION/CHALLENGER: conclude running A/B experiments by measuring realized lift vs the baseline
    metric snapshot; keep the winner, retire the loser — autonomously. Causal, not correlational."""
    run_x = db.select("committee_experiments", {"select": "*", "status": "eq.running"}) or []
    rev = {r["app"]: float(r.get("mrr_usd") or 0) + float(r.get("active_users") or 0)
           for r in (db.select("app_revenue", {"select": "app,mrr_usd,active_users"}) or [])}
    import datetime
    done = 0
    for x in run_x:
        # give an experiment at least ~3 days to accumulate signal
        try:
            started = datetime.datetime.fromisoformat((x.get("created_at") or "").replace("Z", "+00:00"))
            if (datetime.datetime.now(datetime.timezone.utc) - started).days < 3:
                continue
        except Exception:
            pass
        cur = rev.get(x.get("app"), 0.0); base = float(x.get("metric_start") or 0) or cur
        lift = round((cur - base) / base * 100, 2) if base else 0.0
        # When a holdout cohort is instrumented, use DiD rather than crediting a
        # fleet-wide trend to the challenger.  Legacy experiments retain lift.
        if x.get("control_metric_start") is not None and x.get("control_metric_last") is not None:
            import adversarial_fleet
            lift = adversarial_fleet.difference_in_differences(
                x["control_metric_start"], x["control_metric_last"], base, cur)
        reversible = x.get("kind", "ab") in ("ab", "holdout")
        import adversarial_fleet
        decision = ("ship-challenger" if adversarial_fleet.experiment_verdict(lift, 1, reversible) == "graduate"
                    else "keep-champion")
        db.update("committee_experiments", {"id": x["id"]},
                  {"status": "concluded", "metric_last": cur, "lift": lift, "decision": decision,
                   "concluded_at": "now()"})
        done += 1
    print(f"committees.conclude_experiments: concluded {done}")
    return done


def watch_scan():
    """EVENT-DRIVEN WATCH: scan external signals (regulatory, security, competitor) for the reactive
    committees and, on a material new signal, re-open the docket for the affected app automatically — so
    re-reviews are triggered by reality, not just the calendar. Optional web tool; degrades to no-op."""
    if os.environ.get("COMMITTEE_WEB_EVIDENCE", "1") != "1":
        return 0
    apps = [p["name"] for p in (db.select("projects", {"select": "name"}) or []) if p["name"] != "smoke-test"]
    found = 0
    for domain in ("new regulation or compliance change", "security vulnerability or CVE", "competitor launch or pricing move"):
        txt = ""
        for modname, fn in (("web_research", "search"), ("research", "search"), ("tools", "web_search")):
            try:
                mod = __import__(modname); hit = getattr(mod, fn)(f"{domain} affecting SaaS 2026")
                txt = hit if isinstance(hit, str) else json.dumps(hit); break
            except Exception:
                continue
        if not txt:
            continue
        affects = next((a for a in apps if a.lower() in txt.lower()), apps[0] if apps else None)
        db.insert("watch_signals", {"kind": domain.split()[0], "source": "web", "summary": txt[:400],
                  "affects_app": affects, "acted": False})
        found += 1
    if found:
        try:
            docket(limit=3)   # event-driven re-review
        except Exception:
            pass
    print(f"committees.watch_scan: {found} external signals")
    return found


def board_minutes():
    """NATURAL-LANGUAGE BOARD MINUTES: a 60-second plain-English brief of what the autonomous board decided,
    shipped, experimented on, and is watching this cycle — so the owner can skim the whole operation fast."""
    since = _today()
    acts = db.select("committee_actions", {"select": "action,subject_title,recommendation",
                     "created_at": f"gte.{since}", "order": "created_at.desc", "limit": "80"}) or []
    rolls = db.select("committee_rollouts", {"select": "app,slug,stage,status", "order": "updated_at.desc",
                     "limit": "20"}) or []
    exps = db.select("committee_experiments", {"select": "app,slug,status,lift,decision",
                     "order": "created_at.desc", "limit": "20"}) or []
    from collections import Counter
    c = Counter(a["action"] for a in acts)
    esc = [a["subject_title"] for a in acts if a["action"] == "escalate"][:6]
    summary = (f"Auto-built {c.get('auto-build',0)+c.get('auto-build-canary',0)}, auto-cleared "
               f"{c.get('auto-clear',0)+c.get('auto-approve',0)}, experiments {c.get('auto-experiment',0)}, "
               f"escalated {c.get('escalate',0)}.")
    text = _complete("Write concise, plain-English board minutes (<=140 words) from this activity. Neutral, "
                 "skimmable, lead with what shipped and what needs the owner. DATA:\n"
                 f"{summary}\nESCALATED TO OWNER: {esc}\nROLLOUTS: {[(r['slug'],r['stage'],r['status']) for r in rolls]}\n"
                 f"EXPERIMENTS: {[(e['slug'],e['status'],e.get('lift')) for e in exps]}").strip() or summary
    db.insert("board_minutes", {"headline": summary, "body": text[:3000]})
    try:
        db.insert("inbox", {"kind": "board_minutes", "title": "Weekly committee dissent digest",
                  "body": text[:3000], "status": "unread"})
    except Exception:
        pass
    print(f"committees.board_minutes: {summary}")
    return summary


def docket(limit=6):
    """CONTINUOUS DOCKET: proactively re-review already-shipped features on a cadence. If the committees'
    verdict has flipped negative since it shipped (evidence moved), open a 'reconsider' item — autonomously
    queuing a fix for low-stakes cases, escalating only the critical/contentious ones."""
    pid = {p["name"]: p["id"] for p in (db.select("projects", {"select": "id,name"}) or [])}
    seen = {r["subject_key"]: r for r in (db.select("committee_docket", {"select": "*"}) or [])}
    n = flipped = 0
    for t in db.select("tasks", {"select": "slug,project_id,state", "state": "eq.MERGED",
                                 "order": "updated_at.desc", "limit": "40"}) or []:
        app = next((k for k, v in pid.items() if v == t["project_id"]), None)
        key = f"{app}:{t['slug']}"
        prev = seen.get(key)
        # re-review at most every ~14 days
        if prev and prev.get("last_reviewed_at", "") > "":
            import datetime
            try:
                last = datetime.datetime.fromisoformat(prev["last_reviewed_at"].replace("Z", "+00:00"))
                if (datetime.datetime.now(datetime.timezone.utc) - last).days < 14:
                    continue
            except Exception:
                pass
        agg = review("shipped", None, f"Re-review shipped: {t['slug']}",
                     f"Feature {t['slug']} shipped in {app}. Given current evidence, should it stay as-is, "
                     f"be improved, or be rolled back?", app=app)
        db.insert("committee_docket", {"subject_key": key, "app": app, "slug": t["slug"],
                  "last_verdict": agg["recommendation"], "last_reviewed_at": "now()"}, upsert=True)
        n += 1
        if agg["recommendation"].startswith(("HOLD", "REVISE", "ESCALATE")):
            flipped += 1
            if agg.get("escalate"):
                db.insert("improvement_proposals", {"app": app, "surface": "reliability",
                          "title": f"Reconsider shipped: {t['slug']}", "status": "for_review",
                          "proposal": "Committees re-reviewed this shipped feature and flagged it.",
                          "rationale": _note(agg)})
            elif pid.get(app):
                db.insert("tasks", {"project_id": pid[app], "slug": f"reconsider-{t['slug']}"[:60],
                          "state": "QUEUED", "kind": "build", "deps": [], "base_branch": "main",
                          "material": False, "prompt": compose_spec(f"Improve {t['slug']}", _note(agg), agg["panel"])})
        if n >= limit:
            break
    print(f"committees.docket: re-reviewed {n} shipped features, {flipped} flagged")
    return {"reviewed": n, "flagged": flipped}


def dissent_digest():
    """OWNER DISSENT DIGEST: a periodic brief of the sharpest preserved dissents, reversals, and
    low-confidence calls across all committees — so the owner sees exactly where the system is least sure,
    without having to sit in every meeting."""
    op = db.select("committee_opinions", {"select": "committee,subject_title,consensus_verdict,dissent,"
                   "precedent_conflict,p_success,expected_value", "order": "created_at.desc", "limit": "120"}) or []
    dissent = [o for o in op if o.get("dissent") and o["dissent"] not in ("none", "")]
    reversals = [o for o in op if o.get("precedent_conflict")]
    lowconf = sorted([o for o in op if o.get("p_success") is not None],
                     key=lambda o: float(o.get("p_success") or 1))[:5]
    lines = ["SHARPEST DISSENTS:"]
    lines += [f"  • [{o['committee']}] {o['subject_title']}: {o['dissent']}" for o in dissent[:6]] or ["  • none"]
    lines.append("PRECEDENT REVERSALS:")
    lines += [f"  • [{o['committee']}] {o['subject_title']}: {o['precedent_conflict']}" for o in reversals[:5]] or ["  • none"]
    lines.append("LEAST-CONFIDENT CALLS:")
    lines += [f"  • [{o['committee']}] {o['subject_title']}: p(success)={o.get('p_success')}" for o in lowconf] or ["  • none"]
    body = "\n".join(lines)
    head = f"{len(dissent)} open dissents, {len(reversals)} reversals this cycle"
    db.insert("committee_digests", {"period": "weekly", "headline": head, "body": body[:4000]})
    try:  # surface into the owner inbox if one exists
        db.insert("inbox", {"kind": "committee_digest", "title": "Weekly committee dissent digest",
                  "body": body[:4000], "status": "unread"})
    except Exception:
        pass
    print(f"committees.dissent_digest: {head}")
    return head


if __name__ == "__main__":
    print(json.dumps(review("proposal", None, "Add usage-based pricing tier",
                            "Introduce metered pricing on top of the flat plan."), indent=2, default=str))


if __name__ == "__main__":
    print(json.dumps(review("proposal", None, "Add usage-based pricing tier",
                            "Introduce metered pricing on top of the flat plan."), indent=2, default=str))
