import os
import sys


RUNNER = os.path.dirname(os.path.dirname(__file__))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import preflight_gate


class FakeDB:
    def __init__(self):
        self.task_query = None
        self.updates = []

    def select(self, table, params):
        if table == "projects":
            return [{"id": "p1", "name": "demo"}]
        self.task_query = params
        return [{"id": "t1", "slug": "ordinary-build", "prompt": "Implement code.",
                 "kind": "build", "material": False, "note": "old auto route",
                 "model": "stale-model", "force_coder": "stale-coder", "project_id": "p1"}]

    def update(self, table, where, patch):
        self.updates.append((table, where, patch))


class FakeTriage:
    @staticmethod
    def run(*args, **kwargs):
        return {"text": "YES"}


def test_preflight_rotates_queue_and_refreshes_ordinary_routes(monkeypatch):
    fake = FakeDB()
    seen = {}

    def fields(*args, **kwargs):
        seen.update(kwargs)
        return {"prompt": "contracted", "note": "pipeline:preflight-gate",
                "model": "fresh-model", "force_coder": "fresh-coder"}

    monkeypatch.setattr(preflight_gate, "db", fake)
    monkeypatch.setattr(preflight_gate, "app_triage", FakeTriage())
    monkeypatch.setattr(preflight_gate.pipeline_contract, "task_fields", fields)

    preflight_gate.run()

    assert fake.task_query["order"] == "updated_at.asc"
    assert seen["model"] is None
    assert seen["force_coder"] is None
    assert fake.updates[0][2]["force_coder"] == "fresh-coder"
