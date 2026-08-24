"""Lease timings are named constants, not literals buried in the call site.

CLAUDE.md's lease-RPC-night section states the rule this module was violating: "the lease
code carries bare literals ... lift these to module constants or ORCH_-prefixed env vars
so they are fleet-pushable via fleet_control.py".

The TTL floor was the dangerous one: it was written out TWICE, as `max(60, int(ttl))` in
the RPC arguments and again in the locally cached lease dict. A duplicated magic number is
worse than a single one — a later edit fixes one occurrence, the two disagree about how
long the lease lasts, and the cached copy and the server copy expire at different times.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import branch_lease  # noqa: E402


class TestConstantsExistAndAreTunable:
    def test_the_ttl_floor_is_a_named_constant(self):
        assert isinstance(branch_lease.MIN_TTL_SECONDS, int)
        assert branch_lease.MIN_TTL_SECONDS > 0

    def test_the_sha_lookup_timeout_is_a_named_constant(self):
        assert isinstance(branch_lease.SHA_LOOKUP_TIMEOUT_SECONDS, int)
        assert branch_lease.SHA_LOOKUP_TIMEOUT_SECONDS > 0

    @pytest.mark.parametrize("name", [
        "ORCH_BRANCH_LEASE_MIN_TTL_SECONDS",
        "ORCH_BRANCH_LEASE_SHA_TIMEOUT_SECONDS",
    ])
    def test_each_is_orch_prefixed_so_fleet_control_can_push_it(self, name):
        """CLAUDE.md: 'DO prefix config key changes with ORCH_'."""
        assert name in open(branch_lease.__file__, encoding="utf-8").read()

    def test_no_bare_literal_remains_at_the_call_sites(self):
        src = open(branch_lease.__file__, encoding="utf-8").read()
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        assert "max(60, int(ttl))" not in code
        assert "timeout=15" not in code


class TestClampTtl:
    def test_a_short_ttl_is_raised_to_the_floor(self):
        """Below the floor a lease can expire while its task is still starting."""
        assert branch_lease._clamp_ttl(5) == branch_lease.MIN_TTL_SECONDS

    def test_the_floor_itself_is_allowed(self):
        assert branch_lease._clamp_ttl(branch_lease.MIN_TTL_SECONDS) == branch_lease.MIN_TTL_SECONDS

    def test_a_long_ttl_is_untouched(self):
        assert branch_lease._clamp_ttl(7200) == 7200

    def test_a_string_ttl_is_coerced(self):
        assert branch_lease._clamp_ttl("7200") == 7200

    @pytest.mark.parametrize("ttl", [None, "soon", [], {}])
    def test_an_unreadable_ttl_falls_back_instead_of_raising(self, ttl):
        """Refusing to lease because a number would not parse stalls the runner."""
        assert branch_lease._clamp_ttl(ttl) >= branch_lease.MIN_TTL_SECONDS

    def test_a_negative_ttl_cannot_produce_an_already_expired_lease(self):
        assert branch_lease._clamp_ttl(-99) == branch_lease.MIN_TTL_SECONDS


class TestOneDefinitionTwoCallSites:
    def test_both_the_rpc_arg_and_the_cached_lease_use_the_same_clamp(self):
        """The bug the duplication invited: two copies disagreeing about expiry."""
        src = open(branch_lease.__file__, encoding="utf-8").read()
        assert src.count("_clamp_ttl(ttl)") >= 2

    def test_the_cached_ttl_equals_the_ttl_sent_to_the_rpc(self, monkeypatch):
        captured = {}

        def _rpc(_name, args):
            captured["ttl"] = args["p_ttl_seconds"]
            return True

        monkeypatch.setattr(branch_lease.db, "rpc", _rpc)
        monkeypatch.setattr(branch_lease, "_sha", lambda *_a, **_k: "abc123")
        lease = branch_lease.acquire(
            {"id": "t1", "project_id": "p1"}, "agent/x", "/repo", "master", ttl=5)
        assert lease is not None
        assert lease["ttl"] == captured["ttl"] == branch_lease.MIN_TTL_SECONDS


class TestNoBehaviourChange:
    def test_the_default_ttl_is_unchanged(self):
        assert branch_lease.DEFAULT_TTL == int(
            os.environ.get("ORCH_BRANCH_LEASE_TTL_SECONDS", "3600") or 3600)

    def test_the_floor_default_matches_the_literal_it_replaced(self):
        assert branch_lease.MIN_TTL_SECONDS == 60

    def test_the_timeout_default_matches_the_literal_it_replaced(self):
        assert branch_lease.SHA_LOOKUP_TIMEOUT_SECONDS == 15
