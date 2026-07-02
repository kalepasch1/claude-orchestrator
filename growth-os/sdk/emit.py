"""Growth OS event emitter (Python apps / runner / scripts).

Usage:
    from emit import growth
    growth("racefeed").track("activate", segment="racefeed/free-to-play/genz", actor_id=user_id)
    growth("apparently").track("revenue", value=5000, dedup_key=order_id)

PRIVACY: actor_id is hashed locally; raw ids never leave the process. Payload is metadata only.
Fire-and-forget: failures are swallowed so telemetry never breaks the app.
"""
import hashlib
import json
import os
import threading
import urllib.request

_URL = os.environ.get("ORCH_SUPABASE_URL") or os.environ.get("GROWTH_OS_URL", "")
_ANON = os.environ.get("ORCH_SUPABASE_ANON_KEY") or os.environ.get("GROWTH_OS_ANON", "")
_SALT = os.environ.get("GROWTH_ACTOR_SALT", "rotate-me")


def _hash_actor(app: str, actor_id):
    if not actor_id:
        return None
    return hashlib.sha256(f"{app}:{actor_id}:{_SALT}".encode()).hexdigest()


def _post(payload):
    if not _URL or not _ANON:
        return
    try:
        req = urllib.request.Request(
            f"{_URL}/rest/v1/rpc/emit_growth_event",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "apikey": _ANON,
                "Authorization": f"Bearer {_ANON}",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2.5).read()
    except Exception:
        pass  # telemetry must never affect the app


class _App:
    def __init__(self, app):
        self.app = app

    def track(self, event_type, segment=None, channel=None, source=None,
              value=0, actor_id=None, props=None, dedup_key=None, blocking=False):
        payload = {
            "p_app": self.app,
            "p_event_type": event_type,
            "p_segment": segment,
            "p_channel": channel,
            "p_source": source,
            "p_actor_hash": _hash_actor(self.app, actor_id),
            "p_value": value or 0,
            "p_props": props or {},
            "p_dedup_key": dedup_key,
        }
        if blocking:
            _post(payload)
        else:
            threading.Thread(target=_post, args=(payload,), daemon=True).start()


def growth(app: str) -> _App:
    return _App(app)
