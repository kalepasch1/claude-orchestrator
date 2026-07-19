import json
import os
import sys


RUNNER = os.path.dirname(os.path.dirname(__file__))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import cowork_stage


class FakeDB:
    def __init__(self):
        self.inserted = []

    def select(self, table, params):
        if table == "projects":
            return [{"id": "p1", "name": "demo"}]
        return []

    def insert(self, table, row):
        self.inserted.append((table, row))
        return [row]


def test_cowork_stage_persists_shared_triage_route(monkeypatch, tmp_path):
    backlog = tmp_path / "backlog.json"
    backlog.write_text(json.dumps({
        "projects": {"demo": {"repo_path": str(tmp_path), "default_base": "main"}},
        "tasks": [{"project": "demo", "slug": "contracts-demo", "kind": "build",
                   "prompt": "Implement the contract and tests.", "deps": []}],
    }))
    fake = FakeDB()
    monkeypatch.setitem(sys.modules, "db", fake)
    monkeypatch.setattr(cowork_stage.pipeline_contract, "task_fields", lambda *a, **k: {
        "prompt": "CONTRACTED PROMPT", "note": "pipeline:cowork-stage",
        "model": "gpt-5.4-mini", "force_coder": "swarm:openai",
    })

    cowork_stage.stage(str(backlog), commit=True)

    task = [row for table, row in fake.inserted if table == "tasks"][0]
    assert task["prompt"] == "CONTRACTED PROMPT"
    assert task["force_coder"] == "swarm:openai"
    assert task["model"] == "gpt-5.4-mini"
    assert "pipeline:cowork-stage" in task["note"]
