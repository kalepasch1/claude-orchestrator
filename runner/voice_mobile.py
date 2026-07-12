#!/usr/bin/env python3
"""voice_mobile.py - voice/mobile decision endpoint for founder approvals.

Slice-3: full STT→decision_engine pipeline. The endpoint accepts transcribed text
(speech-to-text handled client-side or by a future STT provider), runs it through
decision_engine.ask/decide, and executes the resulting action. Also exposes a digest
endpoint for quick voice-friendly fleet status.
"""
import datetime, json, os, sys
from http.server import HTTPServer, BaseHTTPRequestHandler
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

PORT = int(os.environ.get("ORCH_VOICE_PORT", "7799"))


def voice_digest():
    """Quick voice-friendly fleet status digest."""
    pending = []
    try:
        pending = db.select("approvals", {
            "select": "id,title,kind", "status": "eq.pending",
            "order": "created_at.desc", "limit": "10"
        }) or []
    except Exception:
        pass

    health_line = "health unavailable"
    try:
        import health
        s = health.summary()
        health_line = f"{s.get('avg_health', '?')}/100 health, {s.get('inbox_count', 0)} items need you"
    except Exception:
        pass

    merged_count = 0
    try:
        since = (datetime.datetime.utcnow() - datetime.timedelta(hours=12)).isoformat()
        merged_count = len(db.select("tasks", {
            "select": "id", "state": "eq.MERGED",
            "updated_at": f"gte.{since}", "limit": "200"
        }) or [])
    except Exception:
        pass

    lines = [f"Fleet: {health_line}. {merged_count} merged (12h)."]
    if pending:
        lines.append(f"{len(pending)} pending decisions.")
        for i, p in enumerate(pending[:5], 1):
            lines.append(f"  {i}: {p.get('title', '?')[:80]}")
    else:
        lines.append("No pending decisions.")
    return {"text": "\n".join(lines), "pending_count": len(pending),
            "pending": pending[:10], "merged_12h": merged_count}


def approve_decision(aid):
    try:
        db.update("approvals", {"id": aid}, {"status": "approved", "updated_by": "voice_mobile"})
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def reject_decision(aid):
    try:
        db.update("approvals", {"id": aid}, {"status": "rejected", "updated_by": "voice_mobile"})
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def submit_directive(text):
    try:
        db.insert("approvals", {
            "title": f"voice: {text[:60]}", "kind": "directive",
            "status": "pending",
            "detail": json.dumps({"source": "voice_mobile", "text": text})
        })
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Slice-3: STT → decision_engine pipeline ──────────────────────────────────

def _classify_intent(text):
    """Classify transcribed voice input into an actionable intent.
    Returns (intent, params) where intent is one of:
      digest, approve, reject, ask, decide, directive, unknown
    """
    t = text.strip().lower()
    if not t:
        return "unknown", {}
    # Simple keyword matching — production would use an LLM classifier
    if any(w in t for w in ("status", "digest", "what's happening", "fleet", "summary")):
        return "digest", {}
    if t.startswith("approve"):
        # "approve 1" or "approve <id>"
        parts = text.strip().split(None, 1)
        return "approve", {"ref": parts[1] if len(parts) > 1 else "1"}
    if t.startswith("reject") or t.startswith("deny"):
        parts = text.strip().split(None, 1)
        return "reject", {"ref": parts[1] if len(parts) > 1 else "1"}
    if t.startswith("ask ") or "question" in t:
        return "ask", {"question": text.strip()}
    if any(t.startswith(w) for w in ("decide ", "go with ", "choose ")):
        return "decide", {"decision_text": text.strip()}
    return "directive", {"text": text.strip()}


def _resolve_pending_ref(ref):
    """Resolve a voice reference like '1' or '2' to an approval ID."""
    try:
        idx = int(ref) - 1
        pending = db.select("approvals", {
            "select": "id", "status": "eq.pending",
            "order": "created_at.desc", "limit": "10"
        }) or []
        if 0 <= idx < len(pending):
            return pending[idx]["id"]
    except (ValueError, TypeError):
        pass
    return ref  # treat as literal ID


def process_voice(transcribed_text):
    """Main STT→decision_engine pipeline entry point.
    Accepts transcribed text, classifies intent, routes through
    decision_engine.ask/decide, and returns the result.
    """
    intent, params = _classify_intent(transcribed_text)

    if intent == "digest":
        return {"intent": "digest", "result": voice_digest()}

    if intent == "approve":
        aid = _resolve_pending_ref(params.get("ref", "1"))
        return {"intent": "approve", "result": approve_decision(aid)}

    if intent == "reject":
        aid = _resolve_pending_ref(params.get("ref", "1"))
        return {"intent": "reject", "result": reject_decision(aid)}

    if intent == "ask":
        try:
            import decision_engine
            # Find the most recent pending approval to ask about
            pending = db.select("approvals", {
                "select": "id,title,kind,detail",
                "status": "eq.pending", "order": "created_at.desc", "limit": "1"
            }) or []
            if pending:
                answer = decision_engine.ask(pending[0]["id"], params["question"])
                return {"intent": "ask", "result": {"ok": True, "answer": answer}}
            return {"intent": "ask", "result": {"ok": False, "error": "no pending decisions to ask about"}}
        except Exception as e:
            return {"intent": "ask", "result": {"ok": False, "error": str(e)}}

    if intent == "decide":
        try:
            import decision_engine
            pending = db.select("approvals", {
                "select": "id", "status": "eq.pending",
                "order": "created_at.desc", "limit": "1"
            }) or []
            if pending:
                result = decision_engine.decide(pending[0]["id"], "directive", params["decision_text"])
                return {"intent": "decide", "result": {"ok": True, "decision": result}}
            return {"intent": "decide", "result": {"ok": False, "error": "no pending decisions"}}
        except Exception as e:
            return {"intent": "decide", "result": {"ok": False, "error": str(e)}}

    # Default: directive
    return {"intent": "directive", "result": submit_directive(params.get("text", transcribed_text))}


# ── HTTP server ──────────────────────────────────────────────────────────────

class VoiceMobileHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, data):
        body = json.dumps(data, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/digest", "/"):
            self._json(200, voice_digest())
        elif self.path == "/health":
            self._json(200, {"ok": True})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        body = {}
        l = int(self.headers.get("Content-Length", 0))
        if l > 0:
            try:
                body = json.loads(self.rfile.read(l))
            except Exception:
                self._json(400, {"error": "bad json"})
                return

        if self.path == "/approve":
            self._json(200, approve_decision(body.get("id")))
        elif self.path == "/reject":
            self._json(200, reject_decision(body.get("id")))
        elif self.path == "/directive":
            self._json(200, submit_directive(body.get("text", "")))
        elif self.path == "/voice":
            # Slice-3: STT pipeline endpoint
            text = body.get("text", "")
            if not text:
                self._json(400, {"error": "missing 'text' (transcribed speech)"})
                return
            self._json(200, process_voice(text))
        else:
            self._json(404, {"error": "not found"})


def serve():
    HTTPServer(("0.0.0.0", PORT), VoiceMobileHandler).serve_forever()


if __name__ == "__main__":
    if "--serve" in sys.argv:
        serve()
    else:
        print(json.dumps(voice_digest(), indent=2, default=str))
