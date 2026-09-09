"""restamp_recovery_ledger — do not multiply a scan that never finished.

Re-stamping turns ONE sound scan into N audit records, which is the whole reason
it exists: the fleet queues several reconcile tasks that differ only in their
audit fingerprint, and re-running a ten-minute scan per fingerprint is waste.

Applied to an UNSOUND scan it multiplies the unsoundness instead. A partial
classification picks up a fresh fingerprint and a fresh `restamped_at`, and the
derived ledger is then indistinguishable from one backed by a complete scan —
while the evidence it claims to have classified was never looked at.

That risk is new. The scanners now accept `--max-seconds` and mark a
budget-exhausted ledger `truncated`, precisely so a partial ledger is honest
about itself; without a gate here, re-stamping would launder exactly that
honesty away. The same argument covers UNKNOWN items, whose count is the stated
completion bar for the recovery contract.

The gate is overridable, because an operator re-stamping a partial ledger on
purpose is a real workflow and a hard refusal only teaches people to hand-edit
the JSON. What is NOT optional is that the override be recorded in the output.
"""
import json
import os
import sys

import pytest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

rrl = pytest.importorskip("restamp_recovery_ledger")

FP_OLD = "a" * 64
FP_NEW = "b" * 64


def flat_ledger(**over):
    led = {
        "audit_fingerprint": FP_OLD,
        "base": "origin/master",
        "total": 2,
        "unknown": 0,
        "truncated": False,
        "items": [
            {"ref": "refs/orch-rescue/1", "sha": "s1",
             "classification": "ALREADY_PRESENT", "disposition": "d",
             "evidence": "e"},
            {"ref": "refs/orch-rescue/2", "sha": "s2",
             "classification": "RECOVERABLE_VALUE", "disposition": "d",
             "evidence": "e"},
        ],
    }
    led.update(over)
    return led


def run(tmp_path, ledger, *extra):
    src = tmp_path / "in.json"
    src.write_text(json.dumps(ledger))
    out = tmp_path / "out.json"
    rc = rrl.main(["--in", str(src), "--out", str(out),
                   "--fingerprint", FP_NEW] + list(extra))
    return rc, out


# ── the check itself ────────────────────────────────────────────────────────

def test_a_complete_ledger_passes():
    assert rrl.check_completeness(flat_ledger()) == ""


def test_a_truncated_ledger_is_named_as_such():
    reason = rrl.check_completeness(flat_ledger(truncated=True))
    assert "truncated" in reason
    assert "complete audit" in reason


def test_the_scan_duration_is_quoted_when_available():
    # An operator deciding whether to override wants to know how far it got.
    reason = rrl.check_completeness(
        flat_ledger(truncated=True, scan_seconds=612.5))
    assert "612.5" in reason


def test_unknown_items_are_counted_in_the_refusal():
    led = flat_ledger()
    led["items"][0]["classification"] = "UNKNOWN"
    assert "1 UNKNOWN item" in rrl.check_completeness(led)


def test_an_unrecognised_classification_counts_as_unknown():
    """recount() maps anything outside the vocabulary to UNKNOWN, so a typo or a
    label from a future version cannot slip past the completion bar."""
    led = flat_ledger()
    led["items"][0]["classification"] = "PROBABLY_FINE"
    assert "UNKNOWN" in rrl.check_completeness(led)


def test_the_sources_own_unknown_field_is_not_trusted():
    # A ledger claiming unknown=0 while carrying an UNKNOWN item must not be
    # taken at its word; the items are the evidence.
    led = flat_ledger(unknown=0)
    led["items"][1]["classification"] = "UNKNOWN"
    assert rrl.check_completeness(led) != ""


def test_truncated_false_is_not_treated_as_truncated():
    assert rrl.check_completeness(flat_ledger(truncated=False)) == ""


def test_a_ledger_predating_the_truncated_field_still_passes():
    # Existing committed ledgers have no `truncated` key at all.
    led = flat_ledger()
    del led["truncated"]
    assert rrl.check_completeness(led) == ""


def test_a_non_dict_source_is_refused():
    assert rrl.check_completeness([]) != ""


# ── how main() uses it ──────────────────────────────────────────────────────

def test_a_truncated_source_is_refused_and_writes_nothing(tmp_path, capsys):
    rc, out = run(tmp_path, flat_ledger(truncated=True))
    assert rc == 2
    assert not out.exists(), "a refused restamp must not leave a derived ledger"
    assert "refused" in capsys.readouterr().err


def test_an_unknown_carrying_source_is_refused(tmp_path):
    led = flat_ledger()
    led["items"][0]["classification"] = "UNKNOWN"
    rc, out = run(tmp_path, led)
    assert rc == 2
    assert not out.exists()


def test_the_refusal_names_the_override_flag(tmp_path, capsys):
    run(tmp_path, flat_ledger(truncated=True))
    assert "--allow-incomplete" in capsys.readouterr().err


def test_the_override_lets_it_through(tmp_path):
    rc, out = run(tmp_path, flat_ledger(truncated=True), "--allow-incomplete")
    assert rc == 0
    assert out.exists()


def test_the_override_is_recorded_in_the_derived_ledger(tmp_path):
    """The load-bearing assertion.

    Without this the derived ledger would look exactly like one backed by a
    complete scan, and the gate would be theatre.
    """
    _, out = run(tmp_path, flat_ledger(truncated=True, scan_seconds=100.0),
                 "--allow-incomplete")
    derived = json.loads(out.read_text())
    note = (derived.get("restamp_incomplete_override")
            or (derived.get("meta") or {}).get("restampIncompleteOverride"))
    assert note and "truncated" in note


def test_a_complete_source_restamps_without_an_override_note(tmp_path):
    _, out = run(tmp_path, flat_ledger())
    derived = json.loads(out.read_text())
    assert "restamp_incomplete_override" not in derived
    assert "restampIncompleteOverride" not in (derived.get("meta") or {})


def test_a_complete_source_still_restamps_normally(tmp_path):
    rc, out = run(tmp_path, flat_ledger())
    assert rc == 0
    derived = json.loads(out.read_text())
    assert derived["audit_fingerprint"] == FP_NEW
    assert len(derived["items"]) == 2
    assert derived["unknown"] == 0


def test_completeness_is_reported_before_drift(tmp_path, capsys):
    """Both objections apply; the operator should hear the fundamental one.

    Leading with drift would invite --allow-base-drift, after which the same
    command fails again for a different reason.
    """
    rc, _ = run(tmp_path, flat_ledger(truncated=True),
                "--expect-base-sha", "0123456789")
    assert rc == 2
    err = capsys.readouterr().err
    assert "truncated" in err
    assert "base drift" not in err


def test_allow_base_drift_alone_does_not_waive_incompleteness(tmp_path):
    # Two separate switches, deliberately: reaching for one must never silently
    # waive the other.
    rc, out = run(tmp_path, flat_ledger(truncated=True), "--allow-base-drift")
    assert rc == 2
    assert not out.exists()


def test_allow_incomplete_alone_does_not_waive_base_drift(tmp_path):
    rc, out = run(tmp_path, flat_ledger(truncated=True),
                  "--expect-base-sha", "0123456789", "--allow-incomplete")
    assert rc == 2
    assert not out.exists()
