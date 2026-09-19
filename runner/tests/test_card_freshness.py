import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import card_freshness as cf  # noqa: E402


def test_normalization_section_vs_part_and_jurisdiction():
    k = cf.normalize_authority("31 C.F.R. § 1022.380(a) and 31 CFR part 1010; 31 U.S.C. § 5318(g)(1); 23 NYCRR 200.3; "
                               "91 FR 12345; https://www.federalregister.gov/documents/2026/04/10/2026-07033/anti-money")
    assert {"cfr:31:1022.380", "usc:31:5318", "nycrr:23:200.3", "fr:91:12345", "frdoc:2026-07033"} <= k["strong"]
    assert {"cfr:31:1022", "cfr:31:1010", "nycrr:23:200"} <= k["weak"]
    assert "cfr:31:1010.0" not in k["strong"]
    # NY law only keys when the jurisdiction resolves to NY
    assert "ny:banking:641" in cf.normalize_authority("NY Banking Law § 641", None)["strong"]
    assert "ny:banking:641" in cf.normalize_authority("Banking Law § 641", "NY")["strong"]
    assert cf.normalize_authority("Banking Law § 641 (Texas)", "US_FEDERAL")["strong"] == set()
    assert cf.normalize_authority("published 2026-09-10", None)["strong"] == set()  # a date is not a doc number


def test_matching_requires_section_level_unless_weak_allowed():
    card = {"strong": {"cfr:31:1022.380", "usc:31:5330"}, "weak": {"cfr:31:1022"}}
    entry_part = {"strong": set(), "weak": {"cfr:31:1022"}}
    assert cf.match(card, entry_part) == {"strong": [], "weak": []}
    assert cf.match(card, entry_part, include_weak=True) == {"strong": [], "weak": ["cfr:31:1022"]}
    entry_sec = {"strong": {"cfr:31:1022.380"}, "weak": {"cfr:31:1022"}}
    assert cf.match(card, entry_sec)["strong"] == ["cfr:31:1022.380"]


def _card(cid, chain, minted="2026-09-01T00:00:00Z", process=None, docket="d1"):
    return {"id": cid, "docket_id": docket, "vertical": "finserv", "minted_at": minted, "status": "fresh",
            "authority_chain": json.dumps(chain), "citations": "[]", "process": json.dumps(process or {})}


def test_scan_marks_only_newer_entries_and_is_idempotent(monkeypatch):
    entries = [{"title": "FinCEN amends 31 CFR 1022.380 registration", "summary": "", "source_url": "https://fr/a",
                "jurisdiction": "US_FEDERAL", "published_date": "2026-09-05"},
               {"title": "Older notice on 31 CFR 1022.380", "summary": "", "source_url": "https://fr/old",
                "jurisdiction": "US_FEDERAL", "published_date": "2026-08-01"},
               {"title": "NY DFS amends 23 NYCRR Part 200", "summary": "", "source_url": "https://dfs/200",
                "jurisdiction": "NY", "published_date": "2026-09-06"}]
    cards = [_card("c1", ["31 CFR 1022.380", "31 U.S.C. § 5330"]),
             _card("c2", ["23 NYCRR 200.3"]),                                  # part-level only -> weak
             _card("c3", ["31 CFR 1022.380"], minted="2026-09-10T00:00:00Z"),  # minted after the entry
             _card("c4", ["31 CFR 1022.380"], process={"staleness": {"entry_url": "https://fr/a"}})]  # already marked
    writes = []
    monkeypatch.setattr(cf.db, "update", lambda t, m, p: writes.append((t, m, p)))
    monkeypatch.setattr(cf.db, "upsert", lambda t, row: writes.append((t, row)))
    out = cf.scan(dry_run=True, entries=entries, cards=cards)
    assert [m["card_id"] for m in out["examples"]] == ["c1"] and out["would_stale"] == 1 and writes == []
    out = cf.scan(dry_run=True, include_weak=True, entries=entries, cards=cards)
    assert [m["card_id"] for m in out["examples"]] == ["c1", "c2"] and out["examples"][1]["weak_only"]
    out = cf.scan(dry_run=False, entries=entries, cards=cards)
    assert out["stale_marked"] == 1
    tables = [w[0] for w in writes]
    assert tables == ["verdict_cards", "legal_docket", "controls"]
    _, match_, patch = writes[0]
    assert match_ == {"id": "c1"} and patch["status"] == "stale"
    proc = json.loads(patch["process"])
    assert proc["staleness"]["entry_url"] == "https://fr/a" and proc["staleness"]["matched_keys"] == ["cfr:31:1022.380"]
    assert writes[1][1] == {"id": "d1"} and writes[1][2] == {"status": "stale"}
    assert writes[2][1]["key"] == "card_freshness_stats"


def test_card_keys_read_double_encoded_jsonb_strings():
    c = _card("c", ["NY Banking Law § 641(1)", "31 CFR 1010.100(ff)(5)"])
    c["citations"] = json.dumps([{"source": "31 U.S.C. § 5318(g)(1)", "url": "https://www.law.cornell.edu/uscode/text/31/5318"}])
    k = cf.card_keys(c)
    assert {"ny:banking:641", "cfr:31:1010.100", "usc:31:5318"} <= k["strong"]
    assert cf.card_keys({"authority_chain": "not json", "citations": None})["strong"] == set()
