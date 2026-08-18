import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ev_scheduler as ev

class _FakeDB:
    def select(self, table, params=None): return []   # no projects, no revenue, etc.

def _setup(monkeypatch, self_heat, user_heat):
    monkeypatch.setattr(ev, "db", _FakeDB())
    monkeypatch.setattr(ev, "load_ctx", lambda: {})
    monkeypatch.setattr(ev, "queued_tasks", lambda limit=None: [
        {"id": "self", "project": "orchestrator", "kind": "improvement", "created_at": "2020-01-01"},
        {"id": "user", "project": "apparently", "kind": "build", "created_at": "2026-01-01"},
    ])
    monkeypatch.setattr(ev, "thermal_score", lambda t, ctx: self_heat if t["id"] == "self" else user_heat)

def test_user_work_first_even_when_self_improve_scores_higher(monkeypatch):
    monkeypatch.setenv("ORCH_USER_TASKS_FIRST", "1")
    _setup(monkeypatch, self_heat=100.0, user_heat=0.1)   # self-improve scores 1000x higher
    order = ev.rank_queue()
    assert order.index("user") < order.index("self"), order   # user still claimed first

def test_legacy_pure_ev_when_opted_out(monkeypatch):
    monkeypatch.setenv("ORCH_USER_TASKS_FIRST", "0")
    _setup(monkeypatch, self_heat=100.0, user_heat=0.1)
    order = ev.rank_queue()
    assert order.index("self") < order.index("user"), order   # legacy: higher EV first
