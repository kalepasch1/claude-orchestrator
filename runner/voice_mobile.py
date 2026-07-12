#!/usr/bin/env python3
"""voice_mobile.py - voice/mobile decision endpoint for founder approvals."""
import datetime, json, os, sys
from http.server import HTTPServer, BaseHTTPRequestHandler
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
PORT = int(os.environ.get("ORCH_VOICE_PORT", "7799"))
def voice_digest():
    pending = []
    try: pending = db.select("approvals", {"select": "id,title,kind", "status": "eq.pending", "order": "created_at.desc", "limit": "10"}) or []
    except Exception: pass
    health_line = "health unavailable"
    try:
        import health; s = health.summary()
        health_line = f"{s.get('avg_health', '?')}/100 health, {s.get('inbox_count', 0)} items need you"
    except Exception: pass
    merged_count = 0
    try:
        since = (datetime.datetime.utcnow() - datetime.timedelta(hours=12)).isoformat()
        merged_count = len(db.select("tasks", {"select": "id", "state": "eq.MERGED", "updated_at": f"gte.{since}", "limit": "200"}) or [])
    except Exception: pass
    lines = [f"Fleet: {health_line}. {merged_count} merged (12h)."]
    if pending:
        lines.append(f"{len(pending)} pending decisions.")
        for i, p in enumerate(pending[:5], 1): lines.append(f"  {i}: {p.get('title', '?')[:80]}")
    else: lines.append("No pending decisions.")
    return {"text": "\n".join(lines), "pending_count": len(pending), "pending": pending[:10], "merged_12h": merged_count}
def approve_decision(aid):
    try: db.update("approvals", {"id": aid}, {"status": "approved", "updated_by": "voice_mobile"}); return {"ok": True}
    except Exception as e: return {"ok": False, "error": str(e)}
def reject_decision(aid):
    try: db.update("approvals", {"id": aid}, {"status": "rejected", "updated_by": "voice_mobile"}); return {"ok": True}
    except Exception as e: return {"ok": False, "error": str(e)}
def submit_directive(text):
    try: db.insert("approvals", {"title": f"voice: {text[:60]}", "kind": "directive", "status": "pending", "detail": json.dumps({"source": "voice_mobile", "text": text})}); return {"ok": True}
    except Exception as e: return {"ok": False, "error": str(e)}
class VoiceMobileHandler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _json(self, code, data):
        body = json.dumps(data, default=str).encode(); self.send_response(code)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path in ("/digest", "/"): self._json(200, voice_digest())
        elif self.path == "/health": self._json(200, {"ok": True})
        else: self._json(404, {"error": "not found"})
    def do_POST(self):
        body = {}
        l = int(self.headers.get("Content-Length", 0))
        if l > 0:
            try: body = json.loads(self.rfile.read(l))
            except Exception: self._json(400, {"error": "bad json"}); return
        if self.path == "/approve": self._json(200, approve_decision(body.get("id")))
        elif self.path == "/reject": self._json(200, reject_decision(body.get("id")))
        elif self.path == "/directive": self._json(200, submit_directive(body.get("text", "")))
        else: self._json(404, {"error": "not found"})
def serve():
    HTTPServer(("0.0.0.0", PORT), VoiceMobileHandler).serve_forever()
if __name__ == "__main__":
    if "--serve" in sys.argv: serve()
    else: print(json.dumps(voice_digest(), indent=2, default=str))
