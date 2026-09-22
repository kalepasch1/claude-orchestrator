"""Pure-function tests for corpus_retrieval (no Ollama, no network)."""
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def _use_tmp(monkeypatch, tmp_path):
    import corpus_retrieval as cr
    monkeypatch.setattr(cr, "INDEX_DIR", str(tmp_path))
    monkeypatch.setattr(cr, "META_PATH", str(tmp_path / "meta.jsonl"))
    monkeypatch.setattr(cr, "VEC_PATH", str(tmp_path / "vectors.f32"))
    monkeypatch.setattr(cr, "DIMS", 4)
    cr._CACHE.update(mtime=None, vecs=None, meta=None)
    return cr


def test_truncate_normalize_and_cosine():
    import corpus_retrieval as cr
    v = cr.truncate_normalize([3.0, 4.0, 100.0, 100.0], dims=2)
    assert [round(x, 3) for x in v] == [0.6, 0.8]
    assert abs(cr.cosine(v, v) - 1.0) < 1e-9
    assert cr.cosine([1, 0], [0, 1]) == 0


def test_embed_uses_guarded_transport_and_preserves_normalization(monkeypatch):
    import corpus_retrieval as cr
    import local_embeddings
    from unittest.mock import Mock
    transport = Mock(return_value=[[3.0, 4.0]])
    monkeypatch.setattr(local_embeddings, "embed", transport)
    assert cr.embed(["complete source"], model="selected-model", timeout=600) == [[0.6, 0.8]]
    transport.assert_called_once_with(["complete source"], "selected-model", cr.OLLAMA, timeout=600)
    assert 1 <= cr.BATCH <= 8


def test_embed_capacity_denial_is_not_a_partial_or_successful_batch(monkeypatch):
    import corpus_retrieval as cr
    import local_embeddings
    from unittest.mock import Mock
    transport = Mock(side_effect=local_embeddings.slots.LocalCapacityError("host_headroom"))
    monkeypatch.setattr(local_embeddings, "embed", transport)
    assert cr.embed(["source"]) == []
    assert transport.call_count == 1


def test_embed_empty_input_does_not_call_transport(monkeypatch):
    import corpus_retrieval as cr
    import local_embeddings
    from unittest.mock import Mock
    transport = Mock()
    monkeypatch.setattr(local_embeddings, "embed", transport)
    assert cr.embed([]) == []
    transport.assert_not_called()


def test_index_round_trip_ranking_and_dossier(monkeypatch, tmp_path):
    cr = _use_tmp(monkeypatch, tmp_path)
    rows = [{"clause_id": "a#p0", "doc_id": "a", "heading": "h1", "doc_title": "Banking Law 641", "jurisdiction": "NY",
             "source_url": "https://ny/641", "doc_type": "statute", "text": "No person shall engage in money transmission"},
            {"clause_id": "b#p0", "doc_id": "b", "heading": "h2", "doc_title": "Position limits", "jurisdiction": "US_FEDERAL",
             "source_url": "https://fr/1", "doc_type": "agency_rule", "text": "speculative position limits for energy"},
            {"clause_id": "b#p1", "doc_id": "b", "heading": "h3", "doc_title": "Position limits", "jurisdiction": "US_FEDERAL",
             "source_url": "https://fr/1", "doc_type": "agency_rule", "text": "speculative position limits for energy"}]
    vecs = [cr.truncate_normalize([1, 0, 0, 0]), cr.truncate_normalize([0, 1, 0, 0]), cr.truncate_normalize([0, 0.99, 0.1, 0])]
    cr._append(rows, vecs)
    assert cr._indexed_ids() == {"a#p0", "b#p0", "b#p1"}
    monkeypatch.setattr(cr, "embed", lambda texts, **kw: [cr.truncate_normalize([0.9, 0.1, 0, 0])])
    got = cr.top_passages("money transmission", k=3)
    assert [g["clause_id"] for g in got] == ["a#p0", "b#p0"]  # duplicate text within doc b is collapsed
    assert got[0]["score"] > got[1]["score"] and got[0]["source_url"] == "https://ny/641"
    assert cr.top_passages("x", k=3, jurisdiction="US_FEDERAL")[0]["doc_id"] == "b"
    block = cr.dossier_block("money transmission", k=3)
    assert block.startswith("[1] Banking Law 641 — h1 (NY) https://ny/641\nNo person shall")
    assert "[2]" in block
    assert cr.dossier_block("money transmission", k=3, max_chars=60) == "[1] Banking Law 641 — h1 (NY) https://ny/641\nNo person shall engage in money transmission"[:0] or len(cr.dossier_block("x", k=3, max_chars=60)) <= 60
    st = cr.status()
    assert st["rows"] == 3 and st["dims"] == 4


def test_failures_are_soft(monkeypatch, tmp_path):
    cr = _use_tmp(monkeypatch, tmp_path)
    assert cr.top_passages("anything") == []          # no index
    assert cr.dossier_block("anything") == ""
    cr._append([{"clause_id": "a", "text": "t", "doc_id": "a"}], [cr.truncate_normalize([1, 0, 0, 0])])
    monkeypatch.setattr(cr, "embed", lambda texts, **kw: [])   # Ollama down
    assert cr.top_passages("anything") == []
    assert cr.embed([]) == []


def test_build_skips_indexed_low_quality_and_short(monkeypatch, tmp_path):
    cr = _use_tmp(monkeypatch, tmp_path)
    cr._append([{"clause_id": "old#p0", "doc_id": "old", "text": "x" * 50}], [cr.truncate_normalize([1, 0, 0, 0])])
    pages = [[{"clause_id": "old#p0", "doc_id": "old", "text": "x" * 50},
              {"clause_id": "new#p0", "doc_id": "new", "heading": "h", "text": "y" * 50, "source_url": "u"},
              {"clause_id": "bad#p0", "doc_id": "bad", "text": "z" * 50},
              {"clause_id": "short#p0", "doc_id": "new", "text": "tiny"}], []]
    calls = {"n": 0}

    def fake_select(table, params=None, timeout=40):
        if table == "corpus_documents":
            return [{"doc_id": "new", "title": "New Doc", "jurisdiction_id": "NY", "low_quality": False},
                    {"doc_id": "bad", "title": "Bad", "low_quality": True}] if int(params.get("offset", 0)) == 0 else []
        calls["n"] += 1
        return pages.pop(0) if pages else []
    monkeypatch.setattr(cr.corpus_db, "select", fake_select)
    monkeypatch.setattr(cr, "embed", lambda texts, **kw: [cr.truncate_normalize([0, 1, 0, 0]) for _ in texts])
    out = cr.build_index(log=lambda *a: None)
    assert out["added"] == 1 and out["skipped"] == 3 and out["total"] == 2
    meta = [json.loads(l) for l in open(str(tmp_path / "meta.jsonl"))]
    assert meta[-1]["clause_id"] == "new#p0" and meta[-1]["doc_title"] == "New Doc" and meta[-1]["jurisdiction"] == "NY"
    assert os.path.getsize(str(tmp_path / "vectors.f32")) == 2 * 4 * 4
