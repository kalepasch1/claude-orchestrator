"""test_redact_secrets.py - verify secret hygiene redaction in db.py."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import redact_secrets


class TestRedactSecrets(unittest.TestCase):

    def test_anthropic_key(self):
        text = "error: ANTHROPIC_API_KEY=sk-ant-api03-DOPI6PjJh-6FFglea_k87prPIJmNt9pGvnr3oqKZCJz5ddsDTOJdErGLQNyu7By3DmwxHDPYWT6S-WB4Lrjk0g"
        result = redact_secrets(text)
        self.assertNotIn("sk-ant-api03", result)
        self.assertIn("[REDACTED]", result)

    def test_openai_key(self):
        text = "Using key sk-abcdefghijklmnopqrstuvwxyz1234567890"
        result = redact_secrets(text)
        self.assertNotIn("sk-abcdefghij", result)
        self.assertIn("[REDACTED]", result)

    def test_supabase_jwt(self):
        text = "SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSJ9.abc123def456ghi789"
        result = redact_secrets(text)
        self.assertNotIn("eyJhbGciOi", result)
        self.assertIn("[REDACTED]", result)

    def test_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature"
        result = redact_secrets(text)
        self.assertNotIn("eyJhbGciOi", result)

    def test_generic_api_key(self):
        text = "api_key=ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
        result = redact_secrets(text)
        self.assertNotIn("ABCDEFGHIJKLMNOP", result)

    def test_safe_text_unchanged(self):
        text = "task completed successfully with 0 errors"
        self.assertEqual(redact_secrets(text), text)

    def test_none_input(self):
        self.assertIsNone(redact_secrets(None))

    def test_empty_string(self):
        self.assertEqual(redact_secrets(""), "")

    def test_non_string(self):
        self.assertEqual(redact_secrets(42), 42)


if __name__ == "__main__":
    unittest.main()
