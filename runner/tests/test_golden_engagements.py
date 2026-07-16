"""
test_golden_engagements.py - Tests for golden engagements schema and ingesters.

All tests use bundled fixtures via injected fetcher — no live network.
"""
import os, sys, json, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import golden_engagements as ge


# ── Fixtures ────────────────────────────────────────────────────
FR_FIXTURE = json.dumps({
    "document_number": "2026-11854",
    "title": "Prediction Markets; Public Interest Determinations",
    "type": "Proposed Rule",
    "agencies": [{"name": "Commodity Futures Trading Commission"}],
    "citation": "91 FR 35806",
    "publication_date": "2026-06-12",
}).encode()

EDGAR_FIXTURE = json.dumps({
    "hits": {"total": {"value": 1}, "hits": [{"_source": {"file_num": "test"}}]}
}).encode()

REGSGOV_FIXTURE = json.dumps({
    "data": {"id": "CFTC-2026-0001", "type": "dockets",
             "attributes": {"title": "Prediction Markets"}}
}).encode()

CL_FIXTURE = json.dumps({
    "id": 12345, "case_name": "Test v. CFTC",
    "docket_number": "24-1234",
}).encode()


def _make_fetcher(response_bytes):
    """Return a fetcher that returns the given bytes for any URL."""
    def fetcher(url, headers=None):
        return response_bytes
    return fetcher


class TestSchema(unittest.TestCase):

    def test_stage_creation(self):
        s = ge.Stage(name="nprm", stage_input="input", real_next_document="doc1")
        self.assertEqual(s.name, "nprm")
        self.assertIsNone(s.real_outcome)

    def test_engagement_roundtrip(self):
        eng = ge.build_golden_seed()
        d = eng.to_dict()
        restored = ge.GoldenEngagement.from_dict(d)
        self.assertEqual(restored.matter_id, eng.matter_id)
        self.assertEqual(len(restored.stages), len(eng.stages))

    def test_golden_seed_stages(self):
        eng = ge.build_golden_seed()
        self.assertEqual(eng.agency, "CFTC")
        self.assertGreaterEqual(len(eng.stages), 3)
        self.assertEqual(eng.stages[0].name, "anprm")

    def test_golden_seed_metadata(self):
        eng = ge.build_golden_seed()
        self.assertEqual(eng.metadata["fr_doc_number"], "2026-11854")
        self.assertEqual(eng.metadata["fr_citation"], "91 FR 35806")


class TestIngesters(unittest.TestCase):

    def test_federal_register(self):
        result = ge.ingest_federal_register("2026-11854", fetcher=_make_fetcher(FR_FIXTURE))
        self.assertEqual(result["document_number"], "2026-11854")
        self.assertEqual(result["type"], "Proposed Rule")

    def test_edgar(self):
        result = ge.ingest_edgar("0001234567-24-000001", fetcher=_make_fetcher(EDGAR_FIXTURE))
        self.assertIn("hits", result)

    def test_regulations_gov(self):
        result = ge.ingest_regulations_gov(
            "CFTC-2026-0001", "fake-key", fetcher=_make_fetcher(REGSGOV_FIXTURE)
        )
        self.assertEqual(result["data"]["id"], "CFTC-2026-0001")

    def test_courtlistener(self):
        result = ge.ingest_courtlistener(
            "12345", "fake-token", fetcher=_make_fetcher(CL_FIXTURE)
        )
        self.assertEqual(result["id"], 12345)


class TestSeedFile(unittest.TestCase):

    def test_seed_json_loadable(self):
        seed_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "seeds", "golden_engagements_seed.json"
        )
        with open(seed_path) as f:
            data = json.load(f)
        eng = ge.GoldenEngagement.from_dict(data)
        self.assertEqual(eng.matter_id, "cftc-prediction-markets-2026")


if __name__ == "__main__":
    unittest.main()
