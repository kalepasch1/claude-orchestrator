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
    def __init__(self, response_text="YES"):
        self.response_text = response_text

    def run(self, *args, **kwargs):
        return {"text": self.response_text}


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


def test_extract_scope_yes_with_scope_and_ambiguities():
    response = """YES
SCOPE DEFINITION: Add new database migration for user preferences table, update user model, add tests
AMBIGUITIES/CONCERNS:
- Unclear if migration should be reversible
- Missing details on default preferences schema"""

    actionable, scope_def, ambiguities = preflight_gate._extract_scope_and_ambiguities(response)
    assert actionable is True
    assert "user preferences" in scope_def.lower()
    assert len(ambiguities) == 2
    assert "migration should be reversible" in ambiguities[0]


def test_extract_scope_no_with_reason():
    response = """NO: This is purely a discussion task without concrete deliverables"""

    actionable, scope_def, ambiguities = preflight_gate._extract_scope_and_ambiguities(response)
    assert actionable is False


def test_extract_scope_minimal_response():
    response = """YES"""

    actionable, scope_def, ambiguities = preflight_gate._extract_scope_and_ambiguities(response)
    assert actionable is True
    assert scope_def == ""
    assert ambiguities == []


def test_extract_scope_with_bullet_points():
    response = """YES
SCOPE: Update authentication middleware
- Add JWT token validation
- Update rate limiting logic
- Add new error handling
AMBIGUITIES:
- Performance impact unclear
- Backwards compatibility not documented"""

    actionable, scope_def, ambiguities = preflight_gate._extract_scope_and_ambiguities(response)
    assert actionable is True
    assert "authentication" in scope_def.lower()
    assert len(ambiguities) >= 1


def test_preflight_sharpens_no_response_with_scope_info(monkeypatch):
    fake = FakeDB()
    seen = {}
    response_text = """NO: Task is too vague
SCOPE DEFINITION: Not clearly defined
AMBIGUITIES/CONCERNS:
- Missing implementation details
- No clear success criteria"""

    def fields(*args, **kwargs):
        seen.update(kwargs)
        # Pass through the existing_note so we can verify it was enriched
        return {"prompt": "contracted", "note": kwargs.get("existing_note"),
                "model": "fresh-model", "force_coder": "fresh-coder"}

    monkeypatch.setattr(preflight_gate, "db", fake)
    monkeypatch.setattr(preflight_gate, "app_triage", FakeTriage(response_text))
    monkeypatch.setattr(preflight_gate.pipeline_contract, "task_fields", fields)

    preflight_gate.run()

    assert fake.updates
    # Check that existing_note was populated with scope and ambiguity info
    existing_note = seen.get("existing_note", "")
    assert "preflight: sharpened" in existing_note
    assert "scope:" in existing_note or "ambiguities:" in existing_note


def test_preflight_preserves_scope_for_actionable_tasks(monkeypatch):
    fake = FakeDB()
    seen = {}
    response_text = """YES
SCOPE DEFINITION: Add error handling to API route, add unit tests for edge cases
AMBIGUITIES/CONCERNS:
- Should we add logging for debug purposes?"""

    def fields(*args, **kwargs):
        seen.update(kwargs)
        return {"prompt": "contracted", "note": kwargs.get("existing_note"),
                "model": "fresh-model", "force_coder": "fresh-coder"}

    monkeypatch.setattr(preflight_gate, "db", fake)
    monkeypatch.setattr(preflight_gate, "app_triage", FakeTriage(response_text))
    monkeypatch.setattr(preflight_gate.pipeline_contract, "task_fields", fields)

    preflight_gate.run()

    assert fake.updates
    existing_note = seen.get("existing_note", "")
    # For YES responses, we should include scope and ambiguity info
    assert "scope:" in existing_note or "ambiguities:" in existing_note or existing_note == "old auto route"


def test_extract_scope_empty_response():
    response = ""

    actionable, scope_def, ambiguities = preflight_gate._extract_scope_and_ambiguities(response)
    assert actionable is False
    assert scope_def == ""
    assert ambiguities == []


def test_extract_scope_with_many_ambiguities():
    response = """NO
SCOPE DEFINITION: Update user authentication
AMBIGUITIES/CONCERNS:
- Performance impact on login flow
- Backwards compatibility with existing tokens
- Database migration strategy unclear
- Environment variable names not documented
- Testing coverage for OAuth fallback"""

    actionable, scope_def, ambiguities = preflight_gate._extract_scope_and_ambiguities(response)
    assert actionable is False
    assert "authentication" in scope_def.lower()
    # Should capture first 3 ambiguities
    assert len(ambiguities) >= 3
