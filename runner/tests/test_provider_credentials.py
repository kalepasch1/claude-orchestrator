import os
import tempfile
import unittest
from unittest.mock import patch

import provider_credentials


class ProviderCredentialLoadingTest(unittest.TestCase):
    def test_standalone_loader_reads_only_allowlisted_credentials(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            handle.write("DEEPSEEK_API_KEY=sk-funded\n")
            handle.write("UNRELATED_SECRET=do-not-load\n")
            path = handle.name
        try:
            with patch.dict(os.environ, {}, clear=True):
                loaded = provider_credentials.load_local_env(path)
                self.assertEqual("sk-funded", os.environ.get("DEEPSEEK_API_KEY"))
                self.assertNotIn("UNRELATED_SECRET", os.environ)
                self.assertEqual(["DEEPSEEK_API_KEY"], loaded)
        finally:
            os.unlink(path)

    def test_loader_does_not_overwrite_process_credential(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            handle.write("DEEPSEEK_API_KEY=sk-file\n")
            path = handle.name
        try:
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-process"}, clear=True):
                provider_credentials.load_local_env(path)
                self.assertEqual("sk-process", os.environ["DEEPSEEK_API_KEY"])
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
