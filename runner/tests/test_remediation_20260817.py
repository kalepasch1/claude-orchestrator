import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest, merge_truth, pipeline_funnel
class _FakeDB:
    def __init__(self, fail_first_with=None):
        self.updates=[]; self.selects=[]; self._f=fail_first_with
    def update(self, t, w, p):
        self.updates.append((t,dict(w),dict(p)))
        if len(self.updates)==1 and self._f is not None: raise Exception(self._f)
    def select(self, t, params):
        self.selects.append(dict(params)); return [{"created_at":"2026-08-17T17:00:00Z"}]
def test_evidence_rejection_parks_as_phantom(monkeypatch):
    fake=_FakeDB("check_violation: artifact_commit abc is already cited by task other")
    monkeypatch.setattr(merge_truth,"db",fake)
    monkeypatch.setattr(merge_truth,"gate_merged_patch", lambda task,patch,**kw: patch)
    out=merge_truth.guarded_task_update({"id":1,"slug":"t1","note":"p","artifact_commit":"abc"},{"state":"MERGED","artifact_commit":"abc"})
    assert out is None and len(fake.updates)==2
    assert fake.updates[1][2]["state"]==merge_truth.PHANTOM_STATE
def test_transient_error_does_not_park(monkeypatch):
    fake=_FakeDB("connection reset by peer")
    monkeypatch.setattr(merge_truth,"db",fake)
    monkeypatch.setattr(merge_truth,"gate_merged_patch", lambda task,patch,**kw: patch)
    out=merge_truth.guarded_task_update({"id":2,"slug":"t2"},{"state":"MERGED","artifact_commit":"z"})
    assert out is None and len(fake.updates)==1
def test_funnel_applies_floor(monkeypatch):
    fake=_FakeDB()
    monkeypatch.setattr(pipeline_funnel,"db",fake)
    pipeline_funnel._oldest("tasks",{"state":"eq.QUEUED"},"created_at")
    p=fake.selects[0]
    assert str(p.get("created_at","")).startswith("gte.") and p.get("limit")=="25"
