"""Regression tests for the 2026-08-16 session.

Three defects, all measured against the live fleet before the fix:

1. CARD AMPLIFIER. Terminal outcomes wrote `decided_by` and left `status='approved'`.
   _pick_cards() skips decided_by=train:*, so the train never re-picked the card --
   but _find_existing_card() skips train:* too, so the next producer could not see it
   either and filed a duplicate, forever. Measured: 37,012 approved integrate cards
   over 4,474 distinct slugs, 100% train-authored; train:dup-card alone held 18,518
   cards across 221 slugs (83.8 copies per slug, worst slug 144). Live rate when the
   fleet came back on 08-16: ~150-300 duplicate cards/hour.

2. SCAN WINDOW. PostgREST caps a response at 1,000 rows regardless of `limit`, so
   MERGE_TRAIN_SCAN_LIMIT=3000 hid the truncation rather than widening the window.

3. TRUNCATED STDERR. `stderr[-160:]` in releases.note and the branch-share log kept
   git's trailing hint block and discarded the `! [rejected]` / `error:` lines that
   say why. 4,080 failed releases were recorded that way, and two separate
   investigations reached the wrong root cause from them.
"""

import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import merge_train as mt
import stderr_digest as sd


# --------------------------------------------------------------------------- 1. amplifier

def test_terminal_stamp_retires_the_card_from_the_approved_pool(monkeypatch):
    """A terminal outcome must leave the approved pool, not just get a decided_by."""
    seen = {}
    monkeypatch.setattr(mt.db, "update", lambda t, w, p: seen.update({"t": t, "w": w, "p": p}))

    assert mt._retire_card("card-1", "dup-card") is True
    assert seen["t"] == "approvals"
    assert seen["w"] == {"id": "card-1"}
    assert seen["p"]["decided_by"] == "train:dup-card"
    # THE fix: without this the card stays pickable-by-dedup-invisible forever.
    assert seen["p"]["status"] == mt.TERMINAL_STATUS
    assert seen["p"]["status"] != "approved"


def test_no_terminal_path_writes_decided_by_without_retiring():
    """Every terminal stamp must go through _retire_card.

    Anchored to the statement shape rather than the bare name so a comment mentioning
    the old pattern cannot make this pass or fail spuriously.
    """
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "merge_train.py")).read().splitlines()

    # _retire_card's own body is the ONE legitimate site: its degraded fallback writes
    # decided_by alone when the full patch is rejected, so the outcome is still recorded.
    # Excluded by locating the function rather than by matching its text, so the exemption
    # cannot silently widen to cover a new offender that happens to look similar.
    inside, body = False, set()
    for i, ln in enumerate(src):
        if ln.startswith("def _retire_card("):
            inside = True
        elif inside and ln and not ln[0].isspace():
            inside = False
        if inside:
            body.add(i)

    offenders = [f"line {i + 1}: {ln.strip()}" for i, ln in enumerate(src)
                 if i not in body
                 and 'db.update("approvals"' in ln and "decided_by" in ln]
    assert offenders == [], f"terminal stamp bypasses _retire_card: {offenders}"


def test_retire_card_is_fail_soft(monkeypatch):
    """A stamping error must never propagate into the merge path."""
    def boom(*a, **k):
        raise RuntimeError("postgrest down")
    monkeypatch.setattr(mt.db, "update", boom)
    assert mt._retire_card("card-1", "MERGED") is False      # reported, not raised


def test_retire_card_ignores_empty_id(monkeypatch):
    monkeypatch.setattr(mt.db, "update", lambda *a, **k: pytest.fail("must not write"))
    assert mt._retire_card(None, "MERGED") is False
    assert mt._retire_card("", "MERGED") is False


def _row(outcome, age_s=10):
    ts = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=age_s)
    return {"id": "c1", "slug": "s", "decided_by": f"train:{outcome}",
            "decided_at": ts.isoformat()}


def test_final_outcome_inside_cooldown_blocks_a_refile(monkeypatch):
    monkeypatch.setattr(mt.db, "select", lambda *a, **k: [_row("MERGED")])
    assert mt._recently_finalised("s") is not None


def test_retryable_failure_does_not_block_a_refile(monkeypatch):
    """New work after a TESTFAIL legitimately produces a new card."""
    for outcome in ("TESTFAIL", "BUILDFAIL", "conflict-exhausted", "redo", "REGRESSFAIL"):
        monkeypatch.setattr(mt.db, "select", lambda *a, _o=outcome, **k: [_row(_o)])
        assert mt._recently_finalised("s") is None, outcome


def test_cooldown_lookup_failure_never_blocks_card_creation(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("postgrest down")
    monkeypatch.setattr(mt.db, "select", boom)
    assert mt._recently_finalised("s") is None


def test_ensure_card_does_not_insert_when_recently_finalised(monkeypatch):
    """The actual loop: no live card, but the train just finished this slug."""
    monkeypatch.setattr(mt, "_find_existing_card", lambda slug: None)
    monkeypatch.setattr(mt, "_recently_finalised", lambda slug: {"id": "old"})
    monkeypatch.setattr(mt.db, "insert",
                        lambda *a, **k: pytest.fail("re-filed a finalised slug"))
    assert mt.ensure_integration_card_result("proj", "slug-x") == mt.CARD_EXISTED


def test_ensure_card_still_inserts_for_a_genuinely_new_slug(monkeypatch):
    """The fix must not stop real work being queued."""
    wrote = []
    monkeypatch.setattr(mt, "_find_existing_card", lambda slug: None)
    monkeypatch.setattr(mt, "_recently_finalised", lambda slug: None)
    monkeypatch.setattr(mt.db, "insert", lambda t, row: wrote.append(row))
    assert mt.ensure_integration_card_result("proj", "slug-new") == mt.CARD_CREATED
    assert wrote and wrote[0]["slug"] == "slug-new"


# ------------------------------------------------------------------------ 2. scan window

def test_pick_cards_pages_instead_of_widening_the_limit(monkeypatch):
    """MERGE_TRAIN_SCAN_LIMIT=3000 never widened anything; PostgREST caps at 1,000."""
    calls = {"select_all": 0, "select": 0}

    def fake_select_all(table, params=None, **kw):
        calls["select_all"] += 1
        assert "limit" not in (params or {}), "select_all must page, not carry a limit"
        return []

    monkeypatch.setattr(mt.db, "select_all", fake_select_all)
    monkeypatch.setattr(mt.db, "select",
                        lambda *a, **k: calls.__setitem__("select", calls["select"] + 1) or [])
    mt._pick_cards()
    assert calls["select_all"] >= 1, "the scan must page to exhaustion"


def test_pick_cards_falls_back_when_the_server_cannot_page(monkeypatch):
    """A server that will not page must degrade, not take the train down."""
    def no_paging(*a, **k):
        raise RuntimeError("offset unsupported")
    monkeypatch.setattr(mt.db, "select_all", no_paging)
    monkeypatch.setattr(mt.db, "select", lambda *a, **k: [])
    assert mt._pick_cards() == []          # returned, did not raise


# ---------------------------------------------------------------------- 3. stderr digest

REAL_PUSH_FAILURE = (
    "Enumerating objects: 41, done.\n"
    + "remote: Resolving deltas: 100%\n" * 20
    + "To https://github.com/kalepasch1/2080.git\n"
    " ! [rejected]        agent/x -> agent/x (fetch first)\n"
    "error: failed to push some refs to 'https://github.com/kalepasch1/2080.git'\n"
    "hint: Updates were rejected because the remote contains work that you do\n"
    "hint: not have locally. If you want to integrate the remote changes, use 'git pull'\n"
    "hint: before pushing again.\n"
)


def test_old_tail_truncation_loses_the_cause():
    """Documents the defect this module exists to fix."""
    assert "rejected" not in REAL_PUSH_FAILURE[-160:]


def test_digest_keeps_the_cause_at_the_same_budget():
    """Strictly better than [-160:] at identical storage cost."""
    out = sd.digest(REAL_PUSH_FAILURE, 160)
    assert len(out) <= 160
    assert "rejected" in out
    assert "failed to push" in out


@pytest.mark.parametrize("limit", [160, 300, 800, 2000])
def test_digest_keeps_the_cause_at_every_budget(limit):
    out = sd.digest(REAL_PUSH_FAILURE, limit)
    assert "rejected" in out and "failed to push" in out
    assert len(out) <= max(limit, len(REAL_PUSH_FAILURE))


def test_digest_passes_short_input_through_unchanged():
    assert sd.digest("boom") == "boom"


def test_digest_is_empty_safe():
    assert sd.digest(None) == "" and sd.digest("") == ""


def test_digest_never_raises():
    class Nasty:
        def __str__(self):
            raise ValueError("no")
    assert isinstance(sd.digest(Nasty()), str)


def test_no_tail_truncation_left_in_the_repaired_modules():
    """The 17 sites replaced this session must not come back."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bad = []
    for name in ("runner.py", "release_train.py", "merge_truth.py",
                 "branch_durability.py", "merge_train.py"):
        for i, ln in enumerate(open(os.path.join(root, name)), 1):
            if "[-160:]" in ln or "[-150:]" in ln:
                bad.append(f"{name}:{i}")
    assert bad == [], f"stderr tail-truncation reintroduced at {bad}"
