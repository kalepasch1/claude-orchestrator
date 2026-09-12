"""A suffixed node_modules link must not kill a QA overlay.

The failure this closes, verbatim from the run that queued the task:

    could not create branch-exact QA overlay: unsafe archive member:
    node_modules~agent_cade-tribunal-counterparty-implement-login-step

`materialize` streams `git archive` into a disposable directory and refuses any
member that would land outside it. A `node_modules` link points at a shared
install outside the overlay, so it is correctly unsafe — which is exactly why
`_omittable_runtime_link` exists to skip it instead of raising.

That rule matched only the bare name `node_modules` or a `/node_modules`
suffix. Per-branch installs are linked as `node_modules~<slug>`, and such a link
was neither safe nor omittable, so the whole overlay died over a directory whose
contents QA never reads. Fail-soft is the convention in this runner: skip it,
record it, keep going.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import commit_overlay  # noqa: E402


class _Member:
    """The parts of a tarfile.TarInfo the safety checks actually read."""

    def __init__(self, name, *, sym=False, link="", dev=False, hard=False):
        self.name = name
        self.linkname = link
        self._sym = sym
        self._dev = dev
        self._hard = hard

    def isdev(self):
        return self._dev

    def issym(self):
        return self._sym

    def islnk(self):
        return self._hard


class OmittableRuntimeLinkTest(unittest.TestCase):
    def test_the_reported_member_is_omittable(self):
        member = _Member("node_modules~agent_cade-tribunal-counterparty-implement-login-step")
        self.assertTrue(
            commit_overlay._omittable_runtime_link(member),
            "the exact member from the reported failure still raises",
        )

    def test_plain_runtime_links_stay_omittable(self):
        for name in ("node_modules", ".env", ".env.local", "packages/core/node_modules"):
            self.assertTrue(commit_overlay._omittable_runtime_link(_Member(name)), name)

    def test_a_suffixed_link_nested_in_a_package_is_omittable(self):
        self.assertTrue(
            commit_overlay._omittable_runtime_link(_Member("packages/core/node_modules~agent_x"))
        )

    def test_leading_and_trailing_slashes_do_not_change_the_answer(self):
        self.assertTrue(commit_overlay._omittable_runtime_link(_Member("/node_modules/")))
        self.assertTrue(commit_overlay._omittable_runtime_link(_Member("node_modules~x/")))

    def test_real_source_is_never_omitted(self):
        # The rule must not become a hole: a source file whose path merely
        # mentions node_modules is repository content and has to be extracted.
        for name in (
            "runner/runner.py",
            "docs/node_modules.md",
            "src/node_modules_helper.py",
            "src/my_node_modules",
            "node_modules_notes.txt",
        ):
            self.assertFalse(commit_overlay._omittable_runtime_link(_Member(name)), name)

    def test_a_file_inside_a_runtime_link_is_not_omitted_by_this_rule(self):
        # Only the link itself is skipped. Anything under it never reaches the
        # stream, because the link is not extracted in the first place.
        self.assertFalse(
            commit_overlay._omittable_runtime_link(_Member("node_modules~x/pkg/index.js"))
        )

    def test_an_empty_name_is_not_omittable(self):
        self.assertFalse(commit_overlay._omittable_runtime_link(_Member("")))
        self.assertFalse(commit_overlay._omittable_runtime_link(_Member(None)))


class SafetyStillHoldsTest(unittest.TestCase):
    """The omit rule must not weaken the check it sits next to."""

    def setUp(self):
        self.destination = tempfile.mkdtemp()
        self.outside = tempfile.mkdtemp()

    def test_a_link_pointing_outside_is_still_unsafe(self):
        member = _Member("node_modules~agent_x", sym=True, link=self.outside)
        self.assertFalse(commit_overlay._safe_member(member, self.destination))

    def test_the_pair_now_resolves_to_omit_rather_than_raise(self):
        # This is the whole fix: unsafe AND omittable means skipped, and
        # `materialize` only raises when a member is unsafe and NOT omittable.
        member = _Member("node_modules~agent_x", sym=True, link=self.outside)
        unsafe = not commit_overlay._safe_member(member, self.destination)
        omittable = commit_overlay._omittable_runtime_link(member)
        self.assertTrue(unsafe and omittable)

    def test_an_escaping_path_that_is_not_a_runtime_link_still_raises(self):
        # The guard has to keep working: a traversal attempt is unsafe and NOT
        # omittable, so materialize still refuses it.
        member = _Member("../../etc/passwd")
        self.assertFalse(commit_overlay._safe_member(member, self.destination))
        self.assertFalse(commit_overlay._omittable_runtime_link(member))

    def test_a_device_member_is_never_safe(self):
        member = _Member("node_modules~x", dev=True)
        self.assertFalse(commit_overlay._safe_member(member, self.destination))

    def test_ordinary_content_is_safe(self):
        self.assertTrue(commit_overlay._safe_member(_Member("runner/runner.py"), self.destination))


if __name__ == "__main__":
    unittest.main()
