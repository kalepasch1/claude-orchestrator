"""
A journey receipt must reach the reader, not just the disk.

WHAT WENT WRONG
---------------
DEPLOYED_AND_VERIFIED requires two things: an exact live release SHA, and a
passing production journey receipt. Releases were healthy throughout — 767 in the
week of 2026-08-17 — so the first half was always satisfied.

The second half could never be, for two independent reasons:

  1. production_journey.store() wrote receipts to .runtime/journey-receipts/*.json
     and nowhere else. Host-local files, invisible to other runners, to the web
     UI, and to the ledger.

  2. canonical_proof_ledger.gather_evidence() reads journeys from a table called
     `shipped_metrics` — which did not exist. paginate_checked() recorded a read
     error, evidence["journeys"] stayed empty, and every task answered
     "no production journey receipt for this release sha".

Producer wrote files; consumer read a table; the table was absent. Nothing was
marked verified between 2026-08-07 and 2026-08-23.

Seven receipts existed on the primary host the whole time and no consumer could
see any of them.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import production_journey  # noqa: E402


class _RecordingDB:
    """Captures what would be written, so the shape is asserted without a network."""

    def __init__(self):
        self.rows = []

    def upsert(self, table, row):
        self.rows.append((table, row))
        return row


def _receipt(**over):
    base = {
        "id": "abc123",
        "slug": "release-beethoven-730ed3ff9106",
        "sha": "730ed3ff9106035ce4341937223300fe6d644e22",
        "verdict": production_journey.PASS,
        "url": "https://example.vercel.app",
        "environment": "production",
        "recorded_at": 1786800720.119524,
        "required": True,
        "assertion_count": 3,
        "duration_ms": 812,
        "failed_assertions": [],
        "note": "",
        "probe": "http",
    }
    base.update(over)
    return base


def test_receipt_is_written_to_the_table_the_ledger_reads(monkeypatch):
    fake = _RecordingDB()
    monkeypatch.setitem(sys.modules, "db", fake)

    assert production_journey._publish(_receipt()) is True
    assert len(fake.rows) == 1
    table, row = fake.rows[0]

    assert table == "shipped_metrics", (
        "the ledger selects from shipped_metrics; a receipt written anywhere else "
        "is invisible to the only thing that consumes it"
    )
    # These five columns are exactly what gather_evidence() selects. If this
    # drifts, the ledger silently sees nothing again.
    for column in ("release_sha", "journey", "ok", "url", "recorded_at"):
        assert column in row, f"the ledger selects {column}; the receipt must carry it"

    assert row["release_sha"] == "730ed3ff9106035ce4341937223300fe6d644e22"
    assert row["ok"] is True


def test_a_failing_verdict_is_not_published_as_ok(monkeypatch):
    """ok is the field the ledger gates on. It must mean what it says."""
    fake = _RecordingDB()
    monkeypatch.setitem(sys.modules, "db", fake)

    for verdict in (production_journey.FAIL, production_journey.MISSING,
                    production_journey.FLAKY):
        fake.rows.clear()
        production_journey._publish(_receipt(verdict=verdict))
        assert fake.rows[0][1]["ok"] is False, (
            f"verdict={verdict!r} was published as ok — that is how 'the deploy "
            f"happened' becomes 'the change works'"
        )


def test_publish_failure_never_raises(monkeypatch):
    """The file on disk is the durable record; losing the mirror must not lose it."""
    class Exploding:
        @staticmethod
        def upsert(*_a, **_kw):
            raise RuntimeError("control plane unreachable")

    monkeypatch.setitem(sys.modules, "db", Exploding)
    assert production_journey._publish(_receipt()) is False


def test_a_receipt_without_a_sha_is_not_published(monkeypatch):
    """The ledger keys on release_sha. A receipt without one cannot be matched."""
    fake = _RecordingDB()
    monkeypatch.setitem(sys.modules, "db", fake)
    assert production_journey._publish(_receipt(sha="")) is False
    assert not fake.rows


def test_store_writes_the_file_and_publishes(monkeypatch, tmp_path):
    fake = _RecordingDB()
    monkeypatch.setitem(sys.modules, "db", fake)
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path))

    receipt = _receipt()
    path = production_journey.store(receipt)

    assert os.path.isfile(path), "the durable on-disk record must still be written"
    assert fake.rows, "store() must publish as well as persist"
