import differential_qa


def test_unchanged_baseline_type_failure_is_waived():
    base = "/tmp/base/pages/a.ts(10,2): error TS2322: Type string is not assignable to number"
    candidate = "/tmp/candidate/pages/a.ts(11,2): error TS2322: Type string is not assignable to number"
    assert differential_qa.compare(candidate, base)["allowed"] is True


def test_new_candidate_failure_is_blocked():
    base = "a.ts:1:2 error TS2322: Type string is not assignable to number"
    candidate = base + "\nb.ts:4:5 error TS2304: Cannot find name Widget"
    result = differential_qa.compare(candidate, base)
    assert result["allowed"] is False
    assert len(result["new"]) == 1


def test_timeout_and_dependency_failures_are_never_waived():
    assert differential_qa.compare("tests timed out after 300s", "tests timed out after 300s")["allowed"] is False
    assert differential_qa.compare("Cannot find module vue", "Cannot find module vue")["allowed"] is False
