"""P4 household-legal doc updater — acceptance + fail-soft behaviour."""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    # "2080" is not a valid Python identifier, so the package cannot be imported by dotted
    # path. Same approach as pareto/2080/contracts/test_contracts_smoke.py.
    sys.path.insert(0, _HERE)

import doc_updater as du


FIXTURE = {"regime": "CA", "effective_date": "2026-09-01"}


class TestAcceptance:
    """The acceptance criterion, verbatim: the fixture event updates the template and
    fire_notification() is called without raising."""

    def test_fixture_event_updates_template_and_notifies(self):
        fired = []
        u = du.DocumentUpdater(notifier=lambda uid, s: fired.append((uid, s)))

        ok, template = u.update_lease_template(FIXTURE)
        assert ok is True
        assert template["jurisdiction"] == "CA"
        assert template["effective_date"] == "2026-09-01"
        assert any("CA" in c for c in template["clauses"])

        u.fire_notification("user-1", "lease updated")
        assert fired == [("user-1", "lease updated")]

    def test_apply_and_notify_end_to_end(self):
        u = du.DocumentUpdater()
        ok, _ = u.apply_and_notify(FIXTURE, "user-1")
        assert ok is True
        assert len(u.notifications) == 1
        assert "CA" in u.notifications[0]["summary"]


class TestRegimeEventShapes:
    """The fixture says `regime`; contracts/autonomy.py RegimeEvent says `jurisdiction`."""

    def test_accepts_the_contracts_key(self):
        ok, template = du.DocumentUpdater().update_lease_template(
            {"jurisdiction": "NY", "rule_id": "R-1", "effective_date": "2026-10-01"})
        assert ok is True
        assert template["jurisdiction"] == "NY"

    def test_accepts_a_regime_event_dataclass(self):
        sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "contracts"))
        import autonomy
        ev = autonomy.RegimeEvent(jurisdiction="TX", rule_id="R-9",
                                  effective_date="2026-11-01")
        ok, template = du.DocumentUpdater().update_lease_template(ev)
        assert ok is True
        assert template["jurisdiction"] == "TX"


class TestFailSoft:
    """Every failure returns the ORIGINAL template. A half-applied legal document is worse
    than an unchanged one."""

    def test_none_event_is_a_no_op(self):
        u = du.DocumentUpdater()
        before = dict(u.template)
        ok, template = u.update_lease_template(None)
        assert ok is False
        assert template == before
        assert u.template == before

    def test_event_without_jurisdiction_is_refused(self):
        """Applying a rule change to the wrong jurisdiction's lease is the bad outcome."""
        ok, _ = du.DocumentUpdater().update_lease_template({"effective_date": "2026-09-01"})
        assert ok is False

    def test_empty_dict_is_refused(self):
        assert du.DocumentUpdater().update_lease_template({})[0] is False

    def test_garbage_event_does_not_raise(self):
        for bad in (42, "not-an-event", [], object()):
            ok, _ = du.DocumentUpdater().update_lease_template(bad)
            assert ok is False

    def test_oracle_explosion_leaves_template_untouched(self, monkeypatch):
        u = du.DocumentUpdater()
        before = dict(u.template)
        monkeypatch.setattr(du, "safe_consume_regime_event",
                            lambda e: (_ for _ in ()).throw(RuntimeError("oracle down")))
        ok, template = u.update_lease_template(FIXTURE)
        assert ok is False
        assert template == before

    def test_notification_failure_never_raises(self):
        def boom(uid, summary):
            raise RuntimeError("queue down")
        u = du.DocumentUpdater(notifier=boom)
        u.fire_notification("user-1", "summary")  # must not propagate

    def test_failed_update_does_not_notify(self):
        """Notifying on a no-op trains people to ignore notifications."""
        u = du.DocumentUpdater()
        ok, _ = u.apply_and_notify({"effective_date": "x"}, "user-1")
        assert ok is False
        assert u.notifications == []


class TestIdempotence:

    def test_same_event_twice_does_not_duplicate_the_clause(self):
        u = du.DocumentUpdater()
        u.update_lease_template(FIXTURE)
        _, template = u.update_lease_template(FIXTURE)
        assert len(template["clauses"]) == 1

    def test_revision_increments_per_applied_change(self):
        u = du.DocumentUpdater()
        u.update_lease_template(FIXTURE)
        _, template = u.update_lease_template(
            {"regime": "CA", "rule_id": "R-2", "effective_date": "2026-12-01"})
        assert template["revision"] == 2
        assert len(template["clauses"]) == 2


class TestStringTemplates:

    def test_string_template_is_appended_not_rewritten(self):
        u = du.DocumentUpdater(template="ORIGINAL LEASE BODY")
        ok, template = u.update_lease_template(FIXTURE)
        assert ok is True
        assert "ORIGINAL LEASE BODY" in template
        assert "CA" in template


class TestSummarize:

    def test_summary_is_plain_language(self):
        s = du.DocumentUpdater.summarize(FIXTURE)
        assert "CA" in s and "2026-09-01" in s

    def test_summary_of_a_non_event_is_still_a_string(self):
        assert isinstance(du.DocumentUpdater.summarize(None), str)


class TestSiblingModuleIsOptional:
    """regime_consumer is a sibling P-phase module that is not deployed yet. P4 must be
    shippable on its own rather than blocked behind it."""

    def test_missing_sibling_does_not_break_import_or_update(self):
        assert du._sibling_consume is None or callable(du._sibling_consume)
        assert du.DocumentUpdater().update_lease_template(FIXTURE)[0] is True

    def test_sibling_is_used_when_present(self, monkeypatch):
        monkeypatch.setattr(du, "_sibling_consume",
                            lambda e: {"jurisdiction": "WA", "rule_id": "VIA-SIBLING"})
        ok, template = du.DocumentUpdater().update_lease_template(FIXTURE)
        assert ok is True
        assert template["jurisdiction"] == "WA"

    def test_sibling_returning_none_is_a_no_op(self, monkeypatch):
        monkeypatch.setattr(du, "_sibling_consume", lambda e: None)
        assert du.DocumentUpdater().update_lease_template(FIXTURE)[0] is False

    def test_sibling_explosion_is_fail_soft(self, monkeypatch):
        monkeypatch.setattr(du, "_sibling_consume",
                            lambda e: (_ for _ in ()).throw(RuntimeError("sibling down")))
        assert du.DocumentUpdater().update_lease_template(FIXTURE)[0] is False
