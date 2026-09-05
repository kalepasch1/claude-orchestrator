"""A task that skipped its verifier must not look like one that passed it.

ROLE_SPECS already names the nine mesh roles and route_role() already picks a model for
each. What was missing is the RECEIPT — a record that a role actually acted. Without it,
"every coding task has explicit role receipts" is an intention rather than a checkable
property, and a task that silently skipped its verifier or red_team is indistinguishable
from one that passed both.

Kept pure so it can be asserted anywhere without a database and without a parallel UI, per
the slice's own constraint.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_market as am  # noqa: E402


def _full():
    return [am.receipt(r, model="m", provider="local") for r in am.REQUIRED_ROLES]


class TestRolesAreTheExistingOnes:
    def test_every_required_role_is_a_declared_mesh_role(self):
        """No parallel vocabulary: the receipt check uses ROLE_SPECS, not its own list."""
        for role in am.REQUIRED_ROLES:
            assert role in am.ROLE_SPECS

    def test_the_nine_mesh_roles_are_all_present(self):
        assert set(am.ROLE_SPECS) >= {
            "scout", "planner", "drafter", "verifier", "red_team",
            "judge", "repairer", "treasurer", "privacy_officer"}

    def test_the_required_set_is_narrower_than_all_nine(self):
        """Requiring situational roles on every task makes the gate permanently red."""
        assert set(am.REQUIRED_ROLES) < set(am.ROLE_SPECS)
        assert "treasurer" not in am.REQUIRED_ROLES
        assert "privacy_officer" not in am.REQUIRED_ROLES

    def test_the_required_set_is_fleet_tunable(self):
        """ORCH_-prefixed per CLAUDE.md so it can be tightened without a code change."""
        assert "ORCH_REQUIRED_ROLE_RECEIPTS" in open(am.__file__, encoding="utf-8").read()


class TestReceipt:
    def test_a_known_role_produces_a_receipt(self):
        r = am.receipt("verifier", model="m", provider="local", cost_usd=0.5)
        assert r["role"] == "verifier"
        assert r["cost_usd"] == 0.5

    def test_role_names_are_normalised(self):
        assert am.receipt("  VERIFIER ")["role"] == "verifier"

    @pytest.mark.parametrize("role", ["reviewer", "qa", "", None, 7])
    def test_an_unknown_role_produces_nothing(self, role):
        """A typo that silently counts is worse than a visibly missing receipt."""
        assert am.receipt(role) == {}

    def test_an_unparseable_cost_becomes_zero_rather_than_raising(self):
        assert am.receipt("verifier", cost_usd="lots")["cost_usd"] == 0.0

    def test_the_note_is_bounded(self):
        assert len(am.receipt("verifier", note="x" * 5000)["note"]) <= 300


class TestVerification:
    def test_a_complete_bundle_verifies(self):
        ok, detail = am.verify_receipts(_full())
        assert ok is True
        assert "all required roles" in detail

    def test_a_missing_role_is_named(self):
        partial = [r for r in _full() if r["role"] != "verifier"]
        ok, detail = am.verify_receipts(partial)
        assert ok is False
        assert "verifier" in detail

    def test_no_receipts_at_all_is_incomplete_not_vacuously_complete(self):
        """Fail-closed: this is the exact state the check exists to catch."""
        ok, detail = am.verify_receipts([])
        assert ok is False
        assert "have none" in detail

    def test_unknown_roles_do_not_count_as_coverage(self):
        bogus = [{"role": "reviewer"}, {"role": "qa"}]
        assert am.verify_receipts(bogus)[0] is False

    def test_missing_roles_are_reported_in_declared_order(self):
        assert am.missing_roles([]) == list(am.REQUIRED_ROLES)

    def test_a_later_receipt_for_the_same_role_wins(self):
        rs = [am.receipt("verifier", model="a"), am.receipt("verifier", model="b")]
        assert am.receipts_by_role(rs)["verifier"]["model"] == "b"

    def test_the_required_set_is_overridable_per_call(self):
        assert am.verify_receipts([am.receipt("judge")], required=("judge",))[0] is True

    @pytest.mark.parametrize("receipts", [None, "text", 7, [None, 7, "x"]])
    def test_malformed_input_is_incomplete_rather_than_an_exception(self, receipts):
        ok, _detail = am.verify_receipts(receipts)
        assert ok is False


class TestCost:
    def test_it_totals_the_receipts(self):
        rs = [am.receipt("scout", cost_usd=0.25), am.receipt("judge", cost_usd=0.75)]
        assert am.receipts_cost(rs) == 1.0

    def test_an_unusable_entry_is_skipped_not_fatal(self):
        rs = [am.receipt("scout", cost_usd=0.5), {"role": "judge", "cost_usd": "free"}, None]
        assert am.receipts_cost(rs) == 0.5

    @pytest.mark.parametrize("receipts", [None, [], "text"])
    def test_nothing_costs_nothing(self, receipts):
        assert am.receipts_cost(receipts) == 0.0


class TestNoParallelSurface:
    def test_no_new_ui_module_was_created(self):
        """The slice's own constraint: reuse the existing Now/Approve/dashboard surfaces."""
        runner = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assert not os.path.exists(os.path.join(runner, "role_receipts_dashboard.py"))
        assert not os.path.exists(os.path.join(runner, "role_receipts.py"))

    def test_the_helpers_live_beside_the_roles_they_check(self):
        assert am.verify_receipts.__module__ == am.route_role.__module__
