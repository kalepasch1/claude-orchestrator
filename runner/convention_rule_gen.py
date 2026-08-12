#!/usr/bin/env python3
"""
convention_rule_gen.py - turn each project's CLAUDE.md DO/DON'T rules into MACHINE-CHECKED lint
rules, so agent output matches house style automatically instead of being rejected for it.

The problem this closes: CLAUDE.md is prose. An agent reads "No `console.log` in production code"
and mostly complies, and the times it doesn't, a human catches it at review — the expensive
"works but wrong-style" reject. Prose cannot gate a merge; a compiled rule can.

How it works (deterministic, no model call):
  1. Read CLAUDE.md and collect every DON'T / AVOID / "No X" bullet.
  2. For bullets that name a concrete code token in backticks (`console.log`, `@ts-nocheck`,
     `.from('table')`), compile a `forbidden_pattern` rule. These are precise and checkable.
  3. Every other bullet is recorded as `advisory` — kept in the ruleset for traceability but
     NEVER enforced. A vague sentence must not become a merge gate.
  4. Write `.convention-rules.json` at the repo root.

Safety properties that matter for a fleet that merges unattended:
  - Generated rules default to severity "warn". Regenerating conventions can therefore never
    newly hard-block the merge train. Promotion to "error" is an explicit, human edit of the
    `enforce` list in the ruleset.
  - Rules carry the source bullet, so any violation explains itself and is auditable.
  - Everything is fail-soft: a missing/unreadable CLAUDE.md yields an empty ruleset, not a crash.

Regeneration is wired into the conventions job (synthesize_conventions.run), so the rules track
CLAUDE.md instead of drifting from it.

Usage:
    python3 runner/convention_rule_gen.py [REPO] [--check] [--json]
      (no flags)  regenerate .convention-rules.json for REPO
      --check     apply the ruleset to REPO's source and report violations
"""
import fnmatch
import json
import os
import re
import sys
from argparse import ArgumentParser

RULESET_FILENAME = ".convention-rules.json"
SCHEMA_VERSION = 1

# Bullets that state a prohibition. Matches "- No X", "- DON'T ...", "❌ ...", "**AVOID** ...".
_PROHIBITION = re.compile(
    r"^\s*(?:[-*+]|\d+\.)?\s*(?:\**\s*(?:DON'?TS?|DO\s*NOT|AVOID|NEVER|NO)\b\s*\**[:\s]|[❌🚫])",
    re.I,
)
# A concrete code token inside backticks — the only thing precise enough to enforce.
_CODE_SPAN = re.compile(r"`([^`\n]{2,80})`")
# Tokens too generic to lint on: enforcing these would flag the whole repo.
_TOO_GENERIC = {
    "true", "false", "none", "null", "any", "error", "warn", "test", "tests", "code",
    "env", ".env", "main", "master", "dev", "prod", "production", "string", "number",
}
# A prohibition bullet usually names the REMEDY as well as the offence:
#   "No hardcoded AI models — use `selectModel()` from ..."
# Everything after the remedy marker describes what you SHOULD write, so compiling a rule from a
# token found there bans the correct code. Truncate the bullet at the first marker and only mine
# tokens from the prohibition side. This is the difference between a useful lint and a harmful one.
_REMEDY_MARKER = re.compile(
    r"(?:—|–|→|->|;|,)?\s*(?:use\b|prefer\b|instead\b|replace\s+with\b|switch\s+to\b|via\b)",
    re.I,
)
# Bare file extensions (`.ts`, `.mjs`) name where a rule applies, never the banned construct.
_FILE_EXTENSION = re.compile(r"^\.[A-Za-z][A-Za-z0-9]{0,4}$")

# Default file globs a generated rule applies to, by the language the token looks like.
_DEFAULT_GLOBS = ["*.py", "*.ts", "*.tsx", "*.js", "*.jsx", "*.vue", "*.mjs", "*.cjs"]
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".nuxt", "dist", "build",
              ".pytest_cache", ".venv", "venv", "coverage"}


def _slug(text, maxlen=40):
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return (s[:maxlen] or "rule").rstrip("_")


def _is_enforceable_token(token):
    """A token is enforceable when it is specific enough that a literal match means something."""
    t = (token or "").strip()
    if len(t) < 3 or t.lower() in _TOO_GENERIC:
        return False
    if _FILE_EXTENSION.match(t):
        return False           # scopes a rule, is not itself the banned construct
    if " " in t and not any(c in t for c in "().@"):
        return False           # a phrase, not an identifier
    return bool(re.search(r"[A-Za-z_@.]", t))


def prohibited_clause(bullet):
    """The part of a bullet that states the offence, with any 'use X instead' remedy stripped."""
    m = _REMEDY_MARKER.search(bullet or "")
    head = (bullet or "")[: m.start()] if m else (bullet or "")
    return head.strip() or (bullet or "").strip()


def read_claude_md(repo):
    """CLAUDE.md text for a repo, or '' when absent/unreadable (fail-soft, never raises)."""
    path = os.path.join(repo or ".", "CLAUDE.md")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except FileNotFoundError:
        return ""
    except Exception:
        return ""


def prohibition_bullets(text):
    """Every line of CLAUDE.md that states a prohibition, cleaned of markdown noise."""
    out = []
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip() or not _PROHIBITION.match(line):
            continue
        cleaned = re.sub(r"^\s*(?:[-*+]|\d+\.)?\s*", "", line).strip()
        cleaned = re.sub(r"^[❌🚫]\s*", "", cleaned).strip()
        if cleaned:
            out.append(cleaned)
    return out


def compile_rule(bullet):
    """Compile one prohibition bullet into a rule dict.

    Returns a `forbidden_pattern` rule when the bullet names a concrete backticked token,
    otherwise an `advisory` rule that is recorded but never enforced.
    """
    tokens = [t.strip() for t in _CODE_SPAN.findall(prohibited_clause(bullet))]
    enforceable = [t for t in tokens if _is_enforceable_token(t)]
    if not enforceable:
        return {"id": f"advisory_{_slug(bullet)}", "kind": "advisory", "source": bullet,
                "severity": "off", "message": bullet}
    token = enforceable[0]
    return {
        "id": f"no_{_slug(token)}",
        "kind": "forbidden_pattern",
        "pattern": re.escape(token),
        "token": token,
        "globs": list(_DEFAULT_GLOBS),
        # Generated rules are advisory-by-default: regeneration must never newly block a merge.
        "severity": "warn",
        "source": bullet,
        "message": f"`{token}` is prohibited by CLAUDE.md: {bullet}",
    }


def generate(repo="."):
    """Build the ruleset for a repo from its CLAUDE.md. Always returns a valid ruleset dict."""
    bullets = prohibition_bullets(read_claude_md(repo))
    rules, seen = [], set()
    for b in bullets:
        rule = compile_rule(b)
        if rule["id"] in seen:
            continue
        seen.add(rule["id"])
        rules.append(rule)
    enforced = [r["id"] for r in rules if r["kind"] == "forbidden_pattern"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_from": "CLAUDE.md",
        "repo": os.path.basename(os.path.abspath(repo or ".")),
        "rules": rules,
        # Only ids listed here are ever raised at "error" severity. Empty by design: promotion
        # is a deliberate human act, not a side effect of the conventions job.
        "enforce": [],
        "counts": {"total": len(rules), "checkable": len(enforced),
                   "advisory": len(rules) - len(enforced)},
    }


def ruleset_path(repo="."):
    return os.path.join(repo or ".", RULESET_FILENAME)


def write_ruleset(repo=".", ruleset=None):
    """Write .convention-rules.json. Returns the path, or '' when the write failed (fail-soft)."""
    ruleset = ruleset if ruleset is not None else generate(repo)
    path = ruleset_path(repo)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(ruleset, fh, indent=2, sort_keys=False)
            fh.write("\n")
    except Exception as e:
        print(f"convention_rule_gen: could not write {path} ({e}); fail-soft continue")
        return ""
    return path


def load_ruleset(repo="."):
    """Read a previously generated ruleset, or an empty one when absent/corrupt."""
    try:
        with open(ruleset_path(repo), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) and isinstance(data.get("rules"), list) else {"rules": []}
    except Exception:
        return {"rules": []}


def _iter_source_files(repo, globs):
    for root, dirs, files in os.walk(repo or "."):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.endswith("-wt")]
        for name in files:
            if any(fnmatch.fnmatch(name, g) for g in globs):
                yield os.path.join(root, name)


def check(repo=".", ruleset=None):
    """Apply the enforceable rules to the repo's source. Returns a list of violation dicts."""
    ruleset = ruleset if ruleset is not None else load_ruleset(repo)
    enforce = set(ruleset.get("enforce") or [])
    rules = [r for r in ruleset.get("rules", []) if r.get("kind") == "forbidden_pattern"]
    if not rules:
        return []
    compiled = []
    for r in rules:
        try:
            compiled.append((r, re.compile(r["pattern"])))
        except Exception:
            continue           # a bad pattern is skipped, never fatal
    violations = []
    globs = sorted({g for r in rules for g in r.get("globs", _DEFAULT_GLOBS)})
    for path in _iter_source_files(repo, globs):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except Exception:
            continue
        for rule, rx in compiled:
            if not any(fnmatch.fnmatch(os.path.basename(path), g)
                       for g in rule.get("globs", _DEFAULT_GLOBS)):
                continue
            for i, line in enumerate(lines, start=1):
                if rx.search(line):
                    violations.append({
                        "file": os.path.relpath(path, repo or "."),
                        "line": i,
                        "rule": rule["id"],
                        "message": rule.get("message", ""),
                        "severity": "error" if rule["id"] in enforce else rule.get("severity", "warn"),
                    })
    return violations


def regenerate_for(repo="."):
    """Entry point for the conventions job: rebuild the ruleset after CLAUDE.md is refreshed."""
    ruleset = generate(repo)
    path = write_ruleset(repo, ruleset)
    c = ruleset["counts"]
    print(f"convention_rule_gen: {c['checkable']} checkable + {c['advisory']} advisory rules "
          f"-> {path or '(write failed)'}")
    return ruleset


def main(argv=None):
    p = ArgumentParser(description="Compile CLAUDE.md prohibitions into machine-checked lint rules.")
    p.add_argument("repo", nargs="?", default=os.getcwd(), help="repo root (default: cwd)")
    p.add_argument("--check", action="store_true", help="apply the ruleset instead of regenerating")
    p.add_argument("--json", action="store_true", help="emit JSON")
    p.add_argument("--fail-on-error", action="store_true",
                   help="exit 1 if any violation has severity=error")
    args = p.parse_args(argv)

    if args.check:
        violations = check(args.repo)
        if args.json:
            print(json.dumps(violations, indent=2))
        else:
            for v in violations:
                print(f"{v['file']}:{v['line']}: {v['severity']}: {v['rule']}: {v['message']}")
            print(f"convention_rule_gen: {len(violations)} violation(s)")
        if args.fail_on_error and any(v["severity"] == "error" for v in violations):
            return 1
        return 0

    ruleset = regenerate_for(args.repo)
    if args.json:
        print(json.dumps(ruleset, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
