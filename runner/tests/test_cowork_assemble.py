import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cowork_assemble


class CoworkAssembleTests(unittest.TestCase):
    def test_uses_canonical_prompt_assembler_signature(self):
        calls = []
        assembler = types.SimpleNamespace(
            assemble=lambda body, **kw: calls.append((body, kw)) or {
                "prompt": "ENRICHED", "layers": ["contract", "precedent"]
            }
        )
        contract = types.SimpleNamespace(original_request=lambda prompt: "BODY:" + prompt)
        fake_db = types.SimpleNamespace(select=lambda *_a, **_k: [{
            "id": "t", "prompt": "raw", "kind": "build", "slug": "s", "material": False,
        }])
        with mock.patch.dict(sys.modules, {"prompt_assembler": assembler,
                                           "pipeline_contract": contract}), \
             mock.patch.object(cowork_assemble, "_safe_import", return_value=fake_db):
            prompt, layers = cowork_assemble.get_enriched_prompt(
                "t", "s", "build", 1, "/repo", "p", "app"
            )
        self.assertEqual(prompt, "ENRICHED")
        self.assertEqual(layers, ["contract", "precedent"])
        self.assertEqual(calls[0][0], "BODY:raw")
        self.assertEqual(calls[0][1]["project"], "app")
        self.assertEqual(calls[0][1]["task"]["id"], "t")

    def test_model_router_receives_text_and_attempt(self):
        calls = []
        router = types.SimpleNamespace(
            route=lambda text, attempt: calls.append((text, attempt)) or {
                "model": "fast", "reason": "learned"
            }
        )
        with mock.patch.dict(sys.modules, {"model_router": router}):
            model, reason = cowork_assemble.get_model_suggestion("bugfix", 2, "repair")
        self.assertEqual((model, reason), ("fast", "learned"))
        self.assertEqual(calls, [("bugfix repair", 2)])


if __name__ == "__main__":
    unittest.main()
