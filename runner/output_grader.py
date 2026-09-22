"""Every model output gets a grade, and every call gets a name.

WHY. On 2026-09-21, 1,000 consecutive local-model rows in app_operations carried
quality_score = NULL and verdict = NULL (the columns had existed all along), 97% were
task_class 'unknown' under operation 'completion', and 96% were zero-latency cache
replays. Nobody could say which caller was producing value and which was producing
"Here are 5 specific, docketable questions…" with "[GC's Name]" left in the memo. The memo
layer of Database Steering had been returning EMPTY text for a week and the telemetry
said ok=true.

WHAT. `grade(text, ...)` is deterministic and costs microseconds: emptiness, unfilled
placeholders, chat boilerplate, refusals, malformed JSON when JSON was asked for,
truncation, internal repetition, and rubber-stamping (the same structured verdict over
and over from one caller). `caller()` names the module that asked. model_gateway records
both on every row. `audit()` and `audit_posts()` turn that into an answer to "are the
local models' outputs, and what they post to Supabase, actually worth anything?".

Grading never blocks or alters a completion. It measures.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PLACEHOLDER_RE = re.compile(r"\[(?:GC|Your|Company|Client|Name|Date|Insert|Firm|Recipient|Sender|Address|Title)[^\]]{0,40}\]"
                            r"|\[[A-Z][A-Za-z' ]{1,30}(?:Name|Date|Here)\]|<(?:name|company|date|insert)[^>]*>"
                            r"|\bTBD\b|lorem ipsum|XXX+", re.I)
BOILERPLATE_RE = re.compile(r"^\s*(here (are|is)\b|sure[,!.]|certainly[,!.]|of course[,!.]|great question|"
                            r"i'?d be happy to|below (are|is)\b|as requested[,:])", re.I)
REFUSAL_RE = re.compile(r"\b(as an ai|i (?:cannot|can't|am unable to|won't) (?:help|assist|provide|comply)|"
                        r"i'm sorry, but)\b", re.I)
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)
PENALTY = {"empty": 1.0, "refusal": 0.8, "malformed_json": 0.6, "placeholder": 0.5, "rubber_stamp": 0.4,
           "repetition": 0.4, "truncated": 0.3, "boilerplate": 0.2, "too_short": 0.3}
#: Worst first: the verdict recorded is the most serious flag raised.
ORDER = ("empty", "refusal", "malformed_json", "placeholder", "rubber_stamp", "repetition", "truncated",
         "too_short", "boilerplate")
_recent = {}
_lock = threading.Lock()
RUBBER_WINDOW, RUBBER_REPEATS = 20, 5


def _wants_json(prompt, text) -> bool:
    p = str(prompt or "")[-1500:].lower()
    t = str(text or "").lstrip()
    return "json" in p or t.startswith("{") or t.startswith("[") or t.startswith("```json")


def _json_payload(text):
    t = _FENCE_RE.sub("", str(text or "").strip())
    m = re.search(r"(\{.*\}|\[.*\])", t, re.S)
    if not m:
        raise ValueError("no JSON value")
    return json.loads(m.group(1))


def _rubber_key(payload):
    """The part of a structured verdict that should VARY between inputs."""
    if isinstance(payload, dict):
        keys = [k for k in ("verdict", "score", "conviction", "rating", "decision", "grade") if k in payload]
        if len(keys) >= 2:
            return tuple((k, json.dumps(payload[k], sort_keys=True, default=str)) for k in keys)
    return None


def grade(text, operation="", task_class="", prompt="") -> dict:
    """{"score": 0..1, "verdict": "ok" | <worst flag>, "flags": [...]}. Never raises."""
    flags = []
    try:
        t = str(text or "")
        body = t.strip()
        if not body:
            return {"score": 0.0, "verdict": "empty", "flags": ["empty"]}
        if REFUSAL_RE.search(body[:400]):
            flags.append("refusal")
        if PLACEHOLDER_RE.search(body):
            flags.append("placeholder")
        if BOILERPLATE_RE.search(body):
            flags.append("boilerplate")
        payload = None
        if _wants_json(prompt, body):
            try:
                payload = _json_payload(body)
            except Exception:
                flags.append("malformed_json")
        short_ok = str(task_class or "").lower() in ("rating", "mechanical", "classification", "triage")
        if len(body) < 40 and len(str(prompt or "")) > 1500 and not short_ok and payload is None:
            flags.append("too_short")
        if len(body) > 400 and body[-1] not in ".!?)]}\"'`*:" and payload is None:
            flags.append("truncated")
        lines = [ln.strip().lower() for ln in body.splitlines() if len(ln.strip()) > 25]
        if len(lines) >= 6 and (len(lines) - len(set(lines))) / float(len(lines)) > 0.3:
            flags.append("repetition")
        key = _rubber_key(payload)
        if key is not None:
            with _lock:
                ring = _recent.setdefault(str(operation or "completion"), deque(maxlen=RUBBER_WINDOW))
                ring.append(key)
                if sum(1 for k in ring if k == key) >= RUBBER_REPEATS:
                    flags.append("rubber_stamp")
        score = 1.0
        for f in flags:
            score -= PENALTY.get(f, 0.2)
        verdict = next((f for f in ORDER if f in flags), "ok")
        return {"score": round(max(0.0, score), 3), "verdict": verdict, "flags": flags}
    except Exception as e:
        return {"score": None, "verdict": "ungraded", "flags": ["grader_error:%s" % type(e).__name__]}


_SKIP = ("model_gateway", "output_grader", "prompt_result_cache", "model_policy", "threading", "concurrent")


def caller(default="unknown") -> str:
    """The runner module that asked for the completion (first frame outside the gateway)."""
    try:
        f = sys._getframe(1)
        while f is not None:
            name = os.path.splitext(os.path.basename(f.f_code.co_filename))[0]
            if name and not name.startswith("<") and not any(name.startswith(s) for s in _SKIP):
                return name[:48]
            f = f.f_back
    except Exception:
        return default      # attribution is best-effort: an unnamed call still gets graded
    return default


def audit(limit=1000, provider="local") -> dict:
    """What the graded telemetry says, per caller. Reads app_operations; writes nothing."""
    import db
    rows = db.select("app_operations", {"select": "operation,task_class,model,latency_ms,quality_score,verdict,ok",
                                        "provider": "eq.%s" % provider, "order": "created_at.desc",
                                        "limit": str(limit)}) or []
    out = {"rows": len(rows), "graded": 0, "cache_replays": 0, "callers": {}}
    for r in rows:
        c = out["callers"].setdefault(r.get("operation") or "completion",
                                      {"calls": 0, "fresh": 0, "graded": 0, "mean_quality": None, "verdicts": {}, "_sum": 0.0})
        c["calls"] += 1
        fresh = bool(r.get("latency_ms"))
        c["fresh"] += 1 if fresh else 0
        out["cache_replays"] += 0 if fresh else 1
        if r.get("quality_score") is not None:
            out["graded"] += 1
            c["graded"] += 1
            c["_sum"] += float(r["quality_score"])
        v = str(r.get("verdict") or "ungraded").replace("cached:", "")
        c["verdicts"][v] = c["verdicts"].get(v, 0) + 1
    for c in out["callers"].values():
        c["mean_quality"] = round(c.pop("_sum") / c["graded"], 3) if c["graded"] else None
    return out


def audit_posts(sample=400) -> dict:
    """Grade what was actually POSTED to Supabase by the expert pipeline: docket questions,
    verdict-card positions and internal memo bodies. Reads only."""
    import db
    import docket_matrix
    out = {}
    try:
        dk = db.select("legal_docket", {"select": "question,origin", "order": "created_at.desc,id.asc", "limit": str(sample)}) or []
        reasons = {}
        for d in dk:
            ok, why = docket_matrix.grade_question(d.get("question"), [])
            reasons[why or "ok"] = reasons.get(why or "ok", 0) + 1
        out["legal_docket"] = {"sampled": len(dk), "verdicts": reasons}
    except Exception as e:
        out["legal_docket"] = {"error": "%s: %s" % (type(e).__name__, str(e)[:100])}
    for table, col, order in (("verdict_cards", "position", "minted_at.desc,id.asc"),
                              ("legal_memo_drafts", "body", "updated_at.desc,id.asc")):
        try:
            rows = db.select(table, {"select": col, "order": order, "limit": str(sample)}) or []
            verdicts, total = {}, 0.0
            for r in rows:
                g = grade(r.get(col), operation="audit:%s" % table)
                verdicts[g["verdict"]] = verdicts.get(g["verdict"], 0) + 1
                total += g["score"] or 0.0
            out[table] = {"sampled": len(rows), "mean_quality": round(total / len(rows), 3) if rows else None,
                          "verdicts": verdicts}
        except Exception as e:
            out[table] = {"error": "%s: %s" % (type(e).__name__, str(e)[:100])}
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "audit"
    print(json.dumps(audit_posts() if cmd == "posts" else audit(), indent=2))
