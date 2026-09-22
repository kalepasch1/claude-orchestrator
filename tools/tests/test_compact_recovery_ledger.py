"""compact_recovery_ledger — smaller in git, identical in evidence.

The one thing compaction must never do is lose an item. A recovery ledger's
whole claim is "every piece of evidence was classified and none is UNKNOWN", and
that claim is checked against the committed artefact. A compactor that silently
dropped items — or, worse, dropped UNKNOWN ones — would turn incomplete evidence
into a clean-looking record, which is the exact failure the reconciler family is
built to prevent.

So the tests below pin, in order of importance: item count preserved, UNKNOWN
preserved and recounted, per-item classification/disposition/evidence untouched,
and only then the size win.
"""
import json
import os
import sys

import pytest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

crl = pytest.importorskip("compact_recovery_ledger")


def ledger(n=5, files_per_item=100, classification="ALREADY_PRESENT"):
    return {
        "audit_fingerprint": "f" * 64,
        "base": "origin/master",
        "total": n,
        "unknown": 0,
        "counts": {classification: n},
        "items": [{
            "ref": "refs/orch-rescue/%d" % i,
            "sha": "sha%d" % i,
            "classification": classification,
            "disposition": "reachable from origin/master; no action",
            "evidence": "merge-base --is-ancestor",
            "files": ["path/%d/%d.py" % (i, j) for j in range(files_per_item)],
        } for i in range(n)],
    }


# ── nothing is lost ─────────────────────────────────────────────────────────

def test_every_item_survives(): 
    out = crl.compact_ledger(ledger(n=40), max_files=3)
    assert out["total"] == 40
    assert len(out["items"]) == 40


def test_refs_and_shas_are_untouched():
    src = ledger(n=6)
    out = crl.compact_ledger(src, max_files=2)
    assert [i["ref"] for i in out["items"]] == [i["ref"] for i in src["items"]]
    assert [i["sha"] for i in out["items"]] == [i["sha"] for i in src["items"]]


def test_the_classification_and_its_reason_are_untouched():
    # The reason is the audit. Keeping the label and dropping the reason would
    # leave a ledger nobody can check.
    out = crl.compact_ledger(ledger(n=3), max_files=1)
    for item in out["items"]:
        assert item["classification"] == "ALREADY_PRESENT"
        assert item["disposition"] == "reachable from origin/master; no action"
        assert item["evidence"] == "merge-base --is-ancestor"


def test_unknown_items_are_kept_and_still_counted():
    """The load-bearing one.

    Completion is gated on `unknown == 0`. If compaction dropped or miscounted
    UNKNOWN items the gate would open on evidence nobody classified.
    """
    src = ledger(n=4, classification="UNKNOWN")
    out = crl.compact_ledger(src, max_files=1)
    assert out["unknown"] == 4
    assert out["counts"]["UNKNOWN"] == 4
    assert len(out["items"]) == 4


def test_counts_are_recomputed_not_inherited():
    # A source whose summary disagrees with its own items must not have that
    # disagreement copied forward; the committed artefact tells the truth about
    # itself.
    src = ledger(n=3)
    src["counts"] = {"ALREADY_PRESENT": 999}
    src["total"] = 999
    src["unknown"] = 7
    out = crl.compact_ledger(src, max_files=1)
    assert out["counts"] == {"ALREADY_PRESENT": 3}
    assert out["total"] == 3
    assert out["unknown"] == 0


def test_a_mixed_ledger_keeps_every_classification():
    src = ledger(n=0)
    src["items"] = [
        {"ref": "a", "sha": "1", "classification": "RECOVERABLE_VALUE",
         "disposition": "d", "evidence": "e", "files": ["x"]},
        {"ref": "b", "sha": "2", "classification": "CONFLICTED_NEEDS_FOCUSED_TASK",
         "disposition": "d", "evidence": "e", "files": ["x"]},
        {"ref": "c", "sha": "3", "classification": "UNKNOWN",
         "disposition": "d", "evidence": "e", "files": ["x"]},
    ]
    out = crl.compact_ledger(src, max_files=5)
    assert out["counts"] == {"RECOVERABLE_VALUE": 1,
                             "CONFLICTED_NEEDS_FOCUSED_TASK": 1,
                             "UNKNOWN": 1}


# ── what compaction actually does ───────────────────────────────────────────

def test_the_file_list_is_clipped_and_the_clip_is_declared():
    out = crl.compact_ledger(ledger(n=1, files_per_item=100), max_files=4)
    item = out["items"][0]
    assert len(item["files"]) == 4
    assert item["filesTruncated"] is True
    assert item["files_total"] == 100


def test_a_short_list_is_left_alone_and_marked_untruncated():
    out = crl.compact_ledger(ledger(n=1, files_per_item=2), max_files=10)
    item = out["items"][0]
    assert item["files"] == ["path/0/0.py", "path/0/1.py"]
    assert item["filesTruncated"] is False
    assert item["files_total"] == 2


def test_files_total_is_written_even_when_nothing_was_clipped():
    # Otherwise a reader cannot tell "not clipped" from "field not written".
    out = crl.compact_ledger(ledger(n=1, files_per_item=1), max_files=10)
    assert "files_total" in out["items"][0]


def test_the_disposition_count_still_matches_files_total():
    """Dispositions say "all N touched file(s) modified in base". If the only
    surviving number were len(files) after clipping, the ledger would contradict
    its own prose."""
    src = ledger(n=1, files_per_item=30, classification="SUPERSEDED_BY_NEWER")
    src["items"][0]["disposition"] = "all 30 touched file(s) modified in origin/master"
    out = crl.compact_ledger(src, max_files=5)
    assert out["items"][0]["files_total"] == 30
    assert "all 30 touched" in out["items"][0]["disposition"]


def test_max_files_minus_one_disables_compaction():
    out = crl.compact_ledger(ledger(n=1, files_per_item=50), max_files=-1)
    assert len(out["items"][0]["files"]) == 50
    assert out["items"][0]["filesTruncated"] is False


def test_an_item_without_a_files_array_is_passed_through(): 
    src = {"items": [{"ref": "a", "sha": "1", "classification": "ALREADY_PRESENT"}]}
    out = crl.compact_ledger(src, max_files=3)
    assert out["items"][0] == {"ref": "a", "sha": "1",
                               "classification": "ALREADY_PRESENT"}


def test_the_regeneration_hint_is_recorded():
    # Compaction is only defensible because the dropped data is reproducible.
    # The artefact has to say how.
    out = crl.compact_ledger(ledger(n=1), max_files=1)
    assert "git show" in out["compacted"]["note"]
    assert out["compacted"]["maxFilesPerItem"] == 1
    assert out["compacted"]["itemsTruncated"] == 1


def test_top_level_metadata_survives():
    out = crl.compact_ledger(ledger(n=1), max_files=1)
    assert out["audit_fingerprint"] == "f" * 64
    assert out["base"] == "origin/master"


def test_the_source_ledger_is_not_mutated():
    src = ledger(n=2, files_per_item=20)
    crl.compact_ledger(src, max_files=1)
    assert len(src["items"][0]["files"]) == 20


def test_a_ledger_with_no_items_key_is_returned_unharmed():
    out = crl.compact_ledger({"audit_fingerprint": "x"}, max_files=3)
    assert out["audit_fingerprint"] == "x"


# ── the CLI ─────────────────────────────────────────────────────────────────

def test_the_cli_shrinks_the_file_and_reports_honestly(tmp_path, monkeypatch, capsys):
    src = tmp_path / "in.json"
    src.write_text(json.dumps(ledger(n=30, files_per_item=200)))
    out = tmp_path / "nested" / "out.json"

    monkeypatch.setattr(sys, "argv", ["compact_recovery_ledger.py",
                                      "--in", str(src), "--out", str(out),
                                      "--max-files", "5"])
    assert crl.main() == 0

    report = json.loads(capsys.readouterr().out)
    assert report["items"] == 30
    assert report["unknown"] == 0
    assert report["bytes_after"] < report["bytes_before"]
    assert report["items_truncated"] == 30
    assert json.loads(out.read_text())["total"] == 30


def test_an_unreadable_input_exits_two_rather_than_writing_a_stub(tmp_path, monkeypatch):
    out = tmp_path / "out.json"
    monkeypatch.setattr(sys, "argv", ["compact_recovery_ledger.py",
                                      "--in", str(tmp_path / "missing.json"),
                                      "--out", str(out)])
    assert crl.main() == 2
    assert not out.exists(), "a failed compaction must not leave a partial ledger"


def test_malformed_json_exits_two(tmp_path, monkeypatch):
    src = tmp_path / "in.json"
    src.write_text("{not json")
    monkeypatch.setattr(sys, "argv", ["compact_recovery_ledger.py",
                                      "--in", str(src),
                                      "--out", str(tmp_path / "out.json")])
    assert crl.main() == 2


def test_a_json_array_is_rejected_rather_than_half_processed(tmp_path, monkeypatch):
    src = tmp_path / "in.json"
    src.write_text("[]")
    monkeypatch.setattr(sys, "argv", ["compact_recovery_ledger.py",
                                      "--in", str(src),
                                      "--out", str(tmp_path / "out.json")])
    assert crl.main() == 2
