"""PROPRIETARY -- Apparently Inc. Trade Secret. Protected under DTSA (18 U.S.C. 1836).

Proof for the Assumptions Ledger intake gate (rank 8 core). Pure; injected
resolvers; deterministic.
"""
from runner.assumptions_ledger import validate_assumptions

# fixture resolvers
REPO = {("base1", "server/a.ts"): True}
REG = {"test:a"}


def _resolvers(sha_ok=("base1",)):
    return dict(
        sha_resolves=lambda s: s in sha_ok,
        path_exists_at=lambda sha, p: REPO.get((sha, p), False),
        acceptance_registered=lambda r: r in REG,
    )


def test_all_referents_resolve_accepts_to_queued():
    v = validate_assumptions(
        {"target_path": "server/a.ts", "base_sha": "base1", "acceptance_ref": "test:a"},
        **_resolvers())
    assert v.disposition == "accept" and v.target_state == "QUEUED"


def test_absent_target_path_rejects_spec():
    v = validate_assumptions(
        {"target_path": "server/ghost.ts", "base_sha": "base1", "acceptance_ref": "test:a"},
        **_resolvers())
    assert v.disposition == "reject_spec" and v.target_state == "REJECTED_SPEC"
    assert any("absent at base_sha" in r for r in v.reasons)


def test_unresolvable_base_sha_rejects_spec():
    v = validate_assumptions(
        {"target_path": "server/a.ts", "base_sha": "nope", "acceptance_ref": "test:a"},
        **_resolvers())
    assert v.target_state == "REJECTED_SPEC"
    assert any("base_sha" in r for r in v.reasons)


def test_unregistered_acceptance_ref_rejects_spec():
    v = validate_assumptions(
        {"target_path": "server/a.ts", "base_sha": "base1", "acceptance_ref": "test:missing"},
        **_resolvers())
    assert v.target_state == "REJECTED_SPEC"
    assert any("acceptance_ref" in r for r in v.reasons)


def test_unknown_target_goes_to_human_triage_not_queued_or_rejected():
    for tp in ("UNKNOWN", "", None):
        v = validate_assumptions(
            {"target_path": tp, "base_sha": "base1", "acceptance_ref": "test:a"},
            **_resolvers())
        assert v.disposition == "human_triage" and v.target_state == "HUMAN_TRIAGE"


def test_missing_assumptions_object_is_human_triage():
    v = validate_assumptions(None, **_resolvers())
    assert v.target_state == "HUMAN_TRIAGE"
