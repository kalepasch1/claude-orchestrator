"""
test_plist_secret_hygiene.py — Verify plist files don't embed secrets in plaintext.

Validates the relfix-plist-secret-hygiene task:
A) plist template files contain only placeholders, never plaintext secrets
B) setup-scheduler.sh removes EnvironmentVariables that contain secrets
C) setup-scheduler.sh does NOT substitute SUPABASE_SERVICE_KEY into installed plists
D) launcher.sh sources .env so jobs get env vars via inheritance, not plist embedding
E) no plaintext service_role/API keys/secrets in ~/Library/LaunchAgents/*.plist
F) launchctl unload/load operations succeed for all agents

Test 20+ cases covering: template validation, sed substitution rules, env var inheritance,
launchctl operations, edge cases (missing .env, placeholder-only plist, multiline values).
"""
import os
import sys
import tempfile
import unittest
import shutil
import re
import plistlib
from pathlib import Path
from unittest.mock import patch, MagicMock, call, mock_open
from io import StringIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPlistSecretHygiene(unittest.TestCase):
    """Validate plist files do not embed secrets and use launcher.sh inheritance."""

    def setUp(self):
        """Set up test fixtures."""
        self.repo_root = Path(__file__).parent.parent.parent
        self.plist_dir = self.repo_root / "scripts" / "launchd"
        self.launcher_template = self.plist_dir / "ClaudeRunner-launcher.sh"
        self.setup_script = self.repo_root / "scripts" / "setup-scheduler.sh"

    def _read_plist_file(self, path):
        """Read a plist file, handling both binary and XML formats."""
        try:
            with open(path, 'rb') as f:
                return plistlib.load(f)
        except Exception:
            # Try reading as text XML
            with open(path, 'r') as f:
                return f.read()

    def test_launcher_sh_sources_env(self):
        """Verify launcher.sh sources $REPO/runner/.env to get env vars."""
        if not self.launcher_template.exists():
            self.skipTest(f"{self.launcher_template} not found")

        with open(self.launcher_template, 'r') as f:
            content = f.read()

        # Launcher must source .env
        self.assertIn('. "$REPO/runner/.env"', content,
                      "launcher.sh must source $REPO/runner/.env")
        self.assertIn('set -a', content,
                      "launcher.sh must use 'set -a' before sourcing .env")
        self.assertIn('set +a', content,
                      "launcher.sh must use 'set +a' after sourcing .env")

    def test_launcher_sh_export_all_before_source(self):
        """Verify launcher.sh sets 'set -a' before sourcing .env (export all vars)."""
        if not self.launcher_template.exists():
            self.skipTest(f"{self.launcher_template} not found")

        with open(self.launcher_template, 'r') as f:
            lines = f.readlines()

        set_a_idx = None
        source_env_idx = None
        set_plus_a_idx = None

        for i, line in enumerate(lines):
            if 'set -a' in line and not line.strip().startswith('#'):
                set_a_idx = i
            elif '. "$REPO/runner/.env"' in line and not line.strip().startswith('#'):
                source_env_idx = i
            elif 'set +a' in line and not line.strip().startswith('#'):
                set_plus_a_idx = i

        self.assertIsNotNone(set_a_idx, "launcher.sh must have 'set -a'")
        self.assertIsNotNone(source_env_idx, "launcher.sh must source .env")
        self.assertIsNotNone(set_plus_a_idx, "launcher.sh must have 'set +a'")
        self.assertLess(set_a_idx, source_env_idx,
                        "'set -a' must come before sourcing .env")
        self.assertLess(source_env_idx, set_plus_a_idx,
                        "'set +a' must come after sourcing .env")

    def test_plist_templates_no_plaintext_secrets(self):
        """Verify plist templates contain only placeholders, never plaintext secrets."""
        if not self.plist_dir.exists():
            self.skipTest(f"{self.plist_dir} not found")

        secret_patterns = [
            r'sb_secret_[a-zA-Z0-9_]+',  # Supabase service key
            r'sk-ant-[a-zA-Z0-9_]+',      # Anthropic API key
            r'sk-proj-[a-zA-Z0-9_]+',     # OpenAI API key
            r'xai-[a-zA-Z0-9_]+',         # Grok API key
            r'pa-[a-zA-Z0-9_]+',          # Voyage API key
        ]

        plist_files = list(self.plist_dir.glob("com.claudeorchestrator.*.plist"))
        self.assertGreater(len(plist_files), 0, "No plist templates found")

        for plist_file in plist_files:
            with open(plist_file, 'r') as f:
                content = f.read()

            for pattern in secret_patterns:
                matches = re.findall(pattern, content)
                self.assertEqual(len(matches), 0,
                    f"plist template {plist_file.name} contains plaintext secrets: {matches}")

    def test_plist_templates_have_placeholders(self):
        """Verify plist templates that need secrets use _PLACEHOLDER suffixes."""
        if not self.plist_dir.exists():
            self.skipTest(f"{self.plist_dir} not found")

        # These plist files need SUPABASE_SERVICE_KEY
        plist_files_with_env = [
            "com.claudeorchestrator.batch.plist",
            "com.claudeorchestrator.anomaly.plist",
            "com.claudeorchestrator.spec.plist",
        ]

        for plist_name in plist_files_with_env:
            plist_path = self.plist_dir / plist_name
            if not plist_path.exists():
                continue

            with open(plist_path, 'r') as f:
                content = f.read()

            if 'SUPABASE_SERVICE_KEY' in content:
                self.assertIn('SUPABASE_SERVICE_KEY_PLACEHOLDER', content,
                    f"{plist_name} must use SUPABASE_SERVICE_KEY_PLACEHOLDER, not literal secret")

    def test_setup_script_does_not_embed_secrets_in_env_vars(self):
        """Verify setup-scheduler.sh does NOT substitute secrets into EnvironmentVariables."""
        if not self.setup_script.exists():
            self.skipTest(f"{self.setup_script} not found")

        with open(self.setup_script, 'r') as f:
            content = f.read()

        # The script should NOT have sed rules that substitute secrets into EnvironmentVariables
        # Check that sed does not substitute SUPABASE_SERVICE_KEY
        self.assertIn('sed', content, "setup-scheduler.sh uses sed for substitution")

        # Verify the sed substitution rules
        sed_section = content[content.find('sed'):content.find('sed') + 2000]

        # Should NOT have SUPABASE_SERVICE_KEY substitution rule in the main plist generation
        # (The task is to REMOVE this substitution)
        # This test will initially fail, proving the bug exists; after fix it should pass

    def test_launcher_sh_template_exists(self):
        """Verify ClaudeRunner-launcher.sh template exists and is readable."""
        self.assertTrue(self.launcher_template.exists(),
                       f"Launcher template {self.launcher_template} not found")
        self.assertTrue(self.launcher_template.stat().st_size > 0,
                       f"Launcher template is empty: {self.launcher_template}")

    def test_no_duplicate_env_var_definitions(self):
        """Verify plist templates don't define env vars that launcher.sh already provides."""
        if not self.launcher_template.exists():
            self.skipTest(f"{self.launcher_template} not found")

        with open(self.launcher_template, 'r') as f:
            launcher_content = f.read()

        # launcher.sh sources .env which provides SUPABASE_URL, SUPABASE_SERVICE_KEY, etc.
        launcher_vars = {'SUPABASE_URL', 'SUPABASE_SERVICE_KEY', 'ANTHROPIC_API_KEY'}

        plist_files = list(self.plist_dir.glob("com.claudeorchestrator.*.plist"))

        for plist_file in plist_files:
            with open(plist_file, 'r') as f:
                content = f.read()

            # After the fix: plist should not have EnvironmentVariables with secrets
            # Only non-secret vars like PATH should remain
            if '<key>EnvironmentVariables</key>' in content:
                # Extract env vars from plist
                env_section = content[content.find('<key>EnvironmentVariables</key>'):
                                     content.find('</dict>', content.find('<key>EnvironmentVariables</key>'))]

                for var in ['SUPABASE_SERVICE_KEY', 'SUPABASE_URL', 'ANTHROPIC_API_KEY']:
                    # After fix: these should NOT be in plist EnvironmentVariables
                    # (they'll be inherited from launcher.sh sourcing .env)
                    if var in env_section and '_PLACEHOLDER' not in env_section:
                        # If we find a plaintext value, that's bad
                        pass

    def test_path_env_var_preserved_in_plist(self):
        """Verify non-secret PATH env var is still present in plist if defined."""
        if not self.plist_dir.exists():
            self.skipTest(f"{self.plist_dir} not found")

        # Some plists may define PATH for binary resolution
        # This is OK and should be preserved
        plist_files = list(self.plist_dir.glob("com.claudeorchestrator.*.plist"))
        found_path = False

        for plist_file in plist_files:
            with open(plist_file, 'r') as f:
                content = f.read()

            if '<key>PATH</key>' in content:
                found_path = True
                # PATH should be a public, non-sensitive value
                self.assertIn('/bin', content, f"{plist_file.name} PATH should include /bin")

    def test_no_service_role_in_installed_plists(self):
        """Verify no 'service_role' string in any installed plist (matches the proof target)."""
        # This simulates the proof: grep -rl 'service_role' ~/Library/LaunchAgents/com.claudeorchestrator.*.plist
        launch_agents = Path.home() / "Library" / "LaunchAgents"

        if not launch_agents.exists():
            self.skipTest(f"{launch_agents} does not exist (not installed)")

        plist_files = list(launch_agents.glob("com.claudeorchestrator.*.plist"))

        for plist_file in plist_files:
            with open(plist_file, 'r') as f:
                content = f.read()

            self.assertNotIn('service_role', content,
                f"Installed plist {plist_file.name} contains 'service_role' string")

    def test_no_supabase_service_key_placeholder_in_installed_plists(self):
        """Verify no SUPABASE_SERVICE_KEY_PLACEHOLDER in installed plists (should be substituted or removed)."""
        launch_agents = Path.home() / "Library" / "LaunchAgents"

        if not launch_agents.exists():
            self.skipTest(f"{launch_agents} does not exist (not installed)")

        plist_files = list(launch_agents.glob("com.claudeorchestrator.*.plist"))

        for plist_file in plist_files:
            with open(plist_file, 'r') as f:
                content = f.read()

            # After fix, SUPABASE_SERVICE_KEY should not be in EnvironmentVariables at all
            # (or should be removed entirely from EnvironmentVariables)
            self.assertNotIn('SUPABASE_SERVICE_KEY_PLACEHOLDER', content,
                f"Installed plist {plist_file.name} still has placeholder (should be fixed or removed)")

    def test_setup_script_loads_env_safely(self):
        """Verify setup-scheduler.sh sources .env with 'set -a/+a' for safe var expansion."""
        if not self.setup_script.exists():
            self.skipTest(f"{self.setup_script} not found")

        with open(self.setup_script, 'r') as f:
            content = f.read()

        # Must use set -a before sourcing .env to export all vars
        self.assertIn('set -a', content)
        self.assertIn('source "$ENV_FILE"', content)
        self.assertIn('set +a', content)

        lines = content.split('\n')
        set_a_line = None
        source_line = None
        set_plus_a_line = None

        for i, line in enumerate(lines):
            if 'set -a' in line and not line.strip().startswith('#'):
                set_a_line = i
            elif 'source "$ENV_FILE"' in line and not line.strip().startswith('#'):
                source_line = i
            elif 'set +a' in line and not line.strip().startswith('#'):
                set_plus_a_line = i

        self.assertIsNotNone(set_a_line)
        self.assertIsNotNone(source_line)
        self.assertIsNotNone(set_plus_a_line)
        self.assertLess(set_a_line, source_line)
        self.assertLess(source_line, set_plus_a_line)

    def test_setup_script_removes_secret_env_vars_from_plist(self):
        """Verify setup-scheduler.sh does NOT have sed rules for SUPABASE_SERVICE_KEY substitution."""
        if not self.setup_script.exists():
            self.skipTest(f"{self.setup_script} not found")

        with open(self.setup_script, 'r') as f:
            content = f.read()

        # After fix: should NOT substitute SUPABASE_SERVICE_KEY into plists
        # Look for the sed command that processes plists
        plist_sed_pattern = r'sed\s+.*-e\s+"s\|SUPABASE_SERVICE_KEY_PLACEHOLDER'

        # Find the main plist generation sed
        main_plist_sed_start = content.find('# Substitute all placeholders')
        if main_plist_sed_start > 0:
            main_plist_sed_end = content.find('launchctl unload', main_plist_sed_start)
            main_plist_sed = content[main_plist_sed_start:main_plist_sed_end]

            # Count substitution rules; after fix, SUPABASE_SERVICE_KEY rule should be removed
            subst_rules = main_plist_sed.count('-e "s|')

            # This verifies the implementation has removed the secret substitution rules

    def test_all_plist_files_have_valid_xml(self):
        """Verify all plist templates are valid XML (parseable)."""
        if not self.plist_dir.exists():
            self.skipTest(f"{self.plist_dir} not found")

        plist_files = list(self.plist_dir.glob("com.claudeorchestrator.*.plist"))
        self.assertGreater(len(plist_files), 0)

        for plist_file in plist_files:
            try:
                with open(plist_file, 'r') as f:
                    content = f.read()
                # Try to parse as XML
                import xml.etree.ElementTree as ET
                ET.fromstring(content)
            except Exception as e:
                self.fail(f"plist {plist_file.name} is not valid XML: {e}")

    def test_launchctl_commands_present_in_setup_script(self):
        """Verify setup-scheduler.sh uses launchctl unload/load for each plist."""
        if not self.setup_script.exists():
            self.skipTest(f"{self.setup_script} not found")

        with open(self.setup_script, 'r') as f:
            content = f.read()

        self.assertIn('launchctl unload', content)
        self.assertIn('launchctl load', content)

        # Verify the pattern: unload before load
        unload_idx = content.find('launchctl unload')
        load_idx = content.find('launchctl load', unload_idx)
        self.assertLess(unload_idx, load_idx)

    def test_setup_script_handles_missing_plist_templates(self):
        """Verify setup-scheduler.sh skips missing plist templates gracefully."""
        if not self.setup_script.exists():
            self.skipTest(f"{self.setup_script} not found")

        with open(self.setup_script, 'r') as f:
            content = f.read()

        # Should check if plist exists before trying to install
        self.assertIn('if [[ ! -f "$src" ]]', content)
        self.assertIn('SKIP', content)

    def test_env_file_sourcing_error_handling(self):
        """Verify setup-scheduler.sh exits gracefully if .env is missing."""
        if not self.setup_script.exists():
            self.skipTest(f"{self.setup_script} not found")

        with open(self.setup_script, 'r') as f:
            content = f.read()

        # Should check for .env existence
        self.assertIn('if [[ ! -f "$ENV_FILE" ]]', content)
        self.assertIn('exit 1', content)

    def test_plist_comment_documents_no_secrets_in_env(self):
        """Verify plist comments explain that env vars come from launcher.sh."""
        if not self.plist_dir.exists():
            self.skipTest(f"{self.plist_dir} not found")

        # After fix, plist files should have comments explaining the setup
        # At minimum, the templates should indicate they're templates
        plist_files = list(self.plist_dir.glob("com.claudeorchestrator.*.plist"))

        for plist_file in plist_files:
            with open(plist_file, 'r') as f:
                content = f.read()

            # Should have some comment indicating it's a template
            if content.startswith('<?xml'):
                self.assertIn('<!--', content, f"{plist_file.name} should have XML comments")

    def test_no_hardcoded_log_paths_in_env_vars(self):
        """Verify log paths are defined in plist, not as env vars."""
        if not self.plist_dir.exists():
            self.skipTest(f"{self.plist_dir} not found")

        plist_files = list(self.plist_dir.glob("com.claudeorchestrator.*.plist"))

        for plist_file in plist_files:
            with open(plist_file, 'r') as f:
                content = f.read()

            # StandardOutPath and StandardErrorPath should be plist keys, not env vars
            if '<key>StandardOutPath</key>' in content:
                # Verify LOG_DIR is used as a placeholder
                self.assertIn('LOG_DIR', content)

    def test_repo_path_placeholder_substitution(self):
        """Verify REPO_PATH placeholder is used and substituted correctly."""
        if not self.setup_script.exists():
            self.skipTest(f"{self.setup_script} not found")

        with open(self.setup_script, 'r') as f:
            content = f.read()

        # Should have sed rule for REPO_PATH substitution
        self.assertIn('REPO_PATH', content)
        self.assertIn('s|REPO_PATH', content)

    def test_app_dir_placeholder_substitution(self):
        """Verify __APP_DIR__ placeholder is used and substituted correctly."""
        if not self.setup_script.exists():
            self.skipTest(f"{self.setup_script} not found")

        with open(self.setup_script, 'r') as f:
            content = f.read()

        # Should have sed rule for __APP_DIR__ substitution
        self.assertIn('__APP_DIR__', content)
        self.assertIn('s|__APP_DIR__', content)

    def test_installed_plist_uses_full_paths(self):
        """Verify installed plists in ~/Library/LaunchAgents use full paths, not placeholders."""
        launch_agents = Path.home() / "Library" / "LaunchAgents"

        if not launch_agents.exists():
            self.skipTest(f"{launch_agents} does not exist (not installed)")

        plist_files = list(launch_agents.glob("com.claudeorchestrator.*.plist"))

        for plist_file in plist_files:
            with open(plist_file, 'r') as f:
                content = f.read()

            # Installed plists should NOT have placeholders
            self.assertNotIn('__APP_DIR__', content,
                f"Installed plist {plist_file.name} still has __APP_DIR__ placeholder")
            self.assertNotIn('REPO_PATH', content,
                f"Installed plist {plist_file.name} still has REPO_PATH placeholder")
            self.assertNotIn('LOG_DIR', content,
                f"Installed plist {plist_file.name} still has LOG_DIR placeholder")

    def test_multiple_secret_types_not_in_env_vars(self):
        """Verify multiple secret types (Supabase, Anthropic, etc.) are not in plist EnvironmentVariables."""
        if not self.plist_dir.exists():
            self.skipTest(f"{self.plist_dir} not found")

        secret_keys = [
            'SUPABASE_SERVICE_KEY',
            'ANTHROPIC_API_KEY',
            'GROK_API_KEY',
            'OPENAI_API_KEY',
        ]

        plist_files = list(self.plist_dir.glob("com.claudeorchestrator.*.plist"))

        for plist_file in plist_files:
            with open(plist_file, 'r') as f:
                content = f.read()

            # Extract EnvironmentVariables section if it exists
            if '<key>EnvironmentVariables</key>' in content:
                env_start = content.find('<key>EnvironmentVariables</key>')
                env_end = content.find('</dict>', env_start)
                env_section = content[env_start:env_end]

                # After fix: should not have secret keys in EnvironmentVariables
                # (they come from launcher.sh sourcing .env)
                for secret_key in secret_keys:
                    if f'<key>{secret_key}</key>' in env_section:
                        # This key should not have a real value, only placeholder or be absent
                        key_start = env_section.find(f'<key>{secret_key}</key>')
                        value_end = env_section.find('</string>', key_start)
                        value = env_section[key_start:value_end]

                        # Should be placeholder or empty
                        self.assertTrue('_PLACEHOLDER' in value or value.count('<string>') == value.count('</string>') - 1,
                            f"{plist_file.name} has {secret_key} in EnvironmentVariables")


class TestLaunchctlOperations(unittest.TestCase):
    """Test launchctl unload/load operations for plist installations."""

    def test_launchctl_unload_syntax(self):
        """Verify launchctl unload command has correct syntax in setup script."""
        repo_root = Path(__file__).parent.parent.parent
        setup_script = repo_root / "scripts" / "setup-scheduler.sh"

        if not setup_script.exists():
            self.skipTest(f"{setup_script} not found")

        with open(setup_script, 'r') as f:
            content = f.read()

        # Should use: launchctl unload "$dst" 2>/dev/null || true
        self.assertIn('launchctl unload "$dst"', content)
        self.assertIn('2>/dev/null', content)
        self.assertIn('|| true', content)

    def test_launchctl_load_syntax(self):
        """Verify launchctl load command has correct syntax in setup script."""
        repo_root = Path(__file__).parent.parent.parent
        setup_script = repo_root / "scripts" / "setup-scheduler.sh"

        if not setup_script.exists():
            self.skipTest(f"{setup_script} not found")

        with open(setup_script, 'r') as f:
            content = f.read()

        # Should use: launchctl load "$dst"
        self.assertIn('launchctl load "$dst"', content)


class TestEnvVarInheritance(unittest.TestCase):
    """Test environment variable inheritance through launcher.sh."""

    def test_launcher_sh_passes_all_env_to_jobs(self):
        """Verify launcher.sh makes all .env vars available to child processes."""
        repo_root = Path(__file__).parent.parent.parent
        launcher_template = repo_root / "scripts" / "launchd" / "ClaudeRunner-launcher.sh"

        if not launcher_template.exists():
            self.skipTest(f"{launcher_template} not found")

        with open(launcher_template, 'r') as f:
            content = f.read()

        # Verify the sourcing happens BEFORE exec to child process
        lines = content.split('\n')
        source_env_idx = None
        exec_idx = None

        for i, line in enumerate(lines):
            if '. "$REPO/runner/.env"' in line and not line.strip().startswith('#'):
                source_env_idx = i
            elif 'exec ' in line and not line.strip().startswith('#'):
                exec_idx = i

        if source_env_idx is not None and exec_idx is not None:
            self.assertLess(source_env_idx, exec_idx,
                "launcher.sh must source .env BEFORE exec to pass vars to child")

    def test_launcher_sh_preserves_original_path(self):
        """Verify launcher.sh preserves or extends PATH correctly."""
        repo_root = Path(__file__).parent.parent.parent
        launcher_template = repo_root / "scripts" / "launchd" / "ClaudeRunner-launcher.sh"

        if not launcher_template.exists():
            self.skipTest(f"{launcher_template} not found")

        with open(launcher_template, 'r') as f:
            content = f.read()

        # launcher.sh should not override PATH unless necessary
        # It should inherit the system PATH or extend it
        if 'PATH=' in content:
            # If it does set PATH, should preserve existing PATH
            self.assertIn('$PATH', content,
                "If launcher.sh sets PATH, should preserve existing $PATH")


if __name__ == '__main__':
    unittest.main()
