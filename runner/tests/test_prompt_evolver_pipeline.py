"""End-to-end proof that the UCB1 prompt bandit is wired into the run pipeline.

Every collaborator is mocked except the two production seams under test:
runner._prompt_evolver() (selection) and runner.record() (settlement). The test
drives several simulated runs and asserts the bandit both accumulates real
performance data and shifts its choice toward the arm that delivers.
"""
import importlib.util
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import prompt_evolver  # noqa: E402


@pytest.fixture(scope="module")
def runner_module():
    """Load runner.py by path.

    `import runner` is ambiguous now that runner/ is also a package: under
    full-suite collection it resolves to runner/__init__.py, while an isolated
    invocation may resolve to runner/runner.py.
    """
    module_name = "runner_entrypoint_prompt_evolver_pipeline"
    runner_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner.py")
    spec = importlib.util.spec_from_file_location(module_name, runner_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(module_name, None)


class FakeTemplateStore:
    """In-memory stand-in for the `prompt_templates` table."""

    def __init__(self):
        self.rows = []

    def select(self, table, filters=None):
        if table != "prompt_templates":
            return []
        rows = self.rows
        kind_filter = (filters or {}).get("kind")
        if kind_filter:
            wanted = kind_filter.split("eq.", 1)[-1]
            rows = [r for r in rows if r["kind"] == wanted]
        return [dict(r) for r in rows]

    def insert(self, table, row, resolution=None):
        if table != "prompt_templates":
            return
        # `merge-duplicates` upserts on (kind, template_id) — accumulate, don't append.
        for existing in self.rows:
            if (existing["kind"], existing["template_id"]) == (row["kind"], row["template_id"]):
                existing["total_reward"] += row["total_reward"]
                existing["n_trials"] += row["n_trials"]
                return
        self.rows.append(dict(row))

    def trials(self, template_id):
        return sum(r["n_trials"] for r in self.rows if r["template_id"] == template_id)

    def reward(self, template_id):
        return sum(r["total_reward"] for r in self.rows if r["template_id"] == template_id)


@pytest.fixture
def store(monkeypatch, runner_module):
    fake = FakeTemplateStore()
    prompt_evolver.invalidate()

    monkeypatch.setattr(prompt_evolver.db, "select", fake.select)
    monkeypatch.setattr(prompt_evolver.db, "insert", fake.insert)

    # record()'s other collaborators are irrelevant here — silence them so a
    # failure in this file can only come from the bandit wiring.
    monkeypatch.setattr(runner_module.db, "insert", lambda *a, **k: None)
    monkeypatch.setattr(runner_module.mesh_optimizer, "settle", lambda *a, **k: None)
    monkeypatch.setattr(runner_module.candidate_shared, "harvest", lambda *a, **k: None)

    yield fake
    prompt_evolver.invalidate()


def _run_once(runner_module, kind, base_prompt, integrated, artifact_for=None):
    """Simulate one pipeline pass: select an arm, run, settle the outcome.

    `artifact_for` maps the arm the bandit actually chose to the artifact sha that
    run produced, so a test can make one specific arm the delivering one.
    """
    evolved, template_id = runner_module._prompt_evolver().select_template(kind, base_prompt)
    task = {
        "id": "task-1",
        "slug": "wire-bandit",
        "_prompt_template_id": template_id,
        "artifact_commit": artifact_for(template_id) if artifact_for else "",
    }
    runner_module.record(
        task, "beethoven", task["slug"], kind, "test-model", {"name": "acct"},
        attempt=1, tests_ok=integrated, integrated=integrated, out="",
        t0=time.time(), cost={"input_tokens": 0, "output_tokens": 0, "usd": 0.0},
    )
    return evolved, template_id


def test_selection_seam_resolves_the_real_evolver(runner_module):
    assert runner_module._prompt_evolver() is prompt_evolver


def test_non_base_arm_wraps_the_enriched_prompt(store):
    evolved, template_id = prompt_evolver.select_template("code_gen", "BASE BODY")
    if template_id == "base":
        assert evolved == "BASE BODY"
    else:
        assert evolved.startswith(f"[template:{template_id}]")
        assert "BASE BODY" in evolved


def test_record_feeds_performance_data_back_to_the_bandit(store, runner_module):
    _, template_id = _run_once(runner_module, "code_gen", "prompt", integrated=True,
                               artifact_for=lambda _tid: "abc123")

    assert store.trials(template_id) == 1, "record() must settle the selected arm"
    # First-try integration backed by a real artifact earns partial credit.
    assert store.reward(template_id) == pytest.approx(0.5)


def test_unbacked_merge_claim_earns_no_reward(store, runner_module):
    """Reward hygiene: a merge with no artifact sha must not move the bandit."""
    _, template_id = _run_once(runner_module, "code_gen", "prompt", integrated=True)

    assert store.trials(template_id) == 1
    assert store.reward(template_id) == pytest.approx(0.0)


def test_record_is_a_noop_when_no_arm_was_selected(store, runner_module):
    runner_module.record(
        {"id": "task-2", "slug": "no-arm"}, "beethoven", "no-arm", "code_gen",
        "test-model", {"name": "acct"}, attempt=1, tests_ok=True, integrated=True,
        out="", t0=time.time(), cost={"input_tokens": 0, "output_tokens": 0, "usd": 0.0},
    )
    assert store.rows == []


def test_prompt_evolves_across_runs(store, runner_module):
    """Over repeated runs the bandit explores every arm, then favors the winner."""
    winner = "chain_of_thought"
    seen = []

    # Explore: settle one full pipeline pass per arm. Only `winner` ships a real
    # artifact, so only `winner` earns reward.
    for _ in prompt_evolver.TEMPLATE_IDS:
        _, template_id = _run_once(
            runner_module, "code_gen", "prompt", integrated=True,
            artifact_for=lambda tid: "abc123" if tid == winner else "",
        )
        seen.append(template_id)

    assert set(seen) == set(prompt_evolver.TEMPLATE_IDS), (
        "every arm must be reachable — an unseeded arm can never be selected"
    )
    assert all(store.trials(tid) >= 1 for tid in prompt_evolver.TEMPLATE_IDS)

    # Exploit: keep running until every arm is well sampled, with only `winner`
    # delivering. Sampling the losers too is what shrinks their UCB1 exploration
    # bonus — starving them would keep them at +inf and the bandit would never
    # settle, which is the behavior this test is guarding.
    for _ in range(30):
        for template_id in prompt_evolver.TEMPLATE_IDS:
            prompt_evolver.record_outcome(
                "code_gen", template_id, merged_first_try=True,
                artifact_commit="abc123" if template_id == winner else "")

    evolved, chosen = prompt_evolver.select_template("code_gen", "prompt")
    assert store.reward(winner) > store.reward("base")
    assert chosen == winner, f"bandit should have evolved toward {winner}, chose {chosen}"
    assert evolved.startswith(f"[template:{winner}]")
