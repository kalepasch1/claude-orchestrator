#!/usr/bin/env python3
"""
approval_push.py - fan every decision you need to make out to wherever you want to manage it: email
(audience from $APPROVAL_PUSH_EMAIL / $ORCH_OWNER_EMAIL) and Smarter (which reads the shared
Supabase). For each NEW pending legal / business-model / action card, it writes a row to
`notifications` (the source of truth every surface reads).

Dedup: one notification per approval id. The daily/hourly digest task drains unsent email rows and
mails them; Smarter reads v_pending_decisions live. So you can act from the cockpit, from email, or
from Smarter — same queue, single approval final. Schedule every few minutes.

DIGEST BATCHING
---------------
One outbound ping per run summarising every card pushed, instead of one immediate ping per card.

SECURITY POSTURE (2026-08-13 rework; the previous version was quarantined)
-------------------------------------------------------------------------
  * One-click links are signed with a DEDICATED $APPROVAL_LINK_SIGNING_KEY. The Supabase
    service-role key is used only under an explicit APPROVAL_LINK_ALLOW_SERVICE_KEY=1 opt-in.
  * A missing/short key makes signing RAISE, never fall back to an empty HMAC key. An
    empty-key HMAC is publicly computable, i.e. anyone could forge an approve link.
  * The link TTL is clamped to [5 minutes, 7 days].
  * No owner email address is hardcoded; with no audience configured, no email row is written.
  * Everything printed or handed to a notifier goes through scrub(): signatures never leak.
"""
import os, re, sys, time, hmac, hashlib, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

_TRUTHY = ("1", "true", "yes", "on")

# No personal address is baked into source. Unset -> no email audience, and the email
# rows are simply not written; the Supabase ledger and Smarter still see every card.
AUDIENCE = (os.environ.get("APPROVAL_PUSH_EMAIL")
            or os.environ.get("ORCH_OWNER_EMAIL") or "").strip()

# TTL is clamped: an unbounded or absurd TTL turns a one-click link into a permanent one.
_TTL_MAX_S = 7 * 24 * 3600
_TTL_MIN_S = 300


def _ttl_seconds():
    try:
        ttl = int(os.environ.get("APPROVAL_LINK_TTL_S", str(_TTL_MAX_S)))
    except (TypeError, ValueError):
        ttl = _TTL_MAX_S
    return max(_TTL_MIN_S, min(ttl, _TTL_MAX_S))


LINK_TTL_S = _ttl_seconds()

# A signing key must be long enough to be a key. The previous code fell back to "" when
# the env var was missing and signed anyway — an empty-key HMAC is publicly computable,
# so anyone could mint an "approve" link for any approval id. Refusing to sign is the
# only safe behaviour; the digest degrades to an unsigned cockpit pointer instead.
_MIN_KEY_LEN = 32


class SigningKeyUnavailable(RuntimeError):
    """No usable link-signing key is configured. Never sign, never fall back to empty."""


def _signing_key():
    """Least-privilege signing key.

    `APPROVAL_LINK_SIGNING_KEY` is a dedicated secret shared only with the approvals-api
    edge function. The Supabase SERVICE ROLE key — full read/write on every table — is
    accepted only when an operator explicitly opts in with
    APPROVAL_LINK_ALLOW_SERVICE_KEY=1, because signing user-facing links with the
    highest-privilege credential in the system widens the blast radius of any leak.
    """
    key = (os.environ.get("APPROVAL_LINK_SIGNING_KEY") or "").strip()
    source = "APPROVAL_LINK_SIGNING_KEY"
    if not key and os.environ.get("APPROVAL_LINK_ALLOW_SERVICE_KEY", "").strip().lower() in _TRUTHY:
        key = (os.environ.get("SUPABASE_SERVICE_KEY")
               or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
        source = "SUPABASE_SERVICE_KEY (explicit opt-in)"
    if len(key) < _MIN_KEY_LEN:
        raise SigningKeyUnavailable(
            f"no usable link-signing key (checked {source}); set APPROVAL_LINK_SIGNING_KEY "
            f"to a random secret of >= {_MIN_KEY_LEN} chars. Refusing to sign: an empty or "
            "short key would let anyone forge one-click approvals.")
    return key


_SIG_RX = re.compile(r"(?i)([?&](?:sig|signature|token|key|apikey)=)[^&\s]+")


def scrub(text):
    """Strip link signatures before anything is printed or handed to a notifier."""
    return _SIG_RX.sub(r"\1[REDACTED]", str(text or ""))


def _base_url():
    return (os.environ.get("SUPABASE_URL") or "").rstrip("/")


def cockpit_url():
    """Unsigned pointer used whenever we cannot sign. Grants no authority by itself."""
    return (os.environ.get("APPROVAL_COCKPIT_URL") or "").strip() or (_base_url() or "the cockpit")


def _sign(aid, action, opt=""):
    """Signed one-click decision link, verified by the approvals-api edge function.

    Raises SigningKeyUnavailable rather than emitting a forgeable link.
    """
    key = _signing_key()
    exp = str(int(time.time()) + LINK_TTL_S)
    sig = hmac.new(key.encode(), f"{aid}|{action}|{opt}|{exp}".encode(), hashlib.sha256).hexdigest()
    q = f"id={aid}&action={action}&exp={exp}&sig={sig}" + (f"&opt={opt}" if opt != "" else "")
    return f"{_base_url()}/functions/v1/approvals-api?{q}"


def _unsigned_block(a):
    """What we send when we cannot sign. Carries no authority, only a pointer."""
    return ("  One-click links are disabled: no link-signing key is configured.\n"
            f"  Decide in the cockpit or Smarter: {cockpit_url()}\n"
            f"  (approval id {a.get('id')})")


def _links_block(a):
    """Plain-text action links: flexible options (from alternatives) + approve/deny/defer."""
    try:
        _signing_key()
    except SigningKeyUnavailable:
        return _unsigned_block(a)
    lines = []
    alts = a.get("alternatives") or []
    if isinstance(alts, str):
        try:
            alts = json.loads(alts)
        except Exception:
            alts = []
    for i, alt in enumerate(alts[:4]):
        if isinstance(alt, str):
            alt = {"label": alt}
        label = alt.get("label") or alt.get("title") or f"option {i+1}"
        tag = " *** RECOMMENDED ***" if alt.get("recommended") else ""
        meta = f" [risk: {alt.get('risk','?')} | {'reversible' if alt.get('reversible', True) else 'HARD TO REVERSE'}]"
        desc = (alt.get("description") or "")[:200]
        lines.append(f"  OPTION {i+1} — {str(label)[:90]}{tag}{meta}\n"
                     + (f"    {desc}\n" if desc else "")
                     + f"    {_sign(a['id'], 'option', str(i))}")
    lines.append(f"  APPROVE as proposed:\n    {_sign(a['id'], 'approve')}")
    lines.append(f"  DENY:\n    {_sign(a['id'], 'deny')}")
    lines.append(f"  DEFER / request fuller brief:\n    {_sign(a['id'], 'defer')}")
    return "\n".join(lines)


def build_digest(cards):
    """(title, body) for ONE batched digest covering every card pushed this run.

    The digest deliberately carries NO signed links — it is a summary that points at the
    per-card notifications and the cockpit. Batching the outbound ping is the point: the
    previous code fired one immediate notify.send() per card, so a burst of decisions
    produced a burst of pings and the digest row nobody could act on in one place.
    """
    n = len(cards)
    title = f"{n} decision{'s' if n != 1 else ''} need you"
    lines = [title, ""]
    for a in cards:
        kind = "Decision" if a.get("kind") in ("legal", "material") else "Action"
        lines.append(f"  - [{a.get('project') or '-'}] {kind}: {str(a.get('title') or '')[:120]}")
    lines += ["", f"Decide in the cockpit or Smarter: {cockpit_url()}",
              "Individual notifications carry the one-click links; first decision wins."]
    return title, "\n".join(lines)


def _digest_enabled():
    return os.environ.get("APPROVAL_DIGEST_BATCHING", "1").strip().lower() in _TRUTHY


def run(limit=50):
    # new decisions/actions not yet pushed
    already = {r.get("approval_id") for r in (db.select("notifications", {"select": "approval_id"}) or [])}
    cards = db.select("approvals", {"select": "id,kind,project,title,why,value,risk,alternatives,prebrief,legal_risk_level,radar_tag,detail,brief_json",
                                    "status": "eq.pending",
                                    "kind": "in.(legal,material,secret,operator)",
                                    "order": "created_at.desc", "limit": str(limit)}) or []
    import approval_policy
    pushed = 0
    batched = []
    for a in cards:
        if a["id"] in already:
            continue
        # OWNER POLICY: only narrow legal-structuring questions email immediately;
        # approval_policy.sweep() auto-approves the rest (they land in the daily digest).
        if not approval_policy.is_legal_gated(a):
            continue
        is_decision = a["kind"] in ("legal", "material")
        kind = "decision" if is_decision else "action"
        # skip routine legal that legal_triage already auto-cleared/marked routine
        if a["kind"] == "legal" and (a.get("legal_risk_level") == "routine"):
            continue
        title = ("Decision: " if is_decision else "Action: ") + (a.get("title") or "")[:140]
        bj = a.get("brief_json") or {}
        parts = [f"[{a.get('project') or '-'}] {a.get('title') or ''}"]
        if isinstance(bj, dict) and bj.get("question"):
            parts.append(f"QUESTION: {bj['question']}")
        for k, hdr in (("why", "WHY"), ("value", "VALUE"), ("risk", "RISK"), ("prebrief", "BRIEF")):
            if a.get(k):
                parts.append(f"{hdr}: {str(a[k])[:700]}")
        parts.append("DECIDE (one click):\n" + _links_block(a))
        parts.append("Or manage in the cockpit / Smarter — same queue, first decision wins.")
        body = "\n\n".join(parts)
        row = {"channel": "email", "audience": AUDIENCE, "kind": kind,
               "title": title[:180], "body": body[:4000], "approval_id": a["id"], "sent": False}
        # No configured audience -> no email row. Writing one addressed to a hardcoded
        # personal address is how owner PII ends up in source and in every export.
        if AUDIENCE:
            db.insert("notifications", row)
        # always mirror to Smarter (it reads v_pending_decisions live; no external send)
        db.insert("notifications", {**row, "channel": "smarter"})
        batched.append(a)
        pushed += 1

    # DIGEST BATCHING: one ping per run, not one per card. A burst of decisions used to
    # produce a burst of immediate notify.send() calls, which is both noisy and how the
    # signed link bodies leaked into notifier logs.
    if batched and _digest_enabled():
        d_title, d_body = build_digest(batched)
        try:
            db.insert("notifications", {"channel": "digest", "audience": AUDIENCE,
                                        "kind": "digest", "title": d_title[:180],
                                        "body": d_body[:4000],
                                        "approval_id": batched[0]["id"], "sent": False})
        except Exception:
            pass
        try:
            import notify
            notify.send(scrub(d_title))       # scrubbed: never hand a signature to a notifier
        except Exception:
            pass
    elif batched:
        for a in batched:
            try:
                import notify
                notify.send(scrub("Decision: " + str(a.get("title") or "")[:140]))
            except Exception:
                pass

    dest = AUDIENCE or "(no email audience configured)"
    print(scrub(f"approval_push: pushed {pushed} new decisions/actions to {dest} + Smarter "
                f"({'batched digest' if _digest_enabled() else 'per-card pings'})"))
    return pushed


if __name__ == "__main__":
    run()
