#!/usr/bin/env python3
"""
self_authored_capabilities.py — Discover patterns the orchestrator has learned
from merged work and auto-register them as reusable capabilities.

Scans merged diffs and CLAUDE.md conventions to find repeating patterns
(error handling, module structure, test patterns) and publishes them
to the capability registry so future tasks can instantiate them.

Flow:
  1. Read recent merged diffs from merged_diff_memory
  2. Extract recurring code patterns / conventions
  3. Deduplicate against existing capabilities
  4. Publish new capabilities to the registry
"""
import os, sys, json, re, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

try:
    import capability
except ImportError:
    capability = None

try:
    import merged_diff_memory as mdm
except ImportError:
    mdm = None

MIN_OCCURRENCES = int(os.environ.get("ORCH_CAP_MIN_OCCURRENCES", "3"))
ENABLED = os.environ.get("ORCH_SELF_AUTHOR_CAPS", "true").lower() in ("1", "true", "yes")

# Patterns we look for in merged diffs
PATTERN_SIGNATURES = {
    "fail_soft_handler": re.compile(
        r"except\s+(?:Exception|BaseException).*?(?:pass|return\s+(?:\"\"|None|False|\[\]|\{\}))",
        re.DOTALL),
    "env_config": re.compile(
        r"os\.environ\.get\([\"']ORCH_\w+[\"']"),
    "db_select_pattern": re.compile(
        r"db\.select\([\"']\w+[\"'],\s*\{"),
    "singleton_module": re.compile(
        r"def\s+\w+\(.*?\):\s*\n\s+.*?_instance"),
    "thread_safe_lock": re.compile(
        r"threading\.Lock\(\)"),
    "defensive_file_io": re.compile(
        r"(?:errors=[\"']replace[\"']|FileNotFoundError)"),
}


def scan_recent_diffs(days=14, limit=50):
    """Scan recent merged diffs for recurring patterns."""
    if not mdm:
        return {}
    try:
        diffs = mdm.recent(days=days, limit=limit)
    except Exception:
        diffs = []

    pattern_counts = {name: 0 for name in PATTERN_SIGNATURES}
    pattern_examples = {name: [] for name in PATTERN_SIGNATURES}

    for diff in diffs:
        content = diff.get("diff", "") or diff.get("content", "") or ""
        for name, rx in PATTERN_SIGNATURES.items():
            matches = rx.findall(content)
            if matches:
                pattern_counts[name] += 1
                if len(pattern_examples[name]) < 3:
                    pattern_examples[name].append(matches[0][:200] if matches[0] else "")

    return {name: {"count": pattern_counts[name], "examples": pattern_examples[name]}
            for name in PATTERN_SIGNATURES if pattern_counts[name] >= MIN_OCCURRENCES}


def extract_conventions_from_claude_md():
    """Extract conventions from CLAUDE.md learned-from-merges sections."""
    claude_md = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "CLAUDE.md")
    try:
        with open(claude_md, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return []

    conventions = []
    in_conventions = False
    current = []
    for line in content.split("\n"):
        if "CONVENTIONS" in line.upper():
            in_conventions = True
            continue
        if in_conventions and line.startswith("**") and not line.startswith("***"):
            if current:
                conventions.append(" ".join(current).strip())
            current = [line.strip("* ").strip()]
        elif in_conventions and line.startswith("- ") or line.startswith("* "):
            current.append(line.strip("- *").strip())
        elif in_conventions and line.startswith("#"):
            if current:
                conventions.append(" ".join(current).strip())
            in_conventions = False
            current = []

    if current:
        conventions.append(" ".join(current).strip())
    return [c for c in conventions if len(c) > 20]


def publish_discovered(project_id=None):
    """Discover and publish new capabilities from merged work."""
    if not ENABLED or not capability:
        return {"published": 0, "skipped": 0, "reason": "disabled or capability module missing"}

    patterns = scan_recent_diffs()
    conventions = extract_conventions_from_claude_md()
    published = 0
    skipped = 0

    for name, info in patterns.items():
        slug = f"auto-{name.replace('_', '-')}"
        summary = f"Auto-discovered pattern: {name.replace('_', ' ')} (seen {info['count']}x in recent merges)"
        try:
            result = capability.publish(
                name=name.replace("_", " ").title(),
                slug=slug,
                domain="orchestrator",
                summary=summary,
                contract={"pattern": name, "min_occurrences": info["count"]},
                spec=json.dumps({"examples": info["examples"]}),
                source_project=project_id or "orchestrator",
                consent=True,
            )
            if result:
                published += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1

    for i, conv in enumerate(conventions[:10]):
        slug = f"auto-convention-{i}"
        try:
            result = capability.publish(
                name=f"Convention {i}",
                slug=slug,
                domain="orchestrator",
                summary=conv[:200],
                contract={"type": "convention", "source": "CLAUDE.md"},
                spec=conv,
                source_project=project_id or "orchestrator",
                consent=True,
            )
            if result:
                published += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1

    return {"published": published, "skipped": skipped, "patterns_found": len(patterns),
            "conventions_found": len(conventions)}
