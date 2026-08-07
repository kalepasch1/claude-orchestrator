#!/usr/bin/env python3
"""Generate ruff configuration from CLAUDE.md conventions."""

import re
import sys
from pathlib import Path


def extract_do_avoid_rules(claude_md_path):
    """Extract DO/AVOID rules from CLAUDE.md."""
    with open(claude_md_path, 'r') as f:
        content = f.read()

    rules = []
    lines = content.split('\n')

    in_do_avoid = False
    for i, line in enumerate(lines):
        if '**DO/AVOID RULES**' in line or '**DO/AVOID RULES:**' in line:
            in_do_avoid = True
            continue

        if in_do_avoid:
            if line.startswith('##'):
                in_do_avoid = False
                continue

            if line.strip() and (line.strip().startswith('*') or line.strip().startswith('-')):
                rule_text = line.strip().lstrip('*-+').strip()
                if rule_text:
                    rules.append(rule_text)

    return rules


def map_rules_to_ruff_codes(rules):
    """Map DO/AVOID rules to ruff rule codes."""
    ruff_codes = set()

    all_rules_text = ' '.join(rule.lower() for rule in rules)

    keyword_mappings = {
        'magic number': ['E741'],
        'meaningful': ['E741'],
        'descriptive': ['E741'],
        'variable name': ['E741'],
        'consistent': ['E501', 'W503'],
        'coding style': ['E501', 'W503'],
        'deep nesting': ['C901', 'PLR0912'],
        'nesting': ['C901', 'PLR0912'],
        'complex': ['C901', 'PLR0912'],
        'unnecessary': ['F841', 'PLW0602'],
        'simplif': ['C901', 'E731'],
        'nested loop': ['C901'],
        'long line': ['E501'],
    }

    for keyword, codes in keyword_mappings.items():
        if keyword in all_rules_text:
            ruff_codes.update(codes)

    if not ruff_codes:
        ruff_codes.update(['E741', 'C901', 'E501', 'F841', 'PLR0912'])

    return sorted(ruff_codes)


def generate_ruff_toml(ruff_codes):
    """Generate ruff.toml configuration content."""
    config = '[tool.ruff]\n'
    config += '# Generated from CLAUDE.md conventions\n'
    config += '# Run: python scripts/generate_lint_rules.py\n\n'
    config += 'line-length = 100\n'
    config += 'target-version = "py39"\n\n'
    config += '[tool.ruff.lint]\n'
    config += 'select = [\n'

    for code in ruff_codes:
        config += f'    "{code}",\n'

    config += ']\n\n'
    config += '[tool.ruff.lint.per-file-ignores]\n'
    config += '"__init__.py" = ["F401"]\n'
    config += '"test_*.py" = ["F841"]\n'

    return config


def main():
    repo_root = Path(__file__).parent.parent
    claude_md = repo_root / 'CLAUDE.md'
    ruff_toml = repo_root / '.ruff.toml'

    if not claude_md.exists():
        print(f'Error: {claude_md} not found', file=sys.stderr)
        return 1

    rules = extract_do_avoid_rules(str(claude_md))
    ruff_codes = map_rules_to_ruff_codes(rules)
    new_config = generate_ruff_toml(ruff_codes)

    old_config = ''
    if ruff_toml.exists():
        with open(ruff_toml, 'r') as f:
            old_config = f.read()

    if new_config == old_config:
        print('✓ .ruff.toml unchanged')
        return 0
    else:
        with open(ruff_toml, 'w') as f:
            f.write(new_config)
        print('✓ .ruff.toml regenerated')
        return 1


if __name__ == '__main__':
    sys.exit(main())
