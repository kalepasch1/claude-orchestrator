"""A distillation that restates itself must not reach CLAUDE.md.

CLAUDE.md is the cached context prefix every task pays for. It had accumulated
five auto-appended "Learned from merged work" sections before this check existed,
and the newest was ten bullets of the form "Use a consistent naming convention
for <thing>, with a specific naming pattern" — shaped like a rule, teaching
nothing. The existing quality gate passed it, correctly by its own terms: it IS a
bulleted convention list, and a cheap model asked "is this a coding convention?"
answers yes. Nothing was checking whether the content said anything.

Vacuous guidance is worse than none. It is rented space in the prefix, and it
teaches every agent that this section can be skimmed.

The fixtures below are the REAL texts, not invented ones — the section that
leaked, and the section that should keep passing.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import learn_from_merges as lfm  # noqa: E402


# The section that leaked (verbatim shape, measured circularity 0.60).
CIRCULAR = """
* Use a consistent naming convention for branches, with a specific naming pattern (e.g. `dropbox-beethoven-madeus-web-group-3`)
* Use a specific naming convention for test files, including a specific naming pattern (e.g. `runner/tests/test_convention_class_naming.py`)
* Use a consistent naming convention for commits, with a specific naming pattern (e.g. `dropbox-release-pipeline-slice-4`)
* Merge branches using a specific naming pattern (e.g. `agent/backlog-batch-beethoven-a86bb21-slice-2`)
* Use a specific naming convention for authors (e.g. `kalepasch1 <kalepasch@gmail.com>`)
* DO: Use a consistent naming convention for all code and commits
* AVOID: Name branches and commits with arbitrary or generic names
* DO: Follow the specific naming pattern for branches, commits, and test files
* AVOID: Name test files with arbitrary or generic names
* DO: Use a consistent naming convention for authors and dates
"""

# Section 1 of the committed file (measured circularity 0.25) — names real
# mechanisms, and must keep passing.
SUBSTANTIVE = """
* Centralized configuration management: fleet-wide config changes go through a central `fleet_config` table.
* Safe config keys only: only config keys without secrets or credentials can be pushed fleet-wide.
* DB + git for synchronization: code updates are propagated between machines using git, and database operations through Supabase.
* Kill switches are read live rather than frozen at import, so a pause takes effect without a restart.
* Gateway fleet control: provider routing is decided in `model_policy`, not at each call site.
* DO: read `ORCH_*` knobs through the config helper so a change lands without a restart.
* AVOID: caching a config value at module scope.
* AVOID: writing credentials into `fleet_config`; that table is replicated fleet-wide.
"""


def test_the_circular_distillation_is_rejected():
    accepted, reason = lfm.quality_gate(CIRCULAR, source="test")
    assert not accepted, "the vacuous section that reached CLAUDE.md must be rejected now"
    assert "circular" in reason, reason


def test_the_substantive_distillation_still_passes_the_shape_checks():
    """Calibration: the check must not cost us the sections that were worth having.

    quality_gate also consults a cheap model, which is unavailable offline and
    returns 'no opinion' — so this asserts the circularity check specifically,
    rather than the whole gate, to stay hermetic.
    """
    assert lfm._circularity(SUBSTANTIVE) <= lfm._CIRCULARITY_LIMIT


def test_circularity_is_measured_and_ordered():
    assert lfm._circularity(CIRCULAR) > lfm._circularity(SUBSTANTIVE)


def test_too_few_bullets_is_never_called_circular():
    """A short list cannot be judged, so it must not be rejected by this check."""
    assert lfm._circularity("* one thing here\n* another thing here\n") == 0.0
