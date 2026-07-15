import datetime, os, subprocess, sys
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNNER))

import activation_proof, actuator_leases, flow_promotion, patch_fabric, product_metrics


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def test_conflict_free_branchless_batch_materializes_after_proof(tmp_path, monkeypatch):
    repo = tmp_path / "repo"; repo.mkdir()
    _git(repo, "init"); _git(repo, "config", "user.email", "test@example.com"); _git(repo, "config", "user.name", "Test")
    (repo / "a.txt").write_text("old-a\n"); (repo / "b.txt").write_text("old-b\n")
    _git(repo, "add", "."); _git(repo, "commit", "-m", "base")
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "runtime"))
    items = [
        {"task": {"id": "1", "slug": "one"}, "model_output": "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old-a\n+new-a\n"},
        {"task": {"id": "2", "slug": "two"}, "model_output": "--- a/b.txt\n+++ b/b.txt\n@@ -1 +1 @@\n-old-b\n+new-b\n"},
    ]
    result = patch_fabric.materialize_batch(items, str(repo), "HEAD", "test -f a.txt && test -f b.txt")
    assert result["ok"] and result["batch"] and result["patches"] == 2
    assert _git(repo, "show", f"{result['commit']}:a.txt") == "new-a"
    assert _git(repo, "show-ref", "--verify", f"refs/heads/{result['branch']}")


def test_conflicting_patches_are_never_composed():
    one = {"model_output": "--- a/x\n+++ b/x\n@@ -0,0 +1 @@\n+a\n"}
    two = {"model_output": "--- a/x\n+++ b/x\n@@ -0,0 +1 @@\n+b\n"}
    assert [len(g) for g in patch_fabric.conflict_free_groups([one, two])] == [1, 1]


def test_promotion_requires_samples_and_500x_lower_bound():
    start = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    rows=[]
    for i in range(20):
        at=(start+datetime.timedelta(hours=i)).isoformat()
        rows += [{"variant":"secondary", "value":1000, "observed_at":at},
                 {"variant":"cowork", "value":1, "observed_at":at}]
    assert flow_promotion.evaluate(rows)["promoted"] is True
    assert flow_promotion.evaluate(rows[:10])["promoted"] is False


def test_actuator_lease_fallback_prevents_other_owner(monkeypatch):
    monkeypatch.setattr(actuator_leases.db, "rpc", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    actuator_leases._local.clear()
    assert actuator_leases.acquire("job", 60, "one")["acquired"] is True
    assert actuator_leases.acquire("job", 60, "two")["acquired"] is False


def test_activation_proof_outcome_proves_prior_stages(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path))
    monkeypatch.setattr(activation_proof.db, "insert", lambda *a, **k: None)
    activation_proof.record("secondary_flow", "outcome", True)
    report=activation_proof.audit()
    assert report["capabilities"]["secondary_flow"] == {"invocation":1,"effect":1,"outcome":1}


def test_holdout_assignment_is_stable():
    assert product_metrics.assignment("user", "experiment") == product_metrics.assignment("user", "experiment")
