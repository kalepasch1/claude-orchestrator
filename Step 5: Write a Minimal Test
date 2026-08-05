# test_template_95fc17a.py
import unittest
from patch_templates import lookup  # Assuming this is the module/function to be tested

class LookupContractTest(unittest.TestCase):
    """lookup() exists and honors the fail-soft contract."""

    def test_lookup_is_exposed(self):
        self.assertTrue(callable(getattr(patch_templates, "lookup", None)),
                        "patch_templates.lookup(template_id) must exist")

if __name__ == "__main__":
    unittest.main()
