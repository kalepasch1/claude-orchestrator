"""local_llm / local_research — no network, no models."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def _state(model="M", runner_states=("RunnerReady",), extra_runners=("RunnerShuttingDown",)):
    runners = {f"r{i}": {s: {}} for i, s in enumerate(runner_states)}
    runners.update({f"x{i}": {s: {}} for i, s in enumerate(extra_runners)})
    return {"instances": {"i1": {"MlxRingInstance": {
        "shardAssignments": {"modelId": model, "nodeToRunner": {f"n{i}": f"r{i}" for i in range(len(runner_states))}}}}},
        "runners": runners}


def test_instance_readiness_ignores_runners_of_other_instances(monkeypatch):
    import local_llm as L
    assert L.exo_instance_ready("M", state=_state()) is True           # stale RunnerShuttingDown ignored
    # a runner mid-request is serving, not gone
    assert L.exo_instance_ready("M", state=_state(runner_states=("RunnerRunning",))) is True
    assert L.exo_instance_ready("M", state=_state(runner_states=("RunnerReady", "RunnerRunning"))) is True
    assert L.exo_instance_ready("M", state=_state(runner_states=("RunnerIdle",))) is False
    assert L.exo_instance_ready("M", state=_state(runner_states=("RunnerReady", "RunnerLoading"))) is False
    assert L.exo_instance_ready("OTHER", state=_state()) is False
    assert L.exo_instance_ready("M", state={"instances": {}, "runners": {}}) is False


def test_ladder_prefers_resident_then_placeable(monkeypatch):
    import local_llm as L
    calls = []
    monkeypatch.setattr(L, "MODELS", ["exo:big", "ollama:mid", "exo:small"])
    monkeypatch.setattr(L, "resident", lambda p, m: m == "small")
    monkeypatch.setattr(L, "exo_placeable", lambda m: (m == "big", "planner says so"))
    monkeypatch.setattr(L, "free_gb", lambda: 40.0)
    monkeypatch.setattr(L, "need_gb", lambda m: 24)
    monkeypatch.setattr(L, "_telemetry", lambda *a, **k: None)

    def backend(model, system, user, schema, max_tokens, temperature, timeout):
        calls.append(model)
        return {"text": '{"ok": 1}', "tokens_in": 10, "tokens_out": 5}
    monkeypatch.setitem(L._BACKENDS, "exo", backend)
    monkeypatch.setitem(L._BACKENDS, "ollama", backend)
    r = L.chat("q", json_schema={"type": "object"})
    assert calls == ["small"] and r["json"] == {"ok": 1} and r["provider"] == "exo"


def test_every_rung_skipped_reports_each_reason(monkeypatch):
    import local_llm as L
    monkeypatch.setattr(L, "MODELS", ["exo:big", "ollama:mid"])
    monkeypatch.setattr(L, "resident", lambda p, m: False)
    monkeypatch.setattr(L, "exo_placeable", lambda m: (False, "No cycles found with sufficient memory"))
    monkeypatch.setattr(L, "free_gb", lambda: 8.0)
    monkeypatch.setattr(L, "need_gb", lambda m: 24)
    r = L.chat("q")
    assert r["text"] == "" and "No cycles" in r["error"] and "needs 24 GiB, 8.0 free" in r["error"]
    assert [a["model"] for a in r["attempts"]] == ["exo:big", "ollama:mid"]


def test_strip_thinking_and_json_extraction():
    import local_llm as L
    assert L.strip_thinking("<think>plan</think>  answer ") == "answer"
    assert L.strip_thinking("a<think>x</think>b<think>y</think>c") == "abc"


PAGE = ("Sec. 1022.380 Registration of money services businesses. Except as provided in paragraph (a)(3), "
        "each money services business must register with FinCEN within 180 days after the date the business is established. "
        "Unrelated sentence about postal rates and stamps.")


def test_quote_is_a_verbatim_span_and_verification_is_bytes(monkeypatch):
    import local_research as R
    q = R.best_quote(PAGE, "When must a money services business register with FinCEN?")
    assert q and q in PAGE and R.verified(q, PAGE)
    assert len(q.split(" ")) <= 40
    assert not R.verified("must register with FinCEN within 90 days", PAGE)   # altered text fails
    assert not R.verified("short", PAGE)


def test_citation_resolution_by_rule():
    import local_research as R
    got = {c["authority"]: c["url"] for c in R.resolve(
        "31 CFR 1022.380 and 31 U.S.C. § 5330 and 23 NYCRR 200.3 and NY Banking Law § 641 and doc 2026-07033")}
    assert got["31 CFR 1022.380"] == "https://www.law.cornell.edu/cfr/text/31/1022.380"
    assert got["31 U.S.C. § 5330"] == "https://www.law.cornell.edu/uscode/text/31/5330"
    assert got["23 NYCRR 200.3"].endswith("23-NYCRR-200.3")
    assert got["NY Banking Law § 641"] == "https://www.nysenate.gov/legislation/laws/BNK/641"
    assert got["Federal Register doc. 2026-07033"].endswith("2026-07033.json")
    assert R.resolve("a general discussion of money transmission") == []


def test_build_dossier_verifies_and_reports_unresolvable(monkeypatch):
    import local_research as R
    monkeypatch.setattr(R, "spot", lambda q, c="", chat=None: (["licensing"], ["31 CFR 1022.380", "Some Agency Letter 2019-1"]))
    monkeypatch.setattr(R, "corpus_authority", lambda c: None)
    fetched = {"https://www.law.cornell.edu/cfr/text/31/1022.380": PAGE}
    d, info = R.build("When must an MSB register with FinCEN?", fetcher=lambda u, timeout=25: fetched.get(u, ""),
                      authority_lookup=lambda c: None)
    assert info["verified_sources"] == 1 and info["cost_weighted"] == 0
    src = d["sources"][0]
    assert src["verified"] is True and src["quote"] in PAGE and src["excerpt"]
    assert any("Some Agency Letter" in u for u in d["unresolved"])
    assert "_pages" in d and d["_pages"][src["url"]] == PAGE
    # nothing verifiable -> no dossier at all
    d2, info2 = R.build("q", fetcher=lambda u, timeout=25: "", authority_lookup=lambda c: None)
    assert d2 is None and info2["error"]
