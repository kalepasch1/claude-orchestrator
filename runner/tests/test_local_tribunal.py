"""The local tribunal end to end with a fake model, a fake fetcher and a fake searcher."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

PAGE_A = ("Sec. 1010.100 General definitions. (ff) Money services business. A person wherever located doing business, "
          "whether or not on a regular basis or as an organized or licensed business concern, wholly or in substantial part "
          "within the United States, in one or more of the capacities listed in this section. (5) Money transmitter. "
          "A person that provides money transmission services. The term money transmission services means the acceptance "
          "of currency, funds, or other value that substitutes for currency from one person and the transmission of "
          "currency, funds, or other value that substitutes for currency to another location or person by any means. "
          "Whether a person is a money transmitter as described in this section is a matter of facts and circumstances. ") * 2
PAGE_B = ("Sec. 1022.380 Registration of money services businesses. (a) Registration requirement. Each money services "
          "business, whether or not licensed as a money services business by any State, must register with FinCEN. "
          "The registration form must be filed within 180 days after the date the business is established. "
          "A person that is a money services business solely because that person serves as an agent of another money "
          "services business is not required to register. ") * 2
PAGE_C = ("Sec. 1022.210 Anti-money laundering programs for money services businesses. (a) Each money services business "
          "shall develop, implement, and maintain an effective anti-money laundering program. The program shall be "
          "commensurate with the risks posed by the location and size of, and the nature and volume of the financial "
          "services provided by, the money services business. ") * 2
PAGE_D = ("Sec. 1010.100(ww) Prepaid access. Access to funds or the value of funds that have been paid in advance and can be "
          "retrieved or transferred at some point in the future through an electronic device or vehicle. A provider of "
          "prepaid access is a money services business and must register with FinCEN unless an exclusion applies. ") * 2
PAGES = {"https://www.law.cornell.edu/cfr/text/31/1010.100": PAGE_A, "https://www.law.cornell.edu/cfr/text/31/1022.380": PAGE_B,
         "https://www.law.cornell.edu/cfr/text/31/1022.210": PAGE_C, "https://example.gov/prepaid": PAGE_D}
QUESTION = ("Is a sweepstakes casino that redeems sweeps coins for cash a money transmitter that must register with FinCEN "
            "under 31 CFR 1022.380 and 31 CFR 1010.100, and must it maintain an anti-money laundering program?")
PANEL = [{"id": "e1", "public_label": "Textualist", "method": "textual", "domain": "finserv", "doctrine": "text first"},
         {"id": "e2", "public_label": "Enforcement Realist", "method": "realist", "domain": "finserv", "doctrine": "what FinCEN does"},
         {"id": "e3", "public_label": "Structurer", "method": "structuring", "domain": "finserv", "doctrine": "change the facts"}]


def fetcher(url):
    return PAGES.get(url, "")


def searcher(queries):
    return ([{"backend": "ecfr", "kind": "regulation", "jurisdiction": "US_FEDERAL", "authority": "31 CFR 1022.210",
              "title": "AML programs", "url": "https://www.law.cornell.edu/cfr/text/31/1022.210", "excerpt": "", "citable": True},
             {"backend": "fr", "kind": "rule", "jurisdiction": "US_FEDERAL", "authority": "Prepaid access rule",
              "title": "Prepaid access", "url": "https://example.gov/prepaid", "excerpt": "", "citable": True}],
            [{"backend": "caselaw", "authority": "Some v. Case (ca9, 2020)", "citable": False}])


class FakeModel:
    """Answers each stage from what it is shown, the way a well-behaved model would."""
    def __init__(self, name="mlx-community/Qwen3.5-27B-4bit", bad_quotes=False, overreach=False):
        self.name, self.calls, self.bad_quotes, self.overreach = name, [], bad_quotes, overreach

    def __call__(self, prompt, **kw):
        import re
        tag = kw.get("tag")
        self.calls.append(tag)
        out = {"model": self.name, "provider": "exo", "error": ""}
        if tag == "local.plan":
            j = {"premise_ok": True, "premise_problem": "", "restated_question": "Is the operator a money transmitter?",
                 "jurisdictions": ["US federal"],
                 "issues": ["money transmitter definition acceptance and transmission of value",
                            "registration requirement with FinCEN", "anti-money laundering program"],
                 "authorities": ["31 CFR 1010.100", "31 CFR 1022.380"],
                 "searches": [{"backend": "ecfr", "query": "anti-money laundering program money services business"}]}
        elif tag == "local.extract":
            fs = []
            for pid, text in re.findall(r"\[(P\d+)\][^\n]*\n([^\n]+)", prompt):
                sent = [s for s in re.split(r"(?<=[.])\s+", text) if len(s.split()) >= 8][0]
                quote = " ".join(sent.split()[:30])
                if self.bad_quotes:
                    quote = "the regulation plainly states that every operator everywhere is always a transmitter"
                fs.append({"passage": pid, "quote": quote, "says": "states the operative rule", "bears_on": "decides the issue"})
            j = {"findings": fs}
        elif tag == "local.seat":
            ids = sorted(set(re.findall(r"\[(F\d+)\]", prompt)), key=lambda x: int(x[1:]))
            claims = [{"claim": f"The rule in {i} applies to an operator that accepts and transmits value.", "findings": [i],
                       "kind": "direct"} for i in ids[:6]]
            claims.append({"claim": "State regulators will probably agree with this reading.", "findings": [], "kind": "assumption"})
            j = {"answer": "Yes if it accepts and transmits value; registration and an AML program follow.", "claims": claims,
                 "probability": 0.7, "missing": ["prepaid access exclusion"]}
        elif tag == "local.verify":
            ns = [int(n) for n in re.findall(r"(?m)^(\d+)\. CLAIM", prompt)]
            j = {"checks": [{"n": n, "verdict": ("overreach" if (self.overreach and n == 1) else "supported"),
                             "narrowed": ("The rule applies only where value is accepted and transmitted." if (self.overreach and n == 1) else "")}
                            for n in ns]}
        elif tag == "local.challenge":
            j = {"strongest_opposing_claim": "The agent exclusion may apply.", "from_seat": "Enforcement Realist", "moved": True,
                 "outcome": "partial", "final_answer": "Yes, subject to the agent exclusion.", "probability": 0.65}
        elif tag in ("local.chair", "local.revise"):
            ids = sorted(set(re.findall(r"\[(F\d+)\]", prompt)), key=lambda x: int(x[1:]))[:8]
            body = " ".join(f"The regulation requires registration and a program where value is transmitted [{i}]." for i in ids)
            j = {"verdict": "Yes, if the operator accepts and transmits value.", "memo": ("Answer: yes on these facts. " + body + " ") * 2,
                 "assumptions": ["State treatment was not in the record."], "dissent": "The agent exclusion may apply.",
                 "flips_if": "The operator only acts as an agent.", "conditions": "Facts as stated.", "unsettled": False,
                 "options": [{"option": "Use a licensed payments partner for redemption.", "posture": "conservative",
                              "findings": ids[:2], "abandon_if": "The partner exits."}]}
        elif tag == "local.ground":
            ns = [int(n) for n in re.findall(r"(?m)^(\d+)\. ", prompt.split("EVIDENCE LEDGER")[0])]
            ids = sorted(set(re.findall(r"\[(F\d+)\]", prompt)), key=lambda x: int(x[1:]))
            j = {"sentences": [{"n": n, "findings": ids[:1] if n % 2 else []} for n in ns]}
        elif tag == "local.adversary":
            j = {"breaks": False, "attack": "Agent exclusion not analysed in depth.", "missed_authority": "none",
                 "failing_fact_pattern": "pure agent", "severity": "moderate", "what_would_fix_it": "address the exclusion"}
        else:
            j = {}
        out["json"], out["text"] = j, json.dumps(j)
        return out


def _run(model, **kw):
    import local_tribunal as lt
    return lt.run(QUESTION, context="PRIORITY: medium", vertical="finserv", priority="medium", panel=PANEL,
                  chat=model, fetcher=fetcher, searcher=searcher, **kw)


def test_full_run_mints_a_grounded_memo(tmp_path, monkeypatch):
    import local_tribunal as lt
    monkeypatch.setattr(lt, "LEDGERS", str(tmp_path))
    monkeypatch.setattr(lt, "USE_CORPUS", False)
    monkeypatch.setattr(lt, "_other_models", lambda p: None)
    m = FakeModel()
    out = _run(m)
    assert out["abstain"] is False, out["reason"]
    memo, meta = out["j"]["memo"], out["meta"]
    assert len(memo["citations"]) >= 4 and all(c["verified"] for c in memo["citations"])
    pages = out["dossier"]["_pages"]
    for c in memo["citations"]:                       # every quote is a verbatim slice of a page we hold
        assert c["quote"] in pages[c["url"]]
    assert "F1" not in memo["memo"] and "[1]" in memo["memo"]          # finding ids became citation numbers
    assert 0.1 <= memo["confidence"] <= 0.85                             # computed, never 0.95
    assert meta["confidence_parts"]["claim_coverage"] == 1.0
    assert out["j"]["red_team"]["severity"] == "material" and out["j"]["adversary_done"]["revised"] is True
    assert out["j"]["bouts"] and out["j"]["bouts"][0]["grounds"].startswith("verified claims")
    assert memo["options"] and memo["options"][0]["posture"] == "conservative"
    assert any("example.gov/prepaid" in s["url"] for s in out["dossier"]["sources"])   # search found a source nobody named
    assert "local.plan" in m.calls and "local.verify" in m.calls and "local.revise" in m.calls


def test_small_model_does_the_research_and_abstains_from_the_memo(tmp_path, monkeypatch):
    import local_tribunal as lt
    monkeypatch.setattr(lt, "LEDGERS", str(tmp_path))
    monkeypatch.setattr(lt, "USE_CORPUS", False)
    monkeypatch.setattr(lt, "_other_models", lambda p: None)
    out = _run(FakeModel(name="mlx-community/Qwen3.5-9B-4bit"))
    assert out["abstain"] is True and "9B" in out["reason"]
    assert out["j"] is not None and out["meta"]["findings"] >= 4        # the work is kept
    assert os.listdir(str(tmp_path))                                    # and saved for reuse
    assert out["j"]["memo"]["confidence"] <= 0.60
    forced = _run(FakeModel(name="mlx-community/Qwen3.5-9B-4bit"), force=True)
    assert forced["abstain"] is False


def test_fabricated_quotes_never_become_findings(tmp_path, monkeypatch):
    import local_tribunal as lt
    monkeypatch.setattr(lt, "LEDGERS", str(tmp_path))
    monkeypatch.setattr(lt, "USE_CORPUS", False)
    monkeypatch.setattr(lt, "_other_models", lambda p: None)
    out = _run(FakeModel(bad_quotes=True))
    # The model's invented quotes are all refused. What enters the ledger instead is cut from the
    # pages mechanically, so every citation is still a verbatim slice of a page we hold.
    assert out["meta"]["phases"]["extract"]["by_model"] == 0
    assert out["meta"]["phases"]["extract"]["backfilled"] >= 1
    pages = (out.get("dossier") or {}).get("_pages") or {}
    for c in ((out.get("j") or {}).get("memo") or {}).get("citations") or []:
        assert c["quote"] in pages[c["url"]] and "every operator everywhere" not in c["quote"]


def test_overreach_is_narrowed(tmp_path, monkeypatch):
    import local_tribunal as lt
    monkeypatch.setattr(lt, "LEDGERS", str(tmp_path))
    monkeypatch.setattr(lt, "USE_CORPUS", False)
    monkeypatch.setattr(lt, "_other_models", lambda p: None)
    out = _run(FakeModel(overreach=True))
    ledger = json.load(open(os.path.join(str(tmp_path), os.listdir(str(tmp_path))[0])))
    narrowed = [c for s in ledger["seats"] for c in s["claims"] if c["status"] == "narrowed"]
    assert narrowed and narrowed[0]["claim"].startswith("The rule applies only") and narrowed[0]["original"]


def test_locate_quote_exact_repair_and_refusal():
    import local_tribunal as lt
    p = "Each money services business, whether or not licensed by any State, must register with FinCEN. The form is due in 180 days."
    assert lt.locate_quote("must register with FinCEN", p) == "must register with FinCEN"
    fixed = lt.locate_quote("Each money service business whether or not licensed by any state must register with Fincen", p)
    assert fixed and fixed in p
    assert lt.locate_quote("operators are never required to do anything at all under this part", p) == ""
    assert lt.locate_quote("short", p) == ""


def test_size_parsing_and_severity():
    import local_tribunal as lt
    assert lt.size_b("mlx-community/Qwen3.5-35B-A3B-4bit") == 35 and lt.size_b("qwen3.5:27b-mlx") == 27
    assert lt.size_b("mlx-community/Qwen3.5-9B-4bit") == 9 and lt.size_b("local") == 0
    assert lt.norm_severity("Moderate") == "material" and lt.norm_severity("none") == "none"


def test_grounding_stats_counts_uncited_legal_sentences():
    import local_tribunal as lt
    st = lt.grounding_stats("The rule requires registration [F1]. The statute prohibits unlicensed transmission. It is sunny today.",
                            {"F1"})
    assert st["legal_sentences"] == 2 and st["cited_sentences"] == 1 and st["ratio"] == 0.5 and st["findings_used"] == ["F1"]


def test_passages_are_exact_slices_and_terms_drop_stopwords():
    import authority_search as a
    ps = a.passages(PAGE_B, a.terms("registration requirement with FinCEN agent"), k=2, width=300)
    assert ps and all(p["text"] in PAGE_B for p in ps)
    assert "the" not in a.terms("the registration of the business") and "registration" in a.terms("the registration of the business")
    assert a.passages("", ["x"]) == [] and a.passages(PAGE_B, []) == []


def test_playbook_is_optional(tmp_path, monkeypatch):
    import playbooks
    monkeypatch.setattr(playbooks, "DIR", str(tmp_path))
    assert playbooks.block("finserv", QUESTION) == "" and playbooks.exemplar("finserv", QUESTION) is None
    json.dump({"topics": [{"topic": "money transmission", "keywords": ["money transmitter", "fincen", "registration"],
                           "always_check": ["is value accepted and transmitted"],
                           "governing_authorities": [{"cite": "31 CFR 1010.100", "url": "https://www.law.cornell.edu/cfr/text/31/1010.100", "decides": "who is an MSB"}],
                           "false_premises": ["a state licence removes the federal duty"], "decision_rules": ["facts and circumstances"]}],
               "reasoning_moves": ["separate each regime's trigger"],
               "exemplars": [{"id": "x", "question": "Must a money transmitter register with FinCEN?", "verdict": "yes", "excerpt": "memo"}]},
              open(playbooks.path("finserv"), "w"))
    b = playbooks.block("finserv", QUESTION)
    assert "always check" in b and "31 CFR 1010.100" in b
    assert playbooks.authorities("finserv", QUESTION)[0]["url"].endswith("1010.100")
    assert playbooks.exemplar("finserv", QUESTION)["id"] == "x"


def test_ground_pass_ties_or_strikes_uncited_legal_sentences(monkeypatch):
    import local_tribunal as lt
    findings = [{"id": "F1", "authority": "31 CFR 1022.380", "quote": "must register with FinCEN", "says": "registration is required",
                 "url": "u", "issue": 0, "passage": "P1", "source": "S1"}]
    chair = {"memo": "The rule requires registration [F1]. The statute prohibits unlicensed activity in every state. "
                     "The regulation also requires a written program for every business.", "assumptions": []}

    def chat(prompt, **kw):
        tag = kw.get("tag")
        if tag == "local.ground":
            j = {"sentences": [{"n": 1, "findings": []}, {"n": 2, "findings": ["F1"]}]}
        else:
            j = {"checks": [{"n": 1, "verdict": "supported", "narrowed": ""}]}
        return {"json": j, "text": json.dumps(j), "model": "m-27B", "error": ""}
    out, gp = lt.ground_pass(lt.Calls(chat), chair, findings)
    assert gp == {"uncited": 2, "grounded": 1, "struck": 1, "ratio_before": gp["ratio_before"]}
    assert "every state" not in out["memo"] and any("every state" in a for a in out["assumptions"])
    assert "written program for every business [F1]." in out["memo"]
    assert lt.grounding_stats(out["memo"], {"F1"})["ratio"] == 1.0


def test_backfill_adds_only_verbatim_sentences():
    import local_tribunal as lt
    d = {"issues": ["registration requirement with FinCEN"],
         "passages": [{"id": "P1", "source": "S1", "url": "u", "authority": "31 CFR 1022.380", "issue": 0, "score": 9.0,
                       "text": PAGE_B[:600]}]}
    fs = []
    assert lt.backfill(d, fs, QUESTION) == 1
    assert fs[0]["quote"] in PAGE_B and fs[0]["mechanical"] is True and fs[0]["says"] == fs[0]["quote"][:400]
