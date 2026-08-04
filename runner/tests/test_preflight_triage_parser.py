"""Table-driven coverage for the preflight triage response parser.

Regression context: commit 5330cbec rewrote the triage prompt to demand a
three-part answer ("1. First line: YES or NO", "2. SCOPE DEFINITION:",
"3. AMBIGUITIES/CONCERNS:") but left the parser matching only a bare "YES" on
line 0. Every response in the format the prompt actually requests parsed as
actionable=False with an empty scope. 1,436 tasks were tagged "Preflight scope
concern: Not clearly defined" before it was caught, 18 days later.

Every row below is a shape the prompt itself invites, or a shape observed in
production task notes.
"""
import os
import sys

import pytest

RUNNER = os.path.dirname(os.path.dirname(__file__))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import preflight_gate

parse = preflight_gate._extract_scope_and_ambiguities


# (id, raw response, expected_actionable)
VERDICT_CASES = [
    # --- bare / historical shape that already worked -------------------------
    ("bare_yes",              "YES",                                   True),
    ("bare_no",               "NO",                                    False),
    # --- the shape the prompt literally asks for (all previously broken) -----
    ("numbered_yes",          "1. YES",                                True),
    ("numbered_no",           "1. NO",                                 False),
    ("numbered_paren_yes",    "1) YES",                                True),
    ("numbered_dot_space_no", "1 . NO",                                False),
    # --- markdown emphasis ---------------------------------------------------
    ("bold_yes",              "**YES**",                               True),
    ("bold_no",               "**NO**",                                False),
    ("numbered_bold_yes",     "1. **YES**",                            True),
    ("bold_numbered_yes",     "**1. YES**",                            True),
    ("italic_yes",            "_YES_",                                 True),
    ("code_yes",              "`YES`",                                 True),
    # --- leading whitespace --------------------------------------------------
    ("indented_yes",          "    YES",                               True),
    ("indented_no",           "\t  NO",                                False),
    ("blank_lines_then_yes",  "\n\n   YES",                            True),
    # --- punctuation after the verdict --------------------------------------
    ("colon_yes",             "YES: adds a retry wrapper",             True),
    ("emdash_yes",            "YES — adds retry to fetch.ts",     True),
    ("hyphen_no",             "NO - duplicate of an earlier task",     False),
    ("comma_yes",             "YES, this is a concrete change",        True),
    ("period_no",             "NO.",                                   False),
    # --- case variants -------------------------------------------------------
    ("lower_yes",             "yes",                                   True),
    ("lower_no",              "no",                                    False),
    ("mixed_yes",             "Yes",                                   True),
    ("mixed_numbered_no",     "1. No",                                 False),
    # --- labelled verdicts ---------------------------------------------------
    ("answer_label_yes",      "Answer: YES",                           True),
    ("verdict_label_no",      "Verdict: NO",                           False),
    ("firstline_label_yes",   "First line: YES",                       True),
    # --- word-boundary guards: must NOT be read as a verdict -----------------
    ("yesterday_not_yes",     "YESTERDAY this task was filed",         False),
    ("nothing_not_no",        "Nothing here is concrete",              False),
    ("notes_not_no",          "NOTES: the task is under-specified",    False),
    # --- degenerate inputs ---------------------------------------------------
    ("empty",                 "",                                      False),
    ("whitespace_only",       "   \n\t ",                              False),
    ("none_input",            None,                                    False),
]


@pytest.mark.parametrize("case_id,raw,expected", VERDICT_CASES,
                         ids=[c[0] for c in VERDICT_CASES])
def test_verdict_parsing(case_id, raw, expected):
    actionable, _scope, _amb = parse(raw)
    assert actionable is expected, f"{case_id}: parsed {actionable!r} for {raw!r}"


# The exact three-part answer the triage prompt asks for.
PROMPT_SHAPE = """1. YES
2. SCOPE DEFINITION: Add a retry wrapper around the fetch call in
lib/odds.ts and surface the failure in components/OddsTable.tsx.
3. AMBIGUITIES/CONCERNS: Retry budget is unspecified.
The task does not say whether to retry on 4xx."""

MARKDOWN_SHAPE = """**YES**

**SCOPE DEFINITION:** Update `server/utils/rate-limit.ts` to read the window
from config.

**AMBIGUITIES/CONCERNS:**
- No default window is given.
- Unclear whether existing callers must migrate.
"""

SHORT_HEADERS = """YES
SCOPE: Bump the pinned pnpm version in package.json.
AMBIGUITIES: None
"""

# Observed verbatim in production task notes (the ~3% that happened to parse).
REAL_CAPTURED = """NO
SCOPE DEFINITION: No concrete file/component scope can be derived from this
prompt. The task references "Foulkon gradient," "shared contracts," and "the
graph" without naming a repository path.
AMBIGUITIES/CONCERNS: Referenced entities are undefined; no target repo.
"""

# Same content, but wearing the numbering the prompt asks for — this is the
# variant that produced "Not clearly defined" for 1,436 tasks.
REAL_CAPTURED_NUMBERED = """1. NO
2. SCOPE DEFINITION: No concrete file/component scope can be derived from this
prompt. The task references "Foulkon gradient" without naming a repository path.
3. AMBIGUITIES/CONCERNS: Referenced entities are undefined; no target repo.
"""


def test_prompt_shape_extracts_all_three_parts():
    actionable, scope, amb = parse(PROMPT_SHAPE)
    assert actionable is True
    assert "lib/odds.ts" in scope and "OddsTable.tsx" in scope
    assert "SCOPE" not in scope and "AMBIGUITIES" not in scope
    assert len(amb) == 2
    assert "Retry budget is unspecified." in amb


def test_markdown_shape_extracts_bulleted_ambiguities():
    actionable, scope, amb = parse(MARKDOWN_SHAPE)
    assert actionable is True
    assert "server/utils/rate-limit.ts" in scope
    assert amb == ["No default window is given.",
                   "Unclear whether existing callers must migrate."]


def test_short_headers_and_placeholder_ambiguities_are_dropped():
    actionable, scope, amb = parse(SHORT_HEADERS)
    assert actionable is True
    assert scope == "Bump the pinned pnpm version in package.json."
    assert amb == [], "literal 'None' must not be recorded as an ambiguity"


def test_real_captured_output_still_parses():
    actionable, scope, amb = parse(REAL_CAPTURED)
    assert actionable is False
    assert scope.startswith("No concrete file/component scope")
    assert amb and "undefined" in amb[0]


def test_real_captured_output_with_numbering_now_parses_identically():
    """The regression case: numbering must not erase the scope."""
    plain = parse(REAL_CAPTURED)
    numbered = parse(REAL_CAPTURED_NUMBERED)
    assert numbered[0] is plain[0] is False
    assert numbered[1], "numbered variant produced an empty scope (the 1,436-task bug)"
    assert "Foulkon gradient" in numbered[1]
    assert numbered[2] == plain[2]


def test_verdict_tail_becomes_scope_when_no_section_given():
    actionable, scope, amb = parse("YES — adds retry to fetch.ts")
    assert actionable is True
    assert scope == "adds retry to fetch.ts"
    assert amb == []


def test_unrelated_allcaps_header_closes_the_section():
    actionable, scope, amb = parse(
        "1. YES\n"
        "2. SCOPE DEFINITION: Edit app/page.tsx.\n"
        "3. AMBIGUITIES/CONCERNS: None\n"
        "4. RECOMMENDATION: proceed with the smallest diff\n")
    assert actionable is True
    assert scope == "Edit app/page.tsx."
    assert amb == [], "trailing RECOMMENDATION must not leak into ambiguities"


def test_verdict_buried_behind_a_preamble_is_still_found():
    actionable, scope, _amb = parse(
        "Here is my analysis of the task.\n\n"
        "1. YES\n"
        "2. SCOPE DEFINITION: Add tests for parseOdds().\n")
    assert actionable is True
    assert scope == "Add tests for parseOdds()."


def test_sections_without_a_verdict_default_to_not_actionable():
    actionable, scope, _amb = parse("SCOPE DEFINITION: Something vague.")
    assert actionable is False, "missing verdict must fail safe"
    assert scope == "Something vague."


# --- liveness assertion ------------------------------------------------------
# The defect class: a gate that returns one verdict for >95% of inputs is not
# gating, and looks identical to "the fleet queued a lot of vague tasks".

check = preflight_gate.check_liveness


def test_liveness_alarms_on_the_historical_all_no_window():
    """The exact production distribution: 97.0% NO over 1,480 inputs."""
    window = [False] * 1436 + [True] * 44
    alarm, detail = check(window)
    assert alarm is True
    assert "NO" in detail and "97" in detail


def test_liveness_alarms_symmetrically_on_an_all_yes_window():
    alarm, detail = check([True] * 200)
    assert alarm is True
    assert "YES" in detail


def test_liveness_quiet_on_a_discriminating_window():
    window = ([True] * 60) + ([False] * 140)   # 70% NO — skewed but discriminating
    alarm, detail = check(window)
    assert alarm is False
    assert "OK" in detail


def test_liveness_boundary_is_strictly_greater_than_threshold():
    at_threshold = [False] * 95 + [True] * 5          # exactly 95.0%
    over_threshold = [False] * 96 + [True] * 4        # 96.0%
    assert check(at_threshold)[0] is False, "95% exactly must not alarm"
    assert check(over_threshold)[0] is True


def test_liveness_holds_fire_until_the_window_fills():
    alarm, detail = check([False] * 10)
    assert alarm is False
    assert "not yet evaluable" in detail


def test_liveness_thresholds_are_overridable():
    window = [False] * 8 + [True] * 2                 # 80% NO
    assert check(window, threshold=0.95, min_samples=5)[0] is False
    assert check(window, threshold=0.70, min_samples=5)[0] is True


def test_record_verdicts_dispatches_an_alarm(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight_gate, "_LIVENESS_STATE",
                        str(tmp_path / "verdicts.json"))
    sent = []
    fake = type("A", (), {"alert": staticmethod(
        lambda pattern, project_id="", detail="", severity="":
        sent.append((pattern, severity)) or True)})
    monkeypatch.setitem(sys.modules, "error_alerter", fake)

    alarm, _ = preflight_gate.record_verdicts([False] * 100)
    assert alarm is True
    assert sent == [("preflight_gate_not_discriminating", "high")]

    # window persists across cycles, so a healthy cycle can clear the alarm
    alarm, _ = preflight_gate.record_verdicts([True] * 100)
    assert alarm is False


def test_record_verdicts_survives_an_unwritable_state_path(monkeypatch):
    monkeypatch.setattr(preflight_gate, "_LIVENESS_STATE",
                        "/proc/definitely/not/writable/verdicts.json")
    alarm, detail = preflight_gate.record_verdicts([False] * 100)
    assert alarm is True and detail
