"""modules_during_import / import_with_stubs must leave sys.modules as they found it.

These are the sys.modules twin of during_import / import_with_env, added for the
other half of the leak runner/tests/test_sys_modules_shadowing.py freezes: a
module-scope `sys.modules["db"] = fake` is not scoped to the file that writes it,
because pytest imports every test module during collection.

A restore helper that does not restore is worse than no helper -- it looks like
the fix while being the bug -- so every one of these asserts on sys.modules after
the block, including the "the name was absent before" case that a naive
save-and-put-back gets wrong.
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from env_during_import import import_with_stubs, modules_during_import

ABSENT = "a_module_name_nothing_has_ever_imported"


def _stub(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


class ModulesDuringImport(unittest.TestCase):
    def test_the_stub_is_visible_inside_the_block(self):
        fake = _stub("db", marker="stub")
        with modules_during_import(db=fake):
            self.assertIs(sys.modules["db"], fake)

    def test_a_real_module_is_put_back_afterwards(self):
        import db as real_db
        with modules_during_import(db=_stub("db")):
            pass
        self.assertIs(sys.modules["db"], real_db)

    def test_a_name_that_was_absent_is_absent_again(self):
        """The case a naive save/restore gets wrong: None is not 'no entry'."""
        self.assertNotIn(ABSENT, sys.modules)
        with modules_during_import(**{ABSENT: _stub(ABSENT)}):
            self.assertIn(ABSENT, sys.modules)
        self.assertNotIn(ABSENT, sys.modules)

    def test_restoration_survives_an_exception_in_the_block(self):
        import db as real_db
        with self.assertRaises(ValueError):
            with modules_during_import(db=_stub("db")):
                raise ValueError("boom")
        self.assertIs(sys.modules["db"], real_db)

    def test_several_stubs_are_all_restored(self):
        import db as real_db
        import log as real_log
        with modules_during_import(db=_stub("db"), log=_stub("log")):
            self.assertIsNot(sys.modules["db"], real_db)
            self.assertIsNot(sys.modules["log"], real_log)
        self.assertIs(sys.modules["db"], real_db)
        self.assertIs(sys.modules["log"], real_log)


class ImportWithStubs(unittest.TestCase):
    def test_the_imported_module_bound_the_stub(self):
        calls = []
        fake = _stub("db", select=lambda *a, **k: calls.append(a) or [])
        module = import_with_stubs("metaopt", db=fake)
        self.assertIs(module.db, fake)

    def test_the_process_keeps_neither_the_stub_nor_the_private_copy(self):
        import db as real_db
        before = sys.modules.get("metaopt")
        import_with_stubs("metaopt", db=_stub("db"))

        self.assertIs(sys.modules["db"], real_db)
        self.assertIs(sys.modules.get("metaopt"), before,
                      "the shared metaopt entry must be exactly what it was")

    def test_the_private_copy_is_not_the_shared_one(self):
        import metaopt as shared
        private = import_with_stubs("metaopt", db=_stub("db"))
        self.assertIsNot(private, shared)
        self.assertIsNot(private.db, shared.db)

    def test_a_failing_import_still_restores_everything(self):
        import db as real_db
        with self.assertRaises(ImportError):
            import_with_stubs("no_such_module_anywhere", db=_stub("db"))
        self.assertIs(sys.modules["db"], real_db)
        self.assertNotIn("no_such_module_anywhere", sys.modules)


if __name__ == "__main__":
    unittest.main()
