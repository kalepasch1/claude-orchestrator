"""No merge-conflict markers may be committed to a source file.

Four hisanta files reached master with `<<<<<<<` still in them. They were therefore not
valid Python: `import hisanta` raised SyntaxError and three test modules could not be
collected at all — the suite reported "3 errors" for months while the underlying cause
was one unfinished merge. This guard makes that state fail loudly, immediately.
"""
import os
import sys

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(RUNNER, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import resolve_conflict_markers as rcm  # noqa: E402

OURS = "<<<<<<< HEAD\nkeep me\n=======\ndrop me\n>>>>>>> branch\n"


def test_repository_has_no_conflict_markers():
    marked = rcm.find_marked(RUNNER)
    assert marked == [], "committed conflict markers: " + ", ".join(marked)


def test_hisanta_imports_cleanly():
    """The concrete breakage: this raised SyntaxError before the resolution."""
    if RUNNER not in sys.path:
        sys.path.insert(0, RUNNER)
    import hisanta  # noqa: F401
    from hisanta.contracts.family import CoppaConsent, constitution_check  # noqa: F401
    assert constitution_check("charge_child").name == "DENY"


def test_resolver_keeps_the_requested_side():
    assert rcm.resolve(OURS, "ours") == "keep me\n"
    assert rcm.resolve(OURS, "theirs") == "drop me\n"


def test_resolver_preserves_surrounding_text():
    text = "before\n" + OURS + "after\n"
    assert rcm.resolve(text, "ours") == "before\nkeep me\nafter\n"


def test_resolver_handles_multiple_hunks():
    assert rcm.resolve(OURS + OURS, "ours") == "keep me\nkeep me\n"


def test_unterminated_hunk_is_left_alone():
    """A truncated conflict is for a human — never half-resolve one."""
    broken = "<<<<<<< HEAD\nsomething\n"
    assert rcm.resolve(broken, "ours") == broken


def test_has_markers_detects_both_delimiters():
    assert rcm.has_markers("<<<<<<< HEAD") is True
    assert rcm.has_markers(">>>>>>> branch") is True
    assert rcm.has_markers("a = 1\n") is False
    assert rcm.has_markers("shift = a >>>>>>> 2") is False
