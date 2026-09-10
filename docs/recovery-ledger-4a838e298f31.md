# Recovery ledger — `4a838e298f31`

Audit fingerprint: `4a838e298f31f529077c8934a18562c8896e081af84b34529e3e08f7c89d3f11`
Task slug: `chatgpt-local-reconcile-beethoven-4a838e298f31`
Reconciled: 2026-09-10 · base `origin/master`

Every evidence source was treated as read-only. Nothing was deleted, reset,
cleaned, popped, or moved at its source; the three items that are not merged
here are preserved verbatim in `docs/recovered/4a838e298f31/` as `.py.txt`
(non-collectible by pytest) so their content is durable in git regardless of
what happens to the originating worktree.

## Result

6 evidence items, 0 UNKNOWN.

| # | Source | Item | Classification | Disposition |
|---|--------|------|----------------|-------------|
| 1 | `…-wt/dropbox-release-pipeline-completion-windows-half-l-slice-2-ensure-test-dependenc` | `requirements.txt` | SUPERSEDED_BY_NEWER | none — see below |
| 2 | `…-wt/improve-enhance-branch-management-with-automated-r-slice-2` | `runner/tests/test_adaptive_pipeline.py` | RECOVERABLE_VALUE | integrated on this branch (18 passed) |
| 3 | `…-wt/improve-enhanced-testing-pipeline-inspect-local-br-slice-2` | `runner/tests/test_adaptive_budget.py` | RECOVERABLE_VALUE | integrated on this branch (18 passed) |
| 4 | `…-wt/improve-enhance-test-automation-for-ci-cd-pipeli-slice-5` | `runner/tests/test_action_drafter.py` | CONFLICTED_NEEDS_FOCUSED_TASK | preserved as artifact + follow-up queued |
| 5 | `…-wt/improve-enhanced-testing-pipeline-fix-source-confi-slice-4` | `runner/tests/test_cross_project_templates.py` | CONFLICTED_NEEDS_FOCUSED_TASK | preserved as artifact + follow-up queued |
| 6 | `…-wt/improve-implement-real-time-queue-state-update-slice-5` | `runner/tests/test_adaptive_probe.py` | CONFLICTED_NEEDS_FOCUSED_TASK | preserved as artifact + follow-up queued |

All six worktrees were pinned at head `bcacf428ecb1dae850d2eab98400741cd5467ec0`
and every change was a single **untracked** file — no tracked file was modified,
so there is no diff to reconcile against master, only added content.

## Item 1 — `requirements.txt` · SUPERSEDED_BY_NEWER

The recorded path
`…-wt/dropbox-release-pipeline-completion-windows-half-l-slice-2-ensure-test-dependenc`
no longer exists on disk, so the working copy of the change is gone. It is not
lost value: the intent recorded in the slug ("ensure test dependenc[ies]") is
already satisfied on `origin/master`, whose `requirements.txt` header states
that the file "previously listed only requests/python-dotenv/prometheus-client"
and now carries the full set of packages imported by `runner/`, verified by
`python3 scripts/verify_deps.py`. Master is the newer and more complete
implementation, so it wins. No action.

## Items 2–3 — integrated

`test_adaptive_pipeline.py` (166 lines, 18 tests) and `test_adaptive_budget.py`
(189 lines, 18 tests) cover `runner/adaptive_pipeline.py` and
`runner/adaptive_budget.py`, both of which exist on master with no test file of
their own. Both suites were run against this branch's tree and are green in
~2.6s each with no network access. They are merged as-is; no edits were made to
the recovered content.

## Items 4–6 — conflicted, not merged

These three were run individually against the same tree and are **not**
mergeable in their current state. Merging them would turn the suite red for
every other agent, which the convention notes explicitly warn about, so each is
preserved as an artifact and handed to a focused follow-up task instead.

**`test_cross_project_templates.py`** — 2 failed, 22 passed. Both failures are
defects in the test, not in `runner/cross_project_templates.py`:

- `test_generalises_project_paths` asserts `"project/"` is in the normalised
  string, but `_normalize_intent` emits the uppercase placeholder `PROJECT/`.
- `test_lowercases_and_collapses_whitespace` asserts that `"fix the   bug"`
  (three spaces) survives normalisation, while the function under test
  collapses runs of whitespace to one space — which is what the test's own name
  says it should do. The assertion contradicts the behaviour it is named for.

**`test_adaptive_probe.py`** — 3 failed, 21 passed, and the file takes **52s**.
`test_probe_failure_returns_original` monkeypatches `mg.complete` to raise, then
expects `ap.inject` to return the prompt unchanged; the probe header is injected
anyway, so the patch is not reaching the call site `inject` actually uses. The
52s runtime for 24 tests strongly suggests the un-patched path is reaching a
live model provider, which no unit test should do.

**`test_action_drafter.py`** — **hangs**. It reached 25 of its tests and then
made no further progress for over five minutes before being killed. Same likely
cause as above: an unmocked call to a real provider with no timeout. A test that
never returns is worse than a failing one, because it wedges CI rather than
reporting.

The shared root cause across all three is worth fixing once rather than three
times: these suites patch a module attribute (`mg.complete`) that the code under
test does not resolve through at call time. The follow-up tasks should fix the
seam, not loosen the assertions.
