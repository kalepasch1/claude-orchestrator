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
        text = "Using key " + "sk-" + "abcdefghijklmnopqrstuvwxyz1234567890"
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

    def test_gemini_key(self):
        text = "GEMINI_API_KEY=AIzaSyD4bC9eF2gH5jK8mN1pQ4rS7tU0vW3xY6z fetch failed"
        result = redact_secrets(text)
        self.assertNotIn("AIzaSyD4bC9eF2", result)
        self.assertIn("[REDACTED]", result)

    def test_xai_key(self):
        text = "routing via xai-AbCdEfGhIjKlMnOpQrStUvWxYz012345 for grok"
        result = redact_secrets(text)
        self.assertNotIn("xai-AbCdEfGhIj", result)
        self.assertIn("[REDACTED]", result)

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


# --- the two ways a GitHub credential was still getting through ----------------


def test_a_bare_github_token_is_redacted_without_a_key_name():
    """The shape a PAT actually has when it leaks.

    Redaction used to require either a `token=` style key name or 20+ characters
    after the prefix. A PAT does not arrive that way: it arrives inside git's own
    error output, bare and often truncated. `ghp_` and its siblings cannot be
    anything but a GitHub credential, so a short one is still a credential.
    """
    from db import redact_secrets

    for token in ("ghp_error_token_123", "gho_shortish_one", "ghs_abcdefgh",
                  "github_pat_11ABCDEFG0abcdefghij"):
        assert token not in redact_secrets(token), token
        assert "[REDACTED]" in redact_secrets(token), token


def test_the_fleets_own_pat_variable_name_is_redacted():
    """ORCH_GIT_PAT is where THIS fleet keeps its GitHub credential.

    `pat` was not among the key names the generic key=value pattern knew, so
    `ORCH_GIT_PAT=<secret>` passed through untouched while `token=<same secret>`
    was caught — the redactor was blind to the one spelling this repo uses.
    """
    from db import redact_secrets

    redacted = redact_secrets("ORCH_GIT_PAT=ghp_a_real_looking_secret_value")
    assert "ghp_a_real_looking_secret_value" not in redacted
    assert "[REDACTED]" in redacted


def test_ordinary_prose_is_not_redacted():
    """The floor may not drop so far that documentation trips it."""
    from db import redact_secrets

    for benign in ("the ghp_ prefix identifies a GitHub token",
                   "rotate the token and the password after an incident",
                   "see docs/credentials.md for the pat rotation runbook"):
        assert redact_secrets(benign) == benign, benign
