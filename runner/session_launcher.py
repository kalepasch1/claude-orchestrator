"""
session_launcher.py — launch and track orchestrator sessions via HTTP.

Provides a simple API to start/stop/list orchestrator sessions. Each session
runs a claim-build-push loop and reports its status via the web console.
"""
import os, sys, time, json, logging, uuid, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

log = logging.getLogger(__name__)

# In-memory session registry
_sessions = {}
_lock = threading.Lock()


class Session:
    """Represents an orchestrator execution session."""

    def __init__(self, session_id=None, account=None, max_tasks=50):
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.account = account or f"session-{self.session_id}"
        self.max_tasks = max_tasks
        self.started_at = time.time()
        self.stopped_at = None
        self.tasks_claimed = 0
        self.tasks_done = 0
        self.tasks_failed = 0
        self.status = "idle"
        self.last_error = None

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "account": self.account,
            "status": self.status,
            "tasks_claimed": self.tasks_claimed,
            "tasks_done": self.tasks_done,
            "tasks_failed": self.tasks_failed,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "uptime_s": round(time.time() - self.started_at, 1),
            "last_error": self.last_error,
        }

    def start(self):
        self.status = "running"
        log.info("session_launcher: started session %s", self.session_id)

    def stop(self):
        self.status = "stopped"
        self.stopped_at = time.time()
        log.info("session_launcher: stopped session %s", self.session_id)

    def record_claim(self, count=1):
        self.tasks_claimed += count

    def record_done(self, count=1):
        self.tasks_done += count

    def record_failure(self, error=None):
        self.tasks_failed += 1
        self.last_error = str(error)[:200] if error else None


def create_session(**kwargs):
    """Create and register a new session."""
    session = Session(**kwargs)
    with _lock:
        _sessions[session.session_id] = session
    return session


def get_session(session_id):
    """Get a session by ID."""
    return _sessions.get(session_id)


def list_sessions():
    """List all sessions."""
    with _lock:
        return [s.to_dict() for s in _sessions.values()]


def stop_session(session_id):
    """Stop a session."""
    session = _sessions.get(session_id)
    if session:
        session.stop()
        return True
    return False


def cleanup_old_sessions(max_age_hours=24):
    """Remove sessions older than max_age_hours."""
    cutoff = time.time() - max_age_hours * 3600
    with _lock:
        to_remove = [sid for sid, s in _sessions.items()
                     if s.stopped_at and s.stopped_at < cutoff]
        for sid in to_remove:
            del _sessions[sid]
    return len(to_remove)


if __name__ == "__main__":
    s = create_session()
    s.start()
    s.record_claim(5)
    s.record_done(3)
    s.record_failure("test error")
    print(json.dumps(list_sessions(), indent=2, default=str))
