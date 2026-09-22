"""Verdict cards become steering.

WHY. By 2026-09-21 the expert corps had minted 352 verdict cards — cited, dissented,
with explicit "flips if" conditions — and exactly two modules ever read them. Nothing a
panel concluded reached a coder prompt, a memo or the owner. Insight that steers nothing
is a library, not a strategy.

WHAT. `distill(card)` turns one card into a handful of single-sentence insights, with no
model: the card already separates what must be done (`conditions`), what would change the
answer (`flips_if`), what the record could not establish (`assumptions`) and whether the
law is settled (`unsettled`). Each insight carries its risk band, its lens and the salient
terms that let `brief()` match it to the task a coder is about to do. `sync()` keeps the
table current, `authority_lines()` feeds the internal memos, `owner_lines()` the weekly
report — innovation pathways first, because a strategy that only lists risks is a
compliance function.

Everything here is internal work product under attorney review and says so wherever it
is shown. Never legal advice.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402
import docket_matrix as M  # noqa: E402

TABLE = "steering_insights"
CACHE_TTL_S = int(os.environ.get("ORCH_INSIGHT_TTL_S", "300"))
BRIEF_MAX_CHARS = int(os.environ.get("ORCH_INSIGHT_BRIEF_CHARS", "1200"))
BRIEF_MAX_LINES = int(os.environ.get("ORCH_INSIGHT_BRIEF_LINES", "5"))
MIN_OVERLAP = int(os.environ.get("ORCH_INSIGHT_MIN_OVERLAP", "2"))
ENABLED = os.environ.get("ORCH_EXPERT_INSIGHTS", "true").strip().lower() not in ("0", "false", "no", "off")
HEADER = "## Expert insights (internal, under attorney review — not legal advice)"
KIND_WEIGHT = {"action": 1.0, "gap": 0.9, "tripwire": 0.8, "innovation": 0.85, "opportunity": 0.8, "assumption": 0.5}
_cache = {"at": 0.0, "rows": None}

_ENUM_RE = re.compile(r"(?:(?<=\s)|^)\((?:\d{1,2}|[a-h])\)\s+")
#: An instruction either carries a modal ("must", "never", "do not") or OPENS with a verb.
#: Matching verbs anywhere made "no primary text was opened in this RECORD" an action.
_MODAL_RE = re.compile(r"\b(must|never|do not|don't|should|shall|required to|needs? to|ensure that|within \w+ (?:business )?days?)\b", re.I)
_LEAD_VERBS = ("obtain", "file", "document", "require", "ensure", "log", "retain", "disclose", "confirm", "verify",
               "stop", "cease", "classify", "record", "treat", "supplement", "issue", "adopt", "remove", "add",
               "review", "train", "publish", "notify", "register", "apply", "seek", "limit", "restrict", "map",
               "build", "keep", "use", "act", "escalate", "suspend", "replace", "separate", "maintain", "update")


class _Imperative:
    @staticmethod
    def search(item):
        t = str(item or "").strip()
        first = re.sub(r"^(until then,|meanwhile,|first,|then,|concretely,?|and)\s+", "", t, flags=re.I).split(" ", 1)[0].lower().strip(",:;")
        return bool(_MODAL_RE.search(t)) or first in _LEAD_VERBS


_IMPERATIVE_RE = _Imperative
_GENERIC = set("advice conditioned concretely decision rule under uncertainty because reading until text "
               "confirmed stricter official holding tribunal adversary attack absorbed revised memo prior "
               "position answer first confidence opened located record session provisional material".split())


#: Tokens after which a full stop does NOT end a sentence. Legal prose is made of them, and a
#: splitter that ignores them produced insights reading "Unsettled law — 13(2)(f) and Art."
_ABBREV = ("art", "arts", "sec", "secs", "no", "nos", "v", "vs", "inc", "ltd", "co", "corp", "reg", "regs", "para",
           "paras", "cl", "ch", "pt", "e.g", "i.e", "cf", "u.s", "u.s.c", "c.f.r", "f.r", "n.y", "cal", "stat",
           "ann", "rev", "op", "et al", "approx", "st", "jr", "dr", "mr", "ms")
_UPSIDE_RE = re.compile(r"\b(may lawfully|is permitted|permits|safe harbor|sandbox|no-action|advisory opinion|exempt|"
                        r"exemption|pilot|waiver|advantage|first[- ]mover|can lawfully|lawful route|qualif(?:y|ies) for)\b", re.I)


def _sentences(text) -> list:
    """Sentence split that does not break on legal abbreviations, section numbers or
    single capital initials."""
    text = re.sub(r"\s+", " ", _s(text)).strip()
    out, start = [], 0
    for m in re.finditer(r"[.;!?]\s+(?=[A-Z(\"'“])", text):
        head = text[start:m.start()]
        last = re.split(r"[\s(]", head)[-1].lower().rstrip(".")
        if text[m.start()] == "." and (last in _ABBREV or re.fullmatch(r"[a-z]", last)
                                       or last.endswith("u.s.c") or last.endswith("c.f.r")):
            continue
        out.append(text[start:m.start() + 1].strip())
        start = m.end()
    if text[start:].strip():
        out.append(text[start:].strip())
    return out


def _s(v) -> str:
    return "" if v is None else (v if isinstance(v, str) else json.dumps(v, default=str))


def _items(text, limit=6) -> list:
    """Split '(1) ... (2) ...' / '(a) ...; (b) ...' into items; else imperative sentences."""
    text = re.sub(r"\s+", " ", _s(text)).strip()
    if not text:
        return []
    parts = [p.strip(" ;.—-") for p in _ENUM_RE.split(text) if p and p.strip(" ;.—-")]
    if len(parts) >= 2:
        if not _ENUM_RE.match(text):
            parts = parts[1:]          # the lead-in before the first marker is not an item
    else:
        parts = [s.strip() for s in _sentences(text) if _IMPERATIVE_RE.search(s)]
    return [p for p in parts if len(p) >= 30][:limit]


def _sentence(text, cap=320) -> str:
    text = re.sub(r"\s+", " ", _s(text)).strip(" ;—-")
    if len(text) > cap:
        cut = text[:cap]
        sents = _sentences(cut)
        whole = " ".join(sents[:-1]) if len(sents) > 1 else ""
        text = (whole if len(whole) > cap * 0.5 else cut.rsplit(" ", 1)[0]).rstrip(" ,;:") + ("" if whole and whole.endswith(".") else "…")
    return text[:1].upper() + text[1:] if text else ""


def _terms(*texts, limit=16) -> list:
    words = {}
    for t in texts:
        for w in M.content_words(t):
            if w not in _GENERIC and len(w) >= 5:
                words[w] = words.get(w, 0) + 1
    return [w for w, _ in sorted(words.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))[:limit]]


def _signature(text) -> str:
    return hashlib.sha1(" ".join(sorted(M.content_words(text))).encode("utf-8")).hexdigest()[:20]


def _assumptions(raw) -> list:
    try:
        val = json.loads(raw) if isinstance(raw, str) else raw
        return [str(x) for x in val] if isinstance(val, list) else []
    except Exception:
        return []


def distill(card, docket_row=None) -> list:
    """One verdict card -> insight rows (not yet persisted). Deterministic; no model."""
    card = card or {}
    q = _s(card.get("question"))
    lens, band = M.coords({"question": q, "lens": (docket_row or {}).get("lens"),
                           "risk_band": (docket_row or {}).get("risk_band")})
    try:
        conf = float(card.get("confidence")) if card.get("confidence") is not None else None
    except (TypeError, ValueError):
        conf = None
    base = {"card_id": card.get("id"), "docket_id": card.get("docket_id"), "vertical": card.get("vertical") or "unknown",
            "lens": lens, "risk_band": band, "confidence": conf, "status": "active", "publication_state": "internal"}
    out, seen = [], set()

    def add(kind, text, rationale):
        s = _sentence(text)
        if len(s) < 30:
            return
        sig = _signature(s)
        if sig in seen:
            return
        seen.add(sig)
        out.append({**base, "kind": kind, "insight": s, "rationale": _s(rationale)[:1500],
                    "terms": _terms(q, s), "signature": sig})

    for item in _items(card.get("conditions"), 6):
        # An action is something to DO. "No primary text was opened in this record" is a
        # limit of the record, not an instruction.
        if _IMPERATIVE_RE.search(item):
            add("action", item, card.get("conditions"))
    for item in _items(card.get("flips_if"), 4):
        add("tripwire", "Watch for: " + item, card.get("flips_if"))
    for a in _assumptions(card.get("assumptions"))[:6]:
        m = re.search(r"confidence\s+(0?\.\d+)", a)
        if m and float(m.group(1)) < 0.6:
            add("assumption", "Unverified in the record: " + re.sub(r"^A\d+\.\s*", "", a), a)
            if sum(1 for x in out if x["kind"] == "assumption") >= 2:
                break
    sents = _sentences(card.get("verdict"))
    while sents and re.match(r"^(REVISED|ANSWER|HOLDING)\b[^a-z]{0,80}$|^(REVISED|ANSWER( FIRST)?)\b", sents[0]) and len(sents) > 1:
        sents = sents[1:]          # "REVISED TO ABSORB THE ATTACK." is procedure, not substance
    headline = sents[0] if sents else ""
    if card.get("unsettled") and headline:
        add("gap", "Unsettled law — " + headline, card.get("verdict"))
    # An innovation or opportunity insight must actually describe a way FORWARD. A question
    # asked through that lens on purpose (origin 'matrix') qualifies; a legacy question the
    # keyword classifier merely guessed at qualifies only when the holding itself says so.
    asked_on_purpose = (docket_row or {}).get("origin") == "matrix" and (docket_row or {}).get("lens") == lens
    upside = next((x for x in sents if _UPSIDE_RE.search(x)), "")
    if lens in M.INNOVATION_LENSES and (asked_on_purpose or upside):
        kind = "opportunity" if lens == "opportunity" else "innovation"
        add(kind, ("Opportunity — " if kind == "opportunity" else "Pathway — ") + (upside or headline), card.get("verdict"))
    return out


def _bulk_insert(rows) -> int:
    n = 0
    for i in range(0, len(rows), 100):
        chunk = rows[i:i + 100]
        try:
            res = db._req("POST", "/rest/v1/%s" % TABLE, body=chunk, headers={"Prefer": "return=minimal"})
            n += len(chunk)
            continue
        except Exception as e:
            print(f"steering_insights: bulk insert of {len(chunk)} fell back to per-row: {str(e)[:100]}")
        for r in chunk:
            try:
                db.insert(TABLE, r)
                n += 1
            except Exception as e2:
                print(f"steering_insights: insert failed: {type(e2).__name__}: {str(e2)[:100]}")
    return n


def sync(max_cards=200) -> dict:
    """Distill every card that has no insights yet. Idempotent; never raises."""
    out = {"cards_seen": 0, "cards_distilled": 0, "insights": 0}
    if not ENABLED:
        return out
    try:
        done = {r.get("card_id") for r in (db.select_all(TABLE, {"select": "card_id"}, order="id.asc") or [])}
        cards = db.select("verdict_cards", {
            "select": "id,docket_id,vertical,question,verdict,conditions,flips_if,assumptions,unsettled,confidence,minted_at",
            "order": "minted_at.desc,id.asc", "limit": "1000"}) or []
        out["cards_seen"] = len(cards)
        todo = [c for c in cards if c.get("id") not in done][:max_cards]
        dockets = {}
        ids = [str(c["docket_id"]) for c in todo if c.get("docket_id")]
        for i in range(0, len(ids), 80):
            try:
                for d in db.select("legal_docket", {"select": "id,lens,risk_band,origin", "id": "in.(%s)" % ",".join(ids[i:i + 80]),
                                                    "order": "id.asc", "limit": "200"}) or []:
                    dockets[d["id"]] = d
            except Exception as e:
                print(f"steering_insights: docket tags unavailable: {str(e)[:100]}")
        rows = []
        for c in todo:
            ins = distill(c, dockets.get(c.get("docket_id")))
            if ins:
                out["cards_distilled"] += 1
                rows.extend(ins)
        out["insights"] = _bulk_insert(rows)
        _cache["rows"] = None
    except Exception as e:
        print(f"steering_insights: sync failed: {type(e).__name__}: {str(e)[:120]}")
    return out


def _active() -> list:
    now = time.time()
    if _cache["rows"] is not None and now - _cache["at"] < CACHE_TTL_S:
        return _cache["rows"]
    rows = []
    try:
        rows = db.select(TABLE, {"select": "id,card_id,vertical,kind,lens,risk_band,insight,terms,confidence,created_at",
                                 "status": "eq.active", "order": "created_at.desc,id.asc", "limit": "1000"}) or []
    except Exception as e:
        print(f"steering_insights: read failed: {type(e).__name__}: {str(e)[:100]}")
    _cache["at"], _cache["rows"] = now, rows
    return rows


def _score(row, overlap=0) -> float:
    try:
        conf = float(row.get("confidence")) if row.get("confidence") is not None else 0.7
    except (TypeError, ValueError):
        conf = 0.7
    return (M.RISK_WEIGHT.get(row.get("risk_band"), 0.5) * KIND_WEIGHT.get(row.get("kind"), 0.6)
            * (0.5 + conf / 2.0) * (1.0 + 0.35 * overlap))


def relevant(context, verticals=None, limit=BRIEF_MAX_LINES) -> list:
    """Insights whose salient terms the task text actually shares (>= MIN_OVERLAP distinct
    terms). Relevance is decided by content, never by guessing which project is which
    industry: an irrelevant legal aside in a coder prompt is worse than none."""
    words = M.content_words(context)
    if not words:
        return []
    scored = []
    for r in _active():
        if verticals and r.get("vertical") not in verticals:
            continue
        overlap = len(words & set(r.get("terms") or []))
        if overlap >= MIN_OVERLAP:
            scored.append((_score(r, overlap), overlap, r))
    scored.sort(key=lambda t: (-t[0], -t[1], str(t[2].get("id"))))
    out, seen_cards = [], {}
    for _, _, r in scored:
        if seen_cards.get(r.get("card_id"), 0) >= 2:
            continue                      # at most two lines from one card
        seen_cards[r.get("card_id")] = seen_cards.get(r.get("card_id"), 0) + 1
        out.append(r)
        if len(out) >= limit:
            break
    return out


def brief(project, context="") -> str:
    """The prompt layer: '' unless the task text is about something a panel has ruled on."""
    if not ENABLED or not context:
        return ""
    try:
        rows = relevant(context)
        if not rows:
            return ""
        lines = [HEADER]
        for r in rows:
            lines.append("- [%s · %s] %s (card %s)" % (str(r.get("risk_band") or "").upper(), r.get("kind"),
                                                      r.get("insight"), str(r.get("card_id") or "")[:8]))
        text = "\n".join(lines)
        if len(text) > BRIEF_MAX_CHARS:
            text = text[:BRIEF_MAX_CHARS - 2].rsplit("\n", 1)[0] + "\n…"
        return text + "\n\n"
    except Exception as e:
        print(f"steering_insights: brief failed: {type(e).__name__}: {str(e)[:100]}")
        return ""


def authority_lines(context, vertical="data", limit=3) -> list:
    """Positions the corps has already taken that bear on a memo's subject."""
    try:
        return ["%s (expert card %s, %s)" % (r.get("insight"), str(r.get("card_id") or "")[:8], r.get("kind"))
                for r in relevant(context, verticals=[vertical] if vertical else None, limit=limit)]
    except Exception:
        return []


def owner_lines(days=7, top=3) -> list:
    """Weekly report: innovation pathways first, then the gap count along the risk spectrum."""
    try:
        since = time.time() - days * 86400
        rows = [r for r in _active() if _epoch(r.get("created_at")) >= since]
        if not rows:
            return []
        by_kind, gaps = {}, {}
        for r in rows:
            by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
            if r["kind"] == "gap":
                gaps[r.get("risk_band")] = gaps.get(r.get("risk_band"), 0) + 1
        out = ["Expert insights (%dd): %s" % (days, " · ".join("%d %s" % (n, k) for k, n in sorted(by_kind.items(), key=lambda kv: -kv[1])))]
        if gaps:
            out.append("Regulatory gaps by risk: " + ", ".join("%d %s" % (gaps[b], b) for b in M.RISK_BANDS if gaps.get(b)))
        innov = sorted((r for r in rows if r["kind"] in ("innovation", "opportunity")), key=lambda r: -_score(r))[:top]
        for r in innov:
            out.append("Innovation pathway [%s]: %s" % (r.get("vertical"), str(r.get("insight"))[:220]))
        return out
    except Exception as e:
        print(f"steering_insights: owner_lines failed: {type(e).__name__}: {str(e)[:100]}")
        return []


def _epoch(ts) -> float:
    try:
        from datetime import datetime, timezone
        d = datetime.fromisoformat(str(ts or "").replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except Exception:
        return 0.0


def reset_cache():
    _cache["at"], _cache["rows"] = 0.0, None


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sync"
    if cmd == "brief":
        print(brief("", " ".join(sys.argv[2:])) or "(no relevant insight)")
    elif cmd == "owner":
        print("\n".join(owner_lines()) or "(none)")
    else:
        print(json.dumps(sync(), indent=2))
