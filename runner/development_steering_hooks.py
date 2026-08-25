#!/usr/bin/env python3
"""
development_steering_hooks.py — versioned allow/warn/hold steering at the four
gates where the fleet can do something it cannot take back.

Gates: PLANNING_APPROVAL, TOOL_CALL, INTEGRATION, RELEASE.

Authority split (this is the part that must not blur):
  * Illuminati / Foulkon own GENERAL risk — destructive commands, secrets,
    protected branches, blast radius. They speak on every project.
  * Apparently owns LEGAL/DOMAIN posture, and only contributes where legal
    relevance is actually established for the project and the text. An
    irrelevant-legal proposal must bypass it entirely rather than collect a
    decorative legal opinion.
  * Model prose is never policy. A rule's `authority` is always a named,
    versioned rule id; advisory model text rides along in `advisory` and can
    never by itself produce a WARN or HOLD. `receipt["policy_authorities"]`
    therefore only ever contains rule ids.

Every evaluation returns a receipt carrying rule/authority, rationale, risk,
alternatives, scope, digest, latency and any authorized override — enough to
reconstruct why the fleet was allowed to act.

Safe failure: an internal error never yields a silent ALLOW. Consequential
gates (TOOL_CALL, RELEASE) fail closed to HOLD; advisory gates degrade to WARN.

Pure and dependency-light: `legal_filter` is imported fail-soft, everything
else is local, so this is unit-testable without a database.
"""
import hashlib
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

POLICY_VERSION = "steer-2026.08.1"

ALLOW, WARN, HOLD = "allow", "warn", "hold"
_RANK = {ALLOW: 0, WARN: 1, HOLD: 2}

GATE_PLANNING = "planning_approval"
GATE_TOOL_CALL = "tool_call"
GATE_INTEGRATION = "integration"
GATE_RELEASE = "release"
GATES = (GATE_PLANNING, GATE_TOOL_CALL, GATE_INTEGRATION, GATE_RELEASE)

# Gates where an internal failure must not be waved through.
FAIL_CLOSED_GATES = frozenset({GATE_TOOL_CALL, GATE_RELEASE})

# Projects whose subject matter makes Apparently's legal authority relevant at
# all. Everything else only reaches Apparently if the text itself is legal.
LEGAL_DOMAIN_PROJECTS = frozenset(
    p.strip() for p in os.environ.get(
        "ORCH_STEER_LEGAL_PROJECTS", "apparently,apparently-law,illuminati").split(",") if p.strip())

CACHE_TTL_S = int(os.environ.get("ORCH_STEER_CACHE_TTL_S", "300"))
_CACHE = {}

# --- general risk (Illuminati / Foulkon authority) -------------------------

# No trailing \b: several of these end in punctuation ("rm -rf /"), where a word
# boundary never matches and the rule silently never fires.
_DESTRUCTIVE = re.compile(
    r"\b(?:rm\s+-rf\s+/|drop\s+table\b|truncate\s+table\b"
    r"|git\s+push\s+--force\s+origin\s+(?:main|master)\b"
    r"|delete\s+from\s+\w+\s*;|shutdown\s+-h\b)", re.I)
_PROTECTED_BRANCH = re.compile(r"\bpush\b[^\n]*\b(origin/)?(main|master|dev|production)\b", re.I)
_SECRETISH = re.compile(
    r"(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|AKIA[0-9A-Z]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)")
_CREDENTIAL_WORD = re.compile(r"\b(api[_-]?key|secret[_-]?key|password|private[_-]?key|token)\b\s*[:=]", re.I)

# --- legal posture (Apparently authority) ----------------------------------

_LEGAL_RELEVANT = re.compile(
    r"\b(licen[cs]e|licensing|registration|custody|money\s+transmission|transmitter"
    r"|broker[- ]dealer|fiduciary|legal\s+advice|attorney|regulat|compliance|kyc|aml"
    r"|terms\s+of\s+service|privacy\s+policy|gdpr|hipaa)\b", re.I)
_LEGAL_POSTURE_CHANGE = re.compile(
    r"\b(requires?|force[sd]?|triggers?|obligates?)\b[^.\n]{0,80}"
    r"\b(licen[cs]e|licensing|registration|custody|money\s+transmission|broker[- ]dealer"
    r"|fiduciary|legal\s+advice)\b", re.I)


class SteeringError(Exception):
    """Internal policy failure. Callers see the fail-safe decision, not this."""


# --------------------------------------------------------------------------
# redaction
# --------------------------------------------------------------------------

def redact(text):
    """Strip anything that looks like a live credential. Receipts are stored and
    emailed; a secret that reaches a receipt has effectively been published."""
    s = str(text or "")
    s = _SECRETISH.sub("[REDACTED-SECRET]", s)
    s = _CREDENTIAL_WORD.sub(lambda m: m.group(0).split(m.group(0)[-1])[0] + "=[REDACTED]", s)
    return s


def contains_secret(text):
    s = str(text or "")
    return bool(_SECRETISH.search(s) or _CREDENTIAL_WORD.search(s))


# --------------------------------------------------------------------------
# relevance
# --------------------------------------------------------------------------

def legal_relevance(project, text):
    """Is Apparently's legal authority in scope here at all?

    Returns (bool, reason). A project outside the legal domain still reaches
    Apparently when the proposal's own text is unambiguously legal; a project
    inside it always does.
    """
    proj = str(project or "").strip().lower()
    if proj in LEGAL_DOMAIN_PROJECTS:
        return True, "project %r is in the legal domain" % proj
    if _LEGAL_RELEVANT.search(str(text or "")):
        return True, "proposal text raises a regulated-activity term"
    return False, "no legal or domain relevance established"


# --------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------

def _rule(rule_id, authority, decision, risk, rationale, alternatives=()):
    return {"rule": rule_id, "authority": authority, "decision": decision,
            "risk": risk, "rationale": rationale, "alternatives": list(alternatives)}


def _general_risk_findings(gate, text, context, raw_text=None):
    """Illuminati / Foulkon. Applies to every project.

    `text` is redacted; `raw_text` is not. Secret detection must run against the
    raw text — checking the redacted copy finds nothing, by construction.
    """
    out = []
    if _DESTRUCTIVE.search(text):
        out.append(_rule("general.destructive_command", "illuminati", HOLD, "critical",
                         "proposal contains an irreversible destructive command",
                         ["run against a scratch copy", "ask the owner to run it manually"]))
    if contains_secret(text if raw_text is None else raw_text):
        out.append(_rule("general.secret_material", "foulkon", HOLD, "critical",
                         "proposal carries credential-shaped material",
                         ["reference the secret by name via secrets_manager"]))
    if _PROTECTED_BRANCH.search(text):
        out.append(_rule("general.protected_branch", "foulkon", HOLD, "high",
                         "proposal writes to a protected branch",
                         ["push to agent/<slug> and let the merge train decide"]))
    blast = int(context.get("files_changed") or 0)
    if blast >= int(context.get("broad_change_files") or 40):
        out.append(_rule("general.blast_radius", "illuminati", WARN, "medium",
                         "change touches %d files — broad blast radius" % blast,
                         ["split into non-overlapping slices"]))
    if gate == GATE_RELEASE and not context.get("tests_passed", True):
        out.append(_rule("general.release_without_green_tests", "foulkon", HOLD, "high",
                         "release requested while tests are not green",
                         ["fix the failing proof first"]))
    if gate == GATE_INTEGRATION and context.get("unreviewed"):
        out.append(_rule("general.unreviewed_integration", "illuminati", WARN, "medium",
                         "integrating work that has had no independent review",
                         ["route to an independent reviewer family"]))
    return out


def _legal_findings(gate, text, context):
    """Apparently. Only called when legal relevance is established."""
    out = []
    if _LEGAL_POSTURE_CHANGE.search(text):
        out.append(_rule("legal.posture_change", "apparently", HOLD, "high",
                         "change would move the licensing/registration/custody posture",
                         ["keep the feature informational", "obtain owner sign-off"]))
    elif _LEGAL_RELEVANT.search(text):
        out.append(_rule("legal.regulated_topic", "apparently", WARN, "medium",
                         "change touches a regulated topic without clearly changing posture",
                         ["add disclaimers", "have legal_triage classify it"]))
    try:  # fail-soft bridge to the existing narrow legal gate
        import legal_filter
        if legal_filter.requires_owner_approval(text=text, kind=str(context.get("kind") or "")):
            out.append(_rule("legal.owner_gate", "apparently", HOLD, "high",
                             "legal_filter marks this owner-approval-only",
                             ["queue an owner approval card"]))
    except Exception:
        pass
    return out


# --------------------------------------------------------------------------
# evaluation
# --------------------------------------------------------------------------

def _digest(gate, project, text, context):
    blob = "|".join([POLICY_VERSION, str(gate), str(project or ""), redact(text),
                     str(sorted((context or {}).items(), key=lambda kv: str(kv[0])))])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _cacheable(findings):
    """Only low-risk deterministic outcomes are cached. Anything that held, or
    that any rule called high/critical, is re-evaluated every time."""
    return all(f["decision"] == ALLOW or f["risk"] in ("low", "medium") for f in findings) \
        and not any(f["decision"] == HOLD for f in findings)


def evaluate(gate, project=None, text="", context=None, advisory=None, override=None):
    """Return a steering receipt for one gate. Never raises."""
    started = time.time()
    context = dict(context or {})
    if gate not in GATES:
        return _receipt(gate, project, HOLD, [], started,
                        error="unknown gate %r" % (gate,), digest=None)

    try:
        safe_text = redact(text)
        digest = _digest(gate, project, text, context)
        # Cross-project isolation: the project is inside the cache key, so a
        # decision made for one project can never be served to another.
        ckey = (POLICY_VERSION, gate, str(project or ""), digest)
        hit = _CACHE.get(ckey)
        if hit and (time.time() - hit["cached_at"]) < CACHE_TTL_S:
            rec = dict(hit["receipt"])
            rec["cached"] = True
            rec["latency_ms"] = round((time.time() - started) * 1000.0, 3)
            return _apply_override(rec, override)

        findings = _general_risk_findings(gate, safe_text, context, raw_text=str(text or ""))
        relevant, why = legal_relevance(project, safe_text)
        if relevant:
            findings.extend(_legal_findings(gate, safe_text, context))

        rec = _receipt(gate, project, _worst(findings), findings, started, digest=digest)
        rec["legal_relevant"] = relevant
        rec["legal_relevance_reason"] = why
        # Model prose is advisory only — recorded, never load-bearing.
        rec["advisory"] = redact(advisory) if advisory else None
        if _cacheable(findings):
            _CACHE[ckey] = {"cached_at": time.time(), "receipt": dict(rec)}
        return _apply_override(rec, override)
    except Exception as exc:  # safe failure
        fallback = HOLD if gate in FAIL_CLOSED_GATES else WARN
        return _receipt(gate, project, fallback, [], started,
                        error="steering evaluation failed: %s" % (exc,), digest=None)


def _worst(findings):
    return max([f["decision"] for f in findings] or [ALLOW], key=lambda d: _RANK[d])


def _receipt(gate, project, decision, findings, started, error=None, digest=None):
    return {
        "policy_version": POLICY_VERSION,
        "gate": gate,
        "project": project,
        "scope": "project:%s/gate:%s" % (project or "*", gate),
        "decision": decision,
        "risk": max([f["risk"] for f in findings] or ["none"],
                    key=lambda r: ["none", "low", "medium", "high", "critical"].index(r)),
        "findings": findings,
        # Authorities are rule ids only. Model prose can never appear here.
        "policy_authorities": sorted({f["authority"] for f in findings}),
        "rules": [f["rule"] for f in findings],
        "rationale": "; ".join(f["rationale"] for f in findings) or "no steering rule matched",
        "alternatives": sorted({a for f in findings for a in f["alternatives"]}),
        "digest": digest,
        "latency_ms": round((time.time() - started) * 1000.0, 3),
        "cached": False,
        "advisory": None,
        "override": None,
        "error": error,
        "evaluated_at": time.time(),
    }


# --------------------------------------------------------------------------
# override
# --------------------------------------------------------------------------

def _apply_override(rec, override):
    """An override is only honoured when it is attributed and names the exact
    decision digest it is overriding. Unauthorized overrides are recorded and
    ignored — the audit trail must show the attempt either way."""
    if not override:
        return rec
    ov = dict(override)
    actor = str(ov.get("actor") or "").strip()
    reason = str(ov.get("reason") or "").strip()
    authorized = bool(actor) and bool(reason) and ov.get("digest") == rec.get("digest")
    entry = {
        "actor": actor or None,
        "reason": redact(reason) or None,
        "digest_supplied": ov.get("digest"),
        "authorized": authorized,
        "original_decision": rec["decision"],
        "requested_decision": ov.get("decision"),
        "at": time.time(),
    }
    if authorized and ov.get("decision") in _RANK:
        rec["decision"] = ov["decision"]
        entry["applied"] = True
    else:
        entry["applied"] = False
        entry["refused_because"] = (
            "missing actor" if not actor else
            "missing reason" if not reason else
            "digest does not match the decision being overridden"
            if ov.get("digest") != rec.get("digest") else "unknown decision")
    rec["override"] = entry
    return rec


# --------------------------------------------------------------------------
# gate helpers
# --------------------------------------------------------------------------

def is_blocked(receipt):
    return (receipt or {}).get("decision") == HOLD


def enforce(receipt):
    """Raise on HOLD. Callers that must not proceed use this instead of reading
    the dict, so a forgotten check is a crash rather than a silent release."""
    if is_blocked(receipt):
        raise SteeringError("steering HOLD at %s: %s" % (receipt.get("gate"), receipt.get("rationale")))
    return receipt


def clear_cache():
    _CACHE.clear()
