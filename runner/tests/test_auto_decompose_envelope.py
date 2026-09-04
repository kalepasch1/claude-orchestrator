"""Decomposition must split the request, not the envelope that wraps it.

The gap this slice names is that tasks are decomposed "by a predefined set of rules".
The rules themselves are reasonable — split on numbered sub-items, split on file scope.
What was wrong is WHAT they read: every prompt is wrapped in a pipeline envelope (the
ORCHESTRATION PIPELINE CONTRACT, an AGENTIC-REPAIR DIRECTIVE, "Required completion
behavior:", a truncated prior diff), and those sections are full of numbered and bulleted
lines describing how the task will be ROUTED. Counting them as sub-items turns one brief
into several children that each restate the same envelope — which is what -slice-2,
-slice-3 and -slice-5 with no distinct content between them actually are.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_decompose as ad  # noqa: E402


ENVELOPE = """## ORCHESTRATION PIPELINE CONTRACT
- source: native-claim
- project: beethoven
- task class: mechanical (need 5, risk routine)
1. preflight triage
2. strategy planner
3. agentic coder
## END ORCHESTRATION PIPELINE CONTRACT

# Original improvement request
"""

TRAILER = """

AGENTIC-REPAIR DIRECTIVE
Repair category: rework

Required completion behavior:
1. Reproduce or inspect the concrete failure.
2. Repair the repo setup minimally.
3. Commit the final implementation on the task branch.

Failure context:
```
agent run failed after 3 error-retries
```
"""


class TestStripEnvelope:
    def test_the_contract_block_is_removed(self):
        body = ad.strip_envelope(ENVELOPE + "Fix the widget.")
        assert "ORCHESTRATION PIPELINE" not in body
        assert "Fix the widget." in body

    def test_the_trailing_directives_are_removed(self):
        body = ad.strip_envelope(ENVELOPE + "Fix the widget." + TRAILER)
        assert "AGENTIC-REPAIR DIRECTIVE" not in body
        assert "Required completion behavior" not in body
        assert "Failure context" not in body
        assert "Fix the widget." in body

    def test_a_prompt_without_an_envelope_is_unchanged(self):
        plain = "1. Do X\n\n2. Do Y\n\n3. Do Z"
        assert ad.strip_envelope(plain) == plain

    def test_an_all_envelope_prompt_keeps_its_text(self):
        """Never return nothing — an empty body would hide the task entirely."""
        assert ad.strip_envelope(ENVELOPE).strip()

    @pytest.mark.parametrize("prompt", [None, "", 7, []])
    def test_never_raises(self, prompt):
        ad.strip_envelope(prompt)


class TestNumberedItemExtraction:
    def test_envelope_numbering_is_not_mistaken_for_sub_items(self):
        prompt = ENVELOPE + "Fix the widget." + TRAILER
        assert ad.extract_numbered_items(prompt) == []

    def test_a_genuinely_enumerated_request_still_splits(self):
        prompt = ENVELOPE + ("1. Rename the handler.\n\n"
                             "2. Update its caller.\n\n"
                             "3. Add a regression test.\n") + TRAILER
        items = ad.extract_numbered_items(prompt)
        assert [i["num"] for i in items] == [1, 2, 3]
        assert "Rename the handler" in items[0]["text"]

    def test_a_bare_enumerated_prompt_is_unaffected(self):
        items = ad.extract_numbered_items("1. Alpha\n\n2. Beta\n\n3. Gamma")
        assert len(items) == 3


class TestDecomposeBehaviour:
    def test_an_enveloped_single_request_is_not_decomposed(self, monkeypatch):
        monkeypatch.setattr(ad, "_ENABLED", True)
        tasks = ad.decompose("do-the-thing", ENVELOPE + "Fix the widget." + TRAILER)
        assert len(tasks) == 1
        assert tasks[0]["slug"] == "do-the-thing"

    def test_a_genuinely_enumerated_request_still_decomposes(self, monkeypatch):
        monkeypatch.setattr(ad, "_ENABLED", True)
        prompt = ENVELOPE + ("1. Rename the handler.\n\n"
                             "2. Update its caller.\n\n"
                             "3. Add a regression test.\n") + TRAILER
        tasks = ad.decompose("do-the-thing", prompt)
        assert [t["slug"] for t in tasks] == [
            "do-the-thing-item-1", "do-the-thing-item-2", "do-the-thing-item-3"]

    def test_a_decomposition_child_is_still_never_re_decomposed(self, monkeypatch):
        monkeypatch.setattr(ad, "_ENABLED", True)
        prompt = "1. Alpha\n\n2. Beta\n\n3. Gamma"
        assert len(ad.decompose("parent-slice-2", prompt)) == 1

    def test_should_decompose_agrees_with_decompose(self, monkeypatch):
        monkeypatch.setattr(ad, "_ENABLED", True)
        enveloped = ENVELOPE + "Fix the widget." + TRAILER
        assert ad.should_decompose(enveloped, "do-the-thing") is False
        listed = ENVELOPE + "1. A\n\n2. B\n\n3. C\n" + TRAILER
        assert ad.should_decompose(listed, "do-the-thing") is True
