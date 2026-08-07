"""Tests for lint rule generation from CLAUDE.md."""

import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from generate_lint_rules import (
    extract_do_avoid_rules,
    map_rules_to_ruff_codes,
    generate_ruff_toml,
)


class TestExtractDoAvoidRules:
    """Test extraction of DO/AVOID rules from CLAUDE.md."""

    def test_extract_rules_from_real_file(self):
        """Extract DO/AVOID rules from actual CLAUDE.md."""
        repo_root = Path(__file__).parent.parent
        claude_md = repo_root / 'CLAUDE.md'

        if claude_md.exists():
            rules = extract_do_avoid_rules(str(claude_md))
            assert isinstance(rules, list)
            assert len(rules) > 0
            assert any('DO' in str(r) or 'AVOID' in str(r) for r in rules)

    def test_extract_rules_from_minimal_document(self):
        """Extract rules from a minimal CLAUDE.md snippet."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write('''
## Section

**DO/AVOID RULES**

* **DO** use meaningful variable names
* **AVOID** deep nesting in functions
* Some other text

## Next section
''')
            f.flush()
            path = f.name

        try:
            rules = extract_do_avoid_rules(path)
            assert len(rules) >= 2
            assert any('meaningful' in r.lower() for r in rules)
            assert any('deep nesting' in r.lower() or 'nesting' in r.lower() for r in rules)
        finally:
            Path(path).unlink()

    def test_extract_rules_empty_document(self):
        """Handle documents with no DO/AVOID sections."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write('# No rules here\n\nJust some text.')
            f.flush()
            path = f.name

        try:
            rules = extract_do_avoid_rules(path)
            assert isinstance(rules, list)
        finally:
            Path(path).unlink()


class TestMapRulesToRuffCodes:
    """Test mapping of rules to ruff codes."""

    def test_map_magic_numbers_rule(self):
        """Map 'avoid magic numbers' rule to ruff codes."""
        rules = ['Avoid using magic numbers; use constants or enums instead']
        codes = map_rules_to_ruff_codes(rules)
        assert isinstance(codes, list)
        assert all(isinstance(c, str) for c in codes)

    def test_map_variable_names_rule(self):
        """Map 'meaningful variable names' rule to ruff codes."""
        rules = ['Use meaningful variable names that indicate their purpose']
        codes = map_rules_to_ruff_codes(rules)
        assert 'E741' in codes

    def test_map_deep_nesting_rule(self):
        """Map 'deep nesting' rule to ruff codes."""
        rules = ['Refactor to reduce deep nesting in functions']
        codes = map_rules_to_ruff_codes(rules)
        assert 'C901' in codes

    def test_map_consistent_style_rule(self):
        """Map 'consistent style' rule to ruff codes."""
        rules = ['Ensure consistent coding style throughout the codebase']
        codes = map_rules_to_ruff_codes(rules)
        assert len(codes) > 0

    def test_map_multiple_rules(self):
        """Map multiple rules together."""
        rules = [
            'Use meaningful variable names',
            'Avoid deep nesting',
            'Ensure consistent style',
            'Avoid unnecessary checks',
        ]
        codes = map_rules_to_ruff_codes(rules)
        assert len(codes) > 0
        assert all(isinstance(c, str) for c in codes)

    def test_codes_are_sorted(self):
        """Verify returned codes are sorted."""
        rules = ['Some rules here']
        codes = map_rules_to_ruff_codes(rules)
        assert codes == sorted(codes)

    def test_empty_rules_returns_defaults(self):
        """Empty rules list returns sensible defaults."""
        codes = map_rules_to_ruff_codes([])
        assert len(codes) > 0
        assert 'C901' in codes or 'E741' in codes


class TestGenerateRuffToml:
    """Test generation of .ruff.toml config."""

    def test_generate_valid_toml_format(self):
        """Generated config is valid TOML format."""
        codes = ['E741', 'C901', 'E501']
        config = generate_ruff_toml(codes)

        assert '[tool.ruff]' in config
        assert '[tool.ruff.lint]' in config
        assert 'select' in config
        assert 'line-length' in config

    def test_generated_config_includes_rules(self):
        """Generated config includes all requested rule codes."""
        codes = ['E741', 'C901', 'E501', 'F841']
        config = generate_ruff_toml(codes)

        for code in codes:
            assert f'"{code}"' in config

    def test_generated_config_has_target_version(self):
        """Generated config specifies Python target version."""
        codes = ['E741', 'C901']
        config = generate_ruff_toml(codes)

        assert 'target-version = "py39"' in config

    def test_generated_config_has_line_length(self):
        """Generated config specifies line length."""
        codes = ['E741']
        config = generate_ruff_toml(codes)

        assert 'line-length = 100' in config

    def test_generated_config_has_per_file_ignores(self):
        """Generated config includes per-file ignores."""
        codes = ['E741']
        config = generate_ruff_toml(codes)

        assert '__init__.py' in config
        assert 'test_' in config

    def test_empty_codes_list(self):
        """Handle empty codes list gracefully."""
        config = generate_ruff_toml([])
        assert '[tool.ruff]' in config
        assert 'select = [' in config


class TestIdempotency:
    """Test idempotency of rule generation."""

    def test_generate_twice_same_result(self):
        """Regenerating rules produces identical output."""
        repo_root = Path(__file__).parent.parent
        claude_md = repo_root / 'CLAUDE.md'

        if not claude_md.exists():
            return

        rules1 = extract_do_avoid_rules(str(claude_md))
        codes1 = map_rules_to_ruff_codes(rules1)
        config1 = generate_ruff_toml(codes1)

        rules2 = extract_do_avoid_rules(str(claude_md))
        codes2 = map_rules_to_ruff_codes(rules2)
        config2 = generate_ruff_toml(codes2)

        assert config1 == config2
        assert codes1 == codes2


class TestRegressionPrevention:
    """Test that existing code patterns still pass."""

    def test_ruff_codes_are_valid(self):
        """All generated codes are valid ruff codes."""
        repo_root = Path(__file__).parent.parent
        claude_md = repo_root / 'CLAUDE.md'

        if not claude_md.exists():
            return

        rules = extract_do_avoid_rules(str(claude_md))
        codes = map_rules_to_ruff_codes(rules)

        valid_codes = {
            'C901', 'E501', 'E741', 'F841', 'PLR0912', 'W503', 'E731',
            'PLW0602', 'E502', 'E402', 'F401'
        }

        for code in codes:
            assert code in valid_codes, f'Invalid ruff code: {code}'

    def test_ruff_toml_file_exists_after_generation(self):
        """After running script, .ruff.toml exists."""
        repo_root = Path(__file__).parent.parent
        ruff_toml = repo_root / '.ruff.toml'

        assert ruff_toml.exists(), '.ruff.toml should exist after generation'

    def test_generated_config_parseable(self):
        """Generated .ruff.toml can be parsed as TOML."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib

        repo_root = Path(__file__).parent.parent
        ruff_toml = repo_root / '.ruff.toml'

        if ruff_toml.exists():
            with open(ruff_toml, 'rb') as f:
                config = tomllib.load(f)
            assert 'tool' in config
            assert 'ruff' in config['tool']
